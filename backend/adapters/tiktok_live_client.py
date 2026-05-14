"""TikTokLive listener adapter — implements TikTokLiveSession{Factory,}Port.

Wraps the TikTokLive Python library. Each session connects to ONE
@username's WebCast WebSocket and emits events into a callback. The
service composes many sessions for the multi-live pool.

Auto-reconnect lives here: when the connection drops or the live ends,
we wait a backoff interval and try again, indefinitely, until stop()
is called or the subscription is removed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from TikTokLive import TikTokLiveClient
from TikTokLive.client.errors import (
    AgeRestrictedError,
    InitialCursorMissingError,
    SignatureRateLimitError,
    UserNotFoundError,
    UserOfflineError,
    WebcastBlocked200Error,
    WebsocketURLMissingError,
)
from TikTokLive.client.web.web_settings import WebDefaults


_SIGN_KEYS = (
    "TIKTOK_SIGN_PROVIDER",
    "TIKTOK_EULER_API_KEY",
    "TIKTOK_SESSION_ID",
    "TIKTOK_SESSION_TT_TARGET_IDC",
    "TIKTOK_LOCAL_SIGN_URL",
)
_SIGN_DB_CACHE: tuple[float, dict[str, str]] | None = None
_SIGN_DB_TTL_S = 30.0


def _read_sign_settings_from_db() -> dict[str, str]:
    """Pull the sign-provider rows directly from `app_config` (global
    scope). Cached for `_SIGN_DB_TTL_S` to avoid hammering the DB on
    every reconnect attempt during a thrash. Failures fall through to
    an empty dict so the legacy `CONFIG` path takes over.
    """
    import time as _t
    global _SIGN_DB_CACHE
    now = _t.monotonic()
    if _SIGN_DB_CACHE and (now - _SIGN_DB_CACHE[0]) < _SIGN_DB_TTL_S:
        return _SIGN_DB_CACHE[1]
    try:
        from adapters.persistence.config_persistence import ConfigAdapter
        adapter = ConfigAdapter()
        all_vals = adapter.get_all_values()
        out = {k: all_vals[k] for k in _SIGN_KEYS if k in all_vals and all_vals[k]}
    except Exception:
        out = {}
    _SIGN_DB_CACHE = (now, out)
    return out


def _read_sign_settings() -> dict[str, str]:
    """Resolve sign-provider settings.

    Resolution order:
      1. `app_config` table (global scope) — typed-config DB, which is
         what the admin Configuration UI writes to. This is the new
         source of truth.
      2. Legacy `CONFIG` dict in `backend/config.py` — env-bootstrapped
         at process start. Used as a fallback for installs that haven't
         migrated to typed config or for keys without a DB row.

    Read on every connect so admin GUI edits take effect on the next
    reconnect — no process restart required. The DB read is cached for
    a short TTL so a reconnect storm doesn't hammer the table.

    Critical: the worker process does NOT initialize ConfigService,
    which is why ConfigService.get() can't be used here. The
    ConfigAdapter is cheap (one SELECT against an indexed table) and
    works in any process.
    """
    from config import CONFIG
    db_vals = _read_sign_settings_from_db()

    def _pick(key: str, default: str = "") -> str:
        # DB wins when it has a non-empty value; otherwise legacy CONFIG.
        v = db_vals.get(key)
        if v:
            return str(v).strip()
        return str(CONFIG.get(key) or default).strip()

    return {
        "TIKTOK_SIGN_PROVIDER": _pick("TIKTOK_SIGN_PROVIDER", "euler").lower(),
        "TIKTOK_EULER_API_KEY": _pick("TIKTOK_EULER_API_KEY"),
        "TIKTOK_SESSION_ID": _pick("TIKTOK_SESSION_ID"),
        "TIKTOK_SESSION_TT_TARGET_IDC": _pick("TIKTOK_SESSION_TT_TARGET_IDC"),
        "TIKTOK_LOCAL_SIGN_URL": _pick("TIKTOK_LOCAL_SIGN_URL", "http://127.0.0.1:21214"),
    }


def _lookup_recent_room_id(unique_id: str, *, max_age_s: float) -> int | None:
    """Return the most-recent `room_id` for this handle from
    `tiktok_rooms`, but ONLY if `last_seen_at` is within `max_age_s`.

    Pass through to `TikTokLiveClient.start(room_id=…,
    fetch_room_info=False)` to skip the Euler-signed
    `webcast/room/info` probe on reconnect. None means "we don't have
    a fresh-enough room_id — full probe is needed".

    Cheap query: covered by the `(host_unique_id, last_seen_at DESC)`
    partial index added in `add_tiktok_lives_summary_indexes.py`.
    """
    try:
        from database.core.connection import create_database_engine
        from sqlalchemy import text as _text
        eng = create_database_engine()
        with eng.connect() as c:
            handle = unique_id.lstrip("@")
            row = c.execute(_text("""
              SELECT room_id, last_seen_at
              FROM tiktok_rooms
              WHERE host_unique_id = :h
                AND last_seen_at > NOW() - (:s || ' seconds')::interval
              ORDER BY last_seen_at DESC
              LIMIT 1
            """), {"h": handle, "s": max_age_s}).first()
        if row is None:
            return None
        return int(row.room_id)
    except Exception:
        # Lookup failures are non-fatal — fall through to full probe.
        return None


def invalidate_sign_settings_cache() -> None:
    """Drop the 30s DB cache so the next `_read_sign_settings()` call
    re-reads. Call after a config write if you need the new value to
    take effect before the TTL expires."""
    global _SIGN_DB_CACHE
    _SIGN_DB_CACHE = None


# Default EulerStream URL — captured at module import so we can restore
# it when switching back from the local broker without restarting.
_EULER_DEFAULT_URL = WebDefaults.tiktok_sign_url
from TikTokLive.events import (
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    DonationEvent,
    EmoteChatEvent,
    EnvelopeEvent,
    FollowEvent,
    GiftCollectionUpdateEvent,
    GiftEvent,
    JoinEvent,
    LikeEvent,
    LinkMicArmiesEvent,
    LinkMicBattleEvent,
    LinkMicBattlePunishFinishEvent,
    LinkMicBattleVictoryLapEvent,
    LiveEndEvent,
    LivePauseEvent,
    LiveUnpauseEvent,
    PollEvent,
    QuestionNewEvent,
    RoomUserSeqEvent,
    ShareEvent,
    SubscribeEvent,
)

from ports.tiktok_live import TikTokLiveSessionPort, TikTokLiveSessionFactoryPort

logger = logging.getLogger(__name__)


def _msg_id(event: Any) -> int | None:
    """Extract TikTok's per-emission unique id from a Webcast event.

    Every Webcast* protobuf message carries `base_message.message_id`
    (int64). Same id on a reconnect-cursor replay → the SAME event;
    distinct user actions (even "5 gifts in 1 second") always get
    distinct ids. Returns None for synthetic events we generate
    ourselves (connect / disconnect / live_end), which have no original
    protobuf to mine.
    """
    bm = getattr(event, "base_message", None)
    if bm is None:
        return None
    mid = getattr(bm, "message_id", None)
    if not mid:
        return None
    try:
        v = int(mid)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _user_payload(user: Any) -> dict[str, Any]:
    """Extract a JSON-safe user dict from a TikTokLive event.user.

    Includes the identity flags TikTokLive exposes via ExtendedUser
    properties (is_follower / is_moderator / is_subscribe / is_top_gifter
    plus member_level + gifter_level + fans_club tier when present).
    These let the UI show "🛡️ MOD", "❤️ SUB", "🥇 TOP-FAN" badges next
    to commenters/gifters without an extra DB join.
    """
    if user is None:
        return {}
    avatar_url = None
    avatar = getattr(user, "avatar_thumb", None) or getattr(user, "avatar", None)
    # TikTokLive 6.6.x renamed `url_list` → `m_urls` on ImageModel.
    # Read both so we work across versions; old ones still expose
    # `url_list` as a property in some builds.
    urls = (
        getattr(avatar, "m_urls", None)
        or getattr(avatar, "url_list", None)
    ) if avatar else None
    if urls:
        avatar_url = urls[0]

    identity: dict[str, Any] = {}
    # ExtendedUser properties — guard each with try/except since some are
    # computed properties that can throw on missing nested fields.
    for flag in ("is_follower", "is_following", "is_moderator", "is_subscribe", "is_top_gifter"):
        try:
            v = getattr(user, flag, None)
            if v is not None:
                identity[flag] = bool(v)
        except Exception:
            pass
    for level in ("member_level", "gifter_level", "anchor_level", "fan_ticket_count"):
        try:
            v = getattr(user, level, None)
            if v is not None:
                identity[level] = int(v)
        except Exception:
            pass
    # Fans-club name + level (sometimes nested under fans_club / fans_club_info).
    try:
        fc = getattr(user, "fans_club", None) or getattr(user, "fans_club_info", None)
        if fc:
            badge = getattr(fc, "badge", None)
            if badge:
                lvl = getattr(badge, "level", None)
                if lvl is not None:
                    identity["fans_club_level"] = int(lvl)
            name = getattr(fc, "club_name", None) or getattr(fc, "name", None)
            if name:
                identity["fans_club_name"] = str(name)
    except Exception:
        pass

    out = {
        "user_id": getattr(user, "id", None),
        "unique_id": getattr(user, "unique_id", None),
        "nickname": getattr(user, "nickname", None),
        "avatar_url": avatar_url,
    }
    if identity:
        out["identity"] = identity
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── rate-limited / cached profile fetcher ────────────────────────────
#
# Without these guards, 10+ offline supervisors each scraping
# `tiktok.com/@<handle>` every 60s = a sustained burst from one IP →
# TikTok's anti-bot flags us (DEVICE_BLOCKED on the WS, 403 on profile
# pages). We add two defenses:
#   1. A global async lock + minimum interval (5s) so at most one
#      scrape happens every 5 seconds across all supervisors.
#   2. A 5-minute per-handle cache — if we already fetched recently,
#      skip the network call entirely.
#
# Locality: one Python process. With multiple workers (different
# processes / hosts), each has its own limiter — but they each only
# poll the handles they own, so the per-IP rate stays bounded.

_PROFILE_CACHE_TTL_S = 300.0       # 5 min — long enough to skip storms
_PROFILE_MIN_INTERVAL_S = 5.0      # ~12 req/min ceiling per worker
_profile_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_profile_lock = asyncio.Lock()
_profile_last_fetch_at = 0.0


async def fetch_public_profile_throttled(handle: str) -> dict[str, Any]:
    """Cache + rate-limit wrapper around `fetch_public_profile`.

    - Returns the cached value when <`_PROFILE_CACHE_TTL_S` old.
    - Otherwise serializes through `_profile_lock` and enforces a
      `_PROFILE_MIN_INTERVAL_S` gap between actual network calls.

    Returns a dict in the same shape as `fetch_public_profile`. Never
    raises (best-effort)."""
    import time as _time
    from adapters.tiktok_profile_scraper import fetch_public_profile

    handle = handle.lstrip("@").strip()
    now = _time.monotonic()
    cached = _profile_cache.get(handle)
    if cached:
        ts, payload = cached
        if now - ts < _PROFILE_CACHE_TTL_S:
            return payload

    async with _profile_lock:
        # Re-check cache under lock — another caller may have just fetched.
        now = _time.monotonic()
        cached = _profile_cache.get(handle)
        if cached:
            ts, payload = cached
            if now - ts < _PROFILE_CACHE_TTL_S:
                return payload

        # Enforce minimum gap between actual scrapes.
        global _profile_last_fetch_at
        wait = _PROFILE_MIN_INTERVAL_S - (now - _profile_last_fetch_at)
        if wait > 0:
            await asyncio.sleep(wait)

        _profile_last_fetch_at = _time.monotonic()
        try:
            payload = await fetch_public_profile(handle)
        except Exception:
            logger.exception("fetch_public_profile_throttled: scrape raised")
            payload = {"handle": handle, "error": "scrape failed"}
        _profile_cache[handle] = (_time.monotonic(), payload)
        # Bound cache size so a worker watching many handles doesn't leak.
        if len(_profile_cache) > 256:
            cutoff = _time.monotonic() - _PROFILE_CACHE_TTL_S * 2
            stale_keys = [k for k, v in _profile_cache.items() if v[0] < cutoff]
            for k in stale_keys:
                _profile_cache.pop(k, None)
        return payload


def _first_url(image: Any) -> str | None:
    """Pick the first URL from a TikTokLive ImageModel-shaped object.

    TikTokLive 6.6.x renamed `url_list` → `m_urls`. Read both so the
    extractor works across versions."""
    if image is None:
        return None
    urls = getattr(image, "m_urls", None) or getattr(image, "url_list", None)
    if urls:
        return urls[0]
    return None


def _apply_sign_globals() -> None:
    """Set `WebDefaults.tiktok_sign_url` + `tiktok_sign_api_key` BEFORE a
    new TikTokLiveClient is constructed. The web signer captures both at
    construction time — setting them post-build silently has no effect
    (which is how we ended up sending unauthenticated EulerStream
    requests despite a configured API key)."""
    cfg = _read_sign_settings()
    provider = cfg["TIKTOK_SIGN_PROVIDER"] or "euler"

    if provider == "local":
        WebDefaults.tiktok_sign_url = cfg["TIKTOK_LOCAL_SIGN_URL"] or "http://127.0.0.1:21214"
        WebDefaults.tiktok_sign_api_key = None
        return

    # Either euler or session — both go through EulerStream.
    WebDefaults.tiktok_sign_url = _EULER_DEFAULT_URL
    WebDefaults.tiktok_sign_api_key = cfg["TIKTOK_EULER_API_KEY"] or None


def _apply_sign_client_state(
    client: TikTokLiveClient, *, handle: str | None = None
) -> None:
    """Per-client setup that has to run AFTER construction:
      - `local` mode: stuff the handle into the web client's params so
        the broker knows which TikTok page to load.
      - `session` mode: push the sessionid cookie into the web client.
    """
    cfg = _read_sign_settings()
    provider = cfg["TIKTOK_SIGN_PROVIDER"] or "euler"

    if provider == "local" and handle:
        try:
            client.web.params["unique_id"] = handle.lstrip("@")
        except Exception:
            pass
        return

    if provider == "session":
        sid = cfg["TIKTOK_SESSION_ID"]
        if not sid:
            logger.warning(
                "TIKTOK_SIGN_PROVIDER=session but TIKTOK_SESSION_ID is empty. "
                "Falling back to EulerStream for this connect."
            )
            return
        try:
            client.web.set_session(sid, cfg["TIKTOK_SESSION_TT_TARGET_IDC"] or None)
        except Exception:
            logger.exception(
                "Failed to apply session-id sign provider; falling back to EulerStream."
            )


def attach_euler_logging(client: TikTokLiveClient) -> None:
    """Install httpx event hooks so every Euler-signed request this
    client makes lands in `tiktok_euler_call_log`. Captures the API
    key fingerprint in effect at call time so subsequent key rotations
    appear as a distinct series in the dashboard."""
    try:
        from adapters.tiktok_euler_call_sink import attach_to_client
        cfg = _read_sign_settings()
        raw_key = cfg.get("TIKTOK_EULER_API_KEY") or ""
        if raw_key and len(raw_key) > 16:
            fp = f"{raw_key[:12]}…{raw_key[-8:]} (len={len(raw_key)})"
        elif raw_key:
            fp = f"len={len(raw_key)}"
        else:
            fp = "(none)"
        attach_to_client(client, api_key_fp=fp)
    except Exception:
        # Logging is non-fatal — never block a real listener connect.
        logger.exception("Failed to attach Euler-call logging hook.")


def _battle_user_payload(user_info: Any) -> dict[str, Any]:
    """Extract a JSON-safe payload from a BattleBaseUserInfo. The field
    layout is different from a regular User: nick_name (not nickname),
    display_id (not unique_id), avatar_thumb."""
    if user_info is None:
        return {}
    avatar_url = None
    avatar = getattr(user_info, "avatar_thumb", None)
    # TikTokLive 6.6.x renamed `url_list` → `m_urls` on ImageModel.
    # Read both so we work across versions; old ones still expose
    # `url_list` as a property in some builds.
    urls = (
        getattr(avatar, "m_urls", None)
        or getattr(avatar, "url_list", None)
    ) if avatar else None
    if urls:
        avatar_url = urls[0]
    return {
        "user_id": getattr(user_info, "user_id", None),
        "unique_id": getattr(user_info, "display_id", None) or None,
        "nickname": getattr(user_info, "nick_name", None) or None,
        "avatar_url": avatar_url,
    }


def _battle_tags(user_info_wrapper: Any) -> list[dict[str, Any]]:
    """Extract BattleRivalTag entries — these are TikTok's badge chips
    shown next to a battler (e.g. "Top fan", level indicators, follower
    counts depending on TikTok's UI). Each has bg/icon images + text."""
    out: list[dict[str, Any]] = []
    info = getattr(user_info_wrapper, "user_info", None)
    tags = getattr(info, "tags", None) if info is not None else None
    if not tags:
        return out
    for tag in tags:
        content = getattr(tag, "content", None) or ""
        if not content:
            continue
        icon = getattr(tag, "icon_image", None)
        urls = (
            getattr(icon, "m_urls", None) or getattr(icon, "url_list", None)
        ) if icon else None
        out.append(
            {
                "content": content,
                "icon_url": urls[0] if urls else None,
            }
        )
    return out


def _opponents_from_battle(event: Any) -> list[dict[str, Any]]:
    """Extract opponents (anchors on each side) from a LinkMicBattleEvent.

    Each side of a TikTok PK has one anchor user_id. Their per-anchor
    score lives in `armies[*].user_armies.host_score`. Names + avatars
    live in `anchor_info[*].user_info.user`. team_id (when present)
    comes from `team_users[*].user_ids`.

    Returns: [{user_id, unique_id, nickname, avatar_url, team_id?, score?, tags?}, …]
    """
    # 1. Names + tags + avatars from anchor_info.
    info_map: dict[int, dict[str, Any]] = {}
    for wrapper in (getattr(event, "anchor_info", None) or []):
        info = getattr(wrapper, "user_info", None)
        base = getattr(info, "user", None) if info is not None else None
        if base is None:
            continue
        uid = getattr(base, "user_id", None)
        if not uid:
            continue
        payload = _battle_user_payload(base)
        tags = _battle_tags(wrapper)
        if tags:
            payload["tags"] = tags
        info_map[int(uid)] = payload

    # 2. Team assignment from team_users (if present).
    team_for: dict[int, int] = {}
    for team in (getattr(event, "team_users", None) or []):
        team_id = getattr(team, "team_id", None) or 0
        for uid in (getattr(team, "user_ids", None) or []):
            try:
                team_for[int(uid)] = int(team_id) if team_id else None  # type: ignore[assignment]
            except (TypeError, ValueError):
                continue

    # 3. Per-anchor scores from armies (List[UserArmiesWrapper]).
    score_for: dict[int, int] = {}
    for wrapper in (getattr(event, "armies", None) or []):
        uid = getattr(wrapper, "user_id", None)
        ua = getattr(wrapper, "user_armies", None)
        if not uid or ua is None:
            continue
        score_for[int(uid)] = int(getattr(ua, "host_score", 0) or 0)

    # 4. Build the opponents list — every anchor seen.
    out: list[dict[str, Any]] = []
    all_uids = set(info_map.keys()) | set(score_for.keys()) | set(team_for.keys())
    for uid in all_uids:
        entry: dict[str, Any] = dict(info_map.get(uid) or {"user_id": uid})
        entry["team_id"] = team_for.get(uid)
        entry["score"] = score_for.get(uid, 0)
        out.append(entry)
    return out


def _opponents_from_armies_event(event: Any) -> list[dict[str, Any]]:
    """Extract per-anchor scores from a LinkMicArmiesEvent.

    Two TikTok payload shapes carry per-anchor breakdown:

      • `event.armies` — `Dict[int, BattleUserArmies]` keyed on
        anchor user_id. Each value has `host_score`. This shape
        ships in 1v1 PK battles (the original format).

      • `event.team_armies` — `List[BattleTeamUserArmies]` per
        team. Each team carries `team_users: List[BattleTeamUser]`
        with `(user_id, score)` per anchor on that team. This is
        what multi-guest "team battle" format (2v2, 3v1, 3v3, …)
        ships INSTEAD of populating the top-level `armies` Dict —
        so reading only `event.armies` returns an empty list and
        every per-anchor score gets stuck at 0.

    Read both. Top-level `armies` wins when present (it's the same
    score under a different proto path); `team_users` fills the gap
    for team battles. Caller merges into `opponents[].score`."""
    out: list[dict[str, Any]] = []
    seen_uids: set[int] = set()
    armies = getattr(event, "armies", None)
    if armies:
        try:
            items = armies.items() if hasattr(armies, "items") else []
        except Exception:
            items = []
        for uid, ua in items:
            try:
                score = int(getattr(ua, "host_score", 0) or 0)
                uid_int = int(uid)
                out.append({"user_id": uid_int, "score": score})
                seen_uids.add(uid_int)
            except (TypeError, ValueError):
                continue
    # Fall through to team_armies.team_users for the multi-guest
    # format that doesn't populate the top-level `armies` dict.
    team_armies = getattr(event, "team_armies", None) or []
    for team in team_armies:
        team_id = getattr(team, "team_id", None)
        team_users = getattr(team, "team_users", None) or []
        for tu in team_users:
            try:
                uid_int = int(getattr(tu, "user_id", 0) or 0)
                if uid_int == 0 or uid_int in seen_uids:
                    continue
                score = int(getattr(tu, "score", 0) or 0)
                entry: dict[str, Any] = {"user_id": uid_int, "score": score}
                if team_id is not None:
                    entry["team_id"] = int(team_id)
                out.append(entry)
                seen_uids.add(uid_int)
            except (TypeError, ValueError):
                continue
    return out


def _team_scores(armies: Any) -> dict[str, int]:
    """Per-team total scores from a `team_armies` field
    (List[BattleTeamUserArmies] with team_id + team_total_score)."""
    scores: dict[str, int] = {}
    if not armies:
        return scores
    try:
        for a in armies:
            team_id = getattr(a, "team_id", 0) or 0
            total = getattr(a, "team_total_score", 0) or 0
            if team_id:
                scores[str(int(team_id))] = int(total)
    except (TypeError, AttributeError):
        return {}
    return scores


def _battle_settings_payload(event: Any) -> dict[str, Any]:
    """Extract BattleSetting fields useful for the UI: duration + end_time
    so the countdown clock matches TikTok's own display."""
    s = getattr(event, "battle_setting", None) or getattr(event, "battle_settings", None)
    if s is None:
        return {}
    return {
        "duration_seconds": int(getattr(s, "duration", 0) or 0) or None,
        "start_time_ms": int(getattr(s, "start_time_ms", 0) or 0) or None,
        "end_time_ms": int(getattr(s, "end_time_ms", 0) or 0) or None,
        "extra_duration_seconds": int(getattr(s, "extra_duration_second", 0) or 0) or None,
    }


class TikTokLiveSession(TikTokLiveSessionPort):
    """One auto-reconnecting TikTokLive client."""

    INITIAL_BACKOFF = 5.0
    MAX_BACKOFF = 300.0  # 5 min between reconnect attempts when live is offline
    # When the user is confirmed offline (not just unreachable), poll on a
    # slower cadence — they could be offline for hours.
    OFFLINE_INITIAL_BACKOFF = 60.0
    OFFLINE_MAX_BACKOFF = 900.0  # 15 min
    # When EulerStream's free-tier sign-server rate-limits us, retrying
    # quickly only burns more of the budget. Back off hard.
    SIGN_RATE_LIMIT_INITIAL_BACKOFF = 120.0  # 2 min
    SIGN_RATE_LIMIT_MAX_BACKOFF = 1800.0  # 30 min
    # Park time for terminal errors that have a chance of recovering.
    # `AgeRestrictedError` is per-handshake (not per-stream) — TikTok can
    # serve a non-restricted response on the next attempt depending on
    # sign cookie / rate-limit state, so polling a few minutes later is
    # cheaper than waiting a half-hour. `UserNotFoundError` doesn't
    # recover, so it stays on the long backoff to avoid spinning.
    AGE_RESTRICTED_RETRY_BACKOFF = 180.0  # 3 min
    USER_NOT_FOUND_BACKOFF = 1800.0       # 30 min

    # Room-id reuse window. `tiktok_rooms` keeps the most-recent
    # `room_id` per handle even after the broadcast ends. If
    # `last_seen_at` is within this window, the broadcast is very
    # likely still live and we can pass the cached room_id straight to
    # `TikTokLiveClient.start(room_id=…, fetch_room_info=False)`,
    # SKIPPING the Euler-signed `webcast/room/info` probe entirely
    # (saves ~1 Euler call per session start). If the cached id is
    # stale (broadcast ended), TikTokLive raises UserOfflineError on
    # connect; we catch it and fall back to the full handshake on the
    # next retry, paying the probe cost only once.
    ROOM_ID_REUSE_MAX_AGE_S = 600.0  # 10 min

    def __init__(
        self,
        unique_id: str,
        on_event: Callable[..., Awaitable[None]],
        on_state_change: Callable[[str], Awaitable[None]] | None = None,
        on_terminal_error: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._unique_id = unique_id
        self._on_event = on_event
        self._on_state_change = on_state_change
        self._on_terminal_error = on_terminal_error
        self._client: TikTokLiveClient | None = None
        self._room_id: int | None = None
        self._heartbeat: asyncio.Task[Any] | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopped = False
        # Set to True after a connect attempt with a cached room_id
        # fails; the next attempt forces a fresh probe.
        self._reused_room_id_failed = False

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.connected)

    @property
    def room_id(self) -> int | None:
        return self._room_id

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._supervisor and not self._supervisor.done():
            return
        self._stopped = False
        self._supervisor = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stopped = True
        if self._heartbeat and not self._heartbeat.done():
            self._heartbeat.cancel()
        if self._supervisor and not self._supervisor.done():
            self._supervisor.cancel()
        if self._client and self._client.connected:
            try:
                await self._client.disconnect()
            except asyncio.CancelledError:
                # Heartbeat was already cancelled above; TikTokLive's
                # disconnect awaits that same task, so it propagates a
                # CancelledError. Not an error from our perspective —
                # the connection is being torn down on purpose.
                pass
            except Exception:
                logger.exception("Error disconnecting TikTokLive client for @%s", self._unique_id)
        self._client = None
        self._room_id = None
        await self._notify_state("DISCONNECTED")

    # ── supervisor loop ──────────────────────────────────────────────

    async def _run_forever(self) -> None:
        backoff = self.INITIAL_BACKOFF
        handle = self._unique_id if self._unique_id.startswith("@") else f"@{self._unique_id}"
        # Track which "expected" terminal state we're in so we can:
        #   1. choose the right retry cadence,
        #   2. log a single transition message instead of repeated tracebacks.
        last_offline = False
        last_sign_limited = False
        # Connect-handshake timeout. TikTokLive's client.start() does HTTP
        # to fetch room info + sign URL, then opens the WS — without an
        # explicit timeout, a hung HTTP can park us in CONNECTING forever.
        # 45s is generous; real handshakes are <5s.
        CONNECT_TIMEOUT = 45.0
        while not self._stopped:
            await self._notify_state("CONNECTING")
            # Defined before the try so the except blocks can read it
            # without risking UnboundLocalError on early-throwing
            # exceptions inside the body.
            cached_room_id: int | None = None
            try:
                _apply_sign_globals()
                client = TikTokLiveClient(unique_id=handle)
                _apply_sign_client_state(client, handle=handle)
                attach_euler_logging(client)
                self._wire_handlers(client)
                self._client = client
                # Try the room-id reuse fast path. If `tiktok_rooms`
                # has a fresh row for this handle, pass it to
                # `start(room_id=…, fetch_room_info=False)` and skip
                # the Euler-signed `webcast/room/info` probe. Saves
                # ~1 Euler call per session start on the common case
                # (reconnect within 10 min of last event).
                if not self._reused_room_id_failed:
                    cached_room_id = _lookup_recent_room_id(
                        self._unique_id,
                        max_age_s=self.ROOM_ID_REUSE_MAX_AGE_S,
                    )
                # `fetch_live_check=False` skips the
                # `webcast/room/check_alive` Euler-signed probe. If
                # the room is dead, the subsequent `webcast/fetch`
                # (WS URL sign) returns UserOfflineError anyway —
                # same outcome, one fewer Euler call. Only worth
                # paying when we'd otherwise be blind to a dead room
                # before opening the WS, which we aren't here.
                if cached_room_id is not None:
                    logger.info(
                        "TikTokLive reusing cached room_id=%d for @%s "
                        "(skipping room/info + check_alive probes)",
                        cached_room_id, self._unique_id,
                    )
                    heartbeat = await asyncio.wait_for(
                        client.start(
                            room_id=cached_room_id,
                            fetch_room_info=False,
                            fetch_live_check=False,
                        ),
                        timeout=CONNECT_TIMEOUT,
                    )
                else:
                    heartbeat = await asyncio.wait_for(
                        client.start(
                            fetch_room_info=True,
                            fetch_live_check=False,
                        ),
                        timeout=CONNECT_TIMEOUT,
                    )
                # Connect succeeded — reset the "force fresh probe"
                # flag so the next reconnect can try reuse again.
                self._reused_room_id_failed = False
                self._heartbeat = heartbeat
                self._room_id = client.room_id
                await self._notify_state("CONNECTED")
                logger.info("TikTokLive connected: @%s room=%s", self._unique_id, self._room_id)
                backoff = self.INITIAL_BACKOFF
                last_offline = False
                last_sign_limited = False
                try:
                    await heartbeat
                except Exception as e:
                    logger.info("TikTokLive heartbeat ended for @%s: %r", self._unique_id, e)
            except asyncio.CancelledError:
                raise
            except (UserNotFoundError, AgeRestrictedError) as e:
                # Terminal handshake error. UserNotFound never recovers
                # (handle doesn't exist), so we park on the slow 30-min
                # cadence. AgeRestricted is per-request — TikTok's
                # response depends on sign cookie / WAF state and may
                # flip on the next attempt — so we retry on a much
                # tighter cadence (3 min) so the listener actually
                # picks events back up when the gate clears.
                kind = e.__class__.__name__
                if isinstance(e, AgeRestrictedError):
                    backoff = self.AGE_RESTRICTED_RETRY_BACKOFF
                else:
                    backoff = self.USER_NOT_FOUND_BACKOFF
                logger.error(
                    "@%s terminal: %s — parking for %.0fs before retry.",
                    self._unique_id, kind, backoff,
                )
                # Push the reason up so the service can persist it to
                # tiktok_worker_log and the listener status snapshot —
                # otherwise the UI just sees "ERROR" with no hint why.
                await self._notify_terminal_error(kind, str(e))
                await self._notify_state("ERROR")
                if self._client and self._client.connected:
                    try: await self._client.disconnect()
                    except Exception: pass
                self._client = None
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                continue
            except (
                InitialCursorMissingError,
                WebsocketURLMissingError,
                WebcastBlocked200Error,
                asyncio.TimeoutError,
            ) as e:
                # These mean "the server didn't give us a usable session
                # right now" — same outcome as offline. Switch to the
                # cheap-poll loop, NOT the fast-retry loop, so we don't
                # burn EulerStream credits on an unresolvable handshake.
                if not last_offline:
                    logger.info(
                        "@%s connect failed (%s); switching to cheap-poll mode.",
                        self._unique_id, e.__class__.__name__,
                    )
                last_offline = True
                last_sign_limited = False
                # A stale cached room_id can manifest as either of
                # these (the room id maps to a dead session). Force a
                # full probe next attempt.
                if cached_room_id is not None:
                    self._reused_room_id_failed = True
            except UserOfflineError:
                if not last_offline:
                    logger.info("@%s is offline; will retry on a slow cadence.", self._unique_id)
                last_offline = True
                last_sign_limited = False
                # If we tried the cached-room_id fast path and got
                # UserOffline, the broadcast may have ended — force a
                # fresh probe on the next attempt so we don't keep
                # banging on a dead room.
                if cached_room_id is not None:
                    self._reused_room_id_failed = True
            except SignatureRateLimitError:
                # EulerStream's sign API rate-limited us. Free tier is tiny;
                # retrying fast only deepens the hole. Back off HARD and
                # log once per transition. Set EULER_API_KEY for higher
                # quota: https://eulerstream.com
                if not last_sign_limited:
                    logger.warning(
                        "Sign-server rate-limited (EulerStream 429) for @%s — "
                        "backing off. Set EULER_API_KEY env var to raise the limit.",
                        self._unique_id,
                    )
                last_sign_limited = True
                last_offline = False
                if backoff < self.SIGN_RATE_LIMIT_INITIAL_BACKOFF:
                    backoff = self.SIGN_RATE_LIMIT_INITIAL_BACKOFF
            except Exception:
                # Anything else genuinely is unexpected — keep the loud log.
                logger.exception("TikTokLive supervisor error for @%s", self._unique_id)
                last_offline = False
                last_sign_limited = False

            # Whether we exited cleanly or threw, treat as disconnect + retry.
            if self._client and self._client.connected:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
            self._client = None
            await self._notify_state(
                "DISCONNECTED" if (last_offline or last_sign_limited) else "LIVE_ENDED"
            )

            if self._stopped:
                break

            # Offline path: instead of doubling the WebSocket reconnect
            # backoff (which used to grow to 15 min and made us miss
            # creators going live for that long), poll the cheap public
            # profile endpoint every 60s. That HTML scrape doesn't go
            # through EulerStream so it doesn't burn the sign budget;
            # as soon as `is_live` flips, we exit the wait loop and try
            # the WebSocket again immediately.
            if last_offline:
                await self._notify_state("DISCONNECTED")
                if await self._wait_until_live(poll_seconds=60):
                    backoff = self.INITIAL_BACKOFF
                    last_offline = False
                continue

            # Backoff before retry — sign-rate-limit slowest, generic 5s exp.
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            if last_sign_limited:
                cap = self.SIGN_RATE_LIMIT_MAX_BACKOFF
            else:
                cap = self.MAX_BACKOFF
            backoff = min(backoff * 2, cap)

    async def _wait_until_live(self, *, poll_seconds: float = 30) -> bool:
        """Wait for the creator to go live, reading the cached profile.

        IMPORTANT: sleeps `poll_seconds` BEFORE the first check, AND
        requires TWO consecutive positive reads (separated by another
        `poll_seconds`) before returning True.

        Why: TikTok's profile page reports `is_live=true` for a window
        AFTER a stream actually ends, while the WebSocket starts
        rejecting connections immediately. Without these guards the
        supervisor entered a tight loop:
          connect → UserOfflineError → cache (5-min TTL) still says
          live → return True instantly → reconnect → offline → … =
          one HTTP per second per supervisor, hundreds of req/min
          per worker.

        Sleeping first + double-confirmation absorbs that lag — the
        cost is up to `2 × poll_seconds` of detection latency when a
        creator does go live, which is acceptable.
        """
        # Initial cool-down: we just observed UserOfflineError; the
        # cached "live" value is suspect for at least one poll cycle.
        try:
            await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise

        consecutive_positive = 0
        while not self._stopped:
            is_live = await self._read_live_cache()
            if is_live is True:
                consecutive_positive += 1
                if consecutive_positive >= 2:
                    logger.info(
                        "@%s confirmed LIVE (2 consecutive positive reads) — "
                        "reconnecting WebSocket.",
                        self._unique_id,
                    )
                    return True
                # First positive read: don't trust it yet. Drop the
                # cached entry so the next read does a fresh scrape
                # instead of returning the same possibly-stale answer.
                _profile_cache.pop(self._unique_id.lstrip("@").strip(), None)
            else:
                consecutive_positive = 0
            try:
                await asyncio.sleep(poll_seconds)
            except asyncio.CancelledError:
                raise
        return False

    async def _read_live_cache(self) -> bool | None:
        """Look up live-status from the DB cache the worker's scraper
        maintains. On cache miss, fall back to a single throttled scrape
        so we don't sit blind for ~60s waiting for the scraper to find us.
        Returns True/False/None (= unknown)."""
        # Service is wired through the closure; reach the persistence
        # via the shared on_event callback's owning service. We don't
        # carry that reference here, so use a one-shot scrape on cache
        # miss as a lazy bootstrap. Subsequent waits read from the
        # central scraper's writes.
        try:
            profile = await fetch_public_profile_throttled(self._unique_id)
        except Exception:
            logger.debug(
                "live-cache lazy bootstrap raised for @%s",
                self._unique_id, exc_info=True,
            )
            return None
        if profile is None:
            return None
        v = profile.get("is_live")
        return bool(v) if v is not None else None

    def _wire_handlers(self, client: TikTokLiveClient) -> None:
        s = self

        # Hook the offset-gap tracker into the lib's batch parser.
        # `_parse_webcast_response` is called for every WebSocket frame;
        # we observe each message's `offset` field to detect gaps in the
        # monotonic stream. Loss within a single connection shows up as
        # a jump (offset N+5 right after N); inter-connection loss shows
        # up as disconnect_count.
        from adapters.tiktok_offset_tracker import gap_tracker
        try:
            original_parse = client._parse_webcast_response  # type: ignore[attr-defined]

            async def _parse_with_gap_tracking(webcast_response):
                try:
                    msgs = getattr(webcast_response, "messages", None) or []
                    if msgs:
                        gap_tracker.observe_batch(s._unique_id, msgs)
                except Exception:
                    logger.debug("gap_tracker.observe_batch failed", exc_info=True)
                async for ev in original_parse(webcast_response):
                    yield ev

            client._parse_webcast_response = _parse_with_gap_tracking  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Could not patch _parse_webcast_response for gap tracking", exc_info=True)

        @client.on(ConnectEvent)
        async def _on_connect(event: ConnectEvent) -> None:
            gap_tracker.on_connect(s._unique_id)
            await s._emit(
                "connected",
                {
                    "ts": _now(),
                    "unique_id": event.unique_id,
                    "room_id": client.room_id,
                },
                client.room_id,
            )

        @client.on(DisconnectEvent)
        async def _on_disconnect(_e: DisconnectEvent) -> None:
            gap_tracker.on_disconnect(s._unique_id)
            await s._emit("disconnected", {"ts": _now()}, client.room_id)

        @client.on(LiveEndEvent)
        async def _on_live_end(_e: LiveEndEvent) -> None:
            await s._emit("live_end", {"ts": _now()}, client.room_id)

        @client.on(CommentEvent)
        async def _on_comment(event: CommentEvent) -> None:
            await s._emit(
                "comment",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "user": _user_payload(event.user),
                    "text": event.comment,
                },
                client.room_id,
            )

        @client.on(GiftEvent)
        async def _on_gift(event: GiftEvent) -> None:
            # Skip intermediate combo events for streakable gifts (Rose,
            # Heart, etc.). TikTok fires one event per combo tick AND a
            # final aggregate event when the streak ends — `event.streaking`
            # is True for the in-progress ticks, False for the final.
            # Counting all of them double-records every gift.
            # See TikTokLive.events.GiftEvent.streaking docstring.
            if getattr(event, "streaking", False):
                return

            gift = getattr(event, "gift", None)
            # Icon URL: ExtendedGift exposes both `image` and `icon` as
            # ImageModel-shaped accessors. TikTokLive 6.6.x renamed the
            # URL-list field on ImageModel from `url_list` to `m_urls`;
            # we read both for cross-version compat.
            icon_url = None
            for attr in ("image", "icon"):
                img = getattr(gift, attr, None) if gift else None
                urls = (
                    getattr(img, "m_urls", None)
                    or getattr(img, "url_list", None)
                ) if img else None
                if urls:
                    icon_url = urls[0]
                    break
            diamond = getattr(gift, "diamond_count", None)
            if diamond is None:
                diamond = 0
            # `to_user` is the recipient. In a solo live this is the host;
            # in a multi-guest live or PK it's the specific anchor the
            # gifter targeted. Capture unconditionally so downstream can
            # decide whether to surface (frontend hides it when recipient
            # == host or is missing).
            to_user_obj = getattr(event, "to_user", None)
            payload = {
                "ts": _now(),
                "message_id": _msg_id(event),
                # Gift-specific identity: order_id is the TikTok gift-
                # transaction id. Carrying it alongside message_id makes
                # gift dedup auditable (you can prove "the same exact
                # transaction came in twice") even if message_id ever
                # changes lib-side.
                "order_id": getattr(event, "order_id", None) or None,
                "user": _user_payload(event.user),
                "gift_id": getattr(gift, "id", None),
                "gift_name": getattr(gift, "name", None),
                "gift_icon_url": icon_url,
                "diamond_count": diamond,
                "repeat_count": getattr(event, "repeat_count", 1),
                "streakable": getattr(gift, "streakable", False),
            }
            if to_user_obj is not None:
                payload["to_user"] = _user_payload(to_user_obj)
            await s._emit("gift", payload, client.room_id)

        @client.on(LikeEvent)
        async def _on_like(event: LikeEvent) -> None:
            # `total` is the room's cumulative like counter (matches what
            # TikTok shows on screen). Use it directly — `total_likes` is
            # an older alias that may be None on some payloads.
            total = getattr(event, "total", None)
            if total is None:
                total = getattr(event, "total_likes", None)
            await s._emit(
                "like",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "user": _user_payload(event.user),
                    "count": getattr(event, "count", 1),
                    "total": total,
                    "effect_cnt": getattr(event, "effect_cnt", None),
                },
                client.room_id,
            )

        @client.on(FollowEvent)
        async def _on_follow(event: FollowEvent) -> None:
            await s._emit(
                "follow",
                {"ts": _now(), "message_id": _msg_id(event), "user": _user_payload(event.user)},
                client.room_id,
            )

        @client.on(ShareEvent)
        async def _on_share(event: ShareEvent) -> None:
            await s._emit(
                "share",
                {"ts": _now(), "message_id": _msg_id(event), "user": _user_payload(event.user)},
                client.room_id,
            )

        @client.on(JoinEvent)
        async def _on_join(event: JoinEvent) -> None:
            await s._emit(
                "join",
                {"ts": _now(), "message_id": _msg_id(event), "user": _user_payload(event.user)},
                client.room_id,
            )

        @client.on(SubscribeEvent)
        async def _on_subscribe(event: SubscribeEvent) -> None:
            # SubscribeEvent carries tier / months-subscribed / promo state
            # that we previously dropped on the floor. Capture it all.
            await s._emit(
                "subscribe",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "user": _user_payload(event.user),
                    "sub_month": getattr(event, "sub_month", None),
                    "subscribe_type": getattr(event, "subscribe_type", None),
                    "subscribing_status": getattr(event, "subscribing_status", None),
                    "old_subscribe_status": getattr(event, "old_subscribe_status", None),
                    "package_id": getattr(event, "package_id", None),
                    "gift_source": getattr(event, "gift_source", None),
                    "is_custom": getattr(event, "is_custom", None),
                    "is_send": getattr(event, "is_send", None),
                    "exhibition_type": getattr(event, "exhibition_type", None),
                },
                client.room_id,
            )

        # ── viewer count + popularity ───────────────────────────────
        # RoomUserSeqEvent fires every few seconds with the current viewer
        # tally. Throttle aggressively — we just want a sample, not every
        # update — otherwise a popular live floods the events table.
        last_viewer_count_push = {"ts": 0.0, "value": -1}
        VIEWER_COUNT_MIN_INTERVAL = 30.0   # seconds
        VIEWER_COUNT_DELTA = 0.05          # 5% change forces an emit

        @client.on(RoomUserSeqEvent)
        async def _on_viewer_count(event: RoomUserSeqEvent) -> None:
            import time as _time
            total = getattr(event, "total_user", None)
            if total is None:
                total = getattr(event, "m_total", None)
            if total is None:
                return
            try:
                value = int(total)
            except (TypeError, ValueError):
                return
            now = _time.monotonic()
            prev_value = last_viewer_count_push["value"]
            elapsed = now - last_viewer_count_push["ts"]
            big_change = (
                prev_value <= 0
                or abs(value - prev_value) / max(1, prev_value) >= VIEWER_COUNT_DELTA
            )
            if elapsed < VIEWER_COUNT_MIN_INTERVAL and not big_change:
                return
            last_viewer_count_push["ts"] = now
            last_viewer_count_push["value"] = value
            popularity = getattr(event, "m_popularity", None) or getattr(event, "pop_str", None)
            await s._emit(
                "viewer_count",
                {
                    "ts": _now(),
                    "total": value,
                    "popularity": str(popularity) if popularity is not None else None,
                },
                client.room_id,
            )

        # ── red envelopes (revenue parallel to gifts) ───────────────
        @client.on(EnvelopeEvent)
        async def _on_envelope(event: EnvelopeEvent) -> None:
            info = getattr(event, "envelope_info", None)
            await s._emit(
                "envelope",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "envelope_id": getattr(info, "envelope_id", None) if info else None,
                    "user_id": getattr(info, "user_id", None) if info else None,
                    "diamond_count": getattr(info, "diamond_count", None) if info else None,
                    "delay_time": getattr(info, "delay_time", None) if info else None,
                    "type": getattr(info, "type", None) if info else None,
                },
                client.room_id,
            )

        # ── emoji-only chat (sticker reactions) ─────────────────────
        @client.on(EmoteChatEvent)
        async def _on_emote(event: EmoteChatEvent) -> None:
            emote_list = getattr(event, "emote_list", None) or []
            emotes: list[dict[str, Any]] = []
            for em in emote_list:
                emotes.append({
                    "emote_id": getattr(em, "emote_id", None),
                    "image_url": _first_url(getattr(em, "image", None)),
                })
            if not emotes:
                return
            await s._emit(
                "emote",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "user": _user_payload(event.user),
                    "emotes": emotes,
                },
                client.room_id,
            )

        # NOTE: caption / rank_text / rank_update capture intentionally
        # disabled. Captions were high-volume (~432k rows, 1-2/sec while
        # speaking) with no UI surface that justified the storage cost.
        # rank_* events only ever fired the in-room "Top Viewer" scene
        # (108 rows total) — not the regional/daily live leaderboard
        # operators actually want, and TikTok doesn't expose that one
        # through the WS data plane anyway. The lib still emits these
        # events; we just no longer subscribe.

        # ── interactive polls + Q&A ─────────────────────────────────
        @client.on(PollEvent)
        async def _on_poll(event: PollEvent) -> None:
            basic = getattr(event, "poll_basic_info", None)
            await s._emit(
                "poll",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "poll_id": getattr(event, "poll_id", None),
                    "poll_kind": getattr(event, "poll_kind", None),
                    "message_type": getattr(event, "message_type", None),
                    "title": getattr(basic, "title", None) if basic else None,
                    "options_count": (
                        len(getattr(basic, "options", []) or []) if basic else None
                    ),
                },
                client.room_id,
            )

        @client.on(QuestionNewEvent)
        async def _on_question(event: QuestionNewEvent) -> None:
            q = getattr(event, "question", None)
            if not q:
                return
            await s._emit(
                "question",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "question_id": getattr(q, "question_id", None) or getattr(q, "id", None),
                    # Question proto exposes the body as `content` —
                    # historical reads of `question_text` / `text` were
                    # silent-empty bugs; left as fallbacks for forward-
                    # compat in case the lib aliases them later.
                    "text": (
                        getattr(q, "content", None)
                        or getattr(q, "question_text", None)
                        or getattr(q, "text", None)
                    ),
                    "user": _user_payload(getattr(q, "user", None)),
                },
                client.room_id,
            )

        # ── gift collection progress (collect-N-of-X game mechanics) ─
        # TikTok runs "collection" promos where the room collectively
        # gifts a specific item to unlock an effect. The lib emits an
        # update every round so we can plot ramp-up: which gift is
        # being collected, which round, message_type 1=start 2=update
        # 3=close (TikTok docs are vague — we just store all three).
        @client.on(GiftCollectionUpdateEvent)
        async def _on_gift_collection(event: GiftCollectionUpdateEvent) -> None:
            gc = getattr(event, "gift_collection", None)
            if gc is None:
                return
            gift = getattr(gc, "gift", None)
            # `message_type` is a betterproto enum; coerce to int so the
            # JSONB column stores a plain number instead of "MessageType.X".
            mt = getattr(gc, "message_type", None)
            try:
                mt = int(mt) if mt is not None else None
            except (TypeError, ValueError):
                mt = str(mt) if mt is not None else None
            await s._emit(
                "gift_collection_update",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "round":           getattr(gc, "round", None),
                    "effect_name_key": getattr(gc, "effect_name_key", None) or None,
                    "message_type":    mt,
                    "is_filter_host":  bool(getattr(gc, "is_filter_host", False)) or None,
                    "schema_url":      getattr(gc, "schema_url", None) or None,
                    "gift": {
                        "id":   getattr(gift, "id", None) if gift else None,
                        "name": getattr(gift, "name", None) if gift else None,
                        "image_url": _first_url(getattr(gift, "image", None)) if gift else None,
                    } if gift else None,
                },
                client.room_id,
            )

        # ── live pause / unpause (creator briefly went silent) ──────
        # TikTok fires these when the creator hits the pause button or a
        # moderation tool intervened. Useful for marking gaps in the
        # broadcast timeline ("creator went away from camera for 4 min").
        @client.on(LivePauseEvent)
        async def _on_live_pause(_event: LivePauseEvent) -> None:
            await s._emit(
                "live_pause",
                {
                    "ts": _now(),
                    "tips": str(getattr(_event, "tips", "") or "") or None,
                },
                client.room_id,
            )

        @client.on(LiveUnpauseEvent)
        async def _on_live_unpause(_event: LiveUnpauseEvent) -> None:
            await s._emit(
                "live_unpause",
                {
                    "ts": _now(),
                    "tips": str(getattr(_event, "tips", "") or "") or None,
                },
                client.room_id,
            )

        # ── donations (TikTok Series / charity revenue parallel) ────
        # Money flowing in that ISN'T a gift. `total` is the donated
        # amount; `currency` is its denomination.
        @client.on(DonationEvent)
        async def _on_donation(event: DonationEvent) -> None:
            user_obj = getattr(event, "user", None) or getattr(event, "sponsor", None)
            await s._emit(
                "donation",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "user": _user_payload(user_obj),
                    "total": getattr(event, "total", None),
                    "currency": getattr(event, "currency", None),
                },
                client.room_id,
            )

        # ── PK / link-mic battles ───────────────────────────────────
        # `LinkMicBattleEvent` fires when a battle initiates or its config
        # is announced. `LinkMicArmiesEvent` fires periodically with team
        # scores. `LinkMicBattlePunishFinishEvent` and
        # `LinkMicBattleVictoryLapEvent` mark the end (we treat the first
        # arrival of either as the close signal).

        @client.on(LinkMicBattleEvent)
        async def _on_battle_start(event: LinkMicBattleEvent) -> None:
            opponents = _opponents_from_battle(event)
            scores = _team_scores(getattr(event, "team_armies", None))
            settings = _battle_settings_payload(event)
            await s._emit(
                "match_start",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "battle_id": getattr(event, "battle_id", None),
                    "opponents": opponents,
                    "scores": scores,
                    **settings,
                },
                client.room_id,
            )

        @client.on(LinkMicArmiesEvent)
        async def _on_battle_armies(event: LinkMicArmiesEvent) -> None:
            scores = _team_scores(getattr(event, "team_armies", None))
            opponent_scores = _opponents_from_armies_event(event)
            settings = _battle_settings_payload(event)
            await s._emit(
                "match_update",
                {
                    "message_id": _msg_id(event),
                    "ts": _now(),
                    "battle_id": getattr(event, "battle_id", None),
                    "scores": scores,
                    "opponent_scores": opponent_scores,
                    "total_diamond_count": getattr(event, "total_diamond_count", None),
                    **settings,
                },
                client.room_id,
            )

        @client.on(LinkMicBattlePunishFinishEvent)
        async def _on_battle_punish_finish(event: LinkMicBattlePunishFinishEvent) -> None:
            await s._emit(
                "match_end",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "battle_id": getattr(event, "battle_id", None),
                    "reason": "punish_finish",
                },
                client.room_id,
            )

        @client.on(LinkMicBattleVictoryLapEvent)
        async def _on_battle_victory_lap(event: LinkMicBattleVictoryLapEvent) -> None:
            await s._emit(
                "match_end",
                {
                    "ts": _now(),
                    "message_id": _msg_id(event),
                    "battle_id": getattr(event, "battle_id", None),
                    "reason": "victory_lap",
                },
                client.room_id,
            )

    async def _emit(self, type: str, payload: dict, room_id: int | None) -> None:
        try:
            await self._on_event(type=type, payload=payload, room_id=room_id)
        except Exception as e:
            # Inline-format the traceback so the framework's structured
            # logger doesn't swallow it. `logger.exception()` relies on
            # `exc_info` propagation that some custom formatters drop.
            # `type` shadows builtins.type here — get the class via __class__.
            import traceback as _tb
            tb_text = "".join(
                _tb.format_exception(e.__class__, e, e.__traceback__)
            )
            logger.error(
                "Event handler raised for @%s type=%s — %s: %s\n%s",
                self._unique_id, type, e.__class__.__name__, e, tb_text,
            )

    async def _notify_state(self, state: str) -> None:
        if self._on_state_change is None:
            return
        try:
            await self._on_state_change(state)
        except Exception:
            logger.exception("State callback raised for @%s state=%s", self._unique_id, state)

    async def _notify_terminal_error(self, kind: str, message: str) -> None:
        """Surface terminal connect-time errors (UserNotFoundError,
        AgeRestrictedError) to the service so they can be persisted to
        tiktok_worker_log + the listener-status snapshot, giving the UI
        a concrete reason instead of a bare ERROR state."""
        if self._on_terminal_error is None:
            return
        try:
            await self._on_terminal_error(kind, message)
        except Exception:
            logger.exception(
                "terminal-error callback raised for @%s kind=%s",
                self._unique_id, kind,
            )


class TikTokLiveSessionFactory(TikTokLiveSessionFactoryPort):
    """Factory for TikTokLiveSession. Trivial; matches the port signature."""

    def create(
        self,
        unique_id: str,
        on_event: Callable[..., Awaitable[None]],
        on_state_change: Callable[[str], Awaitable[None]] | None = None,
        on_terminal_error: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> TikTokLiveSessionPort:
        return TikTokLiveSession(
            unique_id=unique_id,
            on_event=on_event,
            on_state_change=on_state_change,
            on_terminal_error=on_terminal_error,
        )
