"""Redis implementation of `TikTokStateCachePort`.

Used in worker-mode deployments where the listener pool and the API
workers are separate processes. State + version live in Redis; deltas
fan out via Redis pub/sub. Both processes share the same state
through Redis as the single source of truth.

Keys:

  tiktok:lives:state:<handle>     JSON-encoded summary dict
  tiktok:lives:version:<handle>   monotonic counter (INCR'd by apply_patch)

Channels:

  tiktok:lives:delta:admin        full `{host, version, patch}` deltas
  tiktok:lives:delta:public       sanitized deltas (operator-only fields stripped)

The persist path runs `apply_patch` synchronously inside `record_event`
(which itself runs in a thread via `to_thread`). A blocking Redis
client is fine in that thread. Subscribers are async (FastAPI WS
routes) and use `redis.asyncio` directly.

Atomicity for `apply_patch` (deep-merge + version increment + publish):
implemented as a Lua script so it's a single Redis round-trip and the
state mutation is atomic w.r.t. concurrent listeners. The publish is
issued from Python after the script returns the new version, because
we need the sanitizer applied on the Python side."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import threading
from typing import Any, AsyncIterator, Callable, Optional

import redis

from ports.tiktok_state_cache import (
    CHANNEL_ADMIN,
    CHANNEL_PUBLIC,
    Channel,
    TikTokStateCachePort,
)

logger = logging.getLogger(__name__)


_STATE_PREFIX = "tiktok:lives:state:"
_VERSION_PREFIX = "tiktok:lives:version:"
_DELTA_CHANNEL_ADMIN = "tiktok:lives:delta:admin"
_DELTA_CHANNEL_PUBLIC = "tiktok:lives:delta:public"


# Lua: read state, deep-merge patch, write back, INCR version. Single
# round-trip + Redis is single-threaded for script execution, so this
# is atomic w.r.t. concurrent SCRIPTs on the same keys. Returns the
# new version as an integer.
#
# Deep merge rules match the in-process adapter: dict values recurse,
# arrays + scalars replace. The tricky part is distinguishing a JSON
# object from a JSON array — both decode to Lua tables. `is_array`
# checks whether all keys are sequential 1-based integers (cjson's
# array encoding). Non-empty arrays are detected; empty tables fall
# back to "object" (treated as recurse-able), which is harmless
# because empty patches are no-ops upstream.
_APPLY_PATCH_LUA = """
local state_key = KEYS[1]
local version_key = KEYS[2]
local patch_json = ARGV[1]

local state_json = redis.call("GET", state_key) or "{}"
local state = cjson.decode(state_json)
local patch = cjson.decode(patch_json)

local function is_array(t)
  if type(t) ~= "table" then return false end
  local n = 0
  for k, _ in pairs(t) do
    if type(k) ~= "number" then return false end
    n = n + 1
  end
  if n == 0 then return false end
  for i = 1, n do
    if t[i] == nil then return false end
  end
  return true
end

local function deepmerge(t, p)
  for k, v in pairs(p) do
    if type(v) == "table" and type(t[k]) == "table"
       and not is_array(v) and not is_array(t[k]) then
      deepmerge(t[k], v)
    else
      t[k] = v
    end
  end
end
deepmerge(state, patch)

redis.call("SET", state_key, cjson.encode(state))
local version = redis.call("INCR", version_key)
return version
"""


class TikTokStateCacheRedis(TikTokStateCachePort):
    """Redis-backed state cache.

    The sync `redis.Redis` client handles persist-path writes
    (apply_patch is sync, runs in `to_thread`). Subscribers use the
    async `redis.asyncio` client from `utils.redis_client` because
    they live on the asyncio event loop. We accept two client
    references at construction time rather than re-creating clients
    here.
    """

    def __init__(
        self,
        *,
        sync_client: redis.Redis,
        async_client_getter: Callable[[], Optional[Any]],
        public_sanitizer: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> None:
        self._sync = sync_client
        # Lazy async-client getter so we don't capture a stale client
        # across uvicorn reloads. The framework already exposes this
        # pattern in `utils.redis_client.get_redis()`.
        self._async_getter = async_client_getter
        self._public_sanitizer = public_sanitizer
        # Preload the Lua script. `register_script` returns a callable
        # that uses `EVALSHA` when possible and falls back to `EVAL` on
        # NOSCRIPT — handles Redis restarts that flush the script cache.
        self._apply_patch_script = self._sync.register_script(_APPLY_PATCH_LUA)

    # ── reads ────────────────────────────────────────────────────────

    def get(self, handle: str) -> tuple[int, dict[str, Any]] | None:
        # Pipelined read for the (state, version) pair so a concurrent
        # apply_patch can't insert a discontinuity between the two
        # GETs. The script INCRs version AFTER setting state, so a
        # pipeline that reads state then version sees a consistent
        # `version >= state_version` — at worst the version is one
        # ahead of the state we read, which is acceptable: the
        # caller's contract is "this is the state at version V or
        # newer." Use `MULTI/EXEC` for stricter guarantees if needed.
        state_key = _STATE_PREFIX + handle
        version_key = _VERSION_PREFIX + handle
        pipe = self._sync.pipeline(transaction=False)
        pipe.get(state_key)
        pipe.get(version_key)
        state_raw, version_raw = pipe.execute()
        if state_raw is None or version_raw is None:
            return None
        try:
            state = json.loads(state_raw)
            version = int(version_raw)
        except (ValueError, TypeError):
            logger.exception("state-cache: malformed Redis entry for %s", handle)
            return None
        return version, state

    def list_versions(self) -> dict[str, int]:
        # SCAN over the version keys. Diagnostic path — not optimized.
        out: dict[str, int] = {}
        cursor = 0
        while True:
            cursor, keys = self._sync.scan(
                cursor=cursor,
                match=_VERSION_PREFIX + "*",
                count=200,
            )
            if keys:
                values = self._sync.mget(keys)
                for k, v in zip(keys, values):
                    if v is None:
                        continue
                    try:
                        handle = (
                            k.decode("utf-8") if isinstance(k, bytes) else k
                        )[len(_VERSION_PREFIX):]
                        out[handle] = int(v)
                    except (ValueError, TypeError):
                        continue
            if cursor == 0:
                break
        return out

    # ── writes ───────────────────────────────────────────────────────

    def set(self, handle: str, version: int, data: dict[str, Any]) -> None:
        state_key = _STATE_PREFIX + handle
        version_key = _VERSION_PREFIX + handle
        pipe = self._sync.pipeline(transaction=True)
        pipe.set(state_key, json.dumps(data))
        pipe.set(version_key, str(version))
        pipe.execute()

    def apply_patch(
        self,
        handle: str,
        patch: dict[str, Any],
    ) -> int | None:
        if not patch:
            return None

        # Apply atomically server-side. Returns the new version.
        state_key = _STATE_PREFIX + handle
        version_key = _VERSION_PREFIX + handle
        try:
            new_version = int(
                self._apply_patch_script(
                    keys=[state_key, version_key],
                    args=[json.dumps(patch)],
                )
            )
        except Exception:
            logger.exception(
                "state-cache: apply_patch script failed for %s", handle,
            )
            return None

        # Publish from Python (the Lua script doesn't publish — we
        # need the public sanitizer applied on the Python side).
        admin_delta = json.dumps(
            {"host": handle, "version": new_version, "patch": patch}
        )
        try:
            self._sync.publish(_DELTA_CHANNEL_ADMIN, admin_delta)
        except Exception:
            logger.exception("state-cache: admin publish failed for %s", handle)

        public_patch = self._sanitize_for_public(patch)
        if public_patch:
            public_delta = json.dumps(
                {"host": handle, "version": new_version, "patch": public_patch}
            )
            try:
                self._sync.publish(_DELTA_CHANNEL_PUBLIC, public_delta)
            except Exception:
                logger.exception(
                    "state-cache: public publish failed for %s", handle,
                )

        return new_version

    def clear(self) -> None:
        # SCAN+DEL the state and version key spaces. Not transactional
        # in the cluster-safe sense, but acceptable for the "admin reset
        # cache" use case which is rare and never racing with writes.
        for prefix in (_STATE_PREFIX, _VERSION_PREFIX):
            cursor = 0
            while True:
                cursor, keys = self._sync.scan(
                    cursor=cursor, match=prefix + "*", count=200,
                )
                if keys:
                    self._sync.delete(*keys)
                if cursor == 0:
                    break

    # ── subscribers ──────────────────────────────────────────────────

    async def subscribe(
        self,
        channel: Channel,
    ) -> AsyncIterator[dict[str, Any]]:
        if channel == CHANNEL_ADMIN:
            ch_name = _DELTA_CHANNEL_ADMIN
        elif channel == CHANNEL_PUBLIC:
            ch_name = _DELTA_CHANNEL_PUBLIC
        else:
            raise ValueError(f"unknown channel: {channel!r}")

        async_client = self._async_getter()
        if async_client is None:
            raise RuntimeError(
                "state-cache: Redis async client unavailable for subscribe()"
            )

        pubsub = async_client.pubsub()
        await pubsub.subscribe(ch_name)
        try:
            async for message in pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if raw is None:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(
                        "state-cache: dropped malformed delta on %s", ch_name,
                    )
                    continue
        finally:
            try:
                await pubsub.unsubscribe(ch_name)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except (AttributeError, Exception):
                # `aclose` was renamed across redis-py versions.
                try:
                    await pubsub.close()
                except Exception:
                    pass

    # ── internals ────────────────────────────────────────────────────

    def _sanitize_for_public(self, patch: dict[str, Any]) -> dict[str, Any]:
        if self._public_sanitizer is None:
            return patch
        return self._public_sanitizer(copy.deepcopy(patch))
