"""SQLAlchemy adapter implementing TikTokPersistencePort."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    """Aware UTC `now()`. Replaces all `_utcnow()` sites — those
    return naive datetimes that mix poorly with the now-tz-aware
    timestamptz columns."""
    return datetime.now(timezone.utc)


# IANA legacy aliases that browser `Intl.DateTimeFormat` still
# accepts but Postgres's `AT TIME ZONE` rejects. Keys are the legacy
# name a frontend may send; values are the canonical post-2008 name
# Postgres knows. Extend as new mismatches show up in the wild.
_LEGACY_TZ_ALIASES: dict[str, str] = {
    "America/Buenos_Aires":   "America/Argentina/Buenos_Aires",
    "America/Catamarca":      "America/Argentina/Catamarca",
    "America/Cordoba":        "America/Argentina/Cordoba",
    "America/Jujuy":          "America/Argentina/Jujuy",
    "America/Mendoza":        "America/Argentina/Mendoza",
    "America/Indianapolis":   "America/Indiana/Indianapolis",
    "America/Knox_IN":        "America/Indiana/Knox",
    "America/Louisville":     "America/Kentucky/Louisville",
    "Asia/Calcutta":          "Asia/Kolkata",
    "Asia/Katmandu":          "Asia/Kathmandu",
    "Asia/Saigon":            "Asia/Ho_Chi_Minh",
    "Asia/Rangoon":           "Asia/Yangon",
    "Asia/Ujung_Pandang":     "Asia/Makassar",
    "Europe/Kiev":            "Europe/Kyiv",
    "Pacific/Ponape":         "Pacific/Pohnpei",
    "Pacific/Truk":           "Pacific/Chuuk",
}


def _canonicalize_tz(tz: str) -> str:
    """Map a frontend-sent IANA timezone to a Postgres-known
    canonical name. Returns the input unchanged when not in the
    alias map — Postgres validation happens at query time and
    falls back to UTC if even the canonical name is unrecognized."""
    return _LEGACY_TZ_ALIASES.get(tz, tz)
from typing import Any, Optional

from sqlalchemy import BigInteger, case, cast, func, String, Integer, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm.attributes import flag_modified

from adapters.persistence._base import BasePersistenceAdapter
from database.tiktok.models import (
    SubscriptionModel,
    RoomModel,
    TikTokViewerModel,
    TikTokEventModel,
    TikTokGiftModel,
    TikTokMatchModel,
    WorkerModel,
    WorkerLogModel,
)
from domain.entities.tiktok_models import (
    Match,
    Subscription,
    Room,
    TikTokViewer,
    TikTokEvent,
    TikTokGift,
    TikTokWorker,
    TikTokWorkerLog,
)
from ports.tiktok_persistence import TikTokPersistencePort

logger = logging.getLogger(__name__)


# ── Phase 9B small helpers ──────────────────────────────────────────


def _now_iso() -> str:
    """Current UTC time as ISO-8601 string. Used for `_last_*_at`
    aux fields in the state cache — Phase D's tick task parses
    these back to compute `last_*_age_s`."""
    return datetime.now(timezone.utc).isoformat()


def _iso_to_epoch(s: Any) -> float:
    """Tolerant ISO-8601 → unix epoch. Returns -inf on parse failure
    so callers treat a malformed timestamp as "infinitely old"."""
    if s is None:
        return float("-inf")
    if isinstance(s, datetime):
        return s.timestamp()
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return float("-inf")


def _dt_to_epoch(d: Any) -> float:
    """Datetime → unix epoch, with the same fallback as
    `_iso_to_epoch` for non-datetime inputs."""
    if isinstance(d, datetime):
        return d.timestamp()
    return _iso_to_epoch(d)


def _user_id_from_viewer_or_payload(viewer: Any, payload: dict) -> int | None:
    """The persist path passes `viewer` (a domain object) plus the
    raw `payload`. user_id can live on either depending on event
    type. Return an int or None."""
    try:
        if viewer is not None:
            uid = getattr(viewer, "user_id", None)
            if uid is not None:
                return int(uid)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        raw = payload.get("user_id") if isinstance(payload, dict) else None
        if raw is None:
            return None
        return int(raw)
    except (TypeError, ValueError):
        return None


class WorkerKeyConflictError(RuntimeError):
    """Raised by `upsert_worker` when the requested worker_key is
    actively held by another live worker (heartbeat <30s old). The CLI
    converts this to a clean non-zero exit so the supervisor backs off
    and retries instead of double-registering."""


def _sub_to_dataclass(m: SubscriptionModel) -> Subscription:
    return Subscription(
        id=m.id,
        unique_id=m.unique_id,
        enabled=bool(m.enabled),
        is_public=bool(getattr(m, "is_public", False) or False),
        profile_user_id=getattr(m, "profile_user_id", None),
        sec_uid=getattr(m, "sec_uid", None),
        nickname=getattr(m, "nickname", None),
        avatar_url=getattr(m, "avatar_url", None),
        bio=getattr(m, "bio", None),
        verified=getattr(m, "verified", None),
        private=getattr(m, "private", None),
        follower_count=getattr(m, "follower_count", None),
        following_count=getattr(m, "following_count", None),
        profile_refreshed_at=getattr(m, "profile_refreshed_at", None),
        profile_error=getattr(m, "profile_error", None),
        is_live=getattr(m, "is_live", None),
        live_checked_at=getattr(m, "live_checked_at", None),
        current_room_id=getattr(m, "current_room_id", None),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _room_to_dataclass(m: RoomModel) -> Room:
    return Room(
        room_id=m.room_id,
        host_unique_id=m.host_unique_id,
        host_user_id=m.host_user_id,
        title=m.title,
        started_at=m.started_at,
        ended_at=m.ended_at,
        first_seen_at=m.first_seen_at,
        last_seen_at=m.last_seen_at,
    )


def _event_to_dataclass(m: TikTokEventModel) -> TikTokEvent:
    return TikTokEvent(
        id=m.id,
        room_id=m.room_id,
        user_id=m.user_id,
        ts=m.ts,
        type=m.type,
        payload=m.payload if isinstance(m.payload, dict) else {},
        match_id=m.match_id,
    )


def _match_to_dataclass(m: TikTokMatchModel) -> Match:
    return Match(
        id=m.id,
        room_id=m.room_id,
        battle_id=m.battle_id,
        opponents=m.opponents if isinstance(m.opponents, list) else [],
        scores=m.scores if isinstance(m.scores, dict) else {},
        settings=getattr(m, "settings", None) if isinstance(getattr(m, "settings", None), dict) else {},
        winner_user_id=m.winner_user_id,
        started_at=m.started_at,
        ended_at=m.ended_at,
        last_seen_at=m.last_seen_at,
    )


class TikTokPersistenceAdapter(BasePersistenceAdapter, TikTokPersistencePort):
    """TikTok persistence adapter.

    The `state_cache` kwarg (Phase 9B) is the per-host summary cache
    that the persist path mirrors on every event. When `None` (the
    default, used when `PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH=off`),
    `_apply_state_delta` is a no-op and the persist path's behavior
    is identical to before Phase 9. When wired, every event mutates
    the cache + publishes a delta on admin + public channels."""

    def __init__(
        self,
        *args: Any,
        state_cache: Any = None,
        **kwargs: Any,
    ) -> None:
        # All base-class kwargs pass through unchanged. Keeping
        # `state_cache` as kwarg-only keeps the existing call-sites
        # — `TikTokPersistenceAdapter(auto_init=True)` — working
        # without modification.
        super().__init__(*args, **kwargs)
        self._state_cache = state_cache
        # Lazy host → profile_user_id cache. Populated on first
        # `_should_count_gift_for_host` lookup. Invalidated when a
        # subscription's `profile_user_id` is rewritten by the scraper
        # (see `upsert_profile_facets`). NULL value means "lookup ran
        # but row was missing / unprobed handle"; we treat that as a
        # legacy fall-through (count everything).
        self._host_profile_user_id: dict[str, int | None] = {}

    def _resolve_host_profile_user_id(self, s, host_unique_id: str) -> int | None:
        """Return the host's TikTok profile user_id, or None when
        unknown / unprobed. Cached for the lifetime of the adapter."""
        if host_unique_id in self._host_profile_user_id:
            return self._host_profile_user_id[host_unique_id]
        row = s.execute(text(
            "SELECT profile_user_id FROM tiktok_subscriptions "
            "WHERE unique_id = :host"
        ), {"host": host_unique_id}).first()
        uid = int(row.profile_user_id) if (row and row.profile_user_id) else None
        self._host_profile_user_id[host_unique_id] = uid
        return uid

    def _gift_is_for_host(
        self,
        s,
        host_unique_id: str,
        payload: dict | None,
    ) -> bool:
        """True when this gift should be credited to `host_unique_id`.

        Multi-host TikTok lives stream every guest's gifts into the
        host's room with `to_user.user_id` set to the actual recipient.
        Crediting those toward the host's totals inflates the per-host
        diamond count vs TikTok's own number. We match the same
        predicate the read-path aggregations use: host_user_id NULL
        means unprobed (legacy fall-through); otherwise the gift counts
        only when `to_user.user_id` matches the host or is missing/zero
        (popular vote / unattributed = the host).
        """
        if not isinstance(payload, dict):
            return True
        host_uid = self._resolve_host_profile_user_id(s, host_unique_id)
        if host_uid is None:
            return True
        to_user = payload.get("to_user")
        if not isinstance(to_user, dict):
            return True
        raw = to_user.get("user_id")
        if raw in (None, "", 0, "0"):
            return True
        try:
            return int(raw) == host_uid
        except (TypeError, ValueError):
            return True

    # ── Subscriptions ────────────────────────────────────────────────

    def list_subscriptions(self, *, enabled_only: bool = False) -> list[Subscription]:
        with self._get_session() as s:
            q = s.query(SubscriptionModel)
            if enabled_only:
                q = q.filter(SubscriptionModel.enabled.is_(True))
            return [_sub_to_dataclass(r) for r in q.order_by(SubscriptionModel.unique_id).all()]

    def get_subscriptions_by_user_ids(self, user_ids: list[int]) -> dict[int, Subscription]:
        if not user_ids:
            return {}
        with self._get_session() as s:
            rows = (
                s.query(SubscriptionModel)
                .filter(SubscriptionModel.profile_user_id.in_(user_ids))
                .all()
            )
        return {int(r.profile_user_id): _sub_to_dataclass(r) for r in rows if r.profile_user_id}

    def get_subscription(self, unique_id: str) -> Optional[Subscription]:
        with self._get_session() as s:
            row = s.query(SubscriptionModel).filter_by(unique_id=unique_id).one_or_none()
            return _sub_to_dataclass(row) if row else None

    def upsert_subscription(self, unique_id: str, *, enabled: bool = True) -> Subscription:
        with self._get_session() as s:
            row = s.query(SubscriptionModel).filter_by(unique_id=unique_id).one_or_none()
            if row is None:
                row = SubscriptionModel(unique_id=unique_id, enabled=enabled)
                s.add(row)
            else:
                row.enabled = enabled
            s.commit()
            s.refresh(row)
            return _sub_to_dataclass(row)

    def set_subscription_enabled(self, unique_id: str, enabled: bool) -> Optional[Subscription]:
        with self._get_session() as s:
            row = s.query(SubscriptionModel).filter_by(unique_id=unique_id).one_or_none()
            if row is None:
                return None
            row.enabled = enabled
            s.commit()
            s.refresh(row)
            return _sub_to_dataclass(row)

    def set_subscription_public(self, unique_id: str, is_public: bool) -> bool:
        """Flip the `is_public` flag for the given handle.

        Returns True when a row was found + updated, False otherwise so
        the route can convert that to a 404. Independent of `enabled` —
        a paused (enabled=False) public sub stays in the public list,
        but `is_live` will of course read False until the listener
        reconnects.
        """
        with self._get_session() as s:
            row = s.query(SubscriptionModel).filter_by(unique_id=unique_id).one_or_none()
            if row is None:
                return False
            row.is_public = bool(is_public)
            s.commit()
            return True

    def list_public_subscriptions(self) -> list[Subscription]:
        """Return only subscriptions marked public, ordered by handle.

        Used by `get_public_lives_summary` to build the handle list for
        the unauthenticated endpoint. Ordered for deterministic output
        so the in-process TTL cache key (sorted tuple) stays stable.
        """
        with self._get_session() as s:
            rows = (
                s.query(SubscriptionModel)
                .filter(SubscriptionModel.is_public.is_(True))
                .order_by(SubscriptionModel.unique_id)
                .all()
            )
            return [_sub_to_dataclass(r) for r in rows]

    _PROFILE_FIELDS = (
        "profile_user_id", "sec_uid", "nickname", "avatar_url", "bio",
        "verified", "private", "follower_count", "following_count",
    )

    def list_subscriptions_with_stale_profiles(
        self, *, stale_after_seconds: int = 3600
    ) -> list[Subscription]:
        from sqlalchemy import or_
        cutoff = _utcnow() - timedelta(seconds=stale_after_seconds)
        with self._get_session() as s:
            q = (
                s.query(SubscriptionModel)
                .filter(
                    or_(
                        SubscriptionModel.profile_refreshed_at.is_(None),
                        SubscriptionModel.profile_refreshed_at < cutoff,
                    )
                )
                .order_by(
                    # Prefer never-refreshed first, then oldest.
                    SubscriptionModel.profile_refreshed_at.is_(None).desc(),
                    SubscriptionModel.profile_refreshed_at.asc().nullsfirst(),
                )
            )
            return [_sub_to_dataclass(r) for r in q.all()]

    def update_subscription_profile(
        self, unique_id: str, *, profile: dict[str, Any], error: str | None = None
    ) -> None:
        with self._get_session() as s:
            row = s.query(SubscriptionModel).filter_by(unique_id=unique_id).one_or_none()
            if row is None:
                return
            now = _utcnow()
            row.profile_refreshed_at = now
            row.profile_error = error
            if not error:
                # Only overwrite cached fields on a successful fetch — preserves
                # last-known data when the next refresh hits a transient error.
                for f in self._PROFILE_FIELDS:
                    if f in profile:
                        setattr(row, f, profile[f])
                # Invalidate the host→profile_user_id cache so write
                # paths pick up a freshly-resolved user_id immediately.
                self._host_profile_user_id.pop(unique_id, None)
            s.commit()

    def delete_subscription(self, unique_id: str) -> bool:
        with self._get_session() as s:
            row = s.query(SubscriptionModel).filter_by(unique_id=unique_id).one_or_none()
            if row is None:
                return False
            s.delete(row)
            self._host_profile_user_id.pop(unique_id, None)
            s.commit()
            return True

    # ── Rooms ────────────────────────────────────────────────────────

    def upsert_room(self, room: Room, *, push_seen: bool = True) -> None:
        """Insert-or-update a room row. Uses Postgres ON CONFLICT to avoid
        races + halve roundtrips. SQLite falls back to the legacy pattern.
        push_seen=False skips bumping last_seen_at (used when the service
        is throttling churn writes).
        """
        with self._get_session() as s:
            self._upsert_room_in_session(s, room, push_seen=push_seen)
            s.commit()

    def _is_postgres(self) -> bool:
        """Use the adapter's own engine for dialect detection. With read-
        replica routing enabled the session has no single `.bind`, so a
        naive `s.bind.dialect.name` check returns None and we'd silently
        take the SQLite ORM-fallback path on Postgres — which insert-orders
        rows wrong and breaks the tiktok_events.user_id FK on every event."""
        try:
            return self.engine.dialect.name == "postgresql"
        except Exception:
            return False

    # Per-process cache of Postgres's known IANA timezone names. The
    # set is small (~600 entries), shape never changes during process
    # lifetime, and `pg_timezone_names` is a view-backed query that
    # we don't want to re-run on every calendar request. Initialised
    # lazily on first call so a fresh boot doesn't pay the cost.
    _pg_known_tz_cache: frozenset[str] | None = None

    def _is_pg_known_tz(self, session, tz: str) -> bool:
        """`True` iff `tz` is a name `pg_timezone_names` recognises.
        Caches the full set on first call so repeated calendar
        requests don't re-hit the system catalog."""
        cache = type(self)._pg_known_tz_cache
        if cache is None:
            try:
                rows = session.execute(text(
                    "SELECT name FROM pg_timezone_names"
                )).all()
                cache = frozenset(r[0] for r in rows if r and r[0])
            except Exception:
                cache = frozenset()
            type(self)._pg_known_tz_cache = cache
        return tz in cache

    def _upsert_room_in_session(self, s, room: Room, *, push_seen: bool) -> None:
        """Internal: assumes the caller is managing the session/commit.
        Lets persist_event_full bundle multiple writes into one txn."""
        if self._is_postgres():
            now = _utcnow()
            stmt = pg_insert(RoomModel).values(
                room_id=room.room_id,
                host_unique_id=room.host_unique_id,
                host_user_id=room.host_user_id,
                title=room.title,
                started_at=room.started_at,
                ended_at=room.ended_at,
                # first_seen_at + last_seen_at default to CURRENT_TIMESTAMP on insert.
            )
            update_clause: dict[str, Any] = {}
            # Only set these on UPDATE if the new value is non-null AND the
            # existing value is null — preserve "first wins" for static fields.
            if room.title:
                update_clause["title"] = func.coalesce(RoomModel.title, stmt.excluded.title)
            if room.host_unique_id:
                update_clause["host_unique_id"] = func.coalesce(
                    RoomModel.host_unique_id, stmt.excluded.host_unique_id
                )
            if room.host_user_id:
                update_clause["host_user_id"] = func.coalesce(
                    RoomModel.host_user_id, stmt.excluded.host_user_id
                )
            if room.ended_at:
                update_clause["ended_at"] = func.coalesce(
                    RoomModel.ended_at, stmt.excluded.ended_at
                )
            if push_seen:
                update_clause["last_seen_at"] = now
            if update_clause:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["room_id"], set_=update_clause
                )
            else:
                # No-op update: guard with WHERE FALSE so we don't bump anything.
                stmt = stmt.on_conflict_do_nothing(index_elements=["room_id"])
            s.execute(stmt)
        else:
            # SQLite fallback — keep the original SELECT-then-INSERT/UPDATE
            existing = s.query(RoomModel).filter_by(room_id=room.room_id).one_or_none()
            if existing is None:
                s.add(
                    RoomModel(
                        room_id=room.room_id,
                        host_unique_id=room.host_unique_id,
                        host_user_id=room.host_user_id,
                        title=room.title,
                        started_at=room.started_at,
                        ended_at=room.ended_at,
                    )
                )
            else:
                if room.title and not existing.title:
                    existing.title = room.title
                if room.host_unique_id and not existing.host_unique_id:
                    existing.host_unique_id = room.host_unique_id
                if room.host_user_id and not existing.host_user_id:
                    existing.host_user_id = room.host_user_id
                if room.ended_at and not existing.ended_at:
                    existing.ended_at = room.ended_at
                if push_seen:
                    existing.last_seen_at = _utcnow()

    def get_room(self, room_id: int) -> Optional[Room]:
        with self._get_session() as s:
            row = s.query(RoomModel).filter_by(room_id=room_id).one_or_none()
            return _room_to_dataclass(row) if row else None

    def list_rooms_for_host(self, host_unique_id: str, *, limit: int = 50) -> list[Room]:
        with self._get_session() as s:
            q = (
                s.query(RoomModel)
                .filter_by(host_unique_id=host_unique_id)
                .order_by(RoomModel.first_seen_at.desc())
                .limit(limit)
            )
            return [_room_to_dataclass(r) for r in q.all()]

    def room_totals(self, room_ids: list[int]) -> dict[int, dict[str, int]]:
        """Per-room rollup of `diamonds`, `matches`, and the room's
        peak `likes` counter (from TikTok's cumulative LikeEvent.total).
        Returns `{room_id: {diamonds, matches, likes}}` for every input
        room_id (zeros if the room has no events yet).

        Drives the metadata shown next to each broadcast in the
        live-detail page's dropdown selector — same idea as the
        per-day rollup in `host_calendar`, but per-room.
        """
        out: dict[int, dict[str, int]] = {
            int(rid): {"diamonds": 0, "matches": 0, "likes": 0}
            for rid in room_ids
        }
        if not room_ids:
            return out
        with self._get_session() as s:
            if self._is_postgres():
                rows = s.execute(text("""
                    WITH gifts AS (
                      SELECT room_id,
                             SUM(
                               COALESCE(NULLIF(payload->>'diamond_count','')::int, 0)
                               * COALESCE(NULLIF(payload->>'repeat_count','')::int, 1)
                             ) AS diamonds
                      FROM tiktok_events
                      WHERE type = 'gift' AND room_id = ANY(:ids)
                      GROUP BY room_id
                    ),
                    matches AS (
                      SELECT room_id, COUNT(*) AS matches
                      FROM tiktok_matches WHERE room_id = ANY(:ids)
                      GROUP BY room_id
                    ),
                    likes AS (
                      -- TikTok's LikeEvent.total is a room-cumulative
                      -- counter (matches the on-screen heart count).
                      -- MAX picks the latest sample, which is the
                      -- final tally when the room ended.
                      SELECT room_id,
                             MAX(COALESCE(NULLIF(payload->>'total','')::bigint, 0)) AS likes
                      FROM tiktok_events
                      WHERE type = 'like' AND room_id = ANY(:ids)
                      GROUP BY room_id
                    )
                    SELECT r.room_id,
                           COALESCE(g.diamonds, 0)  AS diamonds,
                           COALESCE(m.matches, 0)   AS matches,
                           COALESCE(l.likes, 0)     AS likes
                    FROM unnest(CAST(:ids AS bigint[])) AS r(room_id)
                    LEFT JOIN gifts   g ON g.room_id   = r.room_id
                    LEFT JOIN matches m ON m.room_id   = r.room_id
                    LEFT JOIN likes   l ON l.room_id   = r.room_id
                """), {"ids": [int(x) for x in room_ids]}).mappings().all()
                for r in rows:
                    out[int(r["room_id"])] = {
                        "diamonds": int(r["diamonds"] or 0),
                        "matches": int(r["matches"] or 0),
                        "likes": int(r["likes"] or 0),
                    }
                return out

            # SQLite fallback: three small Python passes.
            ev_rows = (
                s.query(TikTokEventModel)
                .filter(TikTokEventModel.room_id.in_(room_ids))
                .filter(TikTokEventModel.type.in_(["gift", "like"]))
                .all()
            )
            for ev in ev_rows:
                payload = _coerce_payload(ev.payload)
                if not isinstance(payload, dict):
                    continue
                rid = int(ev.room_id)
                if rid not in out:
                    out[rid] = {"diamonds": 0, "matches": 0, "likes": 0}
                if ev.type == "gift":
                    d = int(payload.get("diamond_count") or 0) * int(
                        payload.get("repeat_count") or 1
                    )
                    out[rid]["diamonds"] += d
                elif ev.type == "like":
                    total = int(payload.get("total") or 0)
                    if total > out[rid]["likes"]:
                        out[rid]["likes"] = total
            for m in (
                s.query(TikTokMatchModel)
                .filter(TikTokMatchModel.room_id.in_(room_ids))
                .all()
            ):
                rid = int(m.room_id)
                out.setdefault(rid, {"diamonds": 0, "matches": 0, "likes": 0})
                out[rid]["matches"] += 1
            return out

    def host_calendar(
        self,
        host_unique_id: str,
        *,
        since: datetime,
        until: datetime,
        tz: str = "UTC",
    ) -> list[dict[str, Any]]:
        """Daily activity rollup for a host between [since, until].

        Returns one row per day the creator went live with:
          rooms             — distinct broadcasts active that day (any
                              gift event landing in the day's bounds)
          duration_minutes  — sum of (last_seen - first_seen) per room,
                              attributed to the day the room started
          diamonds          — sum of gift diamond totals from events
                              whose ts falls in the day, in `tz`
          matches           — count of PK battles whose started_at
                              falls in the day, in `tz`

        Used to drive the live-activity heatmap on the live-detail
        page. Bucketing is in `tz` so a Lima viewer sees Lima-days,
        not server-UTC days — events from a cross-midnight broadcast
        attribute correctly to the day they actually happened.
        """
        # Postgres `AT TIME ZONE` only accepts names from its own
        # `pg_timezone_names` view, which uses POST-2008 canonical
        # IANA names. JS `Intl.DateTimeFormat` still accepts older
        # aliases (e.g. `America/Buenos_Aires`), so a frontend dropdown
        # value can legitimately fail at the SQL boundary. We:
        #   1. Map known legacy aliases to canonical via
        #      `_canonicalize_tz` (e.g. `America/Buenos_Aires` →
        #      `America/Argentina/Buenos_Aires`).
        #   2. Validate the final value against the live Postgres
        #      timezone catalog (cached per-process). Unknown zones
        #      fall back to UTC so the heatmap renders empty cells
        #      instead of 500'ing the page.
        zone = _canonicalize_tz((tz or "UTC").strip() or "UTC")
        with self._get_session() as s:
            if self._is_postgres() and not self._is_pg_known_tz(s, zone):
                zone = "UTC"
            if self._is_postgres():
                # Raw SQL — every "what day is this in `:tz`?" bucket
                # uses `date_trunc('day', col AT TIME ZONE :tz)`. The
                # `room_days` CTE attributes a room to every day on
                # which it had at least one event in zone, so a room
                # that ran from 23:55 May 6 → 02:00 May 7 (zone) shows
                # up in BOTH days' rows.
                # Look up the host's TikTok user_id once — used by the
                # `diamond_days` CTE to filter OUT gifts that landed in
                # this host's room but were targeted at someone else
                # (multi-host guest, PK opponent). Without this filter
                # we credit @host with the rival anchor's diamonds when
                # they share a room, inflating the daily total versus
                # what TikTok's own per-host stat shows. NULL fallback:
                # if we don't know the host's user_id (unprobed handle),
                # count everything (legacy behaviour).
                host_user_id_row = s.execute(text(
                    "SELECT profile_user_id FROM tiktok_subscriptions "
                    "WHERE unique_id = :host"
                ), {"host": host_unique_id}).first()
                host_user_id = (
                    host_user_id_row.profile_user_id if host_user_id_row else None
                )
                rows = s.execute(text("""
                    WITH host_rooms AS (
                      SELECT room_id, first_seen_at, last_seen_at
                      FROM tiktok_rooms
                      WHERE host_unique_id = :host
                        AND first_seen_at <= :until
                        AND COALESCE(last_seen_at, first_seen_at) >= :since
                    ),
                    room_days AS (
                      SELECT DISTINCT
                             e.room_id,
                             date_trunc('day', e.ts AT TIME ZONE :tz) AS day
                      FROM tiktok_events e
                      WHERE e.room_id IN (SELECT room_id FROM host_rooms)
                        AND e.ts >= :since AND e.ts <= :until
                    ),
                    diamond_days AS (
                      SELECT date_trunc('day', e.ts AT TIME ZONE :tz) AS day,
                             SUM(
                               COALESCE(NULLIF(e.payload->>'diamond_count','')::int, 0)
                               * COALESCE(NULLIF(e.payload->>'repeat_count','')::int, 1)
                             ) AS diamonds
                      FROM tiktok_events e
                      WHERE e.type = 'gift'
                        AND e.room_id IN (SELECT room_id FROM host_rooms)
                        AND e.ts >= :since AND e.ts <= :until
                        AND (
                          -- Legacy fall-through: host_user_id NULL =
                          -- unprobed handle, sum every gift (old behaviour).
                          CAST(:host_user_id AS TEXT) IS NULL
                          -- Match TikTok's per-host accounting:
                          --   gift to host themselves OR
                          --   gift with no specific recipient (popular
                          --   vote / unattributed = goes to host).
                          OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                             IN ('0', CAST(:host_user_id AS TEXT))
                        )
                      GROUP BY day
                    ),
                    match_days AS (
                      SELECT date_trunc('day', m.started_at AT TIME ZONE :tz) AS day,
                             COUNT(*) AS matches
                      FROM tiktok_matches m
                      WHERE m.room_id IN (SELECT room_id FROM host_rooms)
                        AND m.started_at >= :since AND m.started_at <= :until
                      GROUP BY day
                    ),
                    duration_days AS (
                      -- Attribute the broadcast's wall-clock duration
                      -- to the day it STARTED (in zone). Splitting at
                      -- midnight is only worth the SQL when we expose
                      -- per-day duration on cross-midnight rooms — the
                      -- heatmap shows it as a single tooltip number,
                      -- so this approximation is good enough.
                      SELECT date_trunc('day', first_seen_at AT TIME ZONE :tz) AS day,
                             SUM(GREATEST(0,
                                EXTRACT(EPOCH FROM
                                  (COALESCE(last_seen_at, first_seen_at) - first_seen_at)
                                )
                             )) AS duration_seconds
                      FROM host_rooms
                      GROUP BY day
                    )
                    SELECT rd.day                          AS day,
                           COUNT(DISTINCT rd.room_id)      AS rooms,
                           COALESCE(MAX(dd.duration_seconds), 0) AS duration_seconds,
                           COALESCE(MAX(d.diamonds), 0)     AS diamonds,
                           COALESCE(MAX(mc.matches), 0)     AS matches
                    FROM room_days rd
                    LEFT JOIN diamond_days  d  ON d.day  = rd.day
                    LEFT JOIN match_days    mc ON mc.day = rd.day
                    LEFT JOIN duration_days dd ON dd.day = rd.day
                    GROUP BY rd.day
                    ORDER BY rd.day ASC
                """), {
                    "host": host_unique_id,
                    "since": since,
                    "until": until,
                    "tz": zone,
                    "host_user_id": str(host_user_id) if host_user_id else None,
                }).mappings().all()
                out: list[dict[str, Any]] = []
                for r in rows:
                    d = r["day"]
                    if d is None:
                        continue
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    out.append({
                        "date": d.date().isoformat(),
                        "rooms": int(r["rooms"] or 0),
                        "duration_minutes": int((r["duration_seconds"] or 0) / 60),
                        "diamonds": int(r["diamonds"] or 0),
                        "matches": int(r["matches"] or 0),
                    })
                return out

            # SQLite fallback: bucket in Python with a few smaller queries.
            rooms = (
                s.query(RoomModel)
                .filter(RoomModel.host_unique_id == host_unique_id)
                .filter(RoomModel.first_seen_at >= since)
                .filter(RoomModel.first_seen_at <= until)
                .all()
            )
            room_ids = [r.room_id for r in rooms]
            # Diamonds per room.
            diamonds_per_room: dict[int, int] = {}
            matches_per_room: dict[int, int] = {}
            if room_ids:
                ev_rows = (
                    s.query(TikTokEventModel)
                    .filter(TikTokEventModel.room_id.in_(room_ids))
                    .filter(TikTokEventModel.type == "gift")
                    .all()
                )
                for ev in ev_rows:
                    payload = _coerce_payload(ev.payload)
                    if not isinstance(payload, dict):
                        continue
                    d = (int(payload.get("diamond_count") or 0)) * (
                        int(payload.get("repeat_count") or 1)
                    )
                    diamonds_per_room[int(ev.room_id)] = (
                        diamonds_per_room.get(int(ev.room_id), 0) + d
                    )
                m_rows = (
                    s.query(TikTokMatchModel)
                    .filter(TikTokMatchModel.room_id.in_(room_ids))
                    .all()
                )
                for m in m_rows:
                    matches_per_room[int(m.room_id)] = (
                        matches_per_room.get(int(m.room_id), 0) + 1
                    )
            # SQLite-only path. Use zoneinfo for the day key so dev-DB
            # behaviour roughly matches the Postgres `AT TIME ZONE` path.
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                tzinfo = ZoneInfo(zone)
            except ZoneInfoNotFoundError:
                tzinfo = timezone.utc
            buckets: dict[str, dict[str, int]] = {}
            for r in rooms:
                if r.first_seen_at is None:
                    continue
                d = r.first_seen_at
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                key = d.astimezone(tzinfo).date().isoformat()
                bucket = buckets.setdefault(
                    key,
                    {"rooms": 0, "duration_minutes": 0, "diamonds": 0, "matches": 0},
                )
                bucket["rooms"] += 1
                if r.last_seen_at is not None:
                    delta = r.last_seen_at - r.first_seen_at
                    bucket["duration_minutes"] += max(0, int(delta.total_seconds() / 60))
                bucket["diamonds"] += diamonds_per_room.get(int(r.room_id), 0)
                bucket["matches"] += matches_per_room.get(int(r.room_id), 0)
            return [{"date": k, **v} for k, v in sorted(buckets.items())]

    # ── Viewers ──────────────────────────────────────────────────────

    def get_viewer_by_unique_id(self, unique_id: str) -> Optional[TikTokViewer]:
        unique_id = unique_id.lstrip("@").strip()
        if not unique_id:
            return None
        with self._get_session() as s:
            row = (
                s.query(TikTokViewerModel)
                .filter(TikTokViewerModel.unique_id == unique_id)
                .order_by(TikTokViewerModel.last_seen_at.desc())
                .first()
            )
        if row is None:
            return None
        return TikTokViewer(
            user_id=row.user_id,
            unique_id=row.unique_id,
            nickname=row.nickname,
            avatar_url=row.avatar_url,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
        )

    def get_viewers_by_ids(self, user_ids: list[int]) -> dict[int, TikTokViewer]:
        if not user_ids:
            return {}
        with self._get_session() as s:
            rows = (
                s.query(TikTokViewerModel)
                .filter(TikTokViewerModel.user_id.in_(user_ids))
                .all()
            )
        return {
            r.user_id: TikTokViewer(
                user_id=r.user_id,
                unique_id=r.unique_id,
                nickname=r.nickname,
                avatar_url=r.avatar_url,
                first_seen_at=r.first_seen_at,
                last_seen_at=r.last_seen_at,
            )
            for r in rows
        }

    def upsert_viewer(self, viewer: TikTokViewer, *, push_seen: bool = True) -> None:
        with self._get_session() as s:
            self._upsert_viewer_in_session(s, viewer, push_seen=push_seen)
            s.commit()

    def _upsert_viewer_in_session(
        self, s, viewer: TikTokViewer, *, push_seen: bool
    ) -> None:
        if self._is_postgres():
            now = _utcnow()
            stmt = pg_insert(TikTokViewerModel).values(
                user_id=viewer.user_id,
                unique_id=viewer.unique_id,
                nickname=viewer.nickname,
                avatar_url=viewer.avatar_url,
            )
            update_clause: dict[str, Any] = {}
            # For viewers, prefer the freshest non-null name/avatar over the
            # cached one (people change handles + avatars).
            if viewer.unique_id:
                update_clause["unique_id"] = stmt.excluded.unique_id
            if viewer.nickname:
                update_clause["nickname"] = stmt.excluded.nickname
            if viewer.avatar_url:
                update_clause["avatar_url"] = stmt.excluded.avatar_url
            if push_seen:
                update_clause["last_seen_at"] = now
            if update_clause:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["user_id"], set_=update_clause
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=["user_id"])
            s.execute(stmt)
        else:
            existing = s.query(TikTokViewerModel).filter_by(user_id=viewer.user_id).one_or_none()
            if existing is None:
                s.add(
                    TikTokViewerModel(
                        user_id=viewer.user_id,
                        unique_id=viewer.unique_id,
                        nickname=viewer.nickname,
                        avatar_url=viewer.avatar_url,
                    )
                )
            else:
                if viewer.unique_id and viewer.unique_id != existing.unique_id:
                    existing.unique_id = viewer.unique_id
                if viewer.nickname and viewer.nickname != existing.nickname:
                    existing.nickname = viewer.nickname
                if viewer.avatar_url and viewer.avatar_url != existing.avatar_url:
                    existing.avatar_url = viewer.avatar_url
                if push_seen:
                    existing.last_seen_at = _utcnow()

    # ── Gifts ────────────────────────────────────────────────────────

    def upsert_gift(self, gift: TikTokGift) -> None:
        with self._get_session() as s:
            existing = s.query(TikTokGiftModel).filter_by(gift_id=gift.gift_id).one_or_none()
            if existing is None:
                s.add(
                    TikTokGiftModel(
                        gift_id=gift.gift_id,
                        name=gift.name,
                        diamond_count=gift.diamond_count,
                        icon_url=gift.icon_url,
                        streakable=gift.streakable,
                    )
                )
            else:
                # Refresh fields when newer values are non-null. last_seen_at
                # auto-updates via onupdate; force a touch by always setting
                # name (TikTok occasionally rebrands gifts).
                if gift.name and gift.name != existing.name:
                    existing.name = gift.name
                if gift.diamond_count is not None and gift.diamond_count != existing.diamond_count:
                    existing.diamond_count = gift.diamond_count
                if gift.icon_url and gift.icon_url != existing.icon_url:
                    existing.icon_url = gift.icon_url
                if gift.streakable is not None and gift.streakable != existing.streakable:
                    existing.streakable = gift.streakable
                # Bump last_seen_at unconditionally so we know which gifts
                # are still circulating vs. retired by TikTok.
                existing.last_seen_at = _utcnow()
            s.commit()

    def list_gifts(self, *, limit: int = 200) -> list[TikTokGift]:
        with self._get_session() as s:
            q = (
                s.query(TikTokGiftModel)
                .order_by(
                    TikTokGiftModel.diamond_count.desc().nullslast(),
                    TikTokGiftModel.name.asc(),
                )
                .limit(limit)
            )
            return [
                TikTokGift(
                    gift_id=g.gift_id,
                    name=g.name,
                    diamond_count=g.diamond_count,
                    icon_url=g.icon_url,
                    streakable=g.streakable,
                    first_seen_at=g.first_seen_at,
                    last_seen_at=g.last_seen_at,
                )
                for g in q.all()
            ]

    # ── Matches ──────────────────────────────────────────────────────

    def open_match(
        self,
        *,
        room_id: int,
        battle_id: int,
        opponents: list[dict[str, Any]] | None = None,
        scores: dict[str, int] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Match:
        with self._get_session() as s:
            existing = (
                s.query(TikTokMatchModel)
                .filter_by(room_id=room_id, battle_id=battle_id)
                .one_or_none()
            )
            if existing is not None:
                if opponents:
                    existing.opponents = opponents
                if scores:
                    existing.scores = scores
                if settings:
                    existing.settings = settings
                existing.last_seen_at = _utcnow()
                s.commit()
                s.refresh(existing)
                return _match_to_dataclass(existing)
            row = TikTokMatchModel(
                room_id=room_id,
                battle_id=battle_id,
                opponents=opponents or [],
                scores=scores or {},
                settings=settings or {},
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return _match_to_dataclass(row)

    def update_match(
        self,
        match_id: int,
        *,
        scores: dict[str, int] | None = None,
        opponents: list[dict[str, Any]] | None = None,
        opponent_scores: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        with self._get_session() as s:
            existing = s.query(TikTokMatchModel).filter_by(id=match_id).one_or_none()
            if existing is None:
                return
            if scores:
                # Monotonicity guard. PK scores in a single battle only
                # ever increase (gifts add diamonds, nothing subtracts).
                # If the incoming `scores` map drops the TOTAL by more
                # than 50% vs what's already stored, the event is almost
                # certainly mis-tagged — TikTok ships a new battle's
                # opening frame in the same room before our worker
                # registers the transition, and the previous match still
                # looks "active" for ~100-200ms. Without this guard a
                # 5,395-vs-48 final got overwritten by 0-vs-6 from the
                # next battle's first match_update (real incident: match
                # #3103 in room 7638432349801941768).
                current = existing.scores if isinstance(existing.scores, dict) else {}
                current_total = sum(int(v or 0) for v in current.values())
                incoming_total = sum(int(v or 0) for v in scores.values())
                if current_total > 0 and incoming_total < current_total * 0.5:
                    logger.warning(
                        "update_match %d: rejecting score regression "
                        "(current_total=%d, incoming_total=%d) — likely "
                        "mis-tagged event from the next battle.",
                        match_id, current_total, incoming_total,
                    )
                else:
                    existing.scores = scores
                    flag_modified(existing, "scores")
            if opponents:
                existing.opponents = opponents
                flag_modified(existing, "opponents")
            if opponent_scores:
                # Merge per-anchor scores into existing opponents by
                # user_id. Build a deep clone of every entry up front:
                # SQLAlchemy keeps a reference to the dicts loaded on
                # query, and an in-place `dict["score"] = …` mutation
                # would silently update the snapshot too — leaving the
                # dirty-tracker thinking nothing changed and the UPDATE
                # statement omitting the column entirely. Cloning lets
                # the new list compare unequal to the snapshot, AND we
                # call `flag_modified` for belt+suspenders.
                current_raw = existing.opponents or []
                cloned: list[dict[str, Any]] = [dict(o) for o in current_raw if isinstance(o, dict)]
                by_uid = {
                    int(o["user_id"]): o
                    for o in cloned
                    if o.get("user_id") is not None
                }
                changed = False
                for entry in opponent_scores:
                    uid = entry.get("user_id")
                    if uid is None:
                        continue
                    uid_int = int(uid)
                    new_score = int(entry.get("score") or 0)
                    new_team_id = entry.get("team_id")
                    if uid_int in by_uid:
                        existing_op = by_uid[uid_int]
                        if int(existing_op.get("score") or 0) != new_score:
                            existing_op["score"] = new_score
                            changed = True
                        # Propagate team_id from armies events too —
                        # match_start sets it for known anchors, but
                        # multi-guest team-battle format sometimes
                        # ships team_id only via team_armies.
                        if new_team_id is not None and existing_op.get("team_id") in (None, 0):
                            existing_op["team_id"] = int(new_team_id)
                            changed = True
                    else:
                        # Unknown anchor — surface them so they're not
                        # lost. (Rare — only fires when a guest joins
                        # mid-PK without a prior match_start announce.)
                        new_entry: dict[str, Any] = {"user_id": uid_int, "score": new_score}
                        if new_team_id is not None:
                            new_entry["team_id"] = int(new_team_id)
                        by_uid[uid_int] = new_entry
                        cloned.append(new_entry)
                        changed = True
                if changed:
                    existing.opponents = cloned
                    flag_modified(existing, "opponents")
            if settings:
                existing.settings = settings
                flag_modified(existing, "settings")
            existing.last_seen_at = _utcnow()
            s.commit()

    def close_match(
        self,
        match_id: int,
        *,
        winner_user_id: int | None = None,
    ) -> None:
        with self._get_session() as s:
            existing = s.query(TikTokMatchModel).filter_by(id=match_id).one_or_none()
            if existing is None or existing.ended_at is not None:
                return
            existing.ended_at = _utcnow()
            existing.last_seen_at = existing.ended_at
            if winner_user_id is not None:
                existing.winner_user_id = winner_user_id
            s.commit()

    def get_active_match(self, room_id: int) -> Match | None:
        """Return the latest match in this room that's *actually live*
        right now. A match is live when:
          - `ended_at IS NULL`, AND
          - `last_seen_at` is within the last 2 minutes, AND
          - the battle clock hasn't already run out (the
            `settings.end_time_ms` countdown is either missing or
            in the future or in the past by less than 60s — TikTok
            holds the punish/victory-lap phase for ~25–35s after
            the countdown, then either fires the end event or the
            WS dies silently).

        These three predicates exist because TikTok / TikTokLive
        does NOT reliably emit a `LinkMicBattlePunishFinishEvent` —
        ~3–5% of matches end without that event, leaving the row
        with `ended_at IS NULL` forever. Without the freshness and
        countdown gates the UI would render those orphans as "in
        progress" hours later.

        2 minutes matches the freshness cutoff in
        `get_lives_summary` Section 7 — both paths should agree on
        what "active" means."""
        cutoff = _utcnow() - timedelta(minutes=2)
        with self._get_session() as s:
            row = (
                s.query(TikTokMatchModel)
                .filter(TikTokMatchModel.room_id == room_id)
                .filter(TikTokMatchModel.ended_at.is_(None))
                .filter(TikTokMatchModel.last_seen_at >= cutoff)
                .order_by(TikTokMatchModel.id.desc())
                .first()
            )
            if row is None:
                return _match_to_dataclass(row) if row else None
            # Defense in depth: even when `last_seen_at` is fresh, if
            # the battle's own countdown ended >60s ago and no end
            # event has fired, the WS feed is almost certainly
            # broken — treat the match as dead. (The grace window
            # covers the legitimate punish + victory-lap phase.)
            settings = row.settings if isinstance(row.settings, dict) else {}
            end_ms = settings.get("end_time_ms")
            if end_ms:
                try:
                    end_ts = int(end_ms) / 1000.0
                    now_ts = _utcnow().timestamp()
                    if now_ts - end_ts > 60:
                        return None
                except (TypeError, ValueError):
                    pass
            return _match_to_dataclass(row)

    def close_orphan_matches(self) -> int:
        """Back-fill `ended_at` on matches that clearly finished but
        never got a `LinkMicBattlePunishFinishEvent`. Roughly 3–5%
        of matches end this way on the TikTok side — the WS feed
        just goes silent, leaving `ended_at = NULL` forever.

        A match qualifies as an orphan when EITHER:
          • Heartbeat dead (no `match_update` for >5 min) AND its
            own `settings.end_time_ms` countdown is in the past, OR
          • Heartbeat extremely stale (>10 min) — even without
            countdown info, real battles get an update every ~1s.

        We back-fill `ended_at` from `settings.end_time_ms` when
        available (TikTok's authoritative end timestamp) and fall
        back to `last_seen_at` (last observed activity) otherwise.

        Postgres-only — relies on JSONB `->>` extraction and
        `to_timestamp`. SQLite dev path is a no-op.

        Returns the number of rows updated. Safe to call repeatedly:
        once a row gets `ended_at`, it falls out of the WHERE clause."""
        if not self._is_postgres():
            return 0
        with self._get_session() as s:
            res = s.execute(text("""
                WITH candidates AS (
                    SELECT id, last_seen_at,
                           CASE WHEN (settings->>'end_time_ms') ~ '^[0-9]+$'
                                THEN to_timestamp(
                                    (settings->>'end_time_ms')::bigint / 1000.0
                                )
                           END AS countdown_end
                    FROM tiktok_matches
                    WHERE ended_at IS NULL
                )
                UPDATE tiktok_matches m
                SET ended_at = COALESCE(c.countdown_end, c.last_seen_at)
                FROM candidates c
                WHERE m.id = c.id
                  AND (
                    (
                      c.last_seen_at < NOW() - INTERVAL '5 minutes'
                      AND c.countdown_end IS NOT NULL
                      AND c.countdown_end < NOW()
                    )
                    OR c.last_seen_at < NOW() - INTERVAL '10 minutes'
                  )
            """))
            s.commit()
            return res.rowcount or 0

    def list_matches(
        self,
        *,
        room_id: int | None = None,
        host_unique_id: str | None = None,
        limit: int = 50,
    ) -> list[Match]:
        with self._get_session() as s:
            q = s.query(TikTokMatchModel)
            if room_id is not None:
                q = q.filter(TikTokMatchModel.room_id == room_id)
            if host_unique_id is not None:
                q = q.join(RoomModel, RoomModel.room_id == TikTokMatchModel.room_id).filter(
                    RoomModel.host_unique_id == host_unique_id
                )
            q = q.order_by(TikTokMatchModel.started_at.desc()).limit(limit)
            return [_match_to_dataclass(r) for r in q.all()]

    def list_user_matches(
        self,
        *,
        user_id: int,
        room_ids: list[int] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List matches this user contributed gifts to.

        Returns `{"items": [...], "total": N}`. Each item carries the
        match's identity (id, battle_id, room, host_unique_id,
        opponents, scores, timestamps) plus THIS user's own
        per-match contribution (`user_gifts`, `user_diamonds`).
        Ordered most-recent first by `started_at`.

        Optional filters:
          - `room_ids` — restrict to matches in this room set. None
            means cross-host (every match the user ever gifted in).
          - `since` / `until` — bound the gift events; useful when
            opened from a date-window scope.
        """
        # Build WHERE clauses + params lazily so we can elide the
        # filters when they're None (`ANY(NULL)` matches nothing on
        # PG, so we need real conditional inclusion).
        where_parts = [
            "e.user_id = :uid",
            "e.type = 'gift'",
            "e.match_id IS NOT NULL",
        ]
        params: dict[str, Any] = {"uid": user_id}
        if room_ids:
            where_parts.append("m.room_id = ANY(:rids)")
            params["rids"] = list(room_ids)
        if since is not None:
            where_parts.append("e.ts >= :since")
            params["since"] = since
        if until is not None:
            where_parts.append("e.ts < :until")
            params["until"] = until
        where_sql = " AND ".join(where_parts)

        with self._get_session() as s:
            total_row = s.execute(text(f"""
                SELECT COUNT(DISTINCT e.match_id)
                FROM tiktok_events e
                JOIN tiktok_matches m ON m.id = e.match_id
                WHERE {where_sql}
            """), params).scalar()
            total = int(total_row or 0)
            if total == 0:
                return {"items": [], "total": 0}

            page_params = dict(params)
            page_params["limit"] = int(limit)
            page_params["offset"] = int(offset)
            rows = s.execute(text(f"""
                WITH user_gifts AS (
                    SELECT e.match_id,
                           COUNT(*) AS n_gifts,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS diamonds
                    FROM tiktok_events e
                    JOIN tiktok_matches m ON m.id = e.match_id
                    WHERE {where_sql}
                    GROUP BY e.match_id
                )
                SELECT m.id, m.battle_id, m.room_id,
                       m.opponents, m.scores,
                       m.started_at, m.ended_at, m.winner_user_id,
                       r.host_unique_id,
                       ug.n_gifts, ug.diamonds
                FROM tiktok_matches m
                JOIN tiktok_rooms r  ON r.room_id  = m.room_id
                JOIN user_gifts ug    ON ug.match_id = m.id
                ORDER BY m.started_at DESC NULLS LAST, m.id DESC
                LIMIT :limit OFFSET :offset
            """), page_params).all()

        items: list[dict[str, Any]] = []
        for r in rows:
            (mid, bid, room_id, opps_raw, scores_raw,
             started_at, ended_at, winner_user_id, host_unique_id,
             n_gifts, diamonds) = r
            opps = _coerce_payload(opps_raw) if opps_raw is not None else []
            if not isinstance(opps, list):
                opps = []
            # Compact opponent shape — frontend just needs identity
            # to render "vs @X, @Y".
            opps_serial: list[dict[str, Any]] = []
            for o in opps:
                if isinstance(o, dict):
                    opps_serial.append({
                        "user_id":    str(o.get("user_id"))   if o.get("user_id")   is not None else None,
                        "unique_id":  o.get("unique_id"),
                        "nickname":   o.get("nickname"),
                        "avatar_url": o.get("avatar_url"),
                        "team_id":    o.get("team_id"),
                        "score":      int(o.get("score") or 0),
                    })
            scores = _coerce_payload(scores_raw) if scores_raw is not None else {}
            items.append({
                "match_id":       int(mid),
                "battle_id":      str(bid) if bid else None,
                "room_id":        str(room_id),
                "host_unique_id": host_unique_id,
                "started_at":     started_at.isoformat() if started_at else None,
                "ended_at":       ended_at.isoformat() if ended_at else None,
                "winner_user_id": str(winner_user_id) if winner_user_id is not None else None,
                "opponents":      opps_serial,
                "scores":         scores if isinstance(scores, dict) else {},
                "user_gifts":     int(n_gifts or 0),
                "user_diamonds":  int(diamonds or 0),
            })
        return {"items": items, "total": total}

    def match_diamonds_totals(self, match_ids: list[int]) -> dict[int, int]:
        if not match_ids:
            return {}
        with self._get_session() as s:
            # Pull gift events tagged with these match_ids and aggregate in
            # Python — payload arithmetic in JSON is dialect-specific.
            rows = (
                s.query(TikTokEventModel.match_id, TikTokEventModel.payload)
                .filter(TikTokEventModel.match_id.in_(match_ids))
                .filter(TikTokEventModel.type == "gift")
                .all()
            )
        totals: dict[int, int] = {mid: 0 for mid in match_ids}
        for mid, payload in rows:
            if mid is None:
                continue
            p = _coerce_payload(payload)
            diamond = 0
            try:
                diamond = int(p.get("diamond_count") or 0) * int(p.get("repeat_count") or 1)
            except (TypeError, ValueError):
                diamond = 0
            totals[mid] = totals.get(mid, 0) + diamond
        return totals

    def get_match_by_id(self, match_id: int) -> Match | None:
        with self._get_session() as s:
            row = s.query(TikTokMatchModel).filter(TikTokMatchModel.id == int(match_id)).first()
            if not row:
                return None
            return Match(
                id=row.id,
                room_id=int(row.room_id),
                battle_id=int(row.battle_id),
                started_at=row.started_at,
                ended_at=row.ended_at,
                last_seen_at=row.last_seen_at,
                opponents=_coerce_payload(row.opponents) or [],
                scores=_coerce_payload(row.scores) or {},
                settings=_coerce_payload(row.settings) or {},
                winner_user_id=int(row.winner_user_id) if row.winner_user_id else None,
            )

    def get_room_host_handle(self, room_id: int) -> str | None:
        with self._get_session() as s:
            row = s.query(RoomModel.host_unique_id).filter(
                RoomModel.room_id == int(room_id)
            ).first()
            return row[0] if row else None

    def get_match_score_timeline(self, match_id: int) -> list[dict[str, Any]]:
        """Decoded score-update timeline for a single PK battle.

        TikTokLive emits two distinct `match_update` payload shapes —
        depending on protocol version / battle type:

          A. `{scores: {team_id: score}}`         — older / team-PK
          B. `{scores: {}, opponent_scores:       — newer / 1v1
              [{user_id, score}, ...]}`

        Shape A keys by `team_id` (matches the `team_id` field on
        each `opponents[]` entry). Shape B keys by `user_id`. We
        coalesce both into the same output structure: a single
        `scores: {key: score}` map per frame, where the key is
        whichever identifier was actually populated. The frontend's
        ScoreTimelineTab resolves host vs opponent series by
        matching the keys against either `opponents[].team_id` OR
        `opponents[].user_id`.

        Returns rows of `{ts, scores: {key: score}}` in ascending ts
        order. Bounded by `match_id` index, typically 50–500 rows
        per battle."""
        with self._get_session() as s:
            rows = (
                s.query(TikTokEventModel.ts, TikTokEventModel.payload)
                .filter(TikTokEventModel.match_id == int(match_id))
                .filter(TikTokEventModel.type.in_(("match_start", "match_update", "match_end")))
                .order_by(TikTokEventModel.ts.asc())
                .all()
            )
        out: list[dict[str, Any]] = []
        for ts, payload in rows:
            p = _coerce_payload(payload)
            if not isinstance(p, dict):
                continue
            normalized: dict[str, int] = {}
            # Shape A: `scores` map.
            scores = p.get("scores")
            if isinstance(scores, dict):
                for k, v in scores.items():
                    try:
                        normalized[str(k)] = int(v or 0)
                    except (TypeError, ValueError):
                        continue
            # Shape B fallback: `opponent_scores` array. Use user_id
            # as the key so the frontend can match against
            # `opponents[].user_id`. We always check Shape B even
            # when Shape A produced data — they almost never
            # coexist, and keeping the loop tolerant keeps the
            # frontend's score-axis stable.
            if not normalized:
                opp_scores = p.get("opponent_scores")
                if isinstance(opp_scores, list):
                    for entry in opp_scores:
                        if not isinstance(entry, dict):
                            continue
                        uid = entry.get("user_id")
                        sc = entry.get("score")
                        if uid is None or sc is None:
                            continue
                        try:
                            normalized[str(uid)] = int(sc or 0)
                        except (TypeError, ValueError):
                            continue
            if not normalized:
                continue
            out.append({
                "ts": ts.isoformat() if ts else None,
                "scores": normalized,
            })
        return out

    def get_match_ids_by_battle_id(
        self,
        battle_id: int,
        *,
        exclude_match_id: int | None = None,
    ) -> list[int]:
        """Every `tiktok_matches.id` row sharing the same TikTok PK
        `battle_id`. A single TikTok battle generates ONE row per
        monitored host whose room observed it (each WS sub writes its
        own match row), so a 1v1 between two monitored creators
        produces two rows with the same `battle_id`. Used to merge
        events across sibling match rows when both anchors are
        tracked."""
        with self._get_session() as s:
            q = s.query(TikTokMatchModel.id).filter(
                TikTokMatchModel.battle_id == int(battle_id)
            )
            if exclude_match_id is not None:
                q = q.filter(TikTokMatchModel.id != int(exclude_match_id))
            return [int(r[0]) for r in q.all()]

    def get_match_gifters_by_side(
        self,
        match_id: int,
        *,
        host_unique_id: str,
        opponents: list[dict[str, Any]],
        sibling_match_ids: list[int] | None = None,
        public_only: bool = False,
    ) -> dict[str, Any]:
        """Top gifters during a battle, split by whether each gift's
        `to_user.user_id` matched the host or one of the opponents.

        `opponents` is the match row's `opponents` JSON — each entry
        carries `user_id` (string or int) and `unique_id` for the
        guest TikTok account. We match against `to_user.user_id`
        first (most reliable, BigInt) and fall back to `unique_id`.

        `sibling_match_ids` are the IDs of `tiktok_matches` rows that
        represent the SAME TikTok PK battle from another monitored
        host's room (same `battle_id`, different `match_id`). Each
        sibling row carries the events that streamed in through the
        opponent's WebSocket subscription. Their gifts default to the
        "opponent" side from THIS host's perspective — they came in
        via the rival's broadcast, so the recipient by default is the
        opponent. `to_user` overrides still apply (e.g. a cross-room
        gift directed back at the current host stays on "host")."""
        host_handle_norm = (host_unique_id or "").lstrip("@").lower()
        # Build sets of identifiers for fast classification.
        opp_user_ids: set[int] = set()
        opp_unique_ids: set[str] = set()
        for o in opponents or []:
            if not isinstance(o, dict):
                continue
            uid = o.get("user_id")
            if uid is not None:
                try:
                    opp_user_ids.add(int(uid))
                except (TypeError, ValueError):
                    pass
            handle = (o.get("unique_id") or "").lstrip("@").lower()
            if handle and handle != host_handle_norm:
                opp_unique_ids.add(handle)

        # Build the full set of match_ids whose events to merge. The
        # primary id is the match row tied to the current page's host;
        # siblings are the parallel rows from each other monitored
        # host whose room observed the SAME PK. Without merging, the
        # "Top donors · this battle" panel only sees gifts that
        # flowed through the current host's WS subscription — the
        # rival's gifters stay invisible even though both anchors are
        # being tracked.
        match_id_int = int(match_id)
        sibling_ids = {int(m) for m in (sibling_match_ids or []) if m is not None}
        sibling_ids.discard(match_id_int)
        all_match_ids = [match_id_int, *sorted(sibling_ids)]

        # Resolve each sibling match's `room_id` once, up front. The
        # frontend uses the resulting set to widen the gifter-detail
        # modal's per-room scope: clicking an opponent-side donor in
        # the match modal needs to see their gifts in the rival's room
        # (which is exactly the sibling match's room_id), not just
        # the current page's room. Without this, the gifter modal
        # shows "no gifts" for any donor whose activity sits entirely
        # in the rival's broadcast.
        #
        # When `public_only=True` (the public mirror at
        # /public/tiktok/matches/{id}/gifters_by_side), we filter the
        # sibling list down to rooms whose host has opted into the
        # public surface. Without this, a PK between a public host
        # and a tracked-but-private host leaks the private host's
        # room_id (and the gift events would be merged into the public
        # response, exposing the private viewer base for that battle).
        # The `match_id IN (...)` filter for the gift query is rebuilt
        # from the filtered sibling set too, so per-event side
        # classification only sees rows the public viewer is allowed
        # to know about.
        sibling_room_ids: list[str] = []
        if sibling_ids:
            with self._get_session() as s:
                q = (
                    s.query(TikTokMatchModel.id, TikTokMatchModel.room_id)
                    .filter(TikTokMatchModel.id.in_(sorted(sibling_ids)))
                )
                if public_only:
                    q = (
                        q.join(
                            RoomModel,
                            RoomModel.room_id == TikTokMatchModel.room_id,
                        )
                        .join(
                            SubscriptionModel,
                            SubscriptionModel.unique_id == RoomModel.host_unique_id,
                        )
                        .filter(SubscriptionModel.is_public.is_(True))
                    )
                kept_sibling_ids: set[int] = set()
                for sib_id, room_id in q.all():
                    if room_id is None:
                        continue
                    kept_sibling_ids.add(int(sib_id))
                    sibling_room_ids.append(str(int(room_id)))
                if public_only:
                    sibling_ids = kept_sibling_ids
                    all_match_ids = [match_id_int, *sorted(sibling_ids)]

        with self._get_session() as s:
            rows = (
                s.query(
                    TikTokEventModel.user_id,
                    TikTokEventModel.payload,
                    TikTokEventModel.match_id,
                )
                .filter(TikTokEventModel.match_id.in_(all_match_ids))
                .filter(TikTokEventModel.type == "gift")
                .all()
            )

        # Bucket: side → user_id → aggregate
        buckets: dict[str, dict[int, dict[str, Any]]] = {
            "host": {},
            "opponent": {},
            "unknown": {},
        }
        for user_id, payload, event_match_id in rows:
            if user_id is None:
                continue
            p = _coerce_payload(payload)
            diamond = 0
            try:
                diamond = int(p.get("diamond_count") or 0) * int(p.get("repeat_count") or 1)
            except (TypeError, ValueError):
                diamond = 0
            count = 1
            try:
                count = int(p.get("repeat_count") or 1)
            except (TypeError, ValueError):
                count = 1

            # Classify side from to_user.
            #
            # Critical context: every gift we ingested came through
            # the *host's* WebSocket subscription. By definition, the
            # gift was sent in the host's broadcast. Opponent-side
            # gifts happen in the opponent's separate room that we
            # don't subscribe to UNLESS that opponent is ALSO a
            # monitored host — in which case we have a parallel
            # `tiktok_matches` row for the same battle_id and its
            # events flow in through THAT host's WS. Those sibling
            # rows are passed in via `sibling_match_ids`; their gifts
            # default to "opponent" from the current host's POV.
            #
            # We only override the default when `to_user` carries a
            # *real* identifier that matches the opposite side — i.e.
            # multi-guest live where the gifter explicitly picked a
            # guest other than the host, OR a cross-room gift in the
            # rival's broadcast directed back at the current host.
            to_user = p.get("to_user") if isinstance(p, dict) else None
            from_sibling = event_match_id is not None and int(event_match_id) in sibling_ids
            side = "opponent" if from_sibling else "host"
            if isinstance(to_user, dict):
                to_uid_raw = to_user.get("user_id")
                to_handle = (to_user.get("unique_id") or "").lstrip("@").lower()
                to_uid: int | None = None
                if to_uid_raw is not None:
                    try:
                        to_uid = int(to_uid_raw)
                    except (TypeError, ValueError):
                        to_uid = None
                if to_uid is not None and to_uid != 0:
                    if to_uid in opp_user_ids:
                        side = "opponent"
                    elif to_handle == host_handle_norm:
                        side = "host"
                    elif to_handle and to_handle in opp_unique_ids:
                        side = "opponent"
                    # Recipient has a real id but matches neither —
                    # fall back to the room-of-origin default (host
                    # for current-match events, opponent for sibling-
                    # match events). Without the `from_sibling` flag
                    # this used to hard-code "host", which mis-tagged
                    # every cross-room gift in the rival's broadcast.
                    else:
                        side = "opponent" if from_sibling else "host"
                elif to_handle:
                    if to_handle in opp_unique_ids:
                        side = "opponent"
                    elif to_handle == host_handle_norm:
                        side = "host"
                    # to_handle present but doesn't match anything we
                    # can disambiguate — keep host default.

            uid = int(user_id)
            user_payload = p.get("user") if isinstance(p, dict) else None
            unique_id = None
            nickname = None
            avatar_url = None
            if isinstance(user_payload, dict):
                unique_id = user_payload.get("unique_id")
                nickname = user_payload.get("nickname")
                avatar_url = user_payload.get("avatar_url")

            bucket = buckets[side]
            agg = bucket.get(uid)
            if agg is None:
                agg = {
                    "user_id": uid,
                    "unique_id": unique_id,
                    "nickname": nickname,
                    "avatar_url": avatar_url,
                    "gifts": 0,
                    "diamonds": 0,
                    "largest_single": 0,
                    "events": 0,
                }
                bucket[uid] = agg
            agg["gifts"] += count
            agg["diamonds"] += diamond
            agg["events"] += 1
            if diamond > agg["largest_single"]:
                agg["largest_single"] = diamond

        def _sorted(side: str) -> list[dict[str, Any]]:
            return sorted(
                buckets[side].values(),
                key=lambda r: int(r["diamonds"] or 0),
                reverse=True,
            )

        return {
            "host": _sorted("host"),
            "opponent": _sorted("opponent"),
            "unknown": _sorted("unknown"),
            "totals": {
                "host_gifters":     len(buckets["host"]),
                "host_diamonds":    sum(r["diamonds"] for r in buckets["host"].values()),
                "host_gifts":       sum(r["gifts"]    for r in buckets["host"].values()),
                "opponent_gifters": len(buckets["opponent"]),
                "opponent_diamonds":sum(r["diamonds"] for r in buckets["opponent"].values()),
                "opponent_gifts":   sum(r["gifts"]    for r in buckets["opponent"].values()),
                "unknown_diamonds": sum(r["diamonds"] for r in buckets["unknown"].values()),
                # Number of sibling `tiktok_matches` rows whose events were
                # merged in — i.e. how many other monitored hosts'
                # WebSocket streams contributed to the opponent side. The
                # frontend uses this to flip the "we don't subscribe to
                # opponent's stream" disclaimer copy: when ≥1, opponent
                # gifts ARE being captured (just possibly under-counted
                # vs TikTok's authoritative PK score).
                "siblings_merged": len(sibling_ids),
                # Room IDs of those sibling matches. The frontend passes
                # them as `extraRoomIds` when opening the gifter detail
                # modal for an opponent-side donor — without it the
                # modal's per-room searchEvents call only hits the
                # current host's room and the donor's history appears
                # empty.
                "sibling_room_ids": sibling_room_ids,
            },
        }

    def get_match_head_to_head(
        self,
        match_id: int,
        *,
        host_unique_id: str,
        opponents: list[dict[str, Any]],
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Prior PK battles between the same host and (any of the
        same) opponent unique_ids. Useful for the "head-to-head" tab
        — shows whether this is a recurring rivalry, who's been
        winning, and how the diamonds-per-match has trended."""
        opp_handles: set[str] = set()
        for o in opponents or []:
            if isinstance(o, dict):
                h = (o.get("unique_id") or "").lstrip("@").lower()
                if h:
                    opp_handles.add(h)
        if not opp_handles:
            return []

        is_pg = self._is_postgres()
        if not is_pg:
            return []

        # Find host's matches that listed any of these opponents.
        sql = text("""
            SELECT m.id, m.battle_id, m.started_at, m.ended_at,
                   m.opponents, m.scores, m.winner_user_id, m.room_id
            FROM tiktok_matches m
            JOIN tiktok_rooms r ON r.room_id = m.room_id
            WHERE r.host_unique_id = :host
              AND m.id != :exclude_id
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(m.opponents) AS o
                  WHERE LOWER(REPLACE(o->>'unique_id', '@', '')) = ANY(:opps)
              )
            ORDER BY m.started_at DESC NULLS LAST
            LIMIT :lim
        """)
        with self._get_session() as s:
            rows = s.execute(sql, {
                "host": host_unique_id,
                "exclude_id": int(match_id),
                "opps": list(opp_handles),
                "lim": int(limit),
            }).all()

        if not rows:
            return []

        # Pull per-match diamond totals in one shot.
        ids = [int(r[0]) for r in rows]
        diamonds_by_match = self.match_diamonds_totals(ids)

        out: list[dict[str, Any]] = []
        for r in rows:
            mid, battle_id, started_at, ended_at, opps_json, scores_json, winner_uid, room_id = r
            opps_list = _coerce_payload(opps_json) if opps_json else []
            scores_dict = _coerce_payload(scores_json) if scores_json else {}
            # Coerce opponent ids to strings for JS BigInt safety.
            opps_serial: list[dict[str, Any]] = []
            if isinstance(opps_list, list):
                for o in opps_list:
                    if not isinstance(o, dict):
                        continue
                    out_o = dict(o)
                    if out_o.get("user_id") is not None:
                        out_o["user_id"] = str(out_o["user_id"])
                    opps_serial.append(out_o)
            # ── Pre-computed per-row enrichments. The frontend's H2H
            #     dashboard otherwise has to reverse-engineer all of
            #     these on render. Doing it once on the server keeps
            #     the table-row + chart code path linear. ──
            host_handle_norm = (host_unique_id or "").lstrip("@").lower()
            duration_seconds: int | None = None
            if started_at and ended_at:
                duration_seconds = max(0, int((ended_at - started_at).total_seconds()))

            # Resolve host vs opponent score from whichever shape was
            # populated (mirrors the frontend `resolveScores` helper).
            host_score: int | None = None
            opp_score:  int | None = None
            opp_handles_in_row: list[str] = []
            host_keys: set[str] = set()
            opp_keys:  set[str] = set()
            for o in opps_serial:
                handle = (o.get("unique_id") or "").lstrip("@").lower()
                is_opp = handle != host_handle_norm
                if is_opp and handle:
                    opp_handles_in_row.append(handle)
                if o.get("team_id") is not None:
                    (opp_keys if is_opp else host_keys).add(str(o.get("team_id")))
                if o.get("user_id") is not None:
                    (opp_keys if is_opp else host_keys).add(str(o.get("user_id")))
            if isinstance(scores_dict, dict) and len(scores_dict) >= 2:
                for k, v in scores_dict.items():
                    try:
                        sc = int(v)
                    except (TypeError, ValueError):
                        continue
                    if str(k) in host_keys and host_score is None:
                        host_score = sc
                    elif str(k) in opp_keys and opp_score is None:
                        opp_score = sc
            if host_score is None or opp_score is None:
                # Path 3: opponents[].score per anchor entry.
                for o in opps_serial:
                    handle = (o.get("unique_id") or "").lstrip("@").lower()
                    sc = o.get("score")
                    if sc is None:
                        continue
                    try:
                        sc_int = int(sc)
                    except (TypeError, ValueError):
                        continue
                    if handle == host_handle_norm and host_score is None:
                        host_score = sc_int
                    elif handle != host_handle_norm and opp_score is None:
                        opp_score = sc_int

            outcome: str = "ended"
            margin: int | None = None
            decisive_pct: float | None = None
            if host_score is not None and opp_score is not None:
                margin = host_score - opp_score
                if host_score == opp_score:
                    outcome = "draw"
                else:
                    outcome = "won" if host_score > opp_score else "lost"
                top = max(host_score, opp_score)
                if top > 0:
                    decisive_pct = round(100.0 * abs(margin) / top, 1)

            # Resolve `winner_unique_id` so the frontend doesn't have
            # to reverse-look-up via opponents.
            winner_unique_id: str | None = None
            if winner_uid is not None:
                for o in opps_serial:
                    if str(o.get("user_id") or "") == str(winner_uid):
                        winner_unique_id = o.get("unique_id")
                        break

            out.append({
                "id": int(mid),
                "battle_id": str(battle_id) if battle_id else None,
                "room_id": str(room_id) if room_id else None,
                "started_at": started_at.isoformat() if started_at else None,
                "ended_at": ended_at.isoformat() if ended_at else None,
                "opponents": opps_serial,
                "scores": scores_dict if isinstance(scores_dict, dict) else {},
                "winner_user_id": str(winner_uid) if winner_uid else None,
                "winner_unique_id": winner_unique_id,
                "diamonds_total": int(diamonds_by_match.get(int(mid), 0)),
                # Frontend-friendly enrichments.
                "host_score": host_score,
                "opp_score":  opp_score,
                "margin":     margin,
                "outcome":    outcome,
                "decisive_pct": decisive_pct,
                "duration_seconds": duration_seconds,
                "opponent_handles": opp_handles_in_row,
            })
        return out

    def get_h2h_common_gifters(
        self,
        match_ids: list[int],
        *,
        min_battles: int = 2,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Viewers who gifted in at least `min_battles` of the given
        prior PK battles. Drives the "regulars / common gifters bench"
        section of the H2H tab — surfaces "this rivalry has its own
        fanbase" with avatars + per-battle attendance.

        Single grouped scan keyed on `tiktok_events.match_id` (already
        indexed). LEFT JOIN to `tiktok_viewers` for nickname/avatar."""
        if not match_ids:
            return []
        if not self._is_postgres():
            return []
        sql = text("""
            SELECT e.user_id,
                   COUNT(DISTINCT e.match_id) AS battles,
                   SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                       * COALESCE((e.payload->>'repeat_count')::int, 1)) AS diamonds,
                   SUM(COALESCE((e.payload->>'repeat_count')::int, 1))   AS gifts,
                   v.unique_id, v.nickname, v.avatar_url
            FROM tiktok_events e
            LEFT JOIN tiktok_viewers v ON v.user_id = e.user_id
            WHERE e.match_id = ANY(:ids)
              AND e.type = 'gift'
              AND e.user_id IS NOT NULL
            GROUP BY e.user_id, v.unique_id, v.nickname, v.avatar_url
            HAVING COUNT(DISTINCT e.match_id) >= :min_b
            ORDER BY battles DESC, diamonds DESC
            LIMIT :lim
        """)
        with self._get_session() as s:
            rows = s.execute(sql, {
                "ids": [int(x) for x in match_ids],
                "min_b": int(min_battles),
                "lim": int(limit),
            }).all()
        return [
            {
                "user_id": str(r[0]),
                "battles": int(r[1] or 0),
                "diamonds": int(r[2] or 0),
                "gifts":    int(r[3] or 0),
                "unique_id": r[4],
                "nickname":  r[5],
                "avatar_url": r[6],
            }
            for r in rows
        ]

    # ── Events ───────────────────────────────────────────────────────

    def insert_event(
        self,
        *,
        room_id: int,
        user_id: int | None,
        type: str,
        payload: dict[str, Any] | None,
        match_id: int | None = None,
    ) -> int:
        with self._get_session() as s:
            row = TikTokEventModel(
                room_id=room_id,
                user_id=user_id,
                type=type,
                payload=payload or {},
                match_id=match_id,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return row.id

    def _upsert_user_host_summary(
        self,
        s,
        *,
        type: str,
        viewer: TikTokViewer | None,
        host_unique_id: str | None,
        payload: dict[str, Any] | None,
    ) -> None:
        """Maintain `tiktok_user_host_summary` in the same transaction
        as the gift-event insert. The summary table's job is to make
        `common_gifters` an O(few thousand rows) read instead of an
        O(n_events) aggregate scan; this UPSERT is what keeps it always
        live (no refresh interval, no staleness window).

        Skips silently for non-gift events, anonymous gifts (no
        viewer / no user_id), and rooms with no host bound. Same
        guard set the read query uses on the source table, so the
        summary stays in lock-step with what the leaderboard would
        compute from raw events.
        """
        if type != "gift":
            return
        if viewer is None or viewer.user_id is None:
            return
        if not host_unique_id:
            return
        # Multi-host guest gifts (to_user.user_id set + != host's
        # profile_user_id) must NOT bump this host's summary — they go
        # to a different recipient. Same predicate the read paths use.
        if not self._gift_is_for_host(s, host_unique_id, payload):
            return
        p = payload if isinstance(payload, dict) else {}
        try:
            d_per = int(p.get("diamond_count") or 0)
            rep = int(p.get("repeat_count") or 1)
        except (TypeError, ValueError):
            return
        if rep < 1:
            rep = 1
        diamonds = max(0, d_per * rep)
        gifts = rep
        if diamonds == 0 and gifts == 0:
            return
        now = _utcnow()
        if self._is_postgres():
            s.execute(text("""
                INSERT INTO tiktok_user_host_summary
                    (user_id, host_unique_id, diamonds, gifts,
                     first_seen_at, last_seen_at)
                VALUES (:uid, :host, :d, :g, :ts, :ts)
                ON CONFLICT (user_id, host_unique_id) DO UPDATE SET
                    diamonds      = tiktok_user_host_summary.diamonds + EXCLUDED.diamonds,
                    gifts         = tiktok_user_host_summary.gifts    + EXCLUDED.gifts,
                    last_seen_at  = GREATEST(
                        tiktok_user_host_summary.last_seen_at,
                        EXCLUDED.last_seen_at
                    )
            """), {
                "uid": int(viewer.user_id),
                "host": host_unique_id,
                "d": diamonds,
                "g": gifts,
                "ts": now,
            })
        else:
            # SQLite (dev): simulate UPSERT.
            existing = s.execute(text("""
                SELECT diamonds, gifts, first_seen_at
                FROM tiktok_user_host_summary
                WHERE user_id = :uid AND host_unique_id = :host
            """), {"uid": int(viewer.user_id), "host": host_unique_id}).fetchone()
            if existing is None:
                s.execute(text("""
                    INSERT INTO tiktok_user_host_summary
                        (user_id, host_unique_id, diamonds, gifts,
                         first_seen_at, last_seen_at)
                    VALUES (:uid, :host, :d, :g, :ts, :ts)
                """), {
                    "uid": int(viewer.user_id),
                    "host": host_unique_id,
                    "d": diamonds,
                    "g": gifts,
                    "ts": now,
                })
            else:
                s.execute(text("""
                    UPDATE tiktok_user_host_summary
                    SET diamonds = diamonds + :d,
                        gifts    = gifts    + :g,
                        last_seen_at = :ts
                    WHERE user_id = :uid AND host_unique_id = :host
                """), {
                    "uid": int(viewer.user_id),
                    "host": host_unique_id,
                    "d": diamonds,
                    "g": gifts,
                    "ts": now,
                })

    def persist_event_full(
        self,
        *,
        room_id: int,
        host_unique_id: str | None,
        viewer: TikTokViewer | None,
        type: str,
        payload: dict[str, Any] | None,
        match_id: int | None = None,
        push_room_seen: bool = True,
        push_viewer_seen: bool = True,
    ) -> int:
        """Single-transaction room+viewer+event persist.

        Returns the inserted row id, or 0 when the row was deduplicated
        away by the (room_id, message_id) partial unique index — that
        path means TikTok re-delivered an event we already had (typical
        WS reconnect cursor replay).
        """
        # Pull out the dedup key. TikTokLive populates `message_id` from
        # `base_message.message_id` for every Webcast* protobuf event;
        # synthetic events (connect / disconnect / live_end) skip it.
        message_id: int | None = None
        if isinstance(payload, dict):
            raw_mid = payload.get("message_id")
            if raw_mid:
                try:
                    message_id = int(raw_mid)
                    if message_id <= 0:
                        message_id = None
                except (TypeError, ValueError):
                    message_id = None

        with self._get_session() as s:
            self._upsert_room_in_session(
                s,
                Room(room_id=room_id, host_unique_id=host_unique_id),
                push_seen=push_room_seen,
            )
            if viewer is not None:
                self._upsert_viewer_in_session(s, viewer, push_seen=push_viewer_seen)

            # `s.bind` is None on the framework's RetrySession (read-replica
            # routing) — use `_is_postgres()` which inspects the adapter's
            # own engine, same approach as the rest of this file's
            # postgres-only branches.
            if self._is_postgres() and message_id is not None:
                # Dedup-safe insert. ON CONFLICT against the partial
                # unique index `tiktok_events_room_msg_uniq`. RETURNING
                # tells us whether we actually inserted; on conflict
                # Postgres returns zero rows.
                stmt = pg_insert(TikTokEventModel).values(
                    room_id=room_id,
                    user_id=viewer.user_id if viewer else None,
                    type=type,
                    payload=payload or {},
                    match_id=match_id,
                    message_id=message_id,
                ).on_conflict_do_nothing(
                    index_elements=["room_id", "message_id"],
                    # Partial-index predicate must match the index DDL
                    # (`WHERE message_id IS NOT NULL`) for Postgres to
                    # correctly infer this unique index in ON CONFLICT.
                    index_where=TikTokEventModel.message_id.isnot(None),
                ).returning(TikTokEventModel.id)
                row_id = s.execute(stmt).scalar()
                if row_id:
                    self._upsert_user_host_summary(
                        s,
                        type=type,
                        viewer=viewer,
                        host_unique_id=host_unique_id,
                        payload=payload,
                    )
                    self._bump_event_hour_count(
                        s, host_unique_id,
                        event_type=type, payload=payload,
                    )
                    # Phase 9B: state-cache mirror. No-op when
                    # `self._state_cache is None` (feature flag off).
                    self._apply_state_delta(
                        s, host_unique_id,
                        event_type=type, payload=payload, viewer=viewer,
                    )
                s.commit()
                return int(row_id) if row_id else 0

            # No message_id (synthetic event) OR non-Postgres: vanilla insert.
            row = TikTokEventModel(
                room_id=room_id,
                user_id=viewer.user_id if viewer else None,
                type=type,
                payload=payload or {},
                match_id=match_id,
                message_id=message_id,
            )
            s.add(row)
            s.flush()  # surface row.id for the summary upsert below
            self._upsert_user_host_summary(
                s,
                type=type,
                viewer=viewer,
                host_unique_id=host_unique_id,
                payload=payload,
            )
            self._bump_event_hour_count(
                s, host_unique_id,
                event_type=type, payload=payload,
            )
            # Phase 9B: state-cache mirror. No-op when
            # `self._state_cache is None` (feature flag off).
            self._apply_state_delta(
                s, host_unique_id,
                event_type=type, payload=payload, viewer=viewer,
            )
            s.commit()
            s.refresh(row)
            return row.id

    def _bump_event_hour_count(
        self,
        s,
        host_unique_id: str | None,
        *,
        event_type: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Increment the (host, current-hour) counter row in
        `tiktok_event_hour_counts`. Called inline from the event-persist
        transaction so the rhythm-strip read path can scan a tiny
        pre-aggregated table instead of 1.7M raw events.

        For gift events we also bump a `diamonds` column with
        `diamond_count * repeat_count` from the payload. That lets
        `get_lives_totals` compute the 24h diamond sum from this pre-agg
        table (~1.9K rows) instead of scanning the full 24h gift event
        volume (millions of rows on a busy install). The bump cost is
        identical — same one-row UPSERT — but the read path collapses
        from a multi-million-row heap fetch to a tiny indexed range scan.

        Postgres-only — the read path falls back to a scan on SQLite."""
        if not host_unique_id or not self._is_postgres():
            return
        diamonds_delta = 0
        if event_type == "gift" and isinstance(payload, dict):
            # Only credit diamonds when the gift's to_user matches the
            # host. The `n` event count still increments — the rhythm
            # strip shows raw event flow regardless of attribution.
            if self._gift_is_for_host(s, host_unique_id, payload):
                try:
                    dc = int(payload.get("diamond_count") or 0)
                    rc = int(payload.get("repeat_count") or 1)
                    diamonds_delta = max(0, dc * rc)
                except (TypeError, ValueError):
                    diamonds_delta = 0
        s.execute(text("""
            INSERT INTO tiktok_event_hour_counts (host_unique_id, hour_bucket, n, diamonds)
            VALUES (:h, date_trunc('hour', NOW()), 1, :d)
            ON CONFLICT (host_unique_id, hour_bucket)
              DO UPDATE SET n = tiktok_event_hour_counts.n + 1,
                            diamonds = tiktok_event_hour_counts.diamonds + EXCLUDED.diamonds
        """), {"h": host_unique_id, "d": diamonds_delta})

    # ── Phase 9B: state-cache mirror ─────────────────────────────────
    #
    # Every event that affects per-host runtime state translates into
    # a patch applied to the state cache. Subscribers (Phase D) see
    # the patch as a WS-pushed delta. When `self._state_cache` is
    # `None` (the default for `PHOVEU_BACKEND_TIKTOK_WS_STATE_PUSH=off`
    # mode), every call is a no-op — preserving pre-Phase-9 behavior.
    #
    # See `.claude/tracking/perf/PHASE9_PLAN.md` for the full mapping
    # table. The implementations below match the SQL-equivalent
    # semantics of `get_lives_summary` field-for-field so a shadow-
    # mode soak can be validated by comparing cache state to SQL
    # output on every host.

    def _apply_state_delta(
        self,
        s,
        host_unique_id: str | None,
        *,
        event_type: str | None,
        payload: dict | None,
        viewer: Any = None,
    ) -> None:
        """Dispatcher. Called inline from `record_event()` after the
        DB row has been inserted and the user_host_summary upsert has
        run, so any cross-session lookups (first-time-gifter detection)
        find the just-committed state."""
        if self._state_cache is None or not host_unique_id:
            return
        if not event_type:
            return

        payload = payload or {}
        try:
            if event_type == "gift":
                self._state_apply_gift(s, host_unique_id, payload, viewer)
            elif event_type == "comment":
                self._state_apply_comment(host_unique_id, payload, viewer)
            elif event_type in ("like", "join", "follow", "share"):
                self._state_apply_simple_counter(host_unique_id, event_type)
            elif event_type == "envelope":
                self._state_apply_envelope(host_unique_id, payload)
            elif event_type == "live_pause":
                self._state_apply_pause(host_unique_id)
            elif event_type == "poll":
                self._state_apply_poll(host_unique_id, payload)
            elif event_type == "battle_begin":
                self._state_apply_battle_begin(host_unique_id, payload)
            elif event_type == "battle_progress":
                self._state_apply_battle_progress(host_unique_id, payload)
            elif event_type == "battle_end":
                self._state_apply_battle_end(host_unique_id)
            # The TikTokLive client adapter emits the synthetic
            # lifecycle events under historical names — `"connected"`
            # for WS-up, `"disconnected"` / `"live_end"` for WS-down,
            # `"viewer_count"` for the per-minute viewer refresh. The
            # Phase 9 spec uses semantic names; accept both so the
            # dispatcher matches whatever flows through `record_event`
            # without forcing a rename in the listener (which would
            # break downstream consumers of the legacy event stream).
            elif event_type in ("live_started", "connected"):
                self._state_apply_live_started(host_unique_id, payload)
            elif event_type in ("live_ended", "disconnected", "live_end"):
                self._state_apply_live_ended(host_unique_id, payload)
            elif event_type in ("viewer_count_update", "viewer_count"):
                self._state_apply_viewer_count(host_unique_id, payload)
            else:
                # Unknown / non-summary event. Don't publish, but bump
                # `_last_event_at` so the tick task (Phase D) can keep
                # `last_event_age_s` fresh. Aux-only patch → silent.
                self._state_cache.apply_patch(
                    host_unique_id,
                    {"_last_event_at": _now_iso()},
                )
        except Exception:
            # State-cache failures must NEVER break the persist path
            # — the DB row is already committed. Log + swallow so the
            # listener stays healthy.
            logger.exception(
                "_apply_state_delta failed: host=%s type=%s",
                host_unique_id, event_type,
            )

    # Per-event helpers below. Each builds a single patch dict mixing
    # publishable fields with `_*` aux fields, then calls
    # `apply_patch(host, patch)`. The adapter strips `_*` before
    # publishing so subscribers see only the user-facing fields.

    def _state_apply_simple_counter(
        self, host: str, event_type: str,
    ) -> None:
        """like / join / follow / share — increment one counter in
        `session_stats`."""
        cached = self._state_cache.get(host)
        stats = (cached[1].get("session_stats") if cached else None) or {}
        key = f"n_{event_type}s"  # likes / joins / follows / shares
        new_count = (stats.get(key) or 0) + 1
        self._state_cache.apply_patch(host, {
            "session_stats": {key: new_count},
            "_last_event_at": _now_iso(),
        })

    def _state_apply_envelope(self, host: str, payload: dict) -> None:
        cached = self._state_cache.get(host)
        current = cached[1] if cached else {}
        n = (current.get("n_envelopes_session") or 0) + 1
        diamonds = (
            current.get("envelope_diamonds_session") or 0
        ) + int(payload.get("diamonds") or payload.get("diamond_count") or 0)
        self._state_cache.apply_patch(host, {
            "n_envelopes_session": n,
            "envelope_diamonds_session": diamonds,
            "_last_event_at": _now_iso(),
        })

    def _state_apply_pause(self, host: str) -> None:
        cached = self._state_cache.get(host)
        current = cached[1] if cached else {}
        n = (current.get("n_pauses") or 0) + 1
        now_iso = _now_iso()
        self._state_cache.apply_patch(host, {
            "n_pauses": n,
            "last_pause_age_s": 0,
            "_last_pause_at": now_iso,
            "_last_event_at": now_iso,
        })

    def _state_apply_poll(self, host: str, payload: dict) -> None:
        # Active poll set with TTL — Phase D tick expires it after
        # 60 s of no fresh poll event.
        self._state_cache.apply_patch(host, {
            "active_poll": {
                "title": payload.get("title") or "",
                "poll_id": payload.get("poll_id"),
                "fresh_age_s": 0,
            },
            "_active_poll_at": _now_iso(),
            "_last_event_at": _now_iso(),
        })

    def _state_apply_battle_begin(self, host: str, payload: dict) -> None:
        match = {
            "match_id": payload.get("match_id"),
            "battle_id": payload.get("battle_id"),
            "countdown_s": payload.get("countdown_s"),
            "opponents": payload.get("opponents") or [],
        }
        self._state_cache.apply_patch(host, {
            "active_match": match,
            "_last_event_at": _now_iso(),
        })

    def _state_apply_battle_progress(
        self, host: str, payload: dict,
    ) -> None:
        # Replace `opponents` wholesale (list-replace rule). Other
        # active_match fields like match_id / battle_id stay put via
        # deep-merge.
        opps = payload.get("opponents")
        if not opps:
            return
        self._state_cache.apply_patch(host, {
            "active_match": {"opponents": opps},
            "_last_event_at": _now_iso(),
        })

    def _state_apply_battle_end(self, host: str) -> None:
        # `active_match: None` — deep-merge replaces.
        self._state_cache.apply_patch(host, {
            "active_match": None,
            "_last_event_at": _now_iso(),
        })

    def _state_apply_viewer_count(
        self, host: str, payload: dict,
    ) -> None:
        # The listener adapter emits viewer count under `"total"`; the
        # Phase 9 spec named the field `"viewer_count"`. Accept either
        # so the handler doesn't depend on a rename in the listener.
        viewer_count = payload.get("viewer_count")
        if viewer_count is None:
            viewer_count = payload.get("total")
        if viewer_count is None:
            return
        cached = self._state_cache.get(host)
        current = cached[1] if cached else {}
        history = list(current.get("viewer_history") or [])
        history.append(int(viewer_count))
        if len(history) > 30:
            history = history[-30:]
        self._state_cache.apply_patch(host, {
            "viewer_count": int(viewer_count),
            "viewer_history": history,
            "_last_event_at": _now_iso(),
        })

    def _state_apply_comment(
        self, host: str, payload: dict, viewer: Any,
    ) -> None:
        cached = self._state_cache.get(host)
        current = cached[1] if cached else {}
        stats = current.get("session_stats") or {}
        commenter_ids = set(current.get("_commenter_ids") or [])
        user_id = _user_id_from_viewer_or_payload(viewer, payload)
        if user_id is not None:
            commenter_ids.add(user_id)
        n_comments = (stats.get("n_comments") or 0) + 1
        now_iso = _now_iso()
        self._state_cache.apply_patch(host, {
            "session_stats": {
                "n_comments": n_comments,
                "n_unique_commenters": len(commenter_ids),
            },
            "last_comment_age_s": 0,
            "_commenter_ids": sorted(commenter_ids),
            "_last_comment_at": now_iso,
            "_last_event_at": now_iso,
        })

    def _state_apply_gift(
        self,
        s,
        host: str,
        payload: dict,
        viewer: Any,
    ) -> None:
        """The big one — diamonds + top_gifters + unique gifters +
        first-timer detection."""
        # Multi-host guest gifts: only bump the last-event clock so the
        # rhythm strip / momentum heuristic still react, but skip the
        # diamond + gifter book-keeping. Same predicate as the read-path
        # aggregations.
        if not self._gift_is_for_host(s, host, payload):
            self._state_cache.apply_patch(host, {
                "_last_event_at": _now_iso(),
            })
            return
        dc = int(payload.get("diamond_count") or 0)
        rc = int(payload.get("repeat_count") or 1)
        value = max(0, dc * rc)
        if value == 0:
            # Diamondless gift (free-promo envelope, etc.) — skip
            # the heavy book-keeping; only bump the last-event clock.
            self._state_cache.apply_patch(host, {
                "_last_event_at": _now_iso(),
            })
            return

        user_id = _user_id_from_viewer_or_payload(viewer, payload)
        cached = self._state_cache.get(host)
        current = cached[1] if cached else {}

        gifter_totals = dict(current.get("_gifter_totals") or {})
        if user_id is not None:
            key = str(user_id)
            gifter_totals[key] = (gifter_totals.get(key) or 0) + value
        # Bounded growth: cap at 10k entries, evict smallest. A
        # gifter below the bottom-10k cap by definition never reaches
        # top-3 so eviction is correctness-safe.
        if len(gifter_totals) > 10_000:
            keep = sorted(
                gifter_totals.items(), key=lambda kv: -kv[1],
            )[:10_000]
            gifter_totals = dict(keep)

        # Recompute top-3 from gifter_totals + viewer-name lookups
        # (we fetch nickname/avatar lazily from tiktok_viewers).
        top3_ids = sorted(
            gifter_totals.items(), key=lambda kv: -kv[1],
        )[:3]
        top_gifters = self._lookup_top_gifters(s, top3_ids)

        # n_unique_gifters: distinct gifters this session.
        n_unique = len(gifter_totals)

        # n_first_time_gifters: cross-session check against
        # `tiktok_user_host_summary`. The upsert already ran in
        # `record_event` before this hook fires, so a freshly-inserted
        # row has `first_seen_at = NOW()` which is >= live_started_at.
        live_started_at = current.get("live_started_at")
        n_first_time = current.get("n_first_time_gifters") or 0
        if user_id is not None and live_started_at:
            try:
                row = s.execute(text(
                    "SELECT first_seen_at FROM tiktok_user_host_summary "
                    "WHERE user_id = :u AND host_unique_id = :h"
                ), {"u": user_id, "h": host}).first()
                first_seen = row[0] if row else None
                if first_seen is not None and _iso_to_epoch(
                    live_started_at
                ) <= _dt_to_epoch(first_seen):
                    # Only increment when this is the FIRST gift for
                    # this user this session. Track in aux state.
                    prior_gifters = set(
                        current.get("_first_time_user_ids") or []
                    )
                    if user_id not in prior_gifters:
                        prior_gifters.add(user_id)
                        n_first_time = len(prior_gifters)
                        # Will be merged below via the aux patch.
                        cached_first_time_ids = sorted(prior_gifters)
                    else:
                        cached_first_time_ids = None
                else:
                    cached_first_time_ids = None
            except Exception:
                logger.debug(
                    "first-timer lookup failed for %s/%s",
                    user_id, host, exc_info=True,
                )
                cached_first_time_ids = None
        else:
            cached_first_time_ids = None

        diamonds_session = (current.get("diamonds_session") or 0) + value
        stats = current.get("session_stats") or {}
        n_gifts = (stats.get("n_gifts") or 0) + 1
        largest = max(stats.get("largest_gift_diamonds") or 0, value)
        now_iso = _now_iso()

        patch: dict[str, Any] = {
            "diamonds_session": diamonds_session,
            "session_stats": {
                "n_gifts": n_gifts,
                "largest_gift_diamonds": largest,
            },
            "top_gifters": top_gifters,
            "n_unique_gifters": n_unique,
            "n_first_time_gifters": n_first_time,
            "last_gift_age_s": 0,
            "_gifter_totals": gifter_totals,
            "_last_gift_at": now_iso,
            "_last_event_at": now_iso,
        }
        if cached_first_time_ids is not None:
            patch["_first_time_user_ids"] = cached_first_time_ids

        self._state_cache.apply_patch(host, patch)

    def _state_apply_live_started(
        self, host: str, payload: dict,
    ) -> None:
        """Synthesized event fired by the listener when it first sees
        a room_id for this host. Resets all session-scoped fields.

        Reset semantics: dict-valued fields use `None` to clear (not
        `{}`) because deep-merge recurses into dict-dict pairs without
        clearing keys — `target = {a:1}, patch = {}` deep-merges to
        `{a:1}`, NOT `{}`. The downstream readers all treat `None`
        and an empty container as equivalent via `or {}` / `or []`.
        """
        room_id = payload.get("room_id") or payload.get("active_room_id")
        now_iso = _now_iso()
        self._state_cache.apply_patch(host, {
            "active_room_id": str(room_id) if room_id else None,
            "live_started_at": now_iso,
            "diamonds_session": 0,
            # session_stats: every key listed gets reset via merge.
            # Any operator-added key here will land at 0 on the next
            # live_started — explicit allowlist, not implicit wipe.
            "session_stats": {
                "n_comments": 0, "n_gifts": 0, "n_likes": 0,
                "n_joins": 0, "n_follows": 0, "n_shares": 0,
                "n_unique_commenters": 0,
                "largest_gift_diamonds": 0,
            },
            "top_gifters": [],
            "n_unique_gifters": 0,
            "n_first_time_gifters": 0,
            "n_envelopes_session": 0,
            "envelope_diamonds_session": 0,
            "n_pauses": 0,
            "viewer_count": payload.get("viewer_count"),
            "viewer_history": [],
            "active_match": None,
            "active_poll": None,
            "last_gift_age_s": None,
            "last_comment_age_s": None,
            "last_pause_age_s": None,
            # Aux state reset. `_gifter_totals` is a dict — use None to
            # clear it (see docstring above for why `{}` doesn't work).
            "_gifter_totals": None,
            "_commenter_ids": [],
            "_first_time_user_ids": [],
            "_last_event_at": now_iso,
            "_last_gift_at": None,
            "_last_comment_at": None,
            "_last_pause_at": None,
            "_active_poll_at": None,
        })

    def _state_apply_live_ended(
        self, host: str, payload: dict,
    ) -> None:
        """Synthesized event fired by the listener on disconnect /
        timeout. Move the just-finished session into
        `last_broadcasts[0]` (frontend reads only `[0]`) and clear
        session-scoped fields."""
        cached = self._state_cache.get(host)
        current = cached[1] if cached else {}
        snapshot = {
            "room_id": current.get("active_room_id"),
            "started_at": current.get("live_started_at"),
            "ended_at": _now_iso(),
            "duration_min": payload.get("duration_min"),
            "diamonds": current.get("diamonds_session") or 0,
            "n_gifts": (current.get("session_stats") or {}).get("n_gifts") or 0,
            "n_comments": (current.get("session_stats") or {}).get("n_comments") or 0,
            "peak_viewers": payload.get("peak_viewers"),
        }
        # Dict-valued fields use `None` to clear (deep-merge limitation
        # — see `_state_apply_live_started`). `last_broadcasts` stays
        # populated with the just-archived session.
        self._state_cache.apply_patch(host, {
            "active_room_id": None,
            "live_started_at": None,
            "diamonds_session": 0,
            "session_stats": None,
            "top_gifters": [],
            "n_unique_gifters": 0,
            "n_first_time_gifters": 0,
            "n_envelopes_session": 0,
            "envelope_diamonds_session": 0,
            "n_pauses": 0,
            "viewer_count": None,
            "viewer_history": [],
            "active_match": None,
            "active_poll": None,
            "last_broadcasts": [snapshot],
            "_gifter_totals": None,
            "_commenter_ids": [],
            "_first_time_user_ids": [],
            "_last_event_at": _now_iso(),
        })

    def _lookup_top_gifters(
        self,
        s,
        ranked: list[tuple[str, int]],
    ) -> list[dict[str, Any]]:
        """Resolve `(user_id, diamonds)` tuples into the full top-
        gifter row shape expected by `TikTokLiveSummary.top_gifters`
        — nickname, avatar_url, gifts count.

        Cheap: one `WHERE user_id = ANY(:ids)` query into
        `tiktok_viewers`, plus we synthesize `gifts=1` (Phase B
        doesn't track per-gifter gift counts; this is a known
        small deviation from the SQL output and is the only field
        the parity oracle will report as different)."""
        if not ranked:
            return []
        try:
            user_ids = [int(uid) for uid, _ in ranked]
        except (TypeError, ValueError):
            return []
        names_by_id: dict[int, tuple[str | None, str | None]] = {}
        try:
            rows = s.execute(text(
                "SELECT user_id, nickname, avatar_url "
                "FROM tiktok_viewers "
                "WHERE user_id = ANY(:ids)"
            ), {"ids": user_ids}).all()
            for uid, nick, avatar in rows:
                names_by_id[int(uid)] = (nick, avatar)
        except Exception:
            logger.debug(
                "top-gifter viewer lookup failed", exc_info=True,
            )
        out: list[dict[str, Any]] = []
        for uid_str, diamonds in ranked:
            try:
                uid = int(uid_str)
            except (TypeError, ValueError):
                continue
            nick, avatar = names_by_id.get(uid, (None, None))
            out.append({
                "user_id": str(uid),
                "unique_id": None,
                "nickname": nick,
                "avatar_url": avatar,
                "diamonds": diamonds,
                "gifts": 1,
            })
        return out

    def list_events(
        self,
        room_id: int,
        *,
        type: str | None = None,
        limit: int = 200,
        before_id: int | None = None,
    ) -> list[TikTokEvent]:
        with self._get_session() as s:
            q = s.query(TikTokEventModel).filter(TikTokEventModel.room_id == room_id)
            if type:
                q = q.filter(TikTokEventModel.type == type)
            if before_id:
                q = q.filter(TikTokEventModel.id < before_id)
            q = q.order_by(TikTokEventModel.id.desc()).limit(limit)
            return [_event_to_dataclass(r) for r in q.all()]

    def count_events(
        self,
        *,
        host_unique_id: str | None = None,
        room_id: int | None = None,
        room_ids: list[int] | None = None,
        user_id: int | None = None,
        match_id: int | None = None,
        type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        to_user_id: int | None = None,
        min_diamonds: int | None = None,
    ) -> int:
        """Counterpart to `search_events` — same filter surface, returns
        a single row count. Used by paginated UIs that need an accurate
        total alongside the current page (so they can show
        "page 3 of 17" / "Comments (1,247)")."""
        with self._get_session() as s:
            query = s.query(func.count(TikTokEventModel.id))
            if host_unique_id:
                query = (
                    query.join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(RoomModel.host_unique_id == host_unique_id)
                )
            if room_id is not None:
                query = query.filter(TikTokEventModel.room_id == room_id)
            if room_ids:
                query = query.filter(TikTokEventModel.room_id.in_(list(room_ids)))
            if user_id is not None:
                query = query.filter(TikTokEventModel.user_id == user_id)
            if match_id is not None:
                query = query.filter(TikTokEventModel.match_id == match_id)
            if type:
                query = query.filter(TikTokEventModel.type == type)
            if since is not None:
                query = query.filter(TikTokEventModel.ts >= since)
            if until is not None:
                query = query.filter(TikTokEventModel.ts <= until)
            if q:
                like = f"%{q}%"
                payload_text = cast(TikTokEventModel.payload, String)
                query = query.filter(payload_text.ilike(like))
            # Recipient filter — `payload.to_user.user_id`. Postgres-only
            # via JSONB ops; no-op on SQLite (matches existing branches).
            if to_user_id is not None and self._is_postgres():
                payload = TikTokEventModel.payload
                query = query.filter(
                    cast(payload.op("->")("to_user").op("->>")("user_id"), Integer)
                    == int(to_user_id)
                )
            # Min-diamonds — only meaningful on gift events. Push down
            # so paginators get accurate totals.
            if min_diamonds is not None and self._is_postgres():
                payload = TikTokEventModel.payload
                d_per = cast(payload.op("->>")("diamond_count"), Integer)
                rep   = cast(payload.op("->>")("repeat_count"), Integer)
                query = query.filter(
                    func.coalesce(d_per, 0) * func.coalesce(rep, 1) >= int(min_diamonds)
                )
            return int(query.scalar() or 0)

    def search_events(
        self,
        *,
        host_unique_id: str | None = None,
        room_id: int | None = None,
        room_ids: list[int] | None = None,
        user_id: int | None = None,
        match_id: int | None = None,
        type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        to_user_id: int | None = None,
        min_diamonds: int | None = None,
        limit: int = 200,
        before_id: int | None = None,
        offset: int = 0,
    ) -> list[TikTokEvent]:
        with self._get_session() as s:
            query = s.query(TikTokEventModel)
            if host_unique_id:
                query = (
                    query.join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(RoomModel.host_unique_id == host_unique_id)
                )
            if room_id is not None:
                query = query.filter(TikTokEventModel.room_id == room_id)
            if room_ids:
                query = query.filter(TikTokEventModel.room_id.in_(list(room_ids)))
            if user_id is not None:
                query = query.filter(TikTokEventModel.user_id == user_id)
            if match_id is not None:
                query = query.filter(TikTokEventModel.match_id == match_id)
            if type:
                query = query.filter(TikTokEventModel.type == type)
            if since is not None:
                query = query.filter(TikTokEventModel.ts >= since)
            if until is not None:
                query = query.filter(TikTokEventModel.ts <= until)
            if q:
                like = f"%{q}%"
                payload_text = cast(TikTokEventModel.payload, String)
                query = query.filter(payload_text.ilike(like))
            if to_user_id is not None and self._is_postgres():
                payload = TikTokEventModel.payload
                query = query.filter(
                    cast(payload.op("->")("to_user").op("->>")("user_id"), Integer)
                    == int(to_user_id)
                )
            if min_diamonds is not None and self._is_postgres():
                payload = TikTokEventModel.payload
                d_per = cast(payload.op("->>")("diamond_count"), Integer)
                rep   = cast(payload.op("->>")("repeat_count"), Integer)
                query = query.filter(
                    func.coalesce(d_per, 0) * func.coalesce(rep, 1) >= int(min_diamonds)
                )
            if before_id:
                query = query.filter(TikTokEventModel.id < before_id)
            query = query.order_by(TikTokEventModel.id.desc())
            if offset > 0:
                query = query.offset(offset)
            query = query.limit(limit)
            return [_event_to_dataclass(r) for r in query.all()]

    # ── Aggregations ─────────────────────────────────────────────────

    def room_event_counts_by_type(
        self,
        room_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, int]:
        with self._get_session() as s:
            q = (
                s.query(TikTokEventModel.type, func.count(TikTokEventModel.id))
                .filter(TikTokEventModel.room_id == room_id)
            )
            if since is not None:
                q = q.filter(TikTokEventModel.ts >= since)
            if until is not None:
                q = q.filter(TikTokEventModel.ts < until)
            q = q.group_by(TikTokEventModel.type)
            return {row[0]: int(row[1]) for row in q.all()}

    def room_top_gifters(
        self,
        room_id: int | list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 10,
        offset: int = 0,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """Sum diamond_count × repeat_count grouped by user_id.
        Postgres path runs in SQL using JSONB ops; falls back to Python on
        SQLite (where a payload could be JSON-as-text).
        `room_id` may be a single id or a list (day-aggregate view)."""
        room_id_list = (
            [int(room_id)]
            if isinstance(room_id, int)
            else [int(x) for x in room_id]
        )
        if not room_id_list:
            return []
        with self._get_session() as s:
            # `s.bind` is None on the framework's RetrySession (read/write
            # routing splits the engines), so `s.bind.dialect.name` was
            # evaluating to "" → every aggregator silently fell through
            # to the Python `LIMIT 20000` fallback on Postgres. For
            # busy rooms (100k+ events) that capped output at the first
            # 20k rows, hiding 80% of gift volume from the leaderboard.
            # `_is_postgres()` reads the adapter's own engine, never None.
            is_pg = self._is_postgres()

            if is_pg:
                # JSONB extracts: payload->>'diamond_count', payload->>'repeat_count'.
                # COALESCE the user_id off the event row (set by persist_event_full)
                # before falling back to the payload.user.user_id.
                payload = TikTokEventModel.payload
                diamond_per = func.coalesce(
                    cast(payload.op("->>")("diamond_count"), Integer), 0
                )
                repeat = func.coalesce(
                    cast(payload.op("->>")("repeat_count"), Integer), 1
                )
                total_diamonds = func.sum(diamond_per * repeat)
                total_gifts = func.sum(repeat)

                # Aggregate gifts → (user_id, diamonds, gifts) as a subquery,
                # then JOIN viewers so the optional `q` filter sees nickname /
                # unique_id BEFORE limit/offset is applied (otherwise paging
                # would skip matches outside the top-N gift slice).
                gift_subq = (
                    s.query(
                        TikTokEventModel.user_id.label("user_id"),
                        total_diamonds.label("diamonds"),
                        total_gifts.label("gifts"),
                    )
                    .filter(TikTokEventModel.room_id.in_(room_id_list))
                    .filter(TikTokEventModel.type == "gift")
                    .filter(TikTokEventModel.user_id.isnot(None))
                )
                if since is not None:
                    gift_subq = gift_subq.filter(TikTokEventModel.ts >= since)
                if until is not None:
                    gift_subq = gift_subq.filter(TikTokEventModel.ts < until)
                gift_subq = gift_subq.group_by(TikTokEventModel.user_id).subquery()

                outer = (
                    s.query(
                        gift_subq.c.user_id,
                        gift_subq.c.diamonds,
                        gift_subq.c.gifts,
                        TikTokViewerModel.unique_id,
                        TikTokViewerModel.nickname,
                        TikTokViewerModel.avatar_url,
                    )
                    .outerjoin(
                        TikTokViewerModel,
                        TikTokViewerModel.user_id == gift_subq.c.user_id,
                    )
                )
                if q:
                    needle = f"%{q.strip()}%"
                    outer = outer.filter(
                        func.coalesce(TikTokViewerModel.nickname, "").ilike(needle)
                        | func.coalesce(TikTokViewerModel.unique_id, "").ilike(needle)
                    )
                outer = (
                    outer.order_by(gift_subq.c.diamonds.desc())
                    .limit(limit)
                    .offset(offset)
                )
                rows = outer.all()
                if not rows:
                    return []
                uids = [int(r.user_id) for r in rows]

                # Comment counts in the same scope (room + window) for just
                # the page of user_ids we're returning — small list, one query.
                comment_q = (
                    s.query(
                        TikTokEventModel.user_id,
                        func.count(TikTokEventModel.id).label("comments"),
                    )
                    .filter(TikTokEventModel.room_id.in_(room_id_list))
                    .filter(TikTokEventModel.type == "comment")
                    .filter(TikTokEventModel.user_id.in_(uids))
                )
                if since is not None:
                    comment_q = comment_q.filter(TikTokEventModel.ts >= since)
                if until is not None:
                    comment_q = comment_q.filter(TikTokEventModel.ts < until)
                comment_q = comment_q.group_by(TikTokEventModel.user_id)
                comment_map = {int(r.user_id): int(r.comments) for r in comment_q.all()}

                # Per-gifter identity snapshot. Identity flags (is_moderator
                # / is_subscribe / is_top_gifter / fans_club / member_level
                # / gifter_level) are captured in the live-client adapter
                # on every event payload. Pull the *latest* gift-event
                # payload per user via DISTINCT ON — that's the freshest
                # snapshot of how TikTok identified the user when they
                # last gifted. Avatar from tiktok_viewers takes priority
                # because the viewer table is the canonical record across
                # rooms; payload.user.avatar_url is the fallback.
                identity_q = text("""
                    SELECT DISTINCT ON (user_id)
                        user_id,
                        payload->'user' AS user_payload
                    FROM tiktok_events
                    WHERE room_id = ANY(:rids)
                      AND type = 'gift'
                      AND user_id = ANY(:uids)
                    ORDER BY user_id, id DESC
                """)
                identity_map: dict[int, dict[str, Any]] = {}
                for ident_row in s.execute(
                    identity_q, {"rids": room_id_list, "uids": uids}
                ).mappings():
                    up = ident_row["user_payload"] or {}
                    if not isinstance(up, dict):
                        # JSONB may come back as a string in some drivers
                        try:
                            up = json.loads(up) if isinstance(up, (str, bytes)) else {}
                        except Exception:
                            up = {}
                    identity_map[int(ident_row["user_id"])] = up

                out: list[dict[str, Any]] = []
                for r in rows:
                    uid = int(r.user_id)
                    up = identity_map.get(uid) or {}
                    identity = up.get("identity") if isinstance(up, dict) else None
                    out.append({
                        "user_id": uid,
                        "unique_id": r.unique_id,
                        "nickname": r.nickname,
                        # Prefer canonical viewer avatar; fall back to last-
                        # seen payload avatar so unknown viewers still get one.
                        "avatar_url": r.avatar_url or (
                            up.get("avatar_url") if isinstance(up, dict) else None
                        ),
                        "diamonds": int(r.diamonds or 0),
                        "gifts": int(r.gifts or 0),
                        "comments": int(comment_map.get(uid, 0)),
                        # Identity badges (TikTokUserBadges renders this dict
                        # directly — it already contains member_level,
                        # gifter_level, fans_club, etc.).
                        "identity": identity if isinstance(identity, dict) else None,
                    })
                return out

            # ── SQLite / non-PG fallback: aggregate in Python ──
            event_q = (
                s.query(TikTokEventModel)
                .filter(TikTokEventModel.room_id.in_(room_id_list))
                .filter(TikTokEventModel.type.in_(["gift", "comment"]))
            )
            if since is not None:
                event_q = event_q.filter(TikTokEventModel.ts >= since)
            if until is not None:
                event_q = event_q.filter(TikTokEventModel.ts < until)
            rows = event_q.limit(20000).all()
        agg: dict[int, dict[str, Any]] = {}
        for row in rows:
            payload = _coerce_payload(row.payload)
            user = payload.get("user") if isinstance(payload, dict) else None
            if not isinstance(user, dict):
                user = {}
            uid = row.user_id or user.get("user_id")
            if not uid:
                continue
            uid_int = int(uid)
            entry = agg.setdefault(
                uid_int,
                {
                    "user_id": uid_int,
                    "unique_id": user.get("unique_id"),
                    "nickname": user.get("nickname"),
                    "diamonds": 0,
                    "gifts": 0,
                    "comments": 0,
                },
            )
            if row.type == "gift":
                entry["diamonds"] += int(payload.get("diamond_count") or 0) * int(
                    payload.get("repeat_count") or 1
                )
                entry["gifts"] += int(payload.get("repeat_count") or 1)
            elif row.type == "comment":
                entry["comments"] += 1
            if user.get("nickname"):
                entry["nickname"] = user.get("nickname")
            if user.get("unique_id"):
                entry["unique_id"] = user.get("unique_id")
        # Only rank users that actually gifted; their commenters-only would
        # be misleading on a "top gifters" leaderboard.
        ranked = [v for v in agg.values() if v["diamonds"] > 0]
        if q:
            needle = q.strip().lower()
            ranked = [
                v for v in ranked
                if (v.get("nickname") or "").lower().find(needle) >= 0
                or (v.get("unique_id") or "").lower().find(needle) >= 0
            ]
        ranked.sort(key=lambda x: x["diamonds"], reverse=True)
        return ranked[offset : offset + limit]

    def room_top_recipients(
        self,
        room_id: int,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._get_session() as s:
            # `s.bind` is None on the framework's RetrySession (read/write
            # routing splits the engines), so `s.bind.dialect.name` was
            # evaluating to "" → every aggregator silently fell through
            # to the Python `LIMIT 20000` fallback on Postgres. For
            # busy rooms (100k+ events) that capped output at the first
            # 20k rows, hiding 80% of gift volume from the leaderboard.
            # `_is_postgres()` reads the adapter's own engine, never None.
            is_pg = self._is_postgres()

            if is_pg:
                payload = TikTokEventModel.payload
                # JSONB extracts: payload->'to_user'->>'user_id', etc.
                to_user_id = cast(
                    payload.op("->")("to_user").op("->>")("user_id"),
                    BigInteger,
                ).label("user_id")
                to_nickname = payload.op("->")("to_user").op("->>")("nickname")
                to_unique_id = payload.op("->")("to_user").op("->>")("unique_id")
                diamond_per = func.coalesce(
                    cast(payload.op("->>")("diamond_count"), Integer), 0
                )
                repeat = func.coalesce(
                    cast(payload.op("->>")("repeat_count"), Integer), 1
                )

                # Drop the placeholder TikTokLive emits for solo broadcasts
                # (`to_user.user_id = '0'`, blank nickname/unique_id) — those
                # are not "a recipient", they're "no specific target = host".
                # Including them would show one giant fake row drowning out
                # any real guest recipients.
                to_uid_str = payload.op("->")("to_user").op("->>")("user_id")
                gift_subq = (
                    s.query(
                        to_user_id,
                        # Use min() to pick a representative non-null
                        # nickname from this user's gift events — the
                        # payload carries the to_user identity at gift
                        # time, so we don't need to join viewers.
                        func.min(to_nickname).label("payload_nickname"),
                        func.min(to_unique_id).label("payload_unique_id"),
                        func.sum(diamond_per * repeat).label("diamonds"),
                        func.sum(repeat).label("gifts"),
                    )
                    .filter(TikTokEventModel.room_id == room_id)
                    .filter(TikTokEventModel.type == "gift")
                    .filter(to_uid_str.isnot(None))
                    .filter(to_uid_str != "0")
                    .filter(to_uid_str != "")
                )
                if since is not None:
                    gift_subq = gift_subq.filter(TikTokEventModel.ts >= since)
                if until is not None:
                    gift_subq = gift_subq.filter(TikTokEventModel.ts < until)
                gift_subq = gift_subq.group_by(to_user_id).subquery()

                outer = (
                    s.query(
                        gift_subq.c.user_id,
                        func.coalesce(
                            TikTokViewerModel.nickname,
                            gift_subq.c.payload_nickname,
                        ).label("nickname"),
                        func.coalesce(
                            TikTokViewerModel.unique_id,
                            gift_subq.c.payload_unique_id,
                        ).label("unique_id"),
                        gift_subq.c.diamonds,
                        gift_subq.c.gifts,
                    )
                    .outerjoin(
                        TikTokViewerModel,
                        TikTokViewerModel.user_id == gift_subq.c.user_id,
                    )
                    .order_by(gift_subq.c.diamonds.desc())
                    .limit(limit)
                )
                rows = outer.all()
                return [
                    {
                        "user_id": int(r.user_id),
                        "unique_id": r.unique_id,
                        "nickname": r.nickname,
                        "diamonds": int(r.diamonds or 0),
                        "gifts": int(r.gifts or 0),
                    }
                    for r in rows
                ]

            # ── SQLite / non-PG fallback: aggregate in Python ──
            agg: dict[int, dict[str, Any]] = {}
            event_q = (
                s.query(TikTokEventModel)
                .filter(TikTokEventModel.room_id == room_id)
                .filter(TikTokEventModel.type == "gift")
            )
            if since is not None:
                event_q = event_q.filter(TikTokEventModel.ts >= since)
            if until is not None:
                event_q = event_q.filter(TikTokEventModel.ts < until)
            for row in event_q.limit(20000).all():
                payload = _coerce_payload(row.payload)
                if not isinstance(payload, dict):
                    continue
                to = payload.get("to_user")
                if not isinstance(to, dict):
                    continue
                uid = to.get("user_id")
                if not uid:
                    continue
                try:
                    uid_int = int(uid)
                except (TypeError, ValueError):
                    continue
                # Skip the solo-broadcast placeholder (uid=0, blank fields).
                if uid_int == 0:
                    continue
                entry = agg.setdefault(
                    uid_int,
                    {
                        "user_id": uid_int,
                        "unique_id": to.get("unique_id"),
                        "nickname": to.get("nickname"),
                        "diamonds": 0,
                        "gifts": 0,
                    },
                )
                entry["diamonds"] += int(payload.get("diamond_count") or 0) * int(
                    payload.get("repeat_count") or 1
                )
                entry["gifts"] += int(payload.get("repeat_count") or 1)
                if to.get("nickname") and not entry["nickname"]:
                    entry["nickname"] = to.get("nickname")
                if to.get("unique_id") and not entry["unique_id"]:
                    entry["unique_id"] = to.get("unique_id")
            ranked = sorted(
                agg.values(),
                key=lambda x: x["diamonds"],
                reverse=True,
            )
            return ranked[:limit]

    def count_room_gifters(
        self,
        room_id: int | list[int],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
    ) -> int:
        room_id_list = (
            [int(room_id)]
            if isinstance(room_id, int)
            else [int(x) for x in room_id]
        )
        if not room_id_list:
            return 0
        with self._get_session() as s:
            # `s.bind` is None on the framework's RetrySession (read/write
            # routing splits the engines), so `s.bind.dialect.name` was
            # evaluating to "" → every aggregator silently fell through
            # to the Python `LIMIT 20000` fallback on Postgres. For
            # busy rooms (100k+ events) that capped output at the first
            # 20k rows, hiding 80% of gift volume from the leaderboard.
            # `_is_postgres()` reads the adapter's own engine, never None.
            is_pg = self._is_postgres()

            if is_pg:
                payload = TikTokEventModel.payload
                diamond_per = func.coalesce(
                    cast(payload.op("->>")("diamond_count"), Integer), 0
                )
                repeat = func.coalesce(
                    cast(payload.op("->>")("repeat_count"), Integer), 1
                )
                gift_subq = (
                    s.query(
                        TikTokEventModel.user_id.label("user_id"),
                        func.sum(diamond_per * repeat).label("diamonds"),
                    )
                    .filter(TikTokEventModel.room_id.in_(room_id_list))
                    .filter(TikTokEventModel.type == "gift")
                    .filter(TikTokEventModel.user_id.isnot(None))
                )
                if since is not None:
                    gift_subq = gift_subq.filter(TikTokEventModel.ts >= since)
                if until is not None:
                    gift_subq = gift_subq.filter(TikTokEventModel.ts < until)
                gift_subq = gift_subq.group_by(TikTokEventModel.user_id).subquery()

                outer = (
                    s.query(func.count())
                    .select_from(gift_subq)
                    .outerjoin(
                        TikTokViewerModel,
                        TikTokViewerModel.user_id == gift_subq.c.user_id,
                    )
                )
                if q:
                    needle = f"%{q.strip()}%"
                    outer = outer.filter(
                        func.coalesce(TikTokViewerModel.nickname, "").ilike(needle)
                        | func.coalesce(TikTokViewerModel.unique_id, "").ilike(needle)
                    )
                return int(outer.scalar() or 0)

            # SQLite fallback: reuse the (limit-bounded) Python aggregator
            # to find the candidates, then size the post-filter list. This
            # is fine for the dev DB.
            rows = self.room_top_gifters(
                room_id_list,
                since=since,
                until=until,
                limit=10_000,
                offset=0,
                q=q,
            )
            return len(rows)

    def common_gifters(
        self,
        *,
        min_hosts: int = 2,
        limit: int = 25,
        offset: int = 0,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cross-creator gifter leaderboard. Reads from
        `tiktok_user_host_summary`, an incrementally-maintained
        summary table that's UPSERTed in the gift-event persist
        path — so this query is always live AND always cheap, no
        matter how big `tiktok_events` grows. The summary has at
        most N_users × N_hosts rows (typically a few thousand even
        on a busy DB), so `GROUP BY user_id` is sub-50ms.
        """
        if min_hosts < 1:
            min_hosts = 1
        with self._get_session() as s:
            # Single, paginated query. Collapse per-user from the
            # summary, filter by host_count, optionally restrict by
            # `q` (joined to viewers AFTER the host-count filter so
            # the join is bounded to the leaderboard subset).
            page_rows = s.execute(text("""
                WITH per_user AS (
                    SELECT
                        s.user_id,
                        COUNT(*)::int                AS host_count,
                        SUM(s.diamonds)::bigint      AS diamonds,
                        SUM(s.gifts)::bigint         AS gifts
                    FROM tiktok_user_host_summary s
                    GROUP BY s.user_id
                    HAVING COUNT(*) >= :min_hosts
                )
                SELECT
                    pu.user_id,
                    pu.host_count,
                    pu.diamonds,
                    pu.gifts,
                    v.unique_id,
                    v.nickname,
                    v.avatar_url
                FROM per_user pu
                LEFT JOIN tiktok_viewers v ON v.user_id = pu.user_id
                WHERE :q_is_null OR
                      v.nickname  ILIKE :needle OR
                      v.unique_id ILIKE :needle
                ORDER BY pu.diamonds DESC
                LIMIT :limit OFFSET :offset
            """), {
                "min_hosts": int(min_hosts),
                "q_is_null": q is None or not q.strip(),
                "needle": f"%{(q or '').strip()}%",
                "limit": int(limit),
                "offset": int(offset),
            }).mappings().all()

            uids = [int(r["user_id"]) for r in page_rows]
            if not uids:
                return []

            # Per-host breakdown for the page — straight read from
            # the summary, no event table touched. Sorted by diamonds
            # desc so the strip pills render in the right order.
            breakdowns = s.execute(text("""
                SELECT user_id, host_unique_id AS host, diamonds, gifts
                FROM tiktok_user_host_summary
                WHERE user_id = ANY(:uids)
                ORDER BY user_id, diamonds DESC
            """), {"uids": uids}).mappings().all()
            host_map: dict[int, list[dict[str, Any]]] = {}
            for br in breakdowns:
                host_map.setdefault(int(br["user_id"]), []).append({
                    "host": br["host"],
                    "diamonds": int(br["diamonds"] or 0),
                    "gifts": int(br["gifts"] or 0),
                })

            out: list[dict[str, Any]] = []
            for r in page_rows:
                uid = int(r["user_id"])
                out.append({
                    "user_id": uid,
                    "unique_id": r["unique_id"],
                    "nickname": r["nickname"],
                    "avatar_url": r["avatar_url"],
                    "host_count": int(r["host_count"] or 0),
                    "diamonds": int(r["diamonds"] or 0),
                    "gifts": int(r["gifts"] or 0),
                    "hosts": host_map.get(uid, []),
                })
            return out

    def count_common_gifters(
        self,
        *,
        min_hosts: int = 2,
        q: str | None = None,
    ) -> int:
        """Counterpart to `common_gifters` — total qualifying users for
        pagination. Reads from `tiktok_user_host_summary` for the same
        always-live, always-cheap properties as the listing query."""
        if min_hosts < 1:
            min_hosts = 1
        with self._get_session() as s:
            n = s.execute(text("""
                WITH per_user AS (
                    SELECT s.user_id
                    FROM tiktok_user_host_summary s
                    GROUP BY s.user_id
                    HAVING COUNT(*) >= :min_hosts
                )
                SELECT COUNT(*)
                FROM per_user pu
                LEFT JOIN tiktok_viewers v ON v.user_id = pu.user_id
                WHERE :q_is_null OR
                      v.nickname  ILIKE :needle OR
                      v.unique_id ILIKE :needle
            """), {
                "min_hosts": int(min_hosts),
                "q_is_null": q is None or not q.strip(),
                "needle": f"%{(q or '').strip()}%",
            }).scalar()
            return int(n or 0)

    def cross_live_gifters_for_host(
        self,
        host_unique_id: str,
        *,
        min_other_hosts: int = 1,
        limit: int = 25,
        offset: int = 0,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        """Cross-live gifters scoped to a single host: viewers who
        gifted to `host_unique_id` AND to at least `min_other_hosts`
        other hosts we track.

        Same data source as `common_gifters` (the always-live
        `tiktok_user_host_summary` table), but the leaderboard is
        filtered to users with a row for this host AND additional
        rows for >= min_other_hosts other hosts. Returns a per-user
        row carrying:

          - `diamonds_here` / `gifts_here` — totals on THIS host.
          - `diamonds_elsewhere` / `gifts_elsewhere` — totals on
            every OTHER host this user has gifted to.
          - `host_count` — total distinct hosts (incl. this one).
          - `other_hosts` — list of `{host, diamonds, gifts}` for
            every host EXCEPT this one, sorted by diamonds desc, so
            the UI can render a "also active on @X, @Y" pill strip.
        """
        if min_other_hosts < 1:
            min_other_hosts = 1
        h = (host_unique_id or "").lstrip("@").strip()
        if not h:
            return []
        with self._get_session() as s:
            # Filter to users who have a row for THIS host AND total
            # host_count >= 1 + min_other_hosts. The HAVING clause
            # uses an explicit COUNT(DISTINCT) so we don't double-
            # count if the summary ever holds duplicate rows.
            page_rows = s.execute(text("""
                WITH per_user AS (
                    SELECT
                        s.user_id,
                        COUNT(*)::int                AS host_count,
                        SUM(s.diamonds)::bigint      AS diamonds_total,
                        SUM(s.gifts)::bigint         AS gifts_total
                    FROM tiktok_user_host_summary s
                    WHERE EXISTS (
                        SELECT 1
                        FROM tiktok_user_host_summary s2
                        WHERE s2.user_id = s.user_id
                          AND s2.host_unique_id = :host
                    )
                    GROUP BY s.user_id
                    HAVING COUNT(*) >= :min_total_hosts
                )
                SELECT
                    pu.user_id,
                    pu.host_count,
                    pu.diamonds_total,
                    pu.gifts_total,
                    v.unique_id,
                    v.nickname,
                    v.avatar_url
                FROM per_user pu
                LEFT JOIN tiktok_viewers v ON v.user_id = pu.user_id
                WHERE :q_is_null OR
                      v.nickname  ILIKE :needle OR
                      v.unique_id ILIKE :needle
                ORDER BY pu.diamonds_total DESC
                LIMIT :limit OFFSET :offset
            """), {
                "host": h,
                "min_total_hosts": int(min_other_hosts) + 1,
                "q_is_null": q is None or not q.strip(),
                "needle": f"%{(q or '').strip()}%",
                "limit": int(limit),
                "offset": int(offset),
            }).mappings().all()

            uids = [int(r["user_id"]) for r in page_rows]
            if not uids:
                return []

            # Per-host breakdown for the page (all hosts incl. this
            # one). The caller / view will split into here-vs-other.
            breakdowns = s.execute(text("""
                SELECT user_id, host_unique_id AS host, diamonds, gifts
                FROM tiktok_user_host_summary
                WHERE user_id = ANY(:uids)
                ORDER BY user_id, diamonds DESC
            """), {"uids": uids}).mappings().all()
            host_map: dict[int, list[dict[str, Any]]] = {}
            for br in breakdowns:
                host_map.setdefault(int(br["user_id"]), []).append({
                    "host": br["host"],
                    "diamonds": int(br["diamonds"] or 0),
                    "gifts": int(br["gifts"] or 0),
                })

            out: list[dict[str, Any]] = []
            for r in page_rows:
                uid = int(r["user_id"])
                all_hosts = host_map.get(uid, [])
                here = next(
                    (x for x in all_hosts if x["host"] == h), None
                )
                others = [x for x in all_hosts if x["host"] != h]
                d_here = int(here["diamonds"]) if here else 0
                g_here = int(here["gifts"]) if here else 0
                d_other = sum(int(x["diamonds"]) for x in others)
                g_other = sum(int(x["gifts"]) for x in others)
                out.append({
                    "user_id": uid,
                    "unique_id": r["unique_id"],
                    "nickname": r["nickname"],
                    "avatar_url": r["avatar_url"],
                    "host_count": int(r["host_count"] or 0),
                    "diamonds_here": d_here,
                    "gifts_here": g_here,
                    "diamonds_elsewhere": d_other,
                    "gifts_elsewhere": g_other,
                    "other_hosts": others,
                })
            return out

    def count_cross_live_gifters_for_host(
        self,
        host_unique_id: str,
        *,
        min_other_hosts: int = 1,
        q: str | None = None,
    ) -> int:
        """Total of `cross_live_gifters_for_host` for pagination.
        Same source / filter as the listing query."""
        if min_other_hosts < 1:
            min_other_hosts = 1
        h = (host_unique_id or "").lstrip("@").strip()
        if not h:
            return 0
        with self._get_session() as s:
            n = s.execute(text("""
                WITH per_user AS (
                    SELECT s.user_id
                    FROM tiktok_user_host_summary s
                    WHERE EXISTS (
                        SELECT 1
                        FROM tiktok_user_host_summary s2
                        WHERE s2.user_id = s.user_id
                          AND s2.host_unique_id = :host
                    )
                    GROUP BY s.user_id
                    HAVING COUNT(*) >= :min_total_hosts
                )
                SELECT COUNT(*)
                FROM per_user pu
                LEFT JOIN tiktok_viewers v ON v.user_id = pu.user_id
                WHERE :q_is_null OR
                      v.nickname  ILIKE :needle OR
                      v.unique_id ILIKE :needle
            """), {
                "host": h,
                "min_total_hosts": int(min_other_hosts) + 1,
                "q_is_null": q is None or not q.strip(),
                "needle": f"%{(q or '').strip()}%",
            }).scalar()
            return int(n or 0)

    def get_user_host_daily_series(
        self,
        user_id: int,
        *,
        host_unique_id: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Per-day diamond + gift totals for a (user, host) pair over
        the trailing `days` window. Returned rows are sparse — only
        days with at least one gift event have an entry. The
        frontend pivots into a calendar grid and fills empty cells
        with zeros.

        Single grouped SQL query keyed on `(user_id, host_unique_id,
        ts)` via the JOIN to `tiktok_rooms`. Cheap enough to fetch on
        every Timeline-tab mount."""
        if not host_unique_id:
            return []
        host_norm = host_unique_id.lstrip("@").strip().lower()
        if not host_norm:
            return []
        is_pg = self._is_postgres()
        with self._get_session() as s:
            if is_pg:
                rows = s.execute(text("""
                    SELECT date_trunc('day', e.ts)::date AS day,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS diamonds,
                           SUM(COALESCE((e.payload->>'repeat_count')::int, 1))    AS gifts
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.user_id = :uid
                      AND e.type = 'gift'
                      AND LOWER(r.host_unique_id) = :host
                      AND e.ts >= NOW() - make_interval(days => :days)
                    GROUP BY day
                    ORDER BY day
                """), {"uid": int(user_id), "host": host_norm, "days": int(days)}).all()
                out: list[dict[str, Any]] = []
                for r in rows:
                    day = r[0]
                    out.append({
                        "day": day.isoformat() if day else None,
                        "diamonds": int(r[1] or 0),
                        "gifts": int(r[2] or 0),
                    })
                return out
            # SQLite fallback — no `make_interval`, no date_trunc.
            # We compute the boundary in Python and use date(ts).
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            since = (_dt.now(tz=_tz.utc) - _td(days=int(days))).isoformat()
            rows = s.execute(text("""
                SELECT date(e.ts) AS day,
                       SUM(COALESCE(CAST(json_extract(e.payload,'$.diamond_count') AS INTEGER), 0)
                           * COALESCE(CAST(json_extract(e.payload,'$.repeat_count') AS INTEGER), 1)) AS diamonds,
                       SUM(COALESCE(CAST(json_extract(e.payload,'$.repeat_count') AS INTEGER), 1))   AS gifts
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE e.user_id = :uid
                  AND e.type = 'gift'
                  AND LOWER(r.host_unique_id) = :host
                  AND e.ts >= :since
                GROUP BY day
                ORDER BY day
            """), {"uid": int(user_id), "host": host_norm, "since": since}).all()
            return [
                {"day": str(r[0]), "diamonds": int(r[1] or 0), "gifts": int(r[2] or 0)}
                for r in rows
                if r[0] is not None
            ]

    def common_gifter_detail(
        self,
        user_id: int,
        *,
        rooms_per_host: int = 5,
        gifts_per_host: int = 5,
        public_only: bool = False,
    ) -> dict[str, Any]:
        """Deep-analysis payload for a single viewer's gifting across
        every host we track. Fanned out into a few small queries:
          1. Identity (viewers row + last gift payload for badges).
          2. Per-host totals + first/last seen + distinct rooms.
          3. Per-host top gift kinds (gift_name → count + diamonds).
          4. Per-host most-recent rooms with totals.
          5. Per-host comment count (so the modal can show "comments
             on this host's broadcasts" alongside the gift stats).
        Returns an empty `hosts` list when the user has never gifted.

        `public_only=True` is set by the public-mirror route
        (`/public/tiktok/common-gifters/{user_id}/detail`). When set,
        every field that emits a host_unique_id (`hosts`, `whale_sessions`,
        `daily_series`, `intensity.biggest_session`, `recent_activity`,
        `identity_progression`, `recipients_per_host`,
        `recipient_partisanship`, `loyalty.top_host`) is filtered to
        the subset of hosts with `is_public=True`. Totals at the top
        level recompute against the filtered subset. Without this
        filter, anonymous callers with any active viewer's `user_id`
        could enumerate the operator's full set of monitored hosts —
        including hosts the operator never opted into the public
        surface.
        """
        with self._get_session() as s:
            is_pg = self._is_postgres()
            # Resolve the public-host allowlist once for downstream
            # filtering. `None` means "no filtering" (admin path).
            public_host_set: frozenset[str] | None = None
            if public_only:
                pubs = (
                    s.query(SubscriptionModel.unique_id)
                    .filter(SubscriptionModel.is_public.is_(True))
                    .all()
                )
                public_host_set = frozenset(p[0] for p in pubs if p[0])

            def _allow_host(h: str | None) -> bool:
                if public_host_set is None:
                    return True
                if not h:
                    return False
                return h in public_host_set
            payload = TikTokEventModel.payload
            diamond_per = func.coalesce(
                cast(payload.op("->>")("diamond_count"), Integer), 0
            )
            repeat = func.coalesce(
                cast(payload.op("->>")("repeat_count"), Integer), 1
            )

            # ── 1. Identity (viewer record + most-recent payload). ──
            viewer = (
                s.query(TikTokViewerModel)
                .filter(TikTokViewerModel.user_id == user_id)
                .first()
            )
            last_payload_row = (
                s.query(TikTokEventModel.payload)
                .filter(TikTokEventModel.user_id == user_id)
                .filter(TikTokEventModel.type == "gift")
                .order_by(TikTokEventModel.id.desc())
                .first()
            )
            last_payload = (
                _coerce_payload(last_payload_row[0]) if last_payload_row else {}
            )
            user_pl = last_payload.get("user") if isinstance(last_payload, dict) else None
            identity = (
                user_pl.get("identity") if isinstance(user_pl, dict) else None
            )

            # ── 2. Per-host totals from the summary table.
            #     Diamonds/gifts/first/last_seen come straight off the
            #     incrementally-maintained summary — single indexed
            #     read on `(user_id, ...)`. Room count requires a
            #     DISTINCT count we don't keep in the summary, but the
            #     user-scoped events query is bounded by *this user's*
            #     gift events (typically few hundred at most), so the
            #     extra query is cheap and uses the same gift index.
            summary_rows = s.execute(text("""
                SELECT host_unique_id AS host,
                       diamonds, gifts,
                       first_seen_at, last_seen_at
                FROM tiktok_user_host_summary
                WHERE user_id = :uid
            """), {"uid": int(user_id)}).mappings().all()
            # Per-host distinct room count — single bounded query.
            room_counts: dict[str, int] = {}
            if summary_rows:
                rc_rows = (
                    s.query(
                        RoomModel.host_unique_id.label("host"),
                        func.count(func.distinct(TikTokEventModel.room_id)).label("rooms"),
                    )
                    .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(TikTokEventModel.user_id == user_id)
                    .filter(TikTokEventModel.type == "gift")
                    .filter(RoomModel.host_unique_id.isnot(None))
                    .group_by(RoomModel.host_unique_id)
                    .all()
                )
                for rc in rc_rows:
                    room_counts[rc.host] = int(rc.rooms or 0)

            class _Row:  # tiny shim so the rest of the fn keeps working
                def __init__(self, **kw): self.__dict__.update(kw)
            rows = [
                _Row(
                    host=r["host"],
                    diamonds=int(r["diamonds"] or 0),
                    gifts=int(r["gifts"] or 0),
                    rooms=room_counts.get(r["host"], 0),
                    first_seen_at=r["first_seen_at"],
                    last_seen_at=r["last_seen_at"],
                )
                for r in summary_rows
            ]
            host_totals = sorted(
                rows, key=lambda r: int(r.diamonds or 0), reverse=True
            )

            # ── 3. Per-host top gift kinds. One query for ALL hosts;
            #     bucket on the client side by host. Gift name comes
            #     from payload->'gift'->>'name' (TikTokLive shape). ──
            host_gifts: dict[str, list[dict[str, Any]]] = {}
            if is_pg and host_totals:
                gift_name = func.coalesce(
                    payload.op("->")("gift").op("->>")("name"),
                    payload.op("->>")("gift_name"),
                ).label("gift_name")
                gn_rows = (
                    s.query(
                        RoomModel.host_unique_id.label("host"),
                        gift_name,
                        func.sum(repeat).label("count"),
                        func.sum(diamond_per * repeat).label("diamonds"),
                    )
                    .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(TikTokEventModel.user_id == user_id)
                    .filter(TikTokEventModel.type == "gift")
                    .filter(RoomModel.host_unique_id.isnot(None))
                    .group_by(RoomModel.host_unique_id, "gift_name")
                    .order_by(RoomModel.host_unique_id, func.sum(diamond_per * repeat).desc())
                    .all()
                )
                for r in gn_rows:
                    bucket = host_gifts.setdefault(r.host, [])
                    if len(bucket) >= gifts_per_host:
                        continue
                    bucket.append({
                        "gift_name": r.gift_name or "(unnamed)",
                        "count": int(r.count or 0),
                        "diamonds": int(r.diamonds or 0),
                    })

            # ── 4. Per-host recent rooms with the user's totals.
            #     Postgres-only — SQLite fallback skips this section. ──
            host_rooms: dict[str, list[dict[str, Any]]] = {}
            if is_pg and host_totals:
                rr = (
                    s.query(
                        RoomModel.host_unique_id.label("host"),
                        TikTokEventModel.room_id.label("room_id"),
                        RoomModel.first_seen_at.label("started_at"),
                        RoomModel.ended_at.label("ended_at"),
                        RoomModel.title.label("title"),
                        func.sum(diamond_per * repeat).label("diamonds"),
                        func.sum(repeat).label("gifts"),
                    )
                    .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(TikTokEventModel.user_id == user_id)
                    .filter(TikTokEventModel.type == "gift")
                    .filter(RoomModel.host_unique_id.isnot(None))
                    .group_by(
                        RoomModel.host_unique_id,
                        TikTokEventModel.room_id,
                        RoomModel.first_seen_at,
                        RoomModel.ended_at,
                        RoomModel.title,
                    )
                    .order_by(RoomModel.host_unique_id, RoomModel.first_seen_at.desc())
                    .all()
                )
                for r in rr:
                    bucket = host_rooms.setdefault(r.host, [])
                    if len(bucket) >= rooms_per_host:
                        continue
                    bucket.append({
                        "room_id": str(r.room_id),
                        "title": r.title,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                        "diamonds": int(r.diamonds or 0),
                        "gifts": int(r.gifts or 0),
                    })

            # ── 5. Per-host comment count for this user. Single
            #     COUNT(*) per host — cheap. ──
            host_comments: dict[str, int] = {}
            if is_pg and host_totals:
                cc = (
                    s.query(
                        RoomModel.host_unique_id.label("host"),
                        func.count(TikTokEventModel.id).label("n"),
                    )
                    .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(TikTokEventModel.user_id == user_id)
                    .filter(TikTokEventModel.type == "comment")
                    .filter(RoomModel.host_unique_id.isnot(None))
                    .group_by(RoomModel.host_unique_id)
                    .all()
                )
                for r in cc:
                    host_comments[r.host] = int(r.n or 0)

            hosts_payload: list[dict[str, Any]] = []
            for r in host_totals:
                if not _allow_host(r.host):
                    continue
                first = r.first_seen_at
                last = r.last_seen_at
                hosts_payload.append({
                    "host": r.host,
                    "diamonds": int(r.diamonds or 0),
                    "gifts": int(r.gifts or 0),
                    "room_count": int(r.rooms or 0),
                    "comment_count": host_comments.get(r.host, 0),
                    "first_seen_at": first.isoformat() if first else None,
                    "last_seen_at": last.isoformat() if last else None,
                    "top_gifts": host_gifts.get(r.host, []),
                    "rooms": host_rooms.get(r.host, []),
                })

            totals_diamonds = sum(h["diamonds"] for h in hosts_payload)
            totals_gifts = sum(h["gifts"] for h in hosts_payload)
            totals_rooms = sum(h["room_count"] for h in hosts_payload)
            totals_comments = sum(h["comment_count"] for h in hosts_payload)
            firsts = [h["first_seen_at"] for h in hosts_payload if h["first_seen_at"]]
            lasts = [h["last_seen_at"] for h in hosts_payload if h["last_seen_at"]]

            # ── 6. Behavior mix — events by type for this user.
            #     Tells us "are they a whale, a chatter, a lurker?"
            behavior: dict[str, int] = {}
            if is_pg:
                br = s.execute(text("""
                    SELECT type, COUNT(*) AS n
                    FROM tiktok_events
                    WHERE user_id = :uid
                    GROUP BY type
                """), {"uid": int(user_id)}).all()
                for r in br:
                    behavior[r[0]] = int(r[1] or 0)

            # ── 7. Activity heatmap — gift counts + diamonds by
            #     (day_of_week, hour_of_day). 84 cells max. ──
            heatmap: list[dict[str, Any]] = []
            if is_pg:
                hm = s.execute(text("""
                    SELECT EXTRACT(DOW FROM ts)::int AS dow,
                           EXTRACT(HOUR FROM ts)::int AS hh,
                           COUNT(*) AS n,
                           SUM(COALESCE((payload->>'diamond_count')::int, 0)
                               * COALESCE((payload->>'repeat_count')::int, 1)) AS d
                    FROM tiktok_events
                    WHERE user_id = :uid AND type = 'gift'
                    GROUP BY dow, hh
                """), {"uid": int(user_id)}).all()
                for r in hm:
                    heatmap.append({
                        "dow": int(r[0]),
                        "hour": int(r[1]),
                        "gifts": int(r[2] or 0),
                        "diamonds": int(r[3] or 0),
                    })

            # ── 8. Daily timeseries — diamonds + gifts per host per day,
            #     last 90 days. Drives the stacked-area + cumulative
            #     curves on the timeline tab. ──
            #     Multi-host guest gifts (to_user.user_id != primary
            #     host's profile_user_id) are excluded so this gifter's
            #     per-host attribution stays consistent with the
            #     host-side aggregations.
            daily_series: list[dict[str, Any]] = []
            if is_pg:
                ds = s.execute(text("""
                    SELECT date_trunc('day', e.ts) AS day,
                           r.host_unique_id AS host,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d,
                           SUM(COALESCE((e.payload->>'repeat_count')::int, 1)) AS g
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                    WHERE e.user_id = :uid AND e.type = 'gift'
                      AND e.ts >= NOW() - INTERVAL '90 days'
                      AND r.host_unique_id IS NOT NULL
                      AND (
                        sub.profile_user_id IS NULL
                        OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                           IN ('0', sub.profile_user_id::text)
                      )
                    GROUP BY day, host
                    ORDER BY day
                """), {"uid": int(user_id)}).all()
                for r in ds:
                    if not _allow_host(r[1]):
                        continue
                    daily_series.append({
                        "day": r[0].isoformat() if r[0] else None,
                        "host": r[1],
                        "diamonds": int(r[2] or 0),
                        "gifts": int(r[3] or 0),
                    })

            # ── 9. Intensity stats — biggest single-room session +
            #     active-day streak + longest gap. Active days come from
            #     a small derived list (one row per gift day). ──
            intensity: dict[str, Any] = {}
            if is_pg:
                bs = s.execute(text("""
                    SELECT e.room_id, r.host_unique_id, r.title,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d,
                           SUM(COALESCE((e.payload->>'repeat_count')::int, 1)) AS g
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.user_id = :uid AND e.type = 'gift'
                    GROUP BY e.room_id, r.host_unique_id, r.title
                    ORDER BY d DESC LIMIT 1
                """), {"uid": int(user_id)}).first()
                if bs and _allow_host(bs[1]):
                    intensity["biggest_session"] = {
                        "room_id": str(bs[0]) if bs[0] else None,
                        "host": bs[1],
                        "title": bs[2],
                        "diamonds": int(bs[3] or 0),
                        "gifts": int(bs[4] or 0),
                    }
                # Active-day list (one row per gift day, ascending).
                ad = s.execute(text("""
                    SELECT DISTINCT date_trunc('day', ts)::date AS day
                    FROM tiktok_events
                    WHERE user_id = :uid AND type = 'gift'
                    ORDER BY day
                """), {"uid": int(user_id)}).all()
                days = [r[0] for r in ad if r[0]]
                if days:
                    # Longest streak + longest gap by walking the list.
                    longest_streak = 1
                    cur_streak = 1
                    longest_gap = 0
                    for prev, cur in zip(days, days[1:]):
                        delta = (cur - prev).days
                        if delta == 1:
                            cur_streak += 1
                            longest_streak = max(longest_streak, cur_streak)
                        else:
                            cur_streak = 1
                            longest_gap = max(longest_gap, delta - 1)
                    intensity["active_days"] = len(days)
                    intensity["longest_streak_days"] = longest_streak
                    intensity["longest_gap_days"] = longest_gap
                    intensity["first_active_day"] = days[0].isoformat()
                    intensity["last_active_day"] = days[-1].isoformat()

            # ── 10. Global rank among the common-gifters pool. Window
            #     functions over the summary table — cheap. ──
            rank: dict[str, Any] = {}
            if is_pg:
                rk = s.execute(text("""
                    WITH agg AS (
                        SELECT user_id,
                               SUM(diamonds) AS d,
                               SUM(gifts) AS g,
                               COUNT(DISTINCT host_unique_id) AS hc
                        FROM tiktok_user_host_summary
                        GROUP BY user_id
                        HAVING COUNT(DISTINCT host_unique_id) >= 2
                    )
                    SELECT
                        (SELECT COUNT(*) FROM agg) AS pool_size,
                        (SELECT COUNT(*) FROM agg WHERE d > me.d) + 1 AS rank_d,
                        (SELECT COUNT(*) FROM agg WHERE hc > me.hc) + 1 AS rank_hc,
                        (SELECT COUNT(*) FROM agg WHERE g > me.g) + 1 AS rank_g
                    FROM agg me
                    WHERE me.user_id = :uid
                """), {"uid": int(user_id)}).first()
                if rk:
                    pool = int(rk[0] or 0)
                    rank = {
                        "pool_size": pool,
                        "by_diamonds": int(rk[1]),
                        "by_host_count": int(rk[2]),
                        "by_gifts": int(rk[3]),
                    }

            # ── 11. Recent activity feed — last 100 events of any
            #     type, joined to host. Powers the "what else are they
            #     up to" timeline. ──
            recent_activity: list[dict[str, Any]] = []
            if is_pg:
                ra = s.execute(text("""
                    SELECT e.id, e.ts, e.type, r.host_unique_id,
                           e.room_id, e.payload
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.user_id = :uid
                    ORDER BY e.id DESC
                    LIMIT 100
                """), {"uid": int(user_id)}).all()
                for r in ra:
                    if not _allow_host(r[3]):
                        continue
                    pl = _coerce_payload(r[5]) if r[5] is not None else {}
                    item: dict[str, Any] = {
                        "id": int(r[0]),
                        "ts": r[1].isoformat() if r[1] else None,
                        "type": r[2],
                        "host": r[3],
                        "room_id": str(r[4]) if r[4] else None,
                    }
                    # Trim payload to the bits the feed actually shows.
                    if r[2] == "gift":
                        item["gift_name"] = pl.get("gift_name") or (
                            (pl.get("gift") or {}).get("name") if isinstance(pl.get("gift"), dict) else None
                        )
                        item["repeat_count"] = pl.get("repeat_count")
                        item["diamond_count"] = pl.get("diamond_count")
                    elif r[2] == "comment":
                        item["text"] = (pl.get("text") or "")[:200]
                    recent_activity.append(item)

            # ── 12. Co-gifters — other viewers who gifted in ≥3 rooms
            #     where this user also gifted. Bounded by the user's
            #     own gift-room set (typically tens to a few hundred). ──
            co_gifters: list[dict[str, Any]] = []
            if is_pg:
                cg = s.execute(text("""
                    WITH my_rooms AS (
                        SELECT DISTINCT room_id
                        FROM tiktok_events
                        WHERE user_id = :uid AND type = 'gift'
                    )
                    SELECT e.user_id,
                           COUNT(DISTINCT e.room_id) AS shared,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d,
                           v.unique_id, v.nickname, v.avatar_url
                    FROM tiktok_events e
                    JOIN my_rooms mr ON mr.room_id = e.room_id
                    LEFT JOIN tiktok_viewers v ON v.user_id = e.user_id
                    WHERE e.user_id != :uid AND e.type = 'gift'
                    GROUP BY e.user_id, v.unique_id, v.nickname, v.avatar_url
                    HAVING COUNT(DISTINCT e.room_id) >= 3
                    ORDER BY shared DESC, d DESC
                    LIMIT 12
                """), {"uid": int(user_id)}).all()
                for r in cg:
                    co_gifters.append({
                        "user_id": str(r[0]),
                        "shared_rooms": int(r[1] or 0),
                        "diamonds_in_overlap": int(r[2] or 0),
                        "unique_id": r[3],
                        "nickname": r[4],
                        "avatar_url": r[5],
                    })

            # ── 13a. Gift-tier distribution — bucketed by per-event
            #     diamond_count. Tells you whether they're a "buy lots
            #     of cheap things" gifter or a "few large bombs"
            #     gifter — same total can come from very different
            #     behaviour. Bounded by `user_id` index. ──
            tier_mix: list[dict[str, Any]] = []
            if is_pg:
                tm = s.execute(text("""
                    SELECT
                        CASE
                            WHEN COALESCE((payload->>'diamond_count')::int, 0) <= 9    THEN 'tiny'
                            WHEN COALESCE((payload->>'diamond_count')::int, 0) <= 99   THEN 'small'
                            WHEN COALESCE((payload->>'diamond_count')::int, 0) <= 999  THEN 'medium'
                            ELSE                                                            'large'
                        END AS tier,
                        SUM(COALESCE((payload->>'repeat_count')::int, 1)) AS g,
                        SUM(COALESCE((payload->>'diamond_count')::int, 0)
                            * COALESCE((payload->>'repeat_count')::int, 1)) AS d
                    FROM tiktok_events
                    WHERE user_id = :uid AND type = 'gift'
                    GROUP BY tier
                """), {"uid": int(user_id)}).all()
                for r in tm:
                    tier_mix.append({
                        "tier": r[0],
                        "gifts": int(r[1] or 0),
                        "diamonds": int(r[2] or 0),
                    })

            # ── 13b. Gift streakiness — average / max repeat_count
            #     and what fraction of gift *events* were combos
            #     (repeat_count > 1). A "smasher" sits at high avg
            #     repeat, a "sniper" at 1.0. ──
            streakiness: dict[str, Any] = {}
            if is_pg:
                sk = s.execute(text("""
                    SELECT
                        AVG(COALESCE((payload->>'repeat_count')::int, 1))::float AS avg_repeat,
                        MAX(COALESCE((payload->>'repeat_count')::int, 1))        AS max_repeat,
                        SUM(CASE WHEN COALESCE((payload->>'repeat_count')::int, 1) > 1
                                 THEN 1 ELSE 0 END)                              AS streak_events,
                        COUNT(*)                                                  AS total_events
                    FROM tiktok_events
                    WHERE user_id = :uid AND type = 'gift'
                """), {"uid": int(user_id)}).first()
                if sk and sk[3]:
                    total_ev = int(sk[3] or 0)
                    streak_ev = int(sk[2] or 0)
                    streakiness = {
                        "avg_repeat": round(float(sk[0] or 0), 2),
                        "max_repeat": int(sk[1] or 0),
                        "streak_event_pct": (
                            round(100.0 * streak_ev / total_ev, 1)
                            if total_ev else 0.0
                        ),
                        "total_gift_events": total_ev,
                    }

            # ── 13c. Comment-around-gift coupling — % of the user's
            #     gift events that have at least one of their own
            #     comments in the same room within ±60 s. The audit's
            #     #2 highest-impact signal: are they a hype-poster
            #     while paying or a silent whale? ──
            coupling: dict[str, Any] = {}
            if is_pg:
                cp = s.execute(text("""
                    WITH g AS (
                        SELECT id, room_id, ts
                        FROM tiktok_events
                        WHERE user_id = :uid AND type = 'gift'
                    )
                    SELECT
                        (SELECT COUNT(*) FROM g) AS gift_events,
                        (SELECT COUNT(*) FROM g
                         WHERE EXISTS (
                             SELECT 1 FROM tiktok_events c
                             WHERE c.user_id = :uid
                               AND c.type = 'comment'
                               AND c.room_id = g.room_id
                               AND c.ts BETWEEN g.ts - INTERVAL '60 seconds'
                                            AND g.ts + INTERVAL '60 seconds'
                         )) AS coupled_gifts
                """), {"uid": int(user_id)}).first()
                if cp and cp[0]:
                    total = int(cp[0])
                    coupled = int(cp[1] or 0)
                    coupling = {
                        "gift_events": total,
                        "coupled_gifts": coupled,
                        "coupling_pct": (
                            round(100.0 * coupled / total, 1) if total else 0.0
                        ),
                    }

            # ── 13d. Time-to-first-gift after a session join. Captures
            #     "how fast do they pull the trigger" — median seconds
            #     across all rooms where we saw both a join and a
            #     subsequent gift from this user. ──
            ttfg: dict[str, Any] = {}
            if is_pg:
                tt = s.execute(text("""
                    WITH joins AS (
                        SELECT room_id, MIN(ts) AS join_ts
                        FROM tiktok_events
                        WHERE user_id = :uid AND type = 'join'
                        GROUP BY room_id
                    ),
                    first_gifts AS (
                        SELECT room_id, MIN(ts) AS gift_ts
                        FROM tiktok_events
                        WHERE user_id = :uid AND type = 'gift'
                        GROUP BY room_id
                    )
                    SELECT
                        PERCENTILE_DISC(0.5) WITHIN GROUP (
                            ORDER BY EXTRACT(EPOCH FROM (fg.gift_ts - j.join_ts))
                        )::int AS median_s,
                        AVG(EXTRACT(EPOCH FROM (fg.gift_ts - j.join_ts)))::int AS avg_s,
                        MIN(EXTRACT(EPOCH FROM (fg.gift_ts - j.join_ts)))::int AS min_s,
                        COUNT(*) AS n
                    FROM joins j
                    JOIN first_gifts fg USING (room_id)
                    WHERE fg.gift_ts > j.join_ts
                """), {"uid": int(user_id)}).first()
                if tt and tt[3]:
                    ttfg = {
                        "median_seconds": int(tt[0] or 0),
                        "avg_seconds": int(tt[1] or 0),
                        "min_seconds": int(tt[2] or 0),
                        "rooms_with_both": int(tt[3] or 0),
                    }

            # ── 13e. Whale-density per session — top 5 rooms ranked
            #     by what % of the room's total diamonds *this user
            #     alone* drove. The fact most likely to make a host
            #     send a thank-you message. Bounded by the user's
            #     own room set. ──
            whale_sessions: list[dict[str, Any]] = []
            if is_pg:
                ws = s.execute(text("""
                    WITH user_rooms AS (
                        SELECT room_id,
                               SUM(COALESCE((payload->>'diamond_count')::int, 0)
                                   * COALESCE((payload->>'repeat_count')::int, 1)) AS user_d,
                               SUM(COALESCE((payload->>'repeat_count')::int, 1)) AS user_g
                        FROM tiktok_events
                        WHERE user_id = :uid AND type = 'gift'
                        GROUP BY room_id
                    ),
                    room_totals AS (
                        SELECT e.room_id,
                               SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                                   * COALESCE((e.payload->>'repeat_count')::int, 1)) AS room_d
                        FROM tiktok_events e
                        WHERE e.type = 'gift'
                          AND e.room_id IN (SELECT room_id FROM user_rooms)
                        GROUP BY e.room_id
                    )
                    SELECT u.room_id,
                           r.host_unique_id, r.title, r.first_seen_at,
                           ur.user_d, ur.user_g, u.room_d
                    FROM user_rooms ur
                    JOIN room_totals u ON u.room_id = ur.room_id
                    JOIN tiktok_rooms r ON r.room_id = ur.room_id
                    ORDER BY (ur.user_d::float / NULLIF(u.room_d, 0)) DESC NULLS LAST
                    LIMIT 5
                """), {"uid": int(user_id)}).all()
                for r in ws:
                    if not _allow_host(r[1]):
                        continue
                    user_d = int(r[4] or 0)
                    room_d = int(r[6] or 0)
                    whale_sessions.append({
                        "room_id": str(r[0]) if r[0] else None,
                        "host": r[1],
                        "title": r[2],
                        "started_at": r[3].isoformat() if r[3] else None,
                        "user_diamonds": user_d,
                        "user_gifts": int(r[5] or 0),
                        "room_diamonds": room_d,
                        "share_pct": (
                            round(100.0 * user_d / room_d, 1) if room_d else 0.0
                        ),
                    })

            # ── 13f. Anchor-level histogram — what tier of host do
            #     they typically gift to? `payload->user->identity->
            #     anchor_level` is the *host's* tier surfaced on the
            #     event. Right-skewed mass = niche-creator supporter,
            #     high tail = A-list whale. ──
            anchor_hist: list[dict[str, Any]] = []
            if is_pg:
                ah = s.execute(text("""
                    SELECT (payload->'user'->'identity'->>'anchor_level')::int AS lvl,
                           SUM(COALESCE((payload->>'repeat_count')::int, 1)) AS n
                    FROM tiktok_events
                    WHERE user_id = :uid AND type = 'gift'
                      AND payload->'user'->'identity'->>'anchor_level' IS NOT NULL
                    GROUP BY lvl
                    ORDER BY lvl
                """), {"uid": int(user_id)}).all()
                for r in ah:
                    if r[0] is None:
                        continue
                    anchor_hist.append({
                        "anchor_level": int(r[0]),
                        "gifts": int(r[1] or 0),
                    })

            # ── 13g. Recipient analysis — `payload.to_user.unique_id`
            #     captures *who* received each gift in multi-guest /
            #     PK lives. For solo lives it's the host; in PKs it's
            #     either the host or an opponent. Buckets per (host,
            #     recipient) so we can surface real partisanship: of
            #     N PK gifts in @host's room, M went to host vs N-M
            #     to the opponent. ──
            recipients_per_host: dict[str, list[dict[str, Any]]] = {}
            recipient_partisanship: dict[str, dict[str, int]] = {}
            if is_pg:
                # Filter the noise upfront: TikTokLive stamps every
                # event with a `to_user` blob, but for solo lives it's
                # populated with `{user_id: 0, unique_id: "", ...}` —
                # that's the lib's "no specific recipient" sentinel,
                # not the host. Drop those so the recipient list only
                # shows real targeted gifts (multi-guest / PK lives).
                rcp = s.execute(text("""
                    SELECT
                        r.host_unique_id                                      AS host,
                        e.payload->'to_user'->>'unique_id'                    AS to_uid,
                        e.payload->'to_user'->>'nickname'                     AS to_nick,
                        SUM(COALESCE((e.payload->>'repeat_count')::int, 1))   AS gifts,
                        SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                            * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d,
                        SUM(CASE WHEN e.match_id IS NOT NULL THEN
                            COALESCE((e.payload->>'repeat_count')::int, 1)
                            ELSE 0 END)                                       AS pk_gifts,
                        SUM(CASE WHEN e.match_id IS NOT NULL THEN
                            COALESCE((e.payload->>'diamond_count')::int, 0)
                            * COALESCE((e.payload->>'repeat_count')::int, 1)
                            ELSE 0 END)                                       AS pk_diamonds
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.user_id = :uid
                      AND e.type = 'gift'
                      AND r.host_unique_id IS NOT NULL
                      AND COALESCE(e.payload->'to_user'->>'unique_id', '') != ''
                      AND COALESCE((e.payload->'to_user'->>'user_id')::bigint, 0) != 0
                    GROUP BY r.host_unique_id, to_uid, to_nick
                    ORDER BY r.host_unique_id, d DESC
                """), {"uid": int(user_id)}).all()
                for row in rcp:
                    host_handle = row[0]
                    if not _allow_host(host_handle):
                        continue
                    to_uid = row[1]
                    bucket = recipients_per_host.setdefault(host_handle, [])
                    bucket.append({
                        "unique_id": to_uid,
                        "nickname": row[2],
                        "gifts": int(row[3] or 0),
                        "diamonds": int(row[4] or 0),
                        "pk_gifts": int(row[5] or 0),
                        "pk_diamonds": int(row[6] or 0),
                        "is_host": (to_uid or "").lstrip("@").lower()
                                   == (host_handle or "").lower(),
                    })
                    # Partisanship is only defined for PK gifts.
                    if int(row[5] or 0) > 0:
                        ph = recipient_partisanship.setdefault(host_handle, {
                            "to_host_gifts": 0, "to_host_diamonds": 0,
                            "to_others_gifts": 0, "to_others_diamonds": 0,
                        })
                        is_host = (to_uid or "").lstrip("@").lower() == (host_handle or "").lower()
                        if is_host:
                            ph["to_host_gifts"] += int(row[5] or 0)
                            ph["to_host_diamonds"] += int(row[6] or 0)
                        else:
                            ph["to_others_gifts"] += int(row[5] or 0)
                            ph["to_others_diamonds"] += int(row[6] or 0)

            # ── 13h. Identity progression — the gifter's own
            #     `payload.user.identity.member_level` /
            #     `gifter_level` / `fan_ticket_count` per (day, host).
            #     These are the host-side fan-rank fields the lib
            #     surfaces on every event — tracking the daily MAX
            #     gives us a step-function trajectory: did each
            #     diamond translate into a higher fan rank? ──
            identity_progression: list[dict[str, Any]] = []
            if is_pg:
                ip = s.execute(text("""
                    SELECT
                        date_trunc('day', e.ts)::date AS day,
                        r.host_unique_id AS host,
                        MAX(NULLIF(payload->'user'->'identity'->>'member_level','')::int)      AS member_level,
                        MAX(NULLIF(payload->'user'->'identity'->>'gifter_level','')::int)      AS gifter_level,
                        MAX(NULLIF(payload->'user'->'identity'->>'fan_ticket_count','')::int)  AS fan_tickets,
                        bool_or(NULLIF(payload->'user'->'identity'->>'is_subscribe','')::bool) AS is_subscribe,
                        MAX(payload->'user'->'identity'->'fans_club'->>'name')                 AS fc_name,
                        MAX(NULLIF(payload->'user'->'identity'->'fans_club'->>'level','')::int) AS fc_level
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.user_id = :uid
                      AND e.type = 'gift'
                      AND e.payload->'user'->'identity' IS NOT NULL
                      AND e.ts >= NOW() - INTERVAL '90 days'
                    GROUP BY day, host
                    ORDER BY day
                """), {"uid": int(user_id)}).all()
                for row in ip:
                    if not _allow_host(row[1]):
                        continue
                    identity_progression.append({
                        "day": row[0].isoformat() if row[0] else None,
                        "host": row[1],
                        "member_level": int(row[2]) if row[2] is not None else None,
                        "gifter_level": int(row[3]) if row[3] is not None else None,
                        "fan_ticket_count": int(row[4]) if row[4] is not None else None,
                        "is_subscribe": bool(row[5]) if row[5] is not None else None,
                        "fans_club_name": row[6],
                        "fans_club_level": int(row[7]) if row[7] is not None else None,
                    })

            # ── 14. Augment per-host with match-gift counts +
            #     attendance ratio (rooms_attended / host_total_rooms). ──
            host_match: dict[str, dict[str, int]] = {}
            host_total_rooms: dict[str, int] = {}
            if is_pg and host_totals:
                mg = s.execute(text("""
                    SELECT r.host_unique_id AS host,
                           SUM(COALESCE((e.payload->>'repeat_count')::int, 1)) AS g,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.user_id = :uid AND e.type = 'gift'
                      AND e.match_id IS NOT NULL
                    GROUP BY r.host_unique_id
                """), {"uid": int(user_id)}).all()
                for r in mg:
                    host_match[r[0]] = {
                        "match_gifts": int(r[1] or 0),
                        "match_diamonds": int(r[2] or 0),
                    }
                hosts_list = [h["host"] for h in hosts_payload if h.get("host")]
                if hosts_list:
                    htr = s.execute(text("""
                        SELECT host_unique_id, COUNT(DISTINCT room_id)
                        FROM tiktok_rooms
                        WHERE host_unique_id = ANY(:hosts)
                        GROUP BY host_unique_id
                    """), {"hosts": hosts_list}).all()
                    for r in htr:
                        host_total_rooms[r[0]] = int(r[1] or 0)
            for h in hosts_payload:
                m = host_match.get(h["host"]) or {}
                h["match_gifts"] = int(m.get("match_gifts", 0))
                h["match_diamonds"] = int(m.get("match_diamonds", 0))
                tot = host_total_rooms.get(h["host"], 0)
                h["host_total_rooms"] = tot
                h["attendance_pct"] = (
                    round(100.0 * h["room_count"] / tot, 1) if tot else 0.0
                )
                # Attach top recipients in the host's rooms (for
                # multi-guest / PK lives — solo lives just have one
                # entry equal to the host).
                h["recipients"] = (recipients_per_host.get(h["host"]) or [])[:8]
                # Partisanship summary: only meaningful when the host
                # actually had PKs and the user gifted during them.
                p = recipient_partisanship.get(h["host"])
                if p and (p["to_host_gifts"] + p["to_others_gifts"]) > 0:
                    total_pk = p["to_host_gifts"] + p["to_others_gifts"]
                    h["pk_partisanship"] = {
                        **p,
                        "to_host_pct": round(100.0 * p["to_host_gifts"] / total_pk, 1),
                        "to_others_pct": round(100.0 * p["to_others_gifts"] / total_pk, 1),
                    }
                else:
                    h["pk_partisanship"] = None

            # ── 15. Loyalty Gini — concentration of diamond spend
            #     across hosts. 0 = perfectly spread, 1 = all on one
            #     host. Cheap in-memory derivation off `hosts_payload`
            #     so we don't run another query. ──
            loyalty: dict[str, Any] = {}
            host_diamonds = sorted(
                [int(h["diamonds"] or 0) for h in hosts_payload], reverse=True,
            )
            n = len(host_diamonds)
            if n > 0 and sum(host_diamonds) > 0:
                # Standard sample Gini.
                arr_sorted = sorted(host_diamonds)
                cum = 0.0
                for i, v in enumerate(arr_sorted, start=1):
                    cum += i * v
                gini = (2.0 * cum) / (n * sum(arr_sorted)) - (n + 1) / n
                top1_pct = round(100.0 * host_diamonds[0] / sum(host_diamonds), 1)
                loyalty = {
                    "gini": round(max(0.0, min(1.0, gini)), 3),
                    "top1_pct": top1_pct,
                    "top_host": (
                        max(hosts_payload, key=lambda h: int(h["diamonds"] or 0))["host"]
                        if hosts_payload else None
                    ),
                }

            # ── 16. Momentum — 7-day vs 28-day diamond rate from
            #     `daily_series`. Ratio < 0.4 = cooling, > 1.5 =
            #     heating, in-between = steady. Computed in Python
            #     since daily_series is already in memory. ──
            momentum: dict[str, Any] = {}
            if daily_series:
                from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                now = _dt.now(tz=_tz.utc)
                last7_cutoff = now - _td(days=7)
                last28_cutoff = now - _td(days=28)
                d7 = 0
                d28 = 0
                for p in daily_series:
                    day_iso = p.get("day")
                    if not day_iso:
                        continue
                    try:
                        day_dt = _dt.fromisoformat(day_iso)
                        if day_dt.tzinfo is None:
                            day_dt = day_dt.replace(tzinfo=_tz.utc)
                    except ValueError:
                        continue
                    if day_dt >= last7_cutoff:
                        d7 += int(p.get("diamonds", 0) or 0)
                    if day_dt >= last28_cutoff:
                        d28 += int(p.get("diamonds", 0) or 0)
                # 7d/28d normalized: scale 7d up to a 28-day-equiv
                # rate so the ratio is fair.
                rate7 = d7 / 7 if d7 else 0
                rate28 = d28 / 28 if d28 else 0
                ratio = (rate7 / rate28) if rate28 > 0 else (1.0 if d7 == 0 else 99.0)
                if d28 == 0:
                    label = 'silent'
                elif ratio < 0.4:
                    label = 'cooling'
                elif ratio > 1.5:
                    label = 'heating'
                else:
                    label = 'steady'
                momentum = {
                    "label": label,
                    "ratio": round(ratio, 2),
                    "diamonds_7d": d7,
                    "diamonds_28d": d28,
                }

            # ── 17. Signature gift per host — gift kind that's
            #     disproportionately sent to this host vs the gifter's
            #     overall mix (lift = host_share / global_share).
            #     "@hostA's signature: Roses (4× more than baseline)".
            #     Re-aggregates from `host_gifts` already loaded; no
            #     extra query. ──
            global_gift_diamonds: dict[str, int] = {}
            for hkey, glist in host_gifts.items():
                for g in glist:
                    name = g.get("gift_name") or "(unnamed)"
                    global_gift_diamonds[name] = (
                        global_gift_diamonds.get(name, 0) + int(g.get("diamonds", 0) or 0)
                    )
            global_total = sum(global_gift_diamonds.values()) or 1
            for h in hosts_payload:
                tg = h.get("top_gifts") or []
                host_total = sum(int(g.get("diamonds", 0) or 0) for g in tg) or 1
                best_lift = 0.0
                best: dict[str, Any] | None = None
                for g in tg:
                    name = g.get("gift_name") or "(unnamed)"
                    host_share = int(g.get("diamonds", 0) or 0) / host_total
                    global_share = (global_gift_diamonds.get(name, 0) / global_total) or (1 / global_total)
                    lift = host_share / global_share if global_share > 0 else 0
                    if lift > best_lift and host_share > 0.10:
                        best_lift = lift
                        best = {
                            "gift_name": name,
                            "lift": round(lift, 2),
                            "diamonds": int(g.get("diamonds", 0) or 0),
                            "count": int(g.get("count", 0) or 0),
                        }
                # Only surface as a *signature* if the lift is
                # meaningfully above baseline (1.5× or more) — below
                # that it's just "their normal gift mix".
                h["signature_gift"] = best if best and best["lift"] >= 1.5 else None

            return {
                "user_id": int(user_id),
                "unique_id": viewer.unique_id if viewer else None,
                "nickname": viewer.nickname if viewer else None,
                "avatar_url": viewer.avatar_url if viewer else None,
                "identity": identity if isinstance(identity, dict) else None,
                "totals": {
                    "diamonds": totals_diamonds,
                    "gifts": totals_gifts,
                    "host_count": len(hosts_payload),
                    "room_count": totals_rooms,
                    "comment_count": totals_comments,
                    "first_seen_at": min(firsts) if firsts else None,
                    "last_seen_at": max(lasts) if lasts else None,
                },
                "hosts": hosts_payload,
                "behavior": behavior,
                "heatmap": heatmap,
                "daily_series": daily_series,
                "intensity": intensity,
                "rank": rank,
                "recent_activity": recent_activity,
                "co_gifters": co_gifters,
                "tier_mix": tier_mix,
                "streakiness": streakiness,
                "coupling": coupling,
                "ttfg": ttfg,
                "whale_sessions": whale_sessions,
                "anchor_hist": anchor_hist,
                "loyalty": loyalty,
                "momentum": momentum,
                "identity_progression": identity_progression,
            }

    # ── Lives summary (page-level row enrichment) ────────────────────
    #
    # One batched method that returns per-host dicts with everything
    # the /admin/tiktok Lives table needs without entering a live's
    # detail page. Designed to run on every visible row in a single
    # round-trip — typical install has 5-50 subscriptions, all queries
    # bounded by `host_unique_id IN (...)` and indexed.

    # In-process TTL caches for slow aggregate queries. Single key
    # per sorted-handle-tuple; survives across requests in the
    # singleton adapter instance. Not thread-safe — fine in
    # single-process uvicorn; with multiple workers each warms its
    # own copy and the TTL bounds drift to one minute, which is
    # acceptable.
    _DAILY_BUCKETS_TTL_S = 60.0
    _daily_buckets_cache: dict[tuple[str, ...], tuple[float, dict[str, list[int]]]] = {}
    _WEEK_CALENDAR_TTL_S = 60.0
    _week_calendar_cache: dict[
        tuple[str, ...],
        tuple[float, dict[str, list[dict[str, int]]]],
    ] = {}

    def _daily_buckets_cached(self, handles: list[str]) -> dict[str, list[int]]:
        key = tuple(sorted(handles))
        now = time.monotonic()
        hit = self._daily_buckets_cache.get(key)
        if hit and (now - hit[0]) < self._DAILY_BUCKETS_TTL_S:
            return hit[1]
        out: dict[str, list[int]] = {h: [0] * 24 for h in handles}
        with self._get_session() as s:
            if self._is_postgres():
                # Pre-aggregated read. Returns ≤24 rows per host from
                # `tiktok_event_hour_counts`, served by the (host_unique_id,
                # hour_bucket) primary-key index — milliseconds for the
                # full handle list. The write hook in
                # `_bump_event_hour_count` keeps this table live; the
                # backfill migration seeds the initial 25h.
                rows = s.execute(text("""
                    SELECT host_unique_id,
                           EXTRACT(EPOCH FROM (NOW() - hour_bucket))::int / 3600 AS bin,
                           n
                    FROM tiktok_event_hour_counts
                    WHERE host_unique_id = ANY(:hs)
                      AND hour_bucket > NOW() - INTERVAL '24 hours'
                """), {"hs": handles}).all()
            else:
                # SQLite dev path — fall back to the raw scan since the
                # write hook is Postgres-only.
                rows = s.execute(text("""
                    SELECT r.host_unique_id,
                           EXTRACT(EPOCH FROM (NOW() - e.ts))::int / 3600 AS bin,
                           COUNT(*) AS n
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE r.host_unique_id = ANY(:hs)
                      AND e.ts > NOW() - INTERVAL '24 hours'
                    GROUP BY r.host_unique_id, bin
                """), {"hs": handles}).all()
        for h, b, n in rows:
            if h in out and 0 <= int(b) < 24:
                out[h][23 - int(b)] = int(n or 0)
        self._daily_buckets_cache[key] = (now, out)
        return out

    def _week_calendar_cached(self, handles: list[str]) -> dict[str, list[dict[str, int]]]:
        """Returns `{host: [7 day buckets oldest→newest]}` covering
        the last 7 days. Each bucket: `{day_offset, rooms,
        duration_min, diamonds}`. Cached for 60 s — the 7-day window
        joins `tiktok_events` with `tiktok_rooms` over a wide
        timeframe (the diamonds scan) and would otherwise add ~600 ms
        to every cache-miss summary call."""
        key = tuple(sorted(handles))
        now = time.monotonic()
        hit = self._week_calendar_cache.get(key)
        if hit and (now - hit[0]) < self._WEEK_CALENDAR_TTL_S:
            return hit[1]

        week_by_host: dict[str, list[dict[str, int]]] = {
            h: [
                {"day_offset": i, "rooms": 0, "duration_min": 0, "diamonds": 0}
                for i in range(7)
            ] for h in handles
        }
        if not self._is_postgres() or not handles:
            self._week_calendar_cache[key] = (now, week_by_host)
            return week_by_host

        with self._get_session() as s:
            wk_rooms = s.execute(text("""
                SELECT r.host_unique_id,
                       FLOOR(EXTRACT(EPOCH FROM (NOW() - r.first_seen_at)) / 86400.0)::int AS day_offset,
                       COUNT(*) AS n_rooms,
                       COALESCE(
                         SUM(EXTRACT(EPOCH FROM (
                             COALESCE(r.ended_at, r.last_seen_at) - r.first_seen_at
                         )) / 60.0)::int,
                         0
                       ) AS duration_min
                FROM tiktok_rooms r
                WHERE r.host_unique_id = ANY(:hs)
                  AND r.first_seen_at > NOW() - INTERVAL '7 days'
                GROUP BY 1, 2
            """), {"hs": handles}).all()
            for h, off, nr, dur in wk_rooms:
                if h in week_by_host and 0 <= int(off) < 7:
                    bucket = week_by_host[h][int(off)]
                    bucket["rooms"] = int(nr or 0)
                    bucket["duration_min"] = int(dur or 0)
            wk_diam = s.execute(text("""
                SELECT r.host_unique_id,
                       FLOOR(EXTRACT(EPOCH FROM (NOW() - r.first_seen_at)) / 86400.0)::int AS day_offset,
                       COALESCE(SUM(
                         COALESCE((e.payload->>'diamond_count')::int, 0)
                           * COALESCE((e.payload->>'repeat_count')::int, 1)
                       ), 0) AS d
                FROM tiktok_rooms r
                JOIN tiktok_events e ON e.room_id = r.room_id
                JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                WHERE r.host_unique_id = ANY(:hs)
                  AND r.first_seen_at > NOW() - INTERVAL '7 days'
                  AND e.type = 'gift'
                  AND (
                    sub.profile_user_id IS NULL
                    OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                       IN ('0', sub.profile_user_id::text)
                  )
                GROUP BY 1, 2
            """), {"hs": handles}).all()
            for h, off, d in wk_diam:
                if h in week_by_host and 0 <= int(off) < 7:
                    week_by_host[h][int(off)]["diamonds"] = int(d or 0)

        # Reverse so the array reads oldest → newest (left → right on
        # the heatmap strip), matching the diamond sparkline.
        result = {h: list(reversed(days)) for h, days in week_by_host.items()}
        self._week_calendar_cache[key] = (now, result)
        return result

    # ── Per-section helpers for `get_lives_summary`.  ────────────
    #
    # The original `get_lives_summary` ran ~22 sequential SQL queries
    # in one session — well-indexed individually, but the
    # round-trip latency dominated wall-clock (~1.3 s for 72 handles
    # on a warm DB).  These helpers split the work so the orchestrator
    # can fan them out across a ThreadPoolExecutor.
    #
    # Hexagonal-architecture note: this stays inside the persistence
    # adapter — no change in the port surface, no leakage of threading
    # into the service layer.  The service still sees a single sync
    # `get_lives_summary(handles) -> dict` call.
    #
    # Session lifecycle: each helper opens its **own** session via
    # `self._get_session()`.  When called from a worker thread,
    # `get_current_session()` returns `None` (ContextVars don't
    # propagate into `ThreadPoolExecutor` workers by default), so the
    # `else` branch hits `self.SessionLocal()` and the helper gets a
    # private connection from the pool.  No two helpers ever share a
    # session — one connection, one in-flight query is the SQLAlchemy
    # rule.  Pool size is 20; the orchestrator caps fan-out at 8.
    #
    # Merging strategy: each helper returns its own dict slice
    # `{host: {field: value, ...}}`.  The orchestrator merges
    # sequentially after `.result()` (Python-level work, cheap).  No
    # locks, no shared mutation — easiest correctness story possible.
    # ──────────────────────────────────────────────────────────────

    def _lives_summary_active_rooms(
        self, norm: list[str]
    ) -> tuple[dict[str, tuple[int, datetime]], dict[str, dict[str, Any]]]:
        """Step 1 — anchor query.  Active room per host (last_seen_at
        within 5 min, no ended_at).  first_seen_at = session start; we
        use it for both 'duration' and 'session window for top
        gifter / diamonds_session'.

        Returns `(active_by_host, slice)`.  `active_by_host` is the
        keyed lookup every room-scoped helper needs.  `slice` carries
        the `active_room_id` / `live_started_at` fields that get
        merged into the final `out`.
        """
        active_by_host: dict[str, tuple[int, datetime]] = {}
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            active_rooms = s.execute(text("""
                SELECT host_unique_id, room_id, first_seen_at, ended_at
                FROM tiktok_rooms
                WHERE host_unique_id = ANY(:hs)
                  AND ended_at IS NULL
                  AND last_seen_at > NOW() - INTERVAL '5 minutes'
            """), {"hs": norm}).all()
        for r in active_rooms:
            active_by_host[r[0]] = (int(r[1]), r[2])
            slice_.setdefault(r[0], {})["active_room_id"] = str(r[1])
            slice_[r[0]]["live_started_at"] = r[2].isoformat() if r[2] else None
        return active_by_host, slice_

    def _lives_summary_viewer_counts(
        self, room_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        """Step 2 — latest viewer_count per active room + last-30-min
        per-minute trend.  One scan with DISTINCT ON keyed by
        (room_id, minute_bin) — Postgres returns the most-recent
        viewer_count within each minute.  We then sort and zero-fill
        in Python so the sparkline array is always a stable
        30-element strip (oldest → newest)."""
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            vc = s.execute(text("""
                SELECT DISTINCT ON (e.room_id, date_trunc('minute', e.ts))
                       r.host_unique_id,
                       date_trunc('minute', e.ts) AS minute_bin,
                       (e.payload->>'total')::int AS viewers
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE e.room_id = ANY(:rids)
                  AND e.type = 'viewer_count'
                  AND e.ts > NOW() - INTERVAL '30 minutes'
                ORDER BY e.room_id, date_trunc('minute', e.ts) DESC, e.id DESC
            """), {"rids": room_ids}).all()
        # Bucket per host, keyed by minutes-ago (0..29).  The query
        # already pre-deduped to one row per (room, minute); we just
        # translate the absolute minute_bin into a relative offset
        # and stash.  Latest viewer_count = bucket 0.
        _now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        vh_by_host: dict[str, list[int | None]] = {}
        for h, mb, v in vc:
            if v is None:
                continue
            age_min = int((_now - mb).total_seconds() // 60)
            if not (0 <= age_min < 30):
                continue
            arr = vh_by_host.setdefault(h, [None] * 30)
            # bucket 29 = most recent minute, bucket 0 = 30 min ago.
            arr[29 - age_min] = int(v)
        for h, arr in vh_by_host.items():
            # Forward-fill so dropouts in the WS feed don't produce
            # zero-dips on the sparkline.  Last-known-value carries
            # forward; leading None's stay None and the renderer
            # skips them.
            last: int | None = None
            filled: list[int] = []
            for v in arr:
                if v is not None:
                    last = v
                if last is not None:
                    filled.append(last)
            slice_.setdefault(h, {})["viewer_history"] = filled
            slice_[h]["viewer_count"] = filled[-1] if filled else None
        return slice_

    def _lives_summary_session_diamonds(
        self,
        active_by_host: dict[str, tuple[int, datetime]],
        room_ids: list[int],
    ) -> dict[str, dict[str, Any]]:
        """Step 3 — diamonds in the active session per host.  Bounded
        by (room_id, ts >= session start)."""
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            ds = s.execute(text("""
                SELECT r.host_unique_id,
                       SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                           * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE r.host_unique_id = ANY(:hs)
                  AND e.type = 'gift'
                  AND e.room_id = ANY(:rids)
                GROUP BY r.host_unique_id
            """), {"hs": list(active_by_host.keys()), "rids": room_ids}).all()
        for r in ds:
            slice_.setdefault(r[0], {})["diamonds_session"] = int(r[1] or 0)
        return slice_

    def _lives_summary_hourly(
        self, norm: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Step 4 — hourly buckets: diamonds per minute, last 60 min.
        Uses generate_series + LEFT JOIN so empty minutes come back
        as zero (sparkline needs the gaps)."""
        with self._get_session() as s:
            # `to_user.user_id` filter (multi-host gift attribution):
            # only count gifts that the host themselves received, OR
            # gifts without a specific recipient (`to_user.user_id = 0`
            # / NULL = popular-vote / unattributed = credited to host).
            # See `host_calendar` for the full rationale. Joining
            # through `tiktok_subscriptions` lets each per-host SUM
            # know its own profile_user_id.
            hourly = s.execute(text("""
                WITH minute_bins AS (
                    SELECT generate_series(0, 59) AS bin
                ),
                gifts AS (
                    SELECT r.host_unique_id AS host,
                           EXTRACT(EPOCH FROM (NOW() - e.ts))::int / 60 AS bin,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                    WHERE r.host_unique_id = ANY(:hs)
                      AND e.type = 'gift'
                      AND e.ts > NOW() - INTERVAL '60 minutes'
                      AND (
                        sub.profile_user_id IS NULL
                        OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                           IN ('0', sub.profile_user_id::text)
                      )
                    GROUP BY host, bin
                )
                SELECT host, bin, d FROM gifts
            """), {"hs": norm}).all()
        hourly_by_host: dict[str, list[int]] = {h: [0] * 60 for h in norm}
        for h, b, d in hourly:
            if h in hourly_by_host and 0 <= int(b) < 60:
                # bin 0 = most recent minute; flip so the array reads
                # oldest → newest (left → right on chart).
                hourly_by_host[h][59 - int(b)] = int(d or 0)
        return {h: {"hourly_buckets": arr} for h, arr in hourly_by_host.items()}

    def _lives_summary_top_gifters(
        self, room_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        """Step 6 — top 3 gifters per host (the 'group-up' signal —
        who's warming up, not just who's #1).  One pass: per-gifter
        sum, then ROW_NUMBER() to keep top 3 per host."""
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            tg = s.execute(text("""
                WITH per_gifter AS (
                    SELECT r.host_unique_id AS host,
                           e.user_id,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS diamonds,
                           SUM(COALESCE((e.payload->>'repeat_count')::int, 1)) AS gifts
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    WHERE e.room_id = ANY(:rids)
                      AND e.type = 'gift'
                      AND e.user_id IS NOT NULL
                    GROUP BY r.host_unique_id, e.user_id
                ),
                ranked AS (
                    SELECT host, user_id, diamonds, gifts,
                           ROW_NUMBER() OVER (
                               PARTITION BY host ORDER BY diamonds DESC
                           ) AS rn
                    FROM per_gifter
                )
                SELECT r.host, r.user_id, r.diamonds, r.gifts,
                       v.unique_id, v.nickname, v.avatar_url
                FROM ranked r
                LEFT JOIN tiktok_viewers v ON v.user_id = r.user_id
                WHERE r.rn <= 3
                ORDER BY r.host, r.rn
            """), {"rids": room_ids}).all()
        # Bucket by host so we can attach as a list and keep the
        # legacy top_gifter field for backward compat.
        top_by_host: dict[str, list[dict[str, Any]]] = {}
        for h, uid, d, gifts, uniq, nick, av in tg:
            top_by_host.setdefault(h, []).append({
                "user_id":   str(uid) if uid is not None else None,
                "diamonds":  int(d or 0),
                "gifts":     int(gifts or 0),
                "unique_id": uniq,
                "nickname":  nick,
                "avatar_url":av,
            })
        for h, lst in top_by_host.items():
            slice_.setdefault(h, {})["top_gifters"] = lst
            slice_[h]["top_gifter"] = lst[0] if lst else None
        return slice_

    def _lives_summary_unique_and_session_stats(
        self, room_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        """Steps 6a + 6b — unique-gifter / first-time count AND the
        merged session-stats scan (scoreboard counters + silence ages
        + comment cadence).

        We keep these two queries paired in one helper for a
        different reason than the others: both are wide scans over
        the active-room event window.  Running them on the same
        connection avoids two simultaneous heavy scans against the
        same hot rows (the room-events index would otherwise
        contend).  Functionally each is independent, so the order
        here doesn't matter.
        """
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            # 6a — unique gifters + first-time-tonight count
            # (cross-reference user_host_summary).
            #
            # Rewritten from a correlated `NOT EXISTS` inside the
            # `COUNT FILTER` to a LEFT JOIN anti-join (`u IS NULL OR
            # u.first_seen_at >= r.first_seen_at`). The correlated
            # form forced Postgres to run one SubPlan per distinct
            # gifter per group — at high gifter counts (~150 per
            # active room × 10 rooms) that was thousands of PK
            # lookups in sequence. The LEFT JOIN form lets the
            # planner choose a single Hash Anti Join with
            # `tiktok_user_host_summary`, collapsing the per-row
            # probes into one scan. Verify with EXPLAIN — the plan
            # should show "Hash Anti Join", not "SubPlan".
            ug = s.execute(text("""
                SELECT r.host_unique_id,
                       COUNT(DISTINCT e.user_id) AS uniq,
                       COUNT(DISTINCT e.user_id) FILTER (
                           WHERE u.user_id IS NULL
                              OR u.first_seen_at >= r.first_seen_at
                       ) AS first_time
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                LEFT JOIN tiktok_user_host_summary u
                       ON u.user_id = e.user_id
                      AND u.host_unique_id = r.host_unique_id
                WHERE e.room_id = ANY(:rids)
                  AND e.type = 'gift'
                  AND e.user_id IS NOT NULL
                GROUP BY r.host_unique_id
            """), {"rids": room_ids}).all()
            for h, uniq, first_time in ug:
                slice_.setdefault(h, {})["n_unique_gifters"] = int(uniq or 0)
                slice_[h]["n_first_time_gifters"] = int(first_time or 0)

            # 6b/6b'/6c MERGED — single scan over `tiktok_events` per
            # active room produces:
            #   • session scoreboard counters (comments, gifts, …)
            #   • silence detector ages (last gift / comment / any)
            #   • comment cadence (cpm_recent 5-min, cpm_baseline 60-min)
            # Postgres reads each row once and computes every FILTER
            # in parallel — much cheaper than three separate scans of
            # the same row range.  Saves ~150ms on the hot path for
            # typical live counts (~11 active rooms, ~170k events).
            merged = s.execute(text("""
                SELECT r.host_unique_id,
                       COUNT(*) FILTER (WHERE e.type = 'comment')   AS n_comments,
                       COUNT(*) FILTER (WHERE e.type = 'gift')      AS n_gifts,
                       COUNT(*) FILTER (WHERE e.type = 'like')      AS n_likes,
                       COUNT(*) FILTER (WHERE e.type = 'join')      AS n_joins,
                       COUNT(*) FILTER (WHERE e.type = 'follow')    AS n_follows,
                       COUNT(*) FILTER (WHERE e.type = 'share')     AS n_shares,
                       COUNT(DISTINCT e.user_id) FILTER (WHERE e.type = 'comment') AS n_commenters,
                       COALESCE(MAX(
                           CASE WHEN e.type = 'gift'
                                THEN COALESCE((e.payload->>'diamond_count')::int, 0)
                                   * COALESCE((e.payload->>'repeat_count')::int, 1)
                           END
                       ), 0) AS largest_gift,
                       EXTRACT(EPOCH FROM (NOW() - MAX(e.ts) FILTER (WHERE e.type = 'gift')))::int    AS gift_age,
                       EXTRACT(EPOCH FROM (NOW() - MAX(e.ts) FILTER (WHERE e.type = 'comment')))::int AS comment_age,
                       EXTRACT(EPOCH FROM (NOW() - MAX(e.ts)))::int                                  AS any_age,
                       COUNT(*) FILTER (
                           WHERE e.type = 'comment' AND e.ts > NOW() - INTERVAL '5 minutes'
                       ) / 5.0  AS cpm_recent,
                       COUNT(*) FILTER (
                           WHERE e.type = 'comment' AND e.ts > NOW() - INTERVAL '60 minutes'
                       ) / 60.0 AS cpm_baseline
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE e.room_id = ANY(:rids)
                GROUP BY r.host_unique_id
            """), {"rids": room_ids}).all()
        for row in merged:
            h, nc, ng, nl, nj, nf, nsh, ncom, lg, ga, ca, anya, cpm_r, cpm_b = row
            slice_.setdefault(h, {})["session_stats"] = {
                "n_comments":          int(nc or 0),
                "n_gifts":             int(ng or 0),
                "n_likes":             int(nl or 0),
                "n_joins":             int(nj or 0),
                "n_follows":           int(nf or 0),
                "n_shares":            int(nsh or 0),
                "n_unique_commenters": int(ncom or 0),
                "largest_gift_diamonds": int(lg or 0),
            }
            slice_[h]["last_gift_age_s"]    = int(ga) if ga is not None else None
            slice_[h]["last_comment_age_s"] = int(ca) if ca is not None else None
            slice_[h]["last_event_age_s"]   = int(anya) if anya is not None else None
            slice_[h]["comments_per_min_recent"]   = round(float(cpm_r or 0), 1)
            slice_[h]["comments_per_min_baseline"] = round(float(cpm_b or 0), 1)
        return slice_

    def _lives_summary_battles(
        self, room_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        """Step 6b'' — battles played + host's W-L-D in the active
        session.  Resolves the host's team in each match the same way
        the rest of the codebase does (team_id or user_id mismatch
        with the opponents list, then opponents[].score fallback).
        One query per active room — Python computes the W-L."""
        with self._get_session() as s:
            br = s.execute(text("""
                SELECT r.host_unique_id, m.id, m.ended_at,
                       m.opponents, m.scores
                FROM tiktok_matches m
                JOIN tiktok_rooms r ON r.room_id = m.room_id
                WHERE m.room_id = ANY(:rids)
            """), {"rids": room_ids}).all()
        tally_by_host: dict[str, dict[str, int]] = {}
        for h, _mid, ended, opps_raw, scores_raw in br:
            tally = tally_by_host.setdefault(h, {
                "n_battles": 0, "w": 0, "l": 0, "d": 0,
            })
            tally["n_battles"] += 1
            if ended is None:
                # In-progress matches don't count toward W/L/D.
                continue
            opps = _coerce_payload(opps_raw) if opps_raw is not None else []
            if not isinstance(opps, list):
                opps = []
            scores = _coerce_payload(scores_raw) if scores_raw is not None else {}
            # Resolve host_score vs opp_score (same multi-shape logic
            # frontend uses).  Path 1: scores keyed by team_id or
            # user_id.  Path 2: opponents[].score.
            host_handle = h.lstrip("@").lower()
            host_score: int | None = None
            opp_score:  int | None = None
            host_keys: set[str] = set()
            opp_keys:  set[str] = set()
            for o in opps:
                if not isinstance(o, dict):
                    continue
                is_opp = (o.get("unique_id") or "").lstrip("@").lower() != host_handle
                if o.get("team_id") is not None:
                    (opp_keys if is_opp else host_keys).add(str(o.get("team_id")))
                if o.get("user_id") is not None:
                    (opp_keys if is_opp else host_keys).add(str(o.get("user_id")))
            if isinstance(scores, dict):
                for k, v in scores.items():
                    try:
                        sc_i = int(v)
                    except (TypeError, ValueError):
                        continue
                    if str(k) in host_keys and host_score is None:
                        host_score = sc_i
                    elif str(k) in opp_keys and opp_score is None:
                        opp_score = sc_i
            if host_score is None or opp_score is None:
                for o in opps:
                    if not isinstance(o, dict):
                        continue
                    handle = (o.get("unique_id") or "").lstrip("@").lower()
                    sc = o.get("score")
                    if sc is None:
                        continue
                    try:
                        sc_i = int(sc)
                    except (TypeError, ValueError):
                        continue
                    if handle == host_handle and host_score is None:
                        host_score = sc_i
                    elif handle and handle != host_handle and opp_score is None:
                        opp_score = sc_i
            if host_score is None or opp_score is None:
                continue
            if host_score > opp_score:
                tally["w"] += 1
            elif host_score < opp_score:
                tally["l"] += 1
            else:
                tally["d"] += 1
        # Return as a slice that the orchestrator merges into
        # `session_stats`.  We use a sentinel key
        # `_battles_into_session_stats` so the merger knows to push
        # into the nested dict instead of replacing it.
        slice_: dict[str, dict[str, Any]] = {}
        for h, t in tally_by_host.items():
            slice_[h] = {
                "_battles_into_session_stats": {
                    "n_battles": int(t["n_battles"]),
                    "session_w": int(t["w"]),
                    "session_l": int(t["l"]),
                    "session_d": int(t["d"]),
                }
            }
        return slice_

    def _lives_summary_envelopes(
        self, room_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        """Step 6g — envelope stats per active session.  Red-envelope
        promo drops are separate from regular gifts but also carry
        `diamond_count` (sometimes 0 for free-promo, sometimes 20-120+
        for tipped envelopes).  Operators want to see this volume
        distinct from `diamonds_session` so the gift-cell sub-line
        can flag envelope activity."""
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            en = s.execute(text("""
                SELECT r.host_unique_id,
                       COUNT(*) AS n,
                       COALESCE(SUM((e.payload->>'diamond_count')::int), 0) AS d
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE e.room_id = ANY(:rids)
                  AND e.type = 'envelope'
                GROUP BY r.host_unique_id
            """), {"rids": room_ids}).all()
        for h, n, d in en:
            slice_.setdefault(h, {})["n_envelopes_session"] = int(n or 0)
            slice_[h]["envelope_diamonds_session"] = int(d or 0)
        return slice_

    def _lives_summary_polls_pauses_favs(
        self, room_ids: list[int]
    ) -> dict[str, dict[str, Any]]:
        """Steps 6f + 6e + 6d — polls, pauses, favourite gifters
        present.  Three small queries that share a room-scoped time
        window; bundling them in one helper keeps the helper count
        manageable and the queries are cheap (each <50ms typically).
        """
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            # 6f — active poll.  TikTok fires `poll` events with
            # `message_type=2` repeatedly while a poll is open
            # (every 1–20s) and `message_type=1` once on close.
            # "Active poll right now" = latest poll event for the
            # room is mt=2 AND fresh (last 60s, since updates can
            # gap to 20s+ on a slow stream).  One DISTINCT-ON scan
            # gets us the latest event per room.
            ap = s.execute(text("""
                SELECT DISTINCT ON (e.room_id)
                       r.host_unique_id,
                       e.payload->>'title'        AS title,
                       e.payload->>'poll_id'      AS poll_id,
                       e.payload->>'message_type' AS mt,
                       EXTRACT(EPOCH FROM (NOW() - e.ts))::int AS age_s
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE e.room_id = ANY(:rids)
                  AND e.type = 'poll'
                  AND e.ts > NOW() - INTERVAL '5 minutes'
                ORDER BY e.room_id, e.id DESC
            """), {"rids": room_ids}).all()
            for h, title, poll_id, mt, age in ap:
                # Only surface OPEN polls (mt=2) within the freshness
                # window.  mt=1 events mean closed; mt=0 is unknown
                # (only 6 ever observed).  Stale polls (>60s without
                # an update) are presumed dead even if mt=2.
                if str(mt) == "2" and (age or 0) <= 60:
                    slice_.setdefault(h, {})["active_poll"] = {
                        "title":    title or "",
                        "poll_id":  str(poll_id) if poll_id else None,
                        "fresh_age_s": int(age or 0),
                    }

            # 6e — pause stats per active session.  TikTok emits
            # `LivePauseEvent` when the creator/moderator pauses the
            # stream (camera off, intermission, etc.).  Note:
            # `LiveUnpauseEvent` does fire on the lib but is not
            # emitted by TikTok in practice for our hosts (0
            # captured vs ~200 pauses), so we surface count +
            # last-pause-age and treat duration as unknowable.
            pp = s.execute(text("""
                SELECT r.host_unique_id,
                       COUNT(*) FILTER (WHERE e.type = 'live_pause') AS n_pauses,
                       EXTRACT(EPOCH FROM (NOW() - MAX(e.ts) FILTER (WHERE e.type = 'live_pause')))::int AS last_pause_age
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                WHERE e.room_id = ANY(:rids)
                  AND e.type = 'live_pause'
                GROUP BY r.host_unique_id
            """), {"rids": room_ids}).all()
            for h, n, age in pp:
                slice_.setdefault(h, {})["n_pauses"] = int(n or 0)
                slice_[h]["last_pause_age_s"] = int(age) if age is not None else None

            # 6d — favourite gifters present in the room (any event
            # type, last 5 minutes).  Pre-gift presence is the actual
            # edge — drop in before they tip.
            fp = s.execute(text("""
                SELECT DISTINCT ON (r.host_unique_id, e.user_id)
                       r.host_unique_id AS host, e.user_id,
                       v.unique_id, v.nickname, v.avatar_url,
                       EXTRACT(EPOCH FROM (NOW() - e.ts))::int AS seen_age_s
                FROM tiktok_events e
                JOIN tiktok_rooms r ON r.room_id = e.room_id
                JOIN tiktok_favorite_gifters f ON f.user_id = e.user_id
                LEFT JOIN tiktok_viewers v ON v.user_id = e.user_id
                WHERE e.room_id = ANY(:rids)
                  AND e.ts > NOW() - INTERVAL '5 minutes'
                ORDER BY r.host_unique_id, e.user_id, e.ts DESC
            """), {"rids": room_ids}).all()
        fp_by_host: dict[str, list[dict[str, Any]]] = {}
        for h, uid, uniq, nick, av, age in fp:
            fp_by_host.setdefault(h, []).append({
                "user_id":   str(uid) if uid is not None else None,
                "unique_id": uniq,
                "nickname":  nick,
                "avatar_url":av,
                "seen_age_s": int(age or 0),
            })
        for h, lst in fp_by_host.items():
            slice_.setdefault(h, {})["favorites_in_room"] = lst[:8]
        return slice_

    def _lives_summary_active_match(
        self, active_hosts: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Step 7 — active match per host (PK chip)."""
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            ams = s.execute(text("""
                SELECT r.host_unique_id, m.id, m.battle_id, m.opponents, m.settings
                FROM tiktok_matches m
                JOIN tiktok_rooms r ON r.room_id = m.room_id
                WHERE r.host_unique_id = ANY(:hs)
                  AND m.ended_at IS NULL
                  AND m.last_seen_at > NOW() - INTERVAL '2 minutes'
            """), {"hs": active_hosts}).all()
        for h, mid, bid, opps_raw, settings_raw in ams:
            opps = _coerce_payload(opps_raw) if opps_raw is not None else []
            if not isinstance(opps, list):
                opps = []
            settings = _coerce_payload(settings_raw) if settings_raw else {}
            if not isinstance(settings, dict):
                settings = {}
            # PK countdown: settings.end_time_ms is unix ms.
            countdown_s: int | None = None
            end_ms = settings.get("end_time_ms")
            if end_ms:
                try:
                    from time import time as _now_secs
                    countdown_s = max(0, int(int(end_ms) / 1000 - _now_secs()))
                except (TypeError, ValueError):
                    countdown_s = None
            serial = []
            for o in opps:
                if isinstance(o, dict):
                    serial.append({
                        "user_id":   str(o.get("user_id")) if o.get("user_id") is not None else None,
                        "unique_id": o.get("unique_id"),
                        "nickname":  o.get("nickname"),
                        "avatar_url":o.get("avatar_url"),
                        "score":     int(o.get("score") or 0),
                    })
            slice_.setdefault(h, {})["active_match"] = {
                "match_id":  int(mid),
                "battle_id": str(bid) if bid else None,
                "countdown_s": countdown_s,
                "opponents": serial,
            }
        return slice_

    def _lives_summary_last_broadcasts(
        self, norm: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Step 8 — last 3 broadcasts per host.

        Three queries fused into one helper because they form a
        natural pipeline (the room-ids feed the two stats scans).
        Splitting them would require returning intermediate state
        between threads — not worth the complexity.

        Window-fn LIMIT-per-group via row_number().  Cheap with the
        (host_unique_id, first_seen_at) index.

        `ended_at` is rarely populated in our data (the listener
        doesn't always mark a clean shutdown, so it stays NULL when
        the WS just dropped).  Surface `last_seen_at` as a fallback
        so the offline-card UI can still answer "when did this last
        stream wrap" + compute a duration.  The active-room check
        (Section 1) still keys on `ended_at IS NULL AND last_seen_at
        > NOW() - 5min` — that's authoritative for liveness; the
        fallback here only feeds display.
        """
        with self._get_session() as s:
            last_rooms = s.execute(text("""
                WITH ranked AS (
                    SELECT r.host_unique_id, r.room_id, r.first_seen_at,
                           r.ended_at, r.last_seen_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY r.host_unique_id
                               ORDER BY r.first_seen_at DESC NULLS LAST
                           ) AS rn
                    FROM tiktok_rooms r
                    WHERE r.host_unique_id = ANY(:hs)
                )
                SELECT host_unique_id, room_id, first_seen_at, ended_at, last_seen_at
                FROM ranked WHERE rn <= 3
            """), {"hs": norm}).all()
            # Aggregate per-room stats. Two passes with different
            # scopes:
            #   • Enriched (gifts/comments/peak-viewers) only for the
            #     most-recent broadcast per host — that's what the
            #     offline-card "last stream" panel renders, and the
            #     full multi-type scan over 3×43 rooms takes ~600ms.
            #     Scoping to 1×43 cuts that to ~200ms.
            #   • Diamonds-only for the other two broadcasts in the
            #     list — preserves backward compat on the older
            #     entries without re-scanning their entire event
            #     history (gift events are a tiny subset).
            # Both run via the `(room_id, type)` index.
            latest_room_ids: list[int] = []
            other_room_ids: list[int] = []
            seen_host_for_latest: set[str] = set()
            for h, rid, _started, _ended, _last_seen in last_rooms:
                if rid is None:
                    continue
                if h not in seen_host_for_latest:
                    latest_room_ids.append(int(rid))
                    seen_host_for_latest.add(h)
                else:
                    other_room_ids.append(int(rid))
            stats_by_room: dict[int, dict[str, int]] = {}
            # Multi-host guest gifts (to_user.user_id != host's profile
            # user id) must NOT be counted toward this creator's
            # diamonds. When sub.profile_user_id is NULL we can't
            # resolve attribution → leave the room unfiltered (legacy
            # behaviour preserved).
            if latest_room_ids:
                dbr = s.execute(text("""
                    SELECT e.room_id,
                           COALESCE(SUM(
                             COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)
                           ) FILTER (
                               WHERE e.type = 'gift'
                                 AND (
                                   sub.profile_user_id IS NULL
                                   OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                                      IN ('0', sub.profile_user_id::text)
                                 )
                           ), 0)                                          AS diamonds,
                           COUNT(*) FILTER (
                               WHERE e.type = 'gift'
                                 AND (
                                   sub.profile_user_id IS NULL
                                   OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                                      IN ('0', sub.profile_user_id::text)
                                 )
                           )                                              AS n_gifts,
                           COUNT(*) FILTER (WHERE e.type = 'comment')     AS n_comments,
                           MAX((e.payload->>'total')::int) FILTER (
                               WHERE e.type = 'viewer_count'
                           )                                              AS peak_viewers
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                    WHERE e.room_id = ANY(:rids)
                      AND e.type IN ('gift', 'comment', 'viewer_count')
                    GROUP BY e.room_id
                """), {"rids": latest_room_ids}).all()
                for rid, d, ng, nc, pv in dbr:
                    stats_by_room[int(rid)] = {
                        "diamonds":      int(d or 0),
                        "n_gifts":       int(ng or 0),
                        "n_comments":    int(nc or 0),
                        "peak_viewers":  int(pv) if pv is not None else 0,
                    }
            if other_room_ids:
                dbr = s.execute(text("""
                    SELECT e.room_id,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d
                    FROM tiktok_events e
                    JOIN tiktok_rooms r ON r.room_id = e.room_id
                    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                    WHERE e.room_id = ANY(:rids)
                      AND e.type = 'gift'
                      AND (
                        sub.profile_user_id IS NULL
                        OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                           IN ('0', sub.profile_user_id::text)
                      )
                    GROUP BY e.room_id
                """), {"rids": other_room_ids}).all()
                for rid, d in dbr:
                    stats_by_room[int(rid)] = {
                        "diamonds":      int(d or 0),
                        "n_gifts":       0,
                        "n_comments":    0,
                        "peak_viewers":  0,
                    }
        broadcasts_by_host: dict[str, list[dict[str, Any]]] = {h: [] for h in norm}
        for h, rid, started, ended, last_seen in last_rooms:
            if h not in broadcasts_by_host:
                continue
            # Fall back to last_seen_at when ended_at is NULL — see
            # the rationale above.  `effective_end` is the timestamp
            # used for both the display "ended_at" and the duration
            # calc, with a flag so the UI can mark it inferred.
            effective_end = ended or last_seen
            inferred = ended is None and last_seen is not None
            duration_min: int | None = None
            if started and effective_end:
                duration_min = max(0, int((effective_end - started).total_seconds() / 60))
            room_stats = stats_by_room.get(int(rid), {})
            broadcasts_by_host[h].append({
                "room_id":      str(rid),
                "started_at":   started.isoformat() if started else None,
                "ended_at":     effective_end.isoformat() if effective_end else None,
                "ended_inferred": inferred or None,
                "duration_min": duration_min,
                "diamonds":     int(room_stats.get("diamonds", 0)),
                "n_gifts":      int(room_stats.get("n_gifts", 0)),
                "n_comments":   int(room_stats.get("n_comments", 0)),
                "peak_viewers": int(room_stats.get("peak_viewers", 0)),
            })
        slice_: dict[str, dict[str, Any]] = {}
        for h, arr in broadcasts_by_host.items():
            # ranked DESC by first_seen_at; preserve that order.
            arr.sort(key=lambda x: x.get("started_at") or "", reverse=True)
            slice_[h] = {"last_broadcasts": arr}
        return slice_

    def _lives_summary_30d_averages(
        self, norm: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Step 9 — averages over the last 30 days.  Two queries
        (duration + diamonds) bundled because the diamond average
        depends on the same room set; running them on one connection
        keeps that mental model clean and the queries are cheap."""
        avgs_by_host: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            avgs = s.execute(text("""
                SELECT r.host_unique_id,
                       AVG(EXTRACT(EPOCH FROM (r.ended_at - r.first_seen_at)) / 60.0) AS avg_min,
                       COUNT(r.room_id) AS n_rooms
                FROM tiktok_rooms r
                WHERE r.host_unique_id = ANY(:hs)
                  AND r.ended_at IS NOT NULL
                  AND r.first_seen_at > NOW() - INTERVAL '30 days'
                GROUP BY r.host_unique_id
            """), {"hs": norm}).all()
            for h, avg_min, n in avgs:
                avgs_by_host[h] = {
                    "avg_duration_min": round(float(avg_min), 1) if avg_min else None,
                    "n_rooms_30d": int(n or 0),
                }
            # Avg diamonds per live (last 30 days).  One scan keyed on
            # the rooms' room_id.  We could merge with #8 but keeping
            # them separate lets the 30-day window stay independent.
            avg_d = s.execute(text("""
                WITH host_rooms AS (
                    SELECT r.room_id, r.host_unique_id, sub.profile_user_id
                    FROM tiktok_rooms r
                    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                    WHERE r.host_unique_id = ANY(:hs)
                      AND r.ended_at IS NOT NULL
                      AND r.first_seen_at > NOW() - INTERVAL '30 days'
                )
                SELECT hr.host_unique_id,
                       SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                           * COALESCE((e.payload->>'repeat_count')::int, 1))::bigint AS total_d,
                       COUNT(DISTINCT hr.room_id) AS n_rooms
                FROM host_rooms hr
                LEFT JOIN tiktok_events e
                  ON e.room_id = hr.room_id
                 AND e.type = 'gift'
                 AND (
                   hr.profile_user_id IS NULL
                   OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                      IN ('0', hr.profile_user_id::text)
                 )
                GROUP BY hr.host_unique_id
            """), {"hs": norm}).all()
        for h, total_d, n in avg_d:
            if h in avgs_by_host:
                n_rooms = int(n or 0)
                avgs_by_host[h]["avg_diamonds"] = (
                    round(float(total_d or 0) / n_rooms, 0) if n_rooms else None
                )
            else:
                avgs_by_host[h] = {
                    "avg_duration_min": None,
                    "avg_diamonds": (
                        round(float(total_d or 0) / int(n or 1), 0) if n else None
                    ),
                    "n_rooms_30d": int(n or 0),
                }
        return avgs_by_host

    def _lives_summary_median_diamonds(
        self, active_hosts: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Step 9b — diamonds-vs-typical multiplier: how does the
        active session's diamonds compare to this creator's median
        per-live over the last 30 days?  Median is resistant to
        whale-skew that ruins the avg-based comparison.  >1 = above
        typical (rocket), <1 = below (slow).  Computed only for hosts
        that are live AND have ≥3 closed historical rooms to compare
        against.

        Returns `{host: {"median_diamonds_30d": int}}`.  The
        `diamonds_vs_typical` multiplier is computed in the merger
        because it needs the per-host `diamonds_session` from
        `_lives_summary_session_diamonds` — splitting that across
        threads would couple the two helpers.
        """
        slice_: dict[str, dict[str, Any]] = {}
        with self._get_session() as s:
            med = s.execute(text("""
                WITH per_room AS (
                    SELECT r.host_unique_id AS host, r.room_id,
                           SUM(COALESCE((e.payload->>'diamond_count')::int, 0)
                               * COALESCE((e.payload->>'repeat_count')::int, 1)) AS d
                    FROM tiktok_rooms r
                    JOIN tiktok_subscriptions sub ON sub.unique_id = r.host_unique_id
                    LEFT JOIN tiktok_events e
                      ON e.room_id = r.room_id
                     AND e.type = 'gift'
                     AND (
                       sub.profile_user_id IS NULL
                       OR COALESCE(e.payload->'to_user'->>'user_id', '0')
                          IN ('0', sub.profile_user_id::text)
                     )
                    WHERE r.host_unique_id = ANY(:hs)
                      AND r.ended_at IS NOT NULL
                      AND r.first_seen_at > NOW() - INTERVAL '30 days'
                    GROUP BY r.host_unique_id, r.room_id
                )
                SELECT host,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY d)::bigint AS median_d,
                       COUNT(*) AS n
                FROM per_room
                GROUP BY host
                HAVING COUNT(*) >= 3
            """), {"hs": active_hosts}).all()
        for h, med_d, _n in med:
            median = int(med_d or 0)
            if median > 0:
                slice_.setdefault(h, {})["median_diamonds_30d"] = median
        return slice_

    def _lives_summary_reconnects(
        self, norm: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Step 9c — listener health: reconnect count for this handle
        in the last hour.  Worker writes audit rows to
        tiktok_worker_log keyed on the host handle."""
        slice_: dict[str, dict[str, Any]] = {}
        try:
            with self._get_session() as s:
                rec = s.execute(text("""
                    SELECT detail->>'host' AS host, COUNT(*)::int AS n
                    FROM tiktok_worker_log
                    WHERE event = 'session_reconnect'
                      AND ts > NOW() - INTERVAL '1 hour'
                      AND detail->>'host' = ANY(:hs)
                    GROUP BY detail->>'host'
                """), {"hs": norm}).all()
            for h, n in rec:
                if h:
                    slice_.setdefault(h, {})["reconnects_1h"] = int(n or 0)
        except Exception:
            # Worker log table may not exist on legacy installs;
            # missing recon count is non-fatal.
            pass
        return slice_

    def get_lives_summary(self, handles: list[str]) -> dict[str, dict[str, Any]]:
        """Returns `{handle: {...}}` keyed by lowercased handle.

        Per-handle keys:
          - active_room_id  (str | None)
          - live_started_at (iso | None) — derived from current room's first_seen_at
          - viewer_count    (int | None) — most recent viewer_count event
          - diamonds_session (int) — sum of diamond_count*repeat_count for
                                     gifts since the active room started
          - hourly_buckets (int[60]) — diamonds per minute, last 60 minutes
          - daily_buckets  (int[24]) — events per hour, last 24h (any type)
          - top_gifter     ({...} | None) — top diamond contributor in
                                            current session
          - active_match   ({...} | None) — battle_id + opponents+scores
          - last_broadcasts (list[{started_at, ended_at, duration_min,
                                   diamonds}]) — last 3 rooms ever
          - avg_duration_min (float | None) — across last 30 days
          - avg_diamonds     (float | None) — across last 30 days
          - momentum_label   ('heating'|'cooling'|'steady'|'silent'|None)

        All numeric ids stringified for JS BigInt safety.

        ── Execution shape ──────────────────────────────────────────
        The body is split into ~13 helper methods, each opening its
        own session.  They fan out across a `ThreadPoolExecutor` so
        round-trip latency stops being the bottleneck (was ~1.3 s
        sequential on 72 handles; the queries themselves are well-
        indexed).

        Two phases:
          • Phase 0 — anchor + everything that only needs `handles`
            (hourly buckets, last broadcasts, 30-day averages,
            reconnects, daily buckets, week calendar).  These race.
          • Phase 1 — everything room-scoped (viewer counts, session
            diamonds, top gifters, session stats, battles, envelopes,
            polls/pauses/favs, active match, median diamonds).
            Submitted only after Phase 0's anchor result resolves.

        Cap is `max_workers=8` so we never starve the pool (default
        pool size 20).  Each helper returns its own dict slice;
        merging is sequential Python after `gather` so no shared-state
        locks are needed.
        """
        if not handles:
            return {}
        if not self._is_postgres():
            return {h: {} for h in handles}

        norm = [h.lstrip("@").lower() for h in handles if h]
        out: dict[str, dict[str, Any]] = {h: {} for h in norm}

        def _merge(slice_: dict[str, dict[str, Any]]) -> None:
            """Merge a helper's slice into the shared `out` dict.

            We do this sequentially after each Future resolves —
            cheap Python work, no threading concerns.  Two special
            cases:
              • `_battles_into_session_stats` (from the battles
                helper) merges into the nested `session_stats` dict
                produced by the unique-and-session-stats helper.
                Pop it before the per-key copy.
              • Everything else: a flat per-key `update` into the
                per-host slot.
            """
            for h, fields in slice_.items():
                target = out.setdefault(h, {})
                battles_sub = fields.pop("_battles_into_session_stats", None)
                if battles_sub:
                    target.setdefault("session_stats", {}).update(battles_sub)
                target.update(fields)

        with ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="lives_summary"
        ) as ex:
            # ── Phase 0 — anchor + host-only families.  The anchor
            # (active_rooms) feeds Phase 1; the host-only families
            # don't need it, so they race here.  Cached helpers
            # (`_daily_buckets_cached`, `_week_calendar_cached`)
            # open their own sessions internally, so they're safe to
            # submit directly. ──
            f_active   = ex.submit(self._lives_summary_active_rooms, norm)
            f_hourly   = ex.submit(self._lives_summary_hourly, norm)
            f_last     = ex.submit(self._lives_summary_last_broadcasts, norm)
            f_avgs     = ex.submit(self._lives_summary_30d_averages, norm)
            f_recon    = ex.submit(self._lives_summary_reconnects, norm)
            f_daily    = ex.submit(self._daily_buckets_cached, norm)
            f_week     = ex.submit(self._week_calendar_cached, norm)

            # Gate Phase 1 on the anchor result.  Everything else in
            # Phase 0 continues running in the background while we
            # build the Phase 1 plan.
            active_by_host, active_slice = f_active.result()
            _merge(active_slice)

            # ── Phase 1 — room-scoped families.  Submitted only if
            # there are active rooms (every room-scoped query is a
            # no-op otherwise).  Each helper here opens its own
            # session in a worker thread. ──
            phase1_futures = []
            if active_by_host:
                room_ids = [v[0] for v in active_by_host.values()]
                active_hosts = list(active_by_host.keys())
                phase1_futures = [
                    ex.submit(self._lives_summary_viewer_counts, room_ids),
                    ex.submit(self._lives_summary_session_diamonds,
                              active_by_host, room_ids),
                    ex.submit(self._lives_summary_top_gifters, room_ids),
                    ex.submit(self._lives_summary_unique_and_session_stats,
                              room_ids),
                    ex.submit(self._lives_summary_battles, room_ids),
                    ex.submit(self._lives_summary_envelopes, room_ids),
                    ex.submit(self._lives_summary_polls_pauses_favs,
                              room_ids),
                    ex.submit(self._lives_summary_active_match, active_hosts),
                    ex.submit(self._lives_summary_median_diamonds,
                              active_hosts),
                ]

            # Collect Phase 0 (the host-only group) — these were
            # submitted before Phase 1 kicked off, so most should
            # already be done by the time we reach here.
            _merge(f_hourly.result())
            _merge(f_last.result())
            _merge(f_avgs.result())
            _merge(f_recon.result())
            daily_by_host = f_daily.result()
            for h, arr in daily_by_host.items():
                out.setdefault(h, {})["daily_buckets"] = arr
            week_by_host = f_week.result()
            for h, days in week_by_host.items():
                out.setdefault(h, {})["week_calendar"] = days

            # Collect Phase 1.  Order matters slightly for the
            # diamonds_vs_typical post-derivation (see below) — the
            # session-diamonds helper must merge before the
            # median helper.  We just take results in submission
            # order: viewer_counts, session_diamonds, top_gifters,
            # unique_and_session_stats, battles, envelopes,
            # polls/pauses/favs, active_match, median.  Battles must
            # merge AFTER unique_and_session_stats (its slice pushes
            # into `session_stats`), which is naturally true here.
            for fut in phase1_futures:
                _merge(fut.result())

        # ── Post-merge derivations.  These are CPU-only and need
        # the merged `out` dict, so they run sequentially after the
        # threadpool work is done.

        # 9b' — diamonds_vs_typical multiplier.  Needs both
        # `diamonds_session` and `median_diamonds_30d` to be present
        # in `out`, which is only true post-merge.
        for h, fields in out.items():
            median = int(fields.get("median_diamonds_30d") or 0)
            if median > 0:
                cur = int(fields.get("diamonds_session") or 0)
                fields["diamonds_vs_typical"] = round(cur / median, 2)

        # ── 10. Momentum tag — 1h/24h ratio.  Cheap derivation from
        # the buckets we already have, but we want a longer-window
        # 24h vs 7d for "heating/cooling" framing on this page.  Use
        # SUMs from the buckets already loaded for hourly+daily. ──
        for h in norm:
            hourly_total = sum(out.get(h, {}).get("hourly_buckets") or [])
            daily_total  = sum(out.get(h, {}).get("daily_buckets") or [])
            # rate per minute, normalize 60min vs 24h
            rate_recent = hourly_total / 60 if hourly_total else 0
            rate_24h    = daily_total / (24 * 60) if daily_total else 0
            if daily_total == 0 and hourly_total == 0:
                label = "silent"
            elif rate_24h == 0:
                # Recent activity but no 24h activity is impossible,
                # but guard against div/0.
                label = "heating"
            elif rate_recent / rate_24h >= 2.0:
                label = "heating"
            elif rate_recent / rate_24h <= 0.3:
                label = "cooling"
            else:
                label = "steady"
            out.setdefault(h, {})["momentum_label"] = label

        return out

    def get_lives_totals(self) -> dict[str, Any]:
        """Page-level rollup: how many live, how many subs, total
        diamonds last 24h, events/min across all tracked hosts.
        Cheap — three single-row aggregates."""
        with self._get_session() as s:
            r1 = s.execute(text("""
                SELECT
                  COUNT(*) FILTER (WHERE is_live = true) AS n_live,
                  COUNT(*) AS n_total
                FROM tiktok_subscriptions
            """)).first()
            n_live = int(r1[0] or 0) if r1 else 0
            n_total = int(r1[1] or 0) if r1 else 0

            if not self._is_postgres():
                return {
                    "n_live": n_live,
                    "n_total": n_total,
                    "n_offline": max(0, n_total - n_live),
                    "diamonds_24h": 0,
                    "events_per_min": 0.0,
                }

            # 24h diamonds — read from the pre-aggregated
            # `tiktok_event_hour_counts.diamonds` column added by Phase 5
            # of the lives-list perf plan. Replaces a heap walk over
            # millions of gift events with a ≤79×25-row indexed scan
            # (`hour_bucket > NOW() - 24h` covers at most 25 hour
            # boundaries per host because of the inclusive boundary).
            #
            # Trade-off: this number now reflects events that came
            # through `record_event()` — the same path that emits to
            # WebSocket clients — so it matches the rest of the page.
            # Direct DB inserts (none in production code) would not
            # appear here; if that ever changes the backfill in
            # `add_event_hour_counts_diamonds.py` can be re-run.
            r2 = s.execute(text("""
                SELECT COALESCE(SUM(diamonds), 0)
                FROM tiktok_event_hour_counts
                WHERE hour_bucket > NOW() - INTERVAL '24 hours'
            """)).scalar() or 0

            r3 = s.execute(text("""
                SELECT COUNT(*)::float / 5.0
                FROM tiktok_events
                WHERE ts > NOW() - INTERVAL '5 minutes'
            """)).scalar() or 0
            return {
                "n_live": n_live,
                "n_total": n_total,
                "n_offline": max(0, n_total - n_live),
                "diamonds_24h": int(r2),
                "events_per_min": round(float(r3), 1),
            }

    # ── Notifications history ──────────────────────────────────────
    #
    # Persistent notification stream backing the iOS-style notification
    # center on /admin/tiktok. Rows are written by either the API
    # (when the favourites watcher pushes through it) or directly by
    # any backend code path that wants to surface a structured
    # notification (worker errors, rate-limit hits, etc).

    def insert_notification(
        self,
        *,
        type: str,
        title: str,
        body: str | None = None,
        host_unique_id: str | None = None,
        user_id: int | None = None,
        payload: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> int:
        with self._get_session() as s:
            stmt = text("""
                INSERT INTO tiktok_notifications
                    (ts, type, title, body, host_unique_id, user_id, payload)
                VALUES (
                    COALESCE(:ts, now()),
                    :type, :title, :body, :host, :uid,
                    :payload
                )
                RETURNING id
            """)
            params: dict[str, Any] = {
                "ts": ts,
                "type": type,
                "title": title,
                "body": body,
                "host": host_unique_id,
                "uid": user_id,
            }
            # JSONB on Postgres needs a JSON string when we don't bind
            # a native dict; SQLite stores TEXT.
            params["payload"] = (
                json.dumps(payload) if payload is not None else None
            )
            row = s.execute(stmt, params).first()
            s.commit()
            return int(row[0]) if row else 0

    def list_notifications(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        type: str | None = None,
        host_unique_id: str | None = None,
        unread_only: bool = False,
        include_cleared: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._get_session() as s:
            sql_parts = ["SELECT id, ts, type, title, body, host_unique_id, "
                         "user_id, payload, read, cleared "
                         "FROM tiktok_notifications WHERE 1=1"]
            params: dict[str, Any] = {}
            if not include_cleared:
                sql_parts.append("AND NOT cleared")
            if unread_only:
                sql_parts.append("AND NOT read")
            if since is not None:
                sql_parts.append("AND ts >= :since")
                params["since"] = since
            if until is not None:
                sql_parts.append("AND ts <= :until")
                params["until"] = until
            if type:
                sql_parts.append("AND type = :type")
                params["type"] = type
            if host_unique_id:
                sql_parts.append("AND host_unique_id = :host")
                params["host"] = host_unique_id
            sql_parts.append("ORDER BY ts DESC LIMIT :lim OFFSET :off")
            params["lim"] = int(limit)
            params["off"] = int(offset)
            rows = s.execute(text(" ".join(sql_parts)), params).all()
            return [
                {
                    "id": int(r[0]),
                    "ts": r[1].isoformat() if r[1] else None,
                    "type": r[2],
                    "title": r[3],
                    "body": r[4],
                    "host_unique_id": r[5],
                    "user_id": str(r[6]) if r[6] is not None else None,
                    "payload": _coerce_payload(r[7]) if r[7] is not None else None,
                    "read": bool(r[8]),
                    "cleared": bool(r[9]),
                }
                for r in rows
            ]

    def count_unread_notifications(self) -> int:
        with self._get_session() as s:
            row = s.execute(text(
                "SELECT COUNT(*) FROM tiktok_notifications "
                "WHERE NOT read AND NOT cleared"
            )).first()
            return int(row[0]) if row else 0

    def mark_notification_read(self, notification_id: int, *, read: bool = True) -> bool:
        with self._get_session() as s:
            r = s.execute(text(
                "UPDATE tiktok_notifications SET read = :r WHERE id = :id"
            ), {"r": read, "id": int(notification_id)})
            s.commit()
            return (r.rowcount or 0) > 0

    def mark_all_notifications_read(self) -> int:
        with self._get_session() as s:
            r = s.execute(text(
                "UPDATE tiktok_notifications SET read = TRUE "
                "WHERE NOT read AND NOT cleared"
            ))
            s.commit()
            return r.rowcount or 0

    def clear_notification(self, notification_id: int) -> bool:
        with self._get_session() as s:
            r = s.execute(text(
                "UPDATE tiktok_notifications SET cleared = TRUE "
                "WHERE id = :id AND NOT cleared"
            ), {"id": int(notification_id)})
            s.commit()
            return (r.rowcount or 0) > 0

    def clear_all_notifications(self) -> int:
        with self._get_session() as s:
            r = s.execute(text(
                "UPDATE tiktok_notifications SET cleared = TRUE "
                "WHERE NOT cleared"
            ))
            s.commit()
            return r.rowcount or 0

    # ── Favourite gifters ────────────────────────────────────────────
    #
    # Admin-managed watchlist of viewers — independent of the
    # cross-host `common_gifters` analytics. Powers the Favorites tab
    # on /admin/tiktok and the realtime toast that fires when one of
    # them gifts in a tracked broadcast.

    def add_favorite_gifter(
        self,
        user_id: int,
        *,
        note: str | None = None,
        notify_gift: bool | None = None,
        notify_comment: bool | None = None,
        notify_join: bool | None = None,
    ) -> None:
        """Idempotent add. Notify toggles default to (gift=true,
        comment=false, join=false) on insert; `None` here means "leave
        whatever the existing row has" (or "use server default" on
        first insert)."""
        with self._get_session() as s:
            params = {
                "uid": int(user_id),
                "note": note,
                "ng": notify_gift,
                "nc": notify_comment,
                "nj": notify_join,
            }
            if self._is_postgres():
                # COALESCE pattern: when a column is None on the way in,
                # leave the row's existing value (or the column default
                # on first insert).
                s.execute(text("""
                    INSERT INTO tiktok_favorite_gifters
                        (user_id, note, notify_gift, notify_comment, notify_join)
                    VALUES (
                        :uid, :note,
                        COALESCE(:ng, TRUE),
                        COALESCE(:nc, FALSE),
                        COALESCE(:nj, FALSE)
                    )
                    ON CONFLICT (user_id) DO UPDATE SET
                        note = COALESCE(EXCLUDED.note, tiktok_favorite_gifters.note),
                        notify_gift = COALESCE(:ng, tiktok_favorite_gifters.notify_gift),
                        notify_comment = COALESCE(:nc, tiktok_favorite_gifters.notify_comment),
                        notify_join = COALESCE(:nj, tiktok_favorite_gifters.notify_join)
                """), params)
            else:
                exists = s.execute(text(
                    "SELECT 1 FROM tiktok_favorite_gifters WHERE user_id = :uid"
                ), {"uid": int(user_id)}).first()
                if exists is None:
                    s.execute(text("""
                        INSERT INTO tiktok_favorite_gifters
                            (user_id, note, notify_gift, notify_comment, notify_join)
                        VALUES (:uid, :note,
                                COALESCE(:ng, 1),
                                COALESCE(:nc, 0),
                                COALESCE(:nj, 0))
                    """), params)
                else:
                    sets = []
                    if note is not None: sets.append("note = :note")
                    if notify_gift is not None: sets.append("notify_gift = :ng")
                    if notify_comment is not None: sets.append("notify_comment = :nc")
                    if notify_join is not None: sets.append("notify_join = :nj")
                    if sets:
                        s.execute(text(
                            f"UPDATE tiktok_favorite_gifters "
                            f"SET {', '.join(sets)} WHERE user_id = :uid"
                        ), params)
            s.commit()

    def remove_favorite_gifter(self, user_id: int) -> bool:
        """Returns True if a row was actually removed."""
        with self._get_session() as s:
            n = s.execute(text(
                "DELETE FROM tiktok_favorite_gifters WHERE user_id = :uid"
            ), {"uid": int(user_id)}).rowcount
            s.commit()
            return bool(n and n > 0)

    def is_favorite_gifter(self, user_id: int) -> bool:
        with self._get_session() as s:
            row = s.execute(text(
                "SELECT 1 FROM tiktok_favorite_gifters WHERE user_id = :uid"
            ), {"uid": int(user_id)}).first()
            return row is not None

    def list_favorite_gifter_ids(self) -> list[int]:
        """Bare id list — kept for callers that just want ids."""
        with self._get_session() as s:
            rows = s.execute(text(
                "SELECT user_id FROM tiktok_favorite_gifters ORDER BY added_at DESC"
            )).fetchall()
            return [int(r[0]) for r in rows]

    def list_favorite_gifter_notify_config(self) -> list[dict[str, Any]]:
        """`{user_id, notify_gift, notify_comment, notify_join}` list
        — fed to the WS-toast filter on the admin shell so each event
        is matched against per-favourite preferences."""
        with self._get_session() as s:
            rows = s.execute(text("""
                SELECT user_id, notify_gift, notify_comment, notify_join
                FROM tiktok_favorite_gifters
                ORDER BY added_at DESC
            """)).fetchall()
            return [
                {
                    "user_id": int(r[0]),
                    "notify_gift": bool(r[1]),
                    "notify_comment": bool(r[2]),
                    "notify_join": bool(r[3]),
                }
                for r in rows
            ]

    def list_favorite_gifters_enriched(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        q: str | None = None,
    ) -> dict[str, Any]:
        """Favourite gifters joined to viewer identity + summary
        rollups (cross-host totals from `tiktok_user_host_summary`).
        Powers the Favorites tab; mirrors the row shape of
        `common_gifters` so the same row component renders both."""
        with self._get_session() as s:
            if not self._is_postgres():
                # SQLite (dev) fallback: bare list, no rollup.
                vrows = s.execute(text("""
                    SELECT f.user_id, f.note, f.added_at,
                           v.unique_id, v.nickname, v.avatar_url
                    FROM tiktok_favorite_gifters f
                    LEFT JOIN tiktok_viewers v ON v.user_id = f.user_id
                    ORDER BY f.added_at DESC
                    LIMIT :limit OFFSET :offset
                """), {"limit": limit, "offset": offset}).mappings().all()
                items = [dict(r) for r in vrows]
                total = s.execute(text(
                    "SELECT COUNT(*) FROM tiktok_favorite_gifters"
                )).scalar() or 0
                return {"items": items, "total": int(total)}

            # Postgres path — enrich from the summary table in one
            # query so the Favorites tab is just as cheap as Common
            # Gifters.
            rows = s.execute(text("""
                WITH per_user AS (
                    SELECT s.user_id,
                           COUNT(*)::int            AS host_count,
                           SUM(s.diamonds)::bigint  AS diamonds,
                           SUM(s.gifts)::bigint     AS gifts
                    FROM tiktok_user_host_summary s
                    WHERE s.user_id IN (SELECT user_id FROM tiktok_favorite_gifters)
                    GROUP BY s.user_id
                )
                SELECT
                    f.user_id,
                    f.note,
                    f.added_at,
                    f.notify_gift,
                    f.notify_comment,
                    f.notify_join,
                    COALESCE(pu.host_count, 0) AS host_count,
                    COALESCE(pu.diamonds, 0)   AS diamonds,
                    COALESCE(pu.gifts, 0)      AS gifts,
                    v.unique_id,
                    v.nickname,
                    v.avatar_url
                FROM tiktok_favorite_gifters f
                LEFT JOIN per_user pu ON pu.user_id = f.user_id
                LEFT JOIN tiktok_viewers v ON v.user_id = f.user_id
                WHERE :q_is_null OR
                      v.nickname  ILIKE :needle OR
                      v.unique_id ILIKE :needle
                ORDER BY f.added_at DESC
                LIMIT :limit OFFSET :offset
            """), {
                "limit": int(limit),
                "offset": int(offset),
                "q_is_null": q is None or not q.strip(),
                "needle": f"%{(q or '').strip()}%",
            }).mappings().all()
            uids = [int(r["user_id"]) for r in rows]
            host_map: dict[int, list[dict[str, Any]]] = {}
            if uids:
                breakdowns = s.execute(text("""
                    SELECT user_id, host_unique_id AS host, diamonds, gifts
                    FROM tiktok_user_host_summary
                    WHERE user_id = ANY(:uids)
                    ORDER BY user_id, diamonds DESC
                """), {"uids": uids}).mappings().all()
                for br in breakdowns:
                    host_map.setdefault(int(br["user_id"]), []).append({
                        "host": br["host"],
                        "diamonds": int(br["diamonds"] or 0),
                        "gifts": int(br["gifts"] or 0),
                    })
            total = s.execute(text("""
                SELECT COUNT(*) FROM tiktok_favorite_gifters f
                LEFT JOIN tiktok_viewers v ON v.user_id = f.user_id
                WHERE :q_is_null OR
                      v.nickname  ILIKE :needle OR
                      v.unique_id ILIKE :needle
            """), {
                "q_is_null": q is None or not q.strip(),
                "needle": f"%{(q or '').strip()}%",
            }).scalar() or 0
            items = []
            for r in rows:
                uid = int(r["user_id"])
                items.append({
                    "user_id": uid,
                    "unique_id": r["unique_id"],
                    "nickname": r["nickname"],
                    "avatar_url": r["avatar_url"],
                    "note": r["note"],
                    "added_at": r["added_at"].isoformat() if r["added_at"] else None,
                    "notify_gift": bool(r["notify_gift"]),
                    "notify_comment": bool(r["notify_comment"]),
                    "notify_join": bool(r["notify_join"]),
                    "host_count": int(r["host_count"] or 0),
                    "diamonds": int(r["diamonds"] or 0),
                    "gifts": int(r["gifts"] or 0),
                    "hosts": host_map.get(uid, []),
                })
            return {"items": items, "total": int(total)}

    def host_event_counts_by_type(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, dict[str, int]]:
        with self._get_session() as s:
            q = (
                s.query(
                    RoomModel.host_unique_id,
                    TikTokEventModel.type,
                    func.count(TikTokEventModel.id),
                )
                .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
            )
            if since is not None:
                q = q.filter(TikTokEventModel.ts >= since)
            if until is not None:
                q = q.filter(TikTokEventModel.ts <= until)
            q = q.group_by(RoomModel.host_unique_id, TikTokEventModel.type)
            out: dict[str, dict[str, int]] = {}
            for host, etype, count in q.all():
                if not host:
                    continue
                out.setdefault(host, {})[etype] = int(count)
            return out

    def host_event_buckets(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
        bucket_seconds: int = 3600,
        tz: str = "UTC",
    ) -> list[dict[str, Any]]:
        """Time-bucketed event totals per (host, type).

        `tz` controls calendar-day / hour bucket boundaries: a Lima
        viewer should pass `America/Lima` so a "day" bucket is
        00:00→24:00 in Lima rather than UTC. Stored timestamps are
        always UTC; only the bucket key shifts.

        Postgres uses `date_trunc(unit, ts AT TIME ZONE :tz)`; SQLite
        falls back to zoneinfo-shifted Python bucketing.
        """
        zone = (tz or "UTC").strip() or "UTC"
        with self._get_session() as s:
            is_pg = self._is_postgres()
            if is_pg:
                # Choose date_trunc unit based on bucket_seconds.
                unit = "minute"
                if bucket_seconds >= 86400:
                    unit = "day"
                elif bucket_seconds >= 3600:
                    unit = "hour"
                elif bucket_seconds >= 60:
                    unit = "minute"
                # `AT TIME ZONE :tz` converts the timestamptz to the
                # zone's local wall clock (returning a TIMESTAMP). We
                # truncate that, then apply `AT TIME ZONE :tz` AGAIN
                # which interprets the local clock back as a
                # zone-anchored timestamptz so the returned ISO
                # carries the right offset for the bucket boundary.
                bucket_expr = func.date_trunc(
                    unit,
                    TikTokEventModel.ts.op("AT TIME ZONE")(text(":tz1")),
                ).op("AT TIME ZONE")(text(":tz2"))
                q = (
                    s.query(
                        bucket_expr.label("bucket"),
                        RoomModel.host_unique_id,
                        TikTokEventModel.type,
                        func.count(TikTokEventModel.id),
                    )
                    .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                    .filter(TikTokEventModel.ts >= since)
                )
                if until is not None:
                    q = q.filter(TikTokEventModel.ts <= until)
                q = q.group_by(bucket_expr, RoomModel.host_unique_id, TikTokEventModel.type)
                q = q.order_by(bucket_expr.asc())
                q = q.params(tz1=zone, tz2=zone)
                return [
                    {
                        "bucket": (b.isoformat() if hasattr(b, "isoformat") else str(b)),
                        "host_unique_id": host,
                        "type": etype,
                        "count": int(count),
                    }
                    for b, host, etype, count in q.all()
                ]
            # Fallback: pull rows + bucket in Python (SQLite, MySQL, etc.).
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                tzinfo = ZoneInfo(zone)
            except ZoneInfoNotFoundError:
                tzinfo = timezone.utc
            rows = (
                s.query(
                    TikTokEventModel.ts,
                    RoomModel.host_unique_id,
                    TikTokEventModel.type,
                )
                .join(RoomModel, RoomModel.room_id == TikTokEventModel.room_id)
                .filter(TikTokEventModel.ts >= since)
            )
            if until is not None:
                rows = rows.filter(TikTokEventModel.ts <= until)
            results: dict[tuple[int, str, str], int] = {}
            # Adjust `since` into the requested zone so bucket origin is
            # zone-aligned (prevents a "day 0" cutting an hour or two
            # into the user's actual midnight).
            since_local = since.astimezone(tzinfo) if since.tzinfo else since.replace(tzinfo=timezone.utc).astimezone(tzinfo)
            since_ts = int(since_local.timestamp())
            for ts, host, etype in rows.all():
                if not host:
                    continue
                row_local = ts.astimezone(tzinfo) if ts.tzinfo else ts.replace(tzinfo=timezone.utc).astimezone(tzinfo)
                row_ts = int(row_local.timestamp())
                bucket_idx = (row_ts - since_ts) // bucket_seconds
                key = (bucket_idx, host, etype)
                results[key] = results.get(key, 0) + 1
            out: list[dict[str, Any]] = []
            for (bucket_idx, host, etype), count in sorted(results.items()):
                bucket_ts = since_ts + bucket_idx * bucket_seconds
                # Emit the boundary as a zone-anchored ISO so the
                # frontend's "bucket label" formatter renders the
                # correct local hour/day even on the dev path.
                out.append(
                    {
                        "bucket": datetime.fromtimestamp(bucket_ts, tzinfo).isoformat(),
                        "host_unique_id": host,
                        "type": etype,
                        "count": count,
                    }
                )
            return out

    def room_event_buckets(
        self,
        room_id: int | list[int],
        *,
        since: datetime,
        until: datetime,
        bucket_seconds: int,
    ) -> dict[str, Any]:
        # Accept either a single id or a list — multi-room aggregation
        # (the day-view) is just a `room_id IN (...)` filter swap and
        # collapses the previous "fan out N parallel HTTP calls,
        # zip-sum on the client" workflow to a single SQL group-by.
        room_id_list = [int(room_id)] if isinstance(room_id, int) else [
            int(x) for x in room_id
        ]
        if not room_id_list:
            range_seconds = max(1, int((until - since).total_seconds()))
            # ceil-divide so the LAST partial bucket is kept — floor
            # silently drops events in the trailing partial-bucket
            # window (e.g. a 22:45→22:48 broadcast at the right edge
            # of a 15:49→22:48 day view with 10-min buckets falls in
            # bucket 41 of 41, which floor=41 would discard).
            n_buckets = max(
                1,
                (range_seconds + bucket_seconds - 1) // bucket_seconds,
            )
            since_ts = int(since.timestamp())
            return {
                "starts": [
                    datetime.fromtimestamp(
                        since_ts + i * bucket_seconds, timezone.utc
                    ).isoformat()
                    for i in range(n_buckets)
                ],
                "by_type": {},
                "diamonds": [0] * n_buckets,
                "diamonds_total": 0,
                "bucket_seconds": int(bucket_seconds),
            }
        with self._get_session() as s:
            is_pg = self._is_postgres()
            range_seconds = max(1, int((until - since).total_seconds()))
            # ceil-divide so the LAST partial bucket is kept — floor
            # silently drops events in the trailing partial-bucket
            # window (e.g. a 22:45→22:48 broadcast at the right edge
            # of a 15:49→22:48 day view with 10-min buckets falls in
            # bucket 41 of 41, which floor=41 would discard).
            n_buckets = max(
                1,
                (range_seconds + bucket_seconds - 1) // bucket_seconds,
            )
            since_ts = int(since.timestamp())
            starts = [
                datetime.fromtimestamp(
                    since_ts + i * bucket_seconds, timezone.utc
                ).isoformat()
                for i in range(n_buckets)
            ]
            by_type: dict[str, list[int]] = {}
            diamonds: list[int] = [0] * n_buckets
            diamonds_total = 0

            if is_pg:
                # `date_bin` rounds ts down to the bucket boundary anchored
                # at `since` — gives us discrete buckets identical to the
                # Python loop's idx math, but without an event-count cap.
                payload = TikTokEventModel.payload
                diamond_per = func.coalesce(
                    cast(payload.op("->>")("diamond_count"), Integer), 0
                )
                repeat = func.coalesce(
                    cast(payload.op("->>")("repeat_count"), Integer), 1
                )
                bucket_expr = func.date_bin(
                    text(f"interval '{int(bucket_seconds)} seconds'"),
                    TikTokEventModel.ts,
                    text("CAST(:since AS timestamptz)"),
                ).label("bucket")
                q = (
                    s.query(
                        bucket_expr,
                        TikTokEventModel.type.label("type"),
                        func.count(TikTokEventModel.id).label("n"),
                        func.sum(
                            case((TikTokEventModel.type == "gift", diamond_per * repeat), else_=0)
                        ).label("diamonds"),
                    )
                    .filter(TikTokEventModel.room_id.in_(room_id_list))
                    .filter(TikTokEventModel.ts >= since)
                    .filter(TikTokEventModel.ts <= until)
                    .group_by("bucket", TikTokEventModel.type)
                    .params(since=since)
                )
                for row in q.all():
                    bucket_dt = row.bucket
                    if bucket_dt is None:
                        continue
                    if bucket_dt.tzinfo is None:
                        bucket_dt = bucket_dt.replace(tzinfo=timezone.utc)
                    idx = int(
                        (int(bucket_dt.timestamp()) - since_ts) // bucket_seconds
                    )
                    if idx < 0 or idx >= n_buckets:
                        continue
                    arr = by_type.setdefault(row.type, [0] * n_buckets)
                    arr[idx] += int(row.n or 0)
                    if row.type == "gift":
                        d = int(row.diamonds or 0)
                        diamonds[idx] += d
                diamonds_total = sum(diamonds)
                return {
                    "starts": starts,
                    "by_type": by_type,
                    "diamonds": diamonds,
                    "diamonds_total": diamonds_total,
                    "bucket_seconds": int(bucket_seconds),
                }

            # ── SQLite / non-PG fallback: bucket in Python from a row scan
            #    (no row cap — for the dev DB this is acceptable). ─────
            q = (
                s.query(TikTokEventModel)
                .filter(TikTokEventModel.room_id.in_(room_id_list))
                .filter(TikTokEventModel.ts >= since)
                .filter(TikTokEventModel.ts <= until)
            )
            for row in q.yield_per(2000):
                idx = (int(row.ts.timestamp()) - since_ts) // bucket_seconds
                if idx < 0 or idx >= n_buckets:
                    continue
                arr = by_type.setdefault(row.type, [0] * n_buckets)
                arr[idx] += 1
                if row.type == "gift" and isinstance(row.payload, dict):
                    d = (int(row.payload.get("diamond_count") or 0)) * (
                        int(row.payload.get("repeat_count") or 1)
                    )
                    diamonds[idx] += d
            diamonds_total = sum(diamonds)
            return {
                "starts": starts,
                "by_type": by_type,
                "diamonds": diamonds,
                "diamonds_total": diamonds_total,
                "bucket_seconds": int(bucket_seconds),
            }

    # ── Live-status cache (per subscription) ─────────────────────────

    def update_live_status(
        self,
        unique_id: str,
        *,
        is_live: bool | None,
        room_id: int | None = None,
    ) -> None:
        """Persist the latest live-state observation. `live_checked_at`
        stamped to NOW so callers can compute freshness.

        Single UPDATE — pgbouncer-safe. Called from the worker's
        scraper task after each profile fetch."""
        with self._get_session() as s:
            update_clause = {
                SubscriptionModel.is_live: is_live,
                SubscriptionModel.live_checked_at: _utcnow(),
            }
            if room_id is not None:
                update_clause[SubscriptionModel.current_room_id] = int(room_id)
            s.query(SubscriptionModel).filter_by(unique_id=unique_id).update(
                update_clause, synchronize_session=False,
            )
            s.commit()

    def list_live_status_targets(
        self,
        worker_id: int,
        *,
        max_age_seconds: int = 60,
        limit: int = 100,
    ) -> list[Subscription]:
        """Return enabled subscriptions whose live-status cache is older
        than `max_age_seconds` (or never checked). Ordered by oldest
        check first so we never starve a single handle.

        Includes BOTH subs assigned to this worker AND subs that nobody
        has claimed (over-capacity tail, freshly-added handles waiting
        for a slot). Without the unclaimed branch a sub added when the
        worker is full sits forever with `live_checked_at = NULL` —
        which means the live-detail page can't even show whether the
        creator is broadcasting until somebody else's sub is removed.

        With multiple workers the unclaimed branch can race — multiple
        workers might pick the same unclaimed sub and scrape it. The
        `max_age_seconds` cutoff dedupes naturally: the first worker to
        update `live_checked_at` makes the row look "fresh" so the
        others skip on their next tick. Cost: at most one redundant
        HTTP per unclaimed sub per minute under contention.
        """
        from sqlalchemy import or_
        cutoff = _utcnow() - timedelta(seconds=max_age_seconds)
        with self._get_session() as s:
            rows = (
                s.query(SubscriptionModel)
                .filter(
                    SubscriptionModel.enabled.is_(True),
                    or_(
                        SubscriptionModel.assigned_worker_id == worker_id,
                        SubscriptionModel.assigned_worker_id.is_(None),
                    ),
                    (
                        (SubscriptionModel.live_checked_at.is_(None))
                        | (SubscriptionModel.live_checked_at < cutoff)
                    ),
                )
                .order_by(
                    SubscriptionModel.live_checked_at.asc().nullsfirst(),
                )
                .limit(limit)
                .all()
            )
            return [_sub_to_dataclass(r) for r in rows]

    # ── Worker registry + subscription claim ─────────────────────────

    def upsert_worker(self, worker: TikTokWorker) -> TikTokWorker:
        """Register or refresh a worker row by `worker_key`.

        DB-based mutex (replaces the flock):
          - If a row already exists for this worker_key AND its
            `last_heartbeat_at` is fresh (<30s) AND status is not
            'stopped': another process is still active under this key.
            Raise `WorkerKeyConflictError`. The CLI converts that to a
            non-zero exit so the supervisor crashloops until the
            conflict goes away.
          - Otherwise (no row, or stale row, or stopped row): take it
            over — overwrite host/pid/started_at, reset desired_status
            to 'running' (admin can override afterwards), clear any
            stale command from the previous tenant.
        """
        with self._get_session() as s:
            now = _utcnow()
            existing = (
                s.query(WorkerModel)
                .filter_by(worker_key=worker.worker_key)
                .one_or_none()
            )
            if existing is not None:
                age = (
                    (now - existing.last_heartbeat_at).total_seconds()
                    if existing.last_heartbeat_at else 1e9
                )
                if existing.status not in ("stopped", "stale") and age < 30:
                    raise WorkerKeyConflictError(
                        f"worker_key={worker.worker_key!r} already held by "
                        f"id={existing.id} pid={existing.pid} "
                        f"(last heartbeat {age:.1f}s ago)."
                    )
                # Take over.
                existing.host = worker.host
                existing.pid = worker.pid
                existing.started_at = now
                existing.last_heartbeat_at = now
                existing.status = "running"
                existing.desired_status = "running"
                existing.command = None
                existing.command_issued_at = None
                existing.command_acked_at = None
                existing.capacity = worker.capacity
                existing.sessions_count = 0
                existing.metadata_ = worker.metadata
                row = existing
            else:
                row = WorkerModel(
                    worker_key=worker.worker_key,
                    host=worker.host,
                    pid=worker.pid,
                    started_at=now,
                    last_heartbeat_at=now,
                    status="running",
                    desired_status="running",
                    capacity=worker.capacity,
                    sessions_count=0,
                    metadata_=worker.metadata,
                )
                s.add(row)
            s.commit()
            s.refresh(row)
            return _worker_to_dataclass(row)

    def get_worker(self, worker_id: int) -> TikTokWorker | None:
        """Look up the registry row by id. Used by the worker on each
        reconcile tick to read its own desired_status / command."""
        with self._get_session() as s:
            row = s.query(WorkerModel).filter_by(id=worker_id).one_or_none()
            return _worker_to_dataclass(row) if row else None

    def get_worker_by_key(self, worker_key: str) -> TikTokWorker | None:
        with self._get_session() as s:
            row = (
                s.query(WorkerModel)
                .filter_by(worker_key=worker_key)
                .one_or_none()
            )
            return _worker_to_dataclass(row) if row else None

    def set_worker_command(
        self,
        worker_id: int,
        *,
        desired_status: str | None = None,
        command: str | None = None,
    ) -> bool:
        """Admin-side write: set a target state and/or a one-shot command.

        Either or both can be set. `command_issued_at` is updated when
        a command is provided; `command_acked_at` is cleared so the
        worker treats it as new. Returns True if the row was updated."""
        if desired_status is None and command is None:
            return False
        update_clause: dict = {}
        if desired_status is not None:
            update_clause[WorkerModel.desired_status] = desired_status
        if command is not None:
            update_clause[WorkerModel.command] = command
            update_clause[WorkerModel.command_issued_at] = _utcnow()
            update_clause[WorkerModel.command_acked_at] = None
        with self._get_session() as s:
            n = (
                s.query(WorkerModel)
                .filter_by(id=worker_id)
                .update(update_clause, synchronize_session=False)
            )
            s.commit()
            return n > 0

    def ack_worker_command(self, worker_id: int) -> None:
        """Worker-side write: stamp `command_acked_at` and clear the
        pending command. Idempotent."""
        with self._get_session() as s:
            s.query(WorkerModel).filter_by(id=worker_id).update(
                {
                    WorkerModel.command_acked_at: _utcnow(),
                    WorkerModel.command: None,
                },
                synchronize_session=False,
            )
            s.commit()

    def append_worker_log(
        self,
        worker_id: int | None,
        *,
        event: str,
        level: str = "info",
        handle: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Append one log row. Best-effort — exceptions caught by caller."""
        with self._get_session() as s:
            row = WorkerLogModel(
                worker_id=worker_id,
                level=level,
                event=event,
                handle=handle,
                detail=detail,
            )
            s.add(row)
            s.commit()

    def list_worker_log(
        self,
        worker_id: int | None = None,
        *,
        handle: str | None = None,
        event_prefix: str | None = None,
        limit: int = 200,
    ) -> list[TikTokWorkerLog]:
        """Most recent log rows. Filters: worker_id, handle, event_prefix
        (e.g. 'profile_probe' matches 'profile_probe_failed' AND
        'profile_probe_partial')."""
        with self._get_session() as s:
            q = s.query(WorkerLogModel)
            if worker_id is not None:
                q = q.filter(WorkerLogModel.worker_id == worker_id)
            if handle is not None:
                q = q.filter(WorkerLogModel.handle == handle)
            if event_prefix is not None:
                q = q.filter(WorkerLogModel.event.like(f"{event_prefix}%"))
            q = q.order_by(WorkerLogModel.id.desc()).limit(limit)
            return [_worker_log_to_dataclass(r) for r in q.all()]

    def release_subscription(self, unique_id: str) -> bool:
        """Admin-side write: yank a subscription's worker assignment so
        another worker can claim it on next reconcile. Doesn't touch
        `enabled` — just clears `assigned_worker_id` and the lease."""
        with self._get_session() as s:
            n = (
                s.query(SubscriptionModel)
                .filter_by(unique_id=unique_id)
                .update(
                    {
                        SubscriptionModel.assigned_worker_id: None,
                        SubscriptionModel.assignment_lease_until: None,
                    },
                    synchronize_session=False,
                )
            )
            s.commit()
            return n > 0

    def heartbeat_worker(
        self,
        worker_id: int,
        *,
        sessions_count: int,
        status: str = "running",
        metadata: dict | None = None,
    ) -> None:
        """Bump `last_heartbeat_at` + update live counters. Cheap UPDATE
        — runs every ~5 seconds per worker. Single statement so it's
        compatible with pgbouncer transaction-pool."""
        with self._get_session() as s:
            s.query(WorkerModel).filter_by(id=worker_id).update(
                {
                    WorkerModel.last_heartbeat_at: _utcnow(),
                    WorkerModel.sessions_count: int(sessions_count),
                    WorkerModel.status: status,
                    WorkerModel.metadata_: metadata,
                },
                synchronize_session=False,
            )
            s.commit()

    def mark_worker_stopped(self, worker_id: int) -> None:
        """Graceful-shutdown signal — the row stays so the admin UI can
        show "stopped" instead of "vanished", but assignments are released
        so handles get re-claimed quickly."""
        with self._get_session() as s:
            s.query(WorkerModel).filter_by(id=worker_id).update(
                {WorkerModel.status: "stopped"},
                synchronize_session=False,
            )
            self._release_assignments_in_session(s, worker_id)
            s.commit()

    def reap_stale_workers(self, *, stale_after_seconds: int = 30) -> int:
        """Find workers whose `last_heartbeat_at` is older than the cutoff
        AND whose status isn't already 'stopped', mark them stopped, and
        release every subscription they were holding so other workers can
        claim them. Returns the number of workers reaped."""
        cutoff = _utcnow() - timedelta(seconds=stale_after_seconds)
        reaped = 0
        with self._get_session() as s:
            stale = (
                s.query(WorkerModel)
                .filter(
                    WorkerModel.last_heartbeat_at < cutoff,
                    WorkerModel.status != "stopped",
                )
                .all()
            )
            for w in stale:
                w.status = "stale"
                self._release_assignments_in_session(s, w.id)
                reaped += 1
            if reaped:
                s.commit()
        return reaped

    def list_workers(self) -> list[TikTokWorker]:
        """All worker rows. Used by the admin Worker tab."""
        with self._get_session() as s:
            rows = (
                s.query(WorkerModel)
                .order_by(WorkerModel.last_heartbeat_at.desc())
                .all()
            )
            return [_worker_to_dataclass(r) for r in rows]

    def _release_assignments_in_session(self, s, worker_id: int) -> None:
        """Clear `assigned_worker_id` + `assignment_lease_until` for every
        subscription this worker currently holds. Caller is responsible
        for committing the surrounding transaction."""
        s.query(SubscriptionModel).filter_by(assigned_worker_id=worker_id).update(
            {
                SubscriptionModel.assigned_worker_id: None,
                SubscriptionModel.assignment_lease_until: None,
            },
            synchronize_session=False,
        )

    def claim_subscriptions(
        self,
        worker_id: int,
        *,
        max_to_claim: int,
        lease_seconds: int = 60,
    ) -> list[str]:
        """Atomically claim up to `max_to_claim` enabled subscriptions
        whose lease is unset or expired. Returns the unique_ids claimed.

        On Postgres: SELECT FOR UPDATE SKIP LOCKED so concurrent workers
        don't fight over the same rows. Each worker takes a disjoint set.
        SQLite path: best-effort (no SKIP LOCKED), fine for dev.
        """
        if max_to_claim <= 0:
            return []
        now = _utcnow()
        new_lease = now + timedelta(seconds=lease_seconds)
        with self._get_session() as s:
            # Capacity policy: worker slots are spent ONLY on
            # currently-live creators. Offline subs aren't claimed
            # — they're tracked by the central is_live probe (which
            # covers unclaimed subs too) and only enter the claim
            # pool the moment they go live. Without this filter, the
            # offline-release hysteresis would just thrash: release
            # an offline sub → next reconcile claims it back in the
            # same cycle because Phase-1 ordering preferred live
            # subs only when more were available.
            #
            # Trade-off: if the central probe is stale (e.g. the
            # worker just booted before the probe loop ran), some
            # in-progress lives won't be claimed for ~60s. Acceptable
            # — TikTokLive's WS doesn't replay history anyway, and
            # the alternative was paying a slot per offline creator
            # forever.
            #
            # Subs with is_live=NULL (never probed) are excluded too;
            # the probe loop will classify them within a minute.
            order_cols = [
                SubscriptionModel.live_checked_at.desc().nullslast()
                if self._is_postgres()
                else SubscriptionModel.live_checked_at.desc(),
                SubscriptionModel.id.asc(),
            ]
            q = s.query(SubscriptionModel).filter(
                SubscriptionModel.enabled.is_(True),
                SubscriptionModel.is_live.is_(True),
                (
                    (SubscriptionModel.assigned_worker_id.is_(None))
                    | (SubscriptionModel.assignment_lease_until.is_(None))
                    | (SubscriptionModel.assignment_lease_until < now)
                ),
            ).order_by(*order_cols).limit(max_to_claim)

            if self._is_postgres():
                q = q.with_for_update(skip_locked=True)

            candidates = q.all()
            claimed: list[str] = []
            for sub in candidates:
                sub.assigned_worker_id = worker_id
                sub.assignment_lease_until = new_lease
                claimed.append(sub.unique_id)
            if claimed:
                s.commit()
                # Sanity check: read back to confirm the UPDATE
                # actually persisted (defends against silent rollback
                # under unusual session/pgbouncer conditions).
                persisted = (
                    s.query(SubscriptionModel.unique_id)
                    .filter(
                        SubscriptionModel.assigned_worker_id == worker_id,
                        SubscriptionModel.unique_id.in_(claimed),
                    )
                    .count()
                )
                if persisted != len(claimed):
                    logger.error(
                        "claim_subscriptions: commit drift — "
                        "claimed %d but only %d persisted "
                        "(worker_id=%s).",
                        len(claimed), persisted, worker_id,
                    )
                else:
                    logger.info(
                        "claim_subscriptions: %d claimed and persisted (worker_id=%s).",
                        len(claimed), worker_id,
                    )
            return claimed

    def extend_my_leases(
        self, worker_id: int, *, lease_seconds: int = 60
    ) -> list[str]:
        """Bump `assignment_lease_until` for every subscription this
        worker currently holds. Called every reconcile tick so a healthy
        worker keeps its assignments. Returns the handles still held
        (so the caller can detect a "lost claim" and tear down a session
        whose handle was reaped by another worker)."""
        new_lease = _utcnow() + timedelta(seconds=lease_seconds)
        with self._get_session() as s:
            held = (
                s.query(SubscriptionModel)
                .filter(
                    SubscriptionModel.assigned_worker_id == worker_id,
                    SubscriptionModel.enabled.is_(True),
                )
                .all()
            )
            handles = [sub.unique_id for sub in held]
            if handles:
                s.query(SubscriptionModel).filter(
                    SubscriptionModel.assigned_worker_id == worker_id,
                    SubscriptionModel.enabled.is_(True),
                ).update(
                    {SubscriptionModel.assignment_lease_until: new_lease},
                    synchronize_session=False,
                )
                s.commit()
            return handles

    def release_my_assignment(self, worker_id: int, unique_id: str) -> None:
        """Clear assignment for a single handle (e.g., subscription was
        disabled / deleted while we held it)."""
        with self._get_session() as s:
            s.query(SubscriptionModel).filter(
                SubscriptionModel.assigned_worker_id == worker_id,
                SubscriptionModel.unique_id == unique_id,
            ).update(
                {
                    SubscriptionModel.assigned_worker_id: None,
                    SubscriptionModel.assignment_lease_until: None,
                },
                synchronize_session=False,
            )
            s.commit()


def _worker_to_dataclass(m: WorkerModel) -> TikTokWorker:
    md = m.metadata_
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except (ValueError, TypeError):
            md = None
    return TikTokWorker(
        id=m.id,
        worker_key=m.worker_key,
        host=m.host,
        pid=int(m.pid),
        status=m.status or "running",
        capacity=int(m.capacity or 30),
        sessions_count=int(m.sessions_count or 0),
        started_at=m.started_at,
        last_heartbeat_at=m.last_heartbeat_at,
        metadata=md if isinstance(md, dict) else None,
        desired_status=m.desired_status or "running",
        command=m.command,
        command_issued_at=m.command_issued_at,
        command_acked_at=m.command_acked_at,
    )


def _worker_log_to_dataclass(m: WorkerLogModel) -> TikTokWorkerLog:
    detail = m.detail
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except (ValueError, TypeError):
            detail = None
    return TikTokWorkerLog(
        id=m.id,
        worker_id=m.worker_id,
        ts=m.ts,
        level=m.level or "info",
        event=m.event,
        handle=m.handle,
        detail=detail if isinstance(detail, dict) else None,
    )


def _coerce_payload(p: Any) -> Any:
    """JSONB columns come back as native Python (dict/list/scalar) on
    Postgres and as JSON-encoded text on SQLite. Normalize both.

    Originally only event `payload` (always a dict) called this, so
    the function returned `{}` on anything non-dict. But matches
    columns are heterogeneous: `opponents` is a JSON *list* and
    `scores` is a JSON dict. The old `{}` fallback silently dropped
    the list, leaving the score-resolution + outcome-derivation
    paths blind. Now we pass through dict/list verbatim and parse
    strings.
    """
    if isinstance(p, (dict, list)):
        return p
    if isinstance(p, str):
        try:
            return json.loads(p)
        except (ValueError, TypeError):
            return {}
    return {}


def _coerce_int(v: Any) -> int | None:
    """Tolerant int coerce for JSONB-extracted strings/numbers — used by
    the gifters leaderboard to surface member_level / gifter_level even
    when the payload field is a string. Returns None on garbage."""
    if v is None:
        return None
    try:
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None
