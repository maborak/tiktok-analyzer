"""TikTok public-profile scraper.

We need profile info (nickname, avatar, follower count, live state) for
creators we monitor. TikTokLive only knows the webcast API, which gates
most accounts behind a session cookie. Two unauth-friendly paths exist
on the public site:

  1. ``https://www.tiktok.com/@<handle>/live`` — has a `SIGI_STATE` JSON
     blob whose `LiveRoom.liveRoomUserInfo.user` carries everything we
     care about plus current live state (`status` == 2 means live, 4
     means ended; `roomId` is set when live).
  2. ``https://www.tiktok.com/@<handle>`` — has a richer
     `__UNIVERSAL_DATA_FOR_REHYDRATION__` blob under
     `webapp.user-detail.userInfo`. More stats (videoCount, heartCount,
     friendCount) than the live page.

In practice TikTok's anti-bot WAF (SlardarWAF) hits the bare profile URL
much more aggressively than `/live`, so we try `/live` first and fall
back to the profile URL only when the live page didn't yield useful
data. Both endpoints can hit captcha challenges; we detect the WAF
response shape and surface a clear error rather than silently failing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Modern profile URL ships this; live URL ships it too but the scope
# structure is different (it doesn't include webapp.user-detail).
_UNIVERSAL_TAG = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.+?)</script>',
    re.DOTALL,
)

# Legacy tag, still present on /@user/live pages — carries everything we
# need for the live path (less data than the profile path, but enough).
_SIGI_TAG = re.compile(
    r'<script id="SIGI_STATE"[^>]*>(.+?)</script>',
    re.DOTALL,
)

# Sticky WAF page footprint: ~1.5KB HTML with a slardar-config script,
# no profile data.
_WAF_MARKER = "slardar-config"


def _empty_record(handle: str) -> dict[str, Any]:
    return {
        "exists": None,
        "is_live": False,
        "room_id": None,
        "user_id": None,
        "sec_uid": None,
        "unique_id": handle,
        "nickname": None,
        "avatar_url": None,
        "bio": None,
        "verified": None,
        "private": None,
        "follower_count": None,
        "following_count": None,
        "video_count": None,
        "like_count": None,
        "friend_count": None,
        "error": None,
    }


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _detect_waf(html: str) -> bool:
    """SlardarWAF challenge pages are ~1.5KB and contain `slardar-config`
    as the only script tag with embedded JSON."""
    if not html:
        return False
    return len(html) < 4000 and _WAF_MARKER in html


async def fetch_public_profile(handle: str) -> dict[str, Any]:
    """Fetch a TikTok user's public profile.

    Tries the `/live` URL first (less aggressively WAF'd), then falls
    back to the bare profile URL for richer stats. Always returns a
    dict — never raises on network/parse errors. On hard failure the
    returned dict has `error` set; cached fields are left None.
    """
    handle = handle.lstrip("@").strip()
    out = _empty_record(handle)
    if not handle:
        out["error"] = "Empty handle"
        return out

    # Per-attempt diagnostic records. On a WAF / parse failure we
    # surface them in `out["error"]` so the admin UI shows enough
    # context to know whether TikTok served HTTP 403, an empty body,
    # a SlardarWAF challenge, etc.
    debug_records: list[dict[str, Any]] = []

    # Lazy import keeps test surfaces small.
    from TikTokLive import TikTokLiveClient
    client = TikTokLiveClient(unique_id=f"@{handle}")

    try:
        # Path 1: /live — preferred. Often succeeds when /@user is WAF'd.
        live_payload = await _fetch_live_page(client, handle, debug_records)
        if live_payload is not None:
            _merge_from_live(out, live_payload)

        # Path 2: profile root — richer stats.
        need_profile_fallback = (
            out["nickname"] is None
            or out["follower_count"] is None
            or out["video_count"] is None
        )
        if need_profile_fallback:
            profile_payload = await _fetch_profile_page(
                client, handle, debug_records,
            )
            if profile_payload == "WAF":
                if out["nickname"] is None:
                    out["error"] = "TikTok WAF blocked our preview probe."
            elif profile_payload == "NOTFOUND":
                out["exists"] = False
                out["error"] = "User not found on TikTok."
            elif isinstance(profile_payload, dict):
                _merge_from_profile(out, profile_payload)
                out["exists"] = True

        # If neither path filled anything, surface the most informative error.
        if out["exists"] is None and out["nickname"] is None:
            out["exists"] = None
            if not out["error"]:
                out["error"] = "Could not retrieve any profile data."
        elif out["nickname"] and out["exists"] is None:
            out["exists"] = True
    except Exception as e:
        logger.warning("Profile fetch crashed for @%s: %r", handle, e)
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            await client.web.close()
        except Exception:
            pass

    # Always attach the debug trail when there was an error path or
    # we couldn't fully populate the profile, so the UI / DB error
    # column tells the admin "what happened technically".
    if out["error"] or debug_records:
        out["probe_debug"] = debug_records
        if out["error"] and debug_records:
            # Inline a multi-line summary into the human-readable error.
            # Each attempted URL gets one line: reason + HTTP status +
            # body length + truncated snippet (HTML/JSON head).
            lines: list[str] = []
            for rec in debug_records:
                snippet = rec.get("snippet", "")
                if snippet:
                    snippet = " | snippet=" + snippet.replace("\n", " ")[:160]
                lines.append(
                    f"  {rec.get('url', '?')} → "
                    f"reason={rec.get('reason', '?')} "
                    f"http={rec.get('status', '?')} "
                    f"len={rec.get('body_len', 0)}"
                    f"{snippet}"
                )
            out["error"] = out["error"] + "\n" + "\n".join(lines)

    return out


# ─── /live path ────────────────────────────────────────────────────

def _probe_debug(
    *, url: str, status: int | None, body: str, reason: str,
) -> dict[str, Any]:
    """Compact diagnostic payload: HTTP status, body length, leading
    snippet (HTML head minus boilerplate), and a reason tag. Designed
    to fit in the `profile_error` column when WAF / parse failures
    happen, so an admin reading the UI knows WHY a probe failed."""
    snippet = (body or "").strip()
    if len(snippet) > 240:
        snippet = snippet[:240] + "…"
    return {
        "url": url,
        "status": status,
        "body_len": len(body or ""),
        "snippet": snippet,
        "reason": reason,
    }


async def _fetch_live_page(
    client, handle: str, debug_sink: list[dict[str, Any]] | None = None,
) -> dict | None:
    """Return the parsed `LiveRoom.liveRoomUserInfo` dict, or None on
    any failure / WAF / missing data. When a `debug_sink` list is
    passed, append a structured diagnostic record on every failure
    path so the caller can surface it."""
    url = f"https://www.tiktok.com/@{handle}/live"
    try:
        resp = await client.web.get(url=url, base_params=False)
    except Exception as e:
        logger.debug("/live fetch error for @%s: %r", handle, e)
        if debug_sink is not None:
            debug_sink.append({
                "url": url, "status": None, "body_len": 0,
                "snippet": "", "reason": f"exception: {type(e).__name__}: {e}",
            })
        return None
    status = getattr(resp, "status_code", None)
    text = getattr(resp, "text", "") or ""
    if _detect_waf(text):
        logger.warning(
            "WAF detected on %s for @%s (status=%s len=%d); first 200 chars: %s",
            url, handle, status, len(text), text[:200].replace("\n", " "),
        )
        if debug_sink is not None:
            debug_sink.append(_probe_debug(
                url=url, status=status, body=text, reason="waf",
            ))
        return None
    m = _SIGI_TAG.search(text)
    if not m:
        if debug_sink is not None:
            debug_sink.append(_probe_debug(
                url=url, status=status, body=text,
                reason="no SIGI_STATE script tag",
            ))
        return None
    try:
        sigi = json.loads(m.group(1))
    except (TypeError, ValueError) as e:
        if debug_sink is not None:
            debug_sink.append(_probe_debug(
                url=url, status=status, body=m.group(1),
                reason=f"sigi json parse: {e}",
            ))
        return None
    live_room = sigi.get("LiveRoom") if isinstance(sigi, dict) else None
    if not isinstance(live_room, dict):
        if debug_sink is not None:
            debug_sink.append({
                "url": url, "status": status, "body_len": len(text),
                "snippet": "", "reason": "no LiveRoom in SIGI_STATE",
            })
        return None
    info = live_room.get("liveRoomUserInfo")
    if not isinstance(info, dict) and debug_sink is not None:
        debug_sink.append({
            "url": url, "status": status, "body_len": len(text),
            "snippet": "", "reason": "no liveRoomUserInfo",
        })
    return info if isinstance(info, dict) else None


def _merge_from_live(out: dict[str, Any], live_info: dict[str, Any]) -> None:
    user = live_info.get("user") or {}
    stats = live_info.get("stats") or user.get("stats") or {}
    if not isinstance(user, dict):
        return
    out["exists"] = True
    out["unique_id"] = user.get("uniqueId") or out["unique_id"]
    uid = user.get("id")
    out["user_id"] = str(uid) if uid else None
    out["sec_uid"] = user.get("secUid") or out["sec_uid"]
    out["nickname"] = user.get("nickname") or out["nickname"]
    out["bio"] = user.get("signature") or out["bio"]
    if user.get("verified") is not None:
        out["verified"] = bool(user.get("verified"))
    avatar = (
        user.get("avatarLarger")
        or user.get("avatarMedium")
        or user.get("avatarThumb")
    )
    if avatar:
        out["avatar_url"] = avatar

    # Live signal: status==2 means live, 4 means ended, else not live.
    status = user.get("status")
    if status == 2:
        out["is_live"] = True
        rid = user.get("roomId")
        if rid and str(rid) != "0":
            out["room_id"] = str(rid)

    if isinstance(stats, dict):
        if stats.get("followerCount") is not None:
            out["follower_count"] = _opt_int(stats.get("followerCount"))
        if stats.get("followingCount") is not None:
            out["following_count"] = _opt_int(stats.get("followingCount"))


# ─── /@user path ───────────────────────────────────────────────────

async def _fetch_profile_page(
    client, handle: str, debug_sink: list[dict[str, Any]] | None = None,
):
    """Return the parsed `webapp.user-detail` dict, or sentinel strings:
    "WAF" if challenged, "NOTFOUND" if TikTok says user doesn't exist,
    or None on parse failure."""
    url = f"https://www.tiktok.com/@{handle}"
    try:
        resp = await client.web.get(url=url, base_params=False)
    except Exception as e:
        logger.debug("/@user fetch error for @%s: %r", handle, e)
        if debug_sink is not None:
            debug_sink.append({
                "url": url, "status": None, "body_len": 0,
                "snippet": "", "reason": f"exception: {type(e).__name__}: {e}",
            })
        return None
    status = getattr(resp, "status_code", None)
    text = getattr(resp, "text", "") or ""
    if _detect_waf(text):
        logger.warning(
            "WAF detected on %s for @%s (status=%s len=%d); first 200 chars: %s",
            url, handle, status, len(text), text[:200].replace("\n", " "),
        )
        if debug_sink is not None:
            debug_sink.append(_probe_debug(
                url=url, status=status, body=text, reason="waf",
            ))
        return "WAF"
    m = _UNIVERSAL_TAG.search(text)
    if not m:
        if debug_sink is not None:
            debug_sink.append(_probe_debug(
                url=url, status=status, body=text,
                reason="no __UNIVERSAL_DATA_FOR_REHYDRATION__ tag",
            ))
        return None
    try:
        payload = json.loads(m.group(1))
    except (TypeError, ValueError) as e:
        if debug_sink is not None:
            debug_sink.append(_probe_debug(
                url=url, status=status, body=m.group(1),
                reason=f"universal json parse: {e}",
            ))
        return None
    scope = payload.get("__DEFAULT_SCOPE__") or {}
    user_detail = scope.get("webapp.user-detail") or {}
    if user_detail.get("statusCode") == 10221:
        return "NOTFOUND"
    if user_detail.get("statusMsg") == "user_doesnt_exist":
        return "NOTFOUND"
    info = user_detail.get("userInfo")
    return info if isinstance(info, dict) else None


def _merge_from_profile(out: dict[str, Any], info: dict[str, Any]) -> None:
    user = info.get("user") or {}
    stats = info.get("stats") or {}
    if not isinstance(user, dict):
        return
    out["exists"] = True
    out["unique_id"] = user.get("uniqueId") or out["unique_id"]
    uid = user.get("id")
    if uid:
        out["user_id"] = str(uid)
    if user.get("secUid"):
        out["sec_uid"] = user.get("secUid")
    if user.get("nickname"):
        out["nickname"] = user.get("nickname")
    if user.get("signature"):
        out["bio"] = user.get("signature")
    if user.get("verified") is not None:
        out["verified"] = bool(user.get("verified"))
    if user.get("privateAccount") is not None:
        out["private"] = bool(user.get("privateAccount"))
    avatar = (
        user.get("avatarLarger")
        or user.get("avatarMedium")
        or user.get("avatarThumb")
    )
    if avatar:
        out["avatar_url"] = avatar
    # Liveness from this URL is signaled by user.roomId being non-empty.
    rid = user.get("roomId")
    if rid and str(rid) != "0" and str(rid) != "":
        out["is_live"] = True
        out["room_id"] = str(rid)
    if isinstance(stats, dict):
        if stats.get("followerCount") is not None:
            out["follower_count"] = _opt_int(stats.get("followerCount"))
        if stats.get("followingCount") is not None:
            out["following_count"] = _opt_int(stats.get("followingCount"))
        if stats.get("videoCount") is not None:
            out["video_count"] = _opt_int(stats.get("videoCount"))
        if stats.get("heartCount") is not None or stats.get("heart") is not None:
            out["like_count"] = _opt_int(
                stats.get("heartCount") or stats.get("heart")
            )
        if stats.get("friendCount") is not None:
            out["friend_count"] = _opt_int(stats.get("friendCount"))
