"""TikTok public-profile scraper.

Two-phase probe with explicit responsibility split:

  1. **Live status (authoritative)** — Euler-signed
     `client.web.fetch_room_info(unique_id=handle)`. Hits
     `webcast.us.tiktok.com`, not the public website, so the
     anti-bot WAF doesn't apply. Returns `UserOfflineError` for
     non-live creators (confident False), data for live ones
     (confident True + room_id + basic identity from `data.owner`).
     Costs 1 Euler sign per call — paid Euler tier comfortably
     sustains this; free tier will rate-limit.

  2. **Profile stats (best-effort enrichment)** — anonymous
     ``https://www.tiktok.com/@<handle>`` HTML scrape, parsing
     `__UNIVERSAL_DATA_FOR_REHYDRATION__` for follower / video /
     like / friend counts + bio + verified flag. None of these
     come from the WebCast API, so this path is the only source.
     WAF / 403 on this URL is now a *stats degradation*, not a
     live-status problem — the supervisor's recycle decisions
     rely solely on the Euler-derived `is_live`.

The legacy ``/@<handle>/live`` HTML probe is gone. Its only unique
value was live-status discovery, which Euler does better (signed,
no WAF gate, also returns room_id). Keeping it would mean two
anonymous HTTP calls per cycle for redundant data.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# WAF warnings rate-limiter. The scraper hits a WAF wall on most handles
# during a global TikTok anti-bot wave, and logging "WAF detected on …"
# every 60s per handle is pure log spam (a 200-char HTML preview each
# time, identical body). Cache the last-warned timestamp per handle and
# downgrade to DEBUG within the cooldown.
_WAF_WARN_LAST: dict[str, float] = {}
_WAF_WARN_COOLDOWN_S = 600.0  # 10 min

# Modern profile URL ships this; live URL ships it too but the scope
# structure is different (it doesn't include webapp.user-detail).
_UNIVERSAL_TAG = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.+?)</script>',
    re.DOTALL,
)

# Sticky WAF page footprint: ~1.5KB HTML with a slardar-config script,
# no profile data.
_WAF_MARKER = "slardar-config"


def _empty_record(handle: str) -> dict[str, Any]:
    return {
        "exists": None,
        # TRI-STATE: True / False / None. Defaults to None ("unknown")
        # because reaching this fn before any probe path runs means
        # we haven't observed live status yet. The old default of
        # `False` was load-bearing wrong: when both probe paths
        # failed (TikTok 403'd / WAF'd / parse error), the record
        # was returned with is_live=False — which the supervisor
        # treated as a CONFIDENT "user offline" signal and recycled
        # the session. Working live sessions got evicted because
        # TikTok blocked our metadata probe. Keeping it `None` here
        # forces the merge functions below to ONLY flip to True or
        # False when they have actual ground truth.
        "is_live": None,
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
        # ── Step 1: Euler — live status + identity (AUTHORITATIVE) ──
        # Always fires. Webcast.us.tiktok.com isn't gated by the
        # public-site WAF, so this is the reliable discovery path.
        # On success: sets `is_live`, room_id, nickname, avatar,
        # user_id, exists=True. On UserOfflineError: confident
        # `is_live=False`. On UserNotFoundError: `exists=False`.
        # On any other failure (rate-limit, sign error, network):
        # leaves `is_live=None` so the supervisor doesn't make a
        # confident wrong call.
        await _probe_euler_room_info(client, handle, out, debug_records)

        # ── Step 2: Anonymous /@handle — RICH STATS ONLY ────────────
        # Source of follower / video / like / friend counts + bio +
        # verified flag. None of those appear in Euler's room
        # response, so this scrape is the only path that fills them.
        # Failure here is purely a stats freshness issue — the
        # supervisor's recycle decisions don't touch these fields.
        # The DB just keeps last-known values; UI shows them slightly
        # stale rather than blank.
        profile_payload = await _fetch_profile_page(
            client, handle, debug_records,
        )
        if profile_payload == "WAF":
            # Stats degraded but live status (from Euler) is fine.
            # Surface a soft warning so the diagnostic UI can show
            # "stats probe WAF'd, live status from Euler is OK".
            if out["nickname"] is None:
                # Only flag a hard error if Euler didn't fill identity
                # either (creator currently offline + stats WAF'd).
                out["error"] = "TikTok WAF blocked stats probe (live status from Euler still OK)."
        elif profile_payload == "NOTFOUND":
            # Profile page 404 is more authoritative for existence
            # than Euler's UserNotFoundError (which Euler sometimes
            # masks as offline). Override.
            out["exists"] = False
            out["error"] = "User not found on TikTok."
        elif isinstance(profile_payload, dict):
            _merge_from_profile(out, profile_payload)
            out["exists"] = True

        # Final `exists` resolution: Euler succeeding implies the
        # account exists; the stats scrape confirms it. When both
        # paths failed entirely, leave `exists=None` (unknown) and
        # surface a clear error.
        if out["exists"] is None and out["nickname"] is None:
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


async def _probe_euler_room_info(
    client,
    handle: str,
    out: dict[str, Any],
    debug_sink: list[dict[str, Any]] | None,
) -> None:
    """Euler-signed liveness + identity probe. PRIMARY path.

    Calls TikTokLive's `client.web.fetch_room_info(unique_id=...)`,
    which hits `webcast.us.tiktok.com` with an Euler-signed request.
    Different host from the public profile page, different auth
    surface — the public-site WAF doesn't gate this endpoint.

    Mutates `out` in place. Four observable outcomes:

      - Live: sets `is_live=True`, `room_id`, plus nickname /
        avatar / user_id from `data.owner`. Marks `exists=True`.
      - Offline (UserOfflineError): sets `is_live=False`. Note
        the response carries no identity in this branch — UI
        keeps last-known nickname/avatar from a previous probe.
      - Not found (UserNotFoundError): marks `exists=False`,
        `is_live=False`.
      - Indeterminate (rate-limit, sign error, network): leaves
        `is_live` and `exists` at their current values (typically
        `None`). The stats scrape that runs next still gets to
        try; if it succeeds, we at least have identity.

    NEVER raises. Cost: 1 Euler sign request per call. With a paid
    Euler API key this runs every probe cycle (~12/min sustained
    for 72 handles); free tier will quickly rate-limit.
    """
    url_label = "webcast/room/info (Euler-signed)"
    try:
        # Lazy import — the error classes live deep in TikTokLive
        # and we don't want to pay the import cost on every call.
        from TikTokLive.client.errors import (
            UserOfflineError,
            UserNotFoundError,
        )
    except Exception:
        UserOfflineError = Exception  # type: ignore[assignment,misc]
        UserNotFoundError = Exception  # type: ignore[assignment,misc]

    try:
        info = await client.web.fetch_room_info(unique_id=handle)
    except UserOfflineError:
        # TikTok says the creator isn't currently broadcasting.
        # Confident `False` — supervisor can safely deprioritise.
        out["is_live"] = False
        if debug_sink is not None:
            debug_sink.append({
                "url": url_label, "status": None, "body_len": 0,
                "snippet": "", "reason": "euler fallback: UserOfflineError",
            })
        return
    except UserNotFoundError:
        # Account doesn't exist on TikTok. Mark as such; the
        # supervisor and UI both check `exists`.
        out["exists"] = False
        out["is_live"] = False
        if debug_sink is not None:
            debug_sink.append({
                "url": url_label, "status": None, "body_len": 0,
                "snippet": "", "reason": "euler fallback: UserNotFoundError",
            })
        return
    except Exception as e:
        # Sign error / rate-limit / network. Don't pretend we know.
        if debug_sink is not None:
            debug_sink.append({
                "url": url_label, "status": None, "body_len": 0,
                "snippet": "",
                "reason": f"euler fallback failed: {type(e).__name__}: {e}",
            })
        return

    # Successful response. Two possible shapes:
    #   1. Outer envelope: {"data": {...}, "status": 0, ...}
    #   2. Raw room dict (when the library normalises early).
    # The existing `lookup_handle` code unwraps the same way.
    if not isinstance(info, dict):
        if debug_sink is not None:
            debug_sink.append({
                "url": url_label, "status": None, "body_len": 0,
                "snippet": "",
                "reason": f"euler fallback: unexpected response type {type(info).__name__}",
            })
        return
    data = info.get("data", info)
    if not isinstance(data, dict) or not data:
        # Empty envelope — TikTokLive sometimes returns this instead
        # of raising. Treat as "not live" (no active room found).
        out["is_live"] = False
        if debug_sink is not None:
            debug_sink.append({
                "url": url_label, "status": None, "body_len": 0,
                "snippet": "", "reason": "euler fallback: empty envelope",
            })
        return

    # Status field semantics match the SIGI path: 2 = live, anything
    # else = not live. Some payloads omit `status` and signal liveness
    # through the presence of `id` (room_id) + a non-empty `title`.
    status = data.get("status")
    room_id = data.get("id") or data.get("room_id")
    if status == 2 or (status is None and room_id):
        out["is_live"] = True
        if room_id and str(room_id) != "0":
            out["room_id"] = str(room_id)
        # Reuse the nicknames / avatars / counts the response carries
        # so this isn't ONLY a liveness probe — fills the cache too.
        owner = data.get("owner") or {}
        if isinstance(owner, dict):
            if not out.get("nickname"):
                out["nickname"] = owner.get("nickname")
            if not out.get("user_id") and owner.get("id"):
                out["user_id"] = str(owner["id"])
            if not out.get("avatar_url"):
                ava = owner.get("avatar_medium") or owner.get("avatar_thumb")
                if isinstance(ava, dict):
                    urls = ava.get("url_list") or []
                    if urls:
                        out["avatar_url"] = urls[0]
        out["exists"] = True
        return

    # Status set but != 2 → confirmed offline.
    out["is_live"] = False
    if debug_sink is not None:
        debug_sink.append({
            "url": url_label, "status": None, "body_len": 0, "snippet": "",
            "reason": f"euler fallback: status={status} (not live)",
        })


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
        # Rate-limit: WARNING once per handle per 10 min so a global
        # WAF wave doesn't drown the log. Subsequent hits within the
        # window go to DEBUG. The 200-char body preview only fires
        # alongside the WARNING (the cheap reason field stays).
        now = time.monotonic()
        last = _WAF_WARN_LAST.get(handle, 0.0)
        if (now - last) >= _WAF_WARN_COOLDOWN_S:
            _WAF_WARN_LAST[handle] = now
            logger.warning(
                "WAF detected on %s for @%s (status=%s len=%d); first 200 chars: %s",
                url, handle, status, len(text), text[:200].replace("\n", " "),
            )
        else:
            logger.debug(
                "WAF detected on %s for @%s (status=%s, suppressed; "
                "next warn in %.0fs)",
                url, handle, status,
                _WAF_WARN_COOLDOWN_S - (now - last),
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
