"""
Guest Product Check Limits

Tracks how many times an unauthenticated IP has used POST /products/add
for products that do not already exist in the database.
Guests are allowed GUEST_CHECK_MAX_ATTEMPTS free checks per GUEST_CHECK_TTL_SECONDS window.

Defaults: 5 checks per 24 hours per IP.

Config keys (backend/config.py / .env):
  PHOVEU_BACKEND_GUEST_CHECK_MAX_ATTEMPTS  (default: 5)
  PHOVEU_BACKEND_GUEST_CHECK_TTL_SECONDS   (default: 86400)

Storage: Redis when available, in-memory per-process fallback.
"""

import asyncio
import time
import logging
from typing import Dict, Tuple

from config import CONFIG
from utils.redis_client import get_redis, mark_redis_unavailable

logger = logging.getLogger(__name__)

# In-memory fallback (per-process only)
# Key: client IP, Value: (window_start_timestamp, attempt_count)
_mem_storage: Dict[str, Tuple[float, int]] = {}

_REDIS_PREFIX = "guest_limit:"


async def _redis_check_and_record(ip: str, ttl_seconds: int, max_attempts: int) -> bool:
    """Atomically check and increment via Redis INCR + EXPIRE."""
    r = get_redis()
    key = f"{_REDIS_PREFIX}{ip}"

    count = await r.incr(key)
    if count == 1:
        # First request in this window — set expiry
        await r.expire(key, ttl_seconds)

    if count > max_attempts:
        logger.info(
            "Guest limit reached for IP=%s (%d/%d uses, Redis)",
            ip, count, max_attempts,
        )
        return False

    logger.info(
        "Guest check recorded for IP=%s (%d/%d uses, TTL=%ds, Redis)",
        ip, count, max_attempts, ttl_seconds,
    )
    return True


def _mem_check_and_record(ip: str, ttl_seconds: int, max_attempts: int) -> bool:
    """In-memory fallback (per-process only)."""
    now = time.time()

    if ip in _mem_storage:
        window_start, count = _mem_storage[ip]
        if now - window_start < ttl_seconds:
            if count >= max_attempts:
                logger.info(
                    "Guest limit reached for IP=%s (%d/%d uses, window started %.0fs ago)",
                    ip, count, max_attempts, now - window_start,
                )
                return False
            _mem_storage[ip] = (window_start, count + 1)
            logger.info(
                "Guest check recorded for IP=%s (%d/%d uses, TTL=%ds)",
                ip, count + 1, max_attempts, ttl_seconds,
            )
            return True
        del _mem_storage[ip]

    _mem_storage[ip] = (now, 1)
    logger.info("Guest check recorded for IP=%s (1/%d uses, TTL=%ds)", ip, max_attempts, ttl_seconds)
    return True


async def async_check_and_record_guest_attempt(ip: str) -> bool:
    """
    Async version — prefers Redis, falls back to in-memory.

    Returns True (and records the attempt) if the IP has not yet exhausted
    GUEST_CHECK_MAX_ATTEMPTS within the TTL window.
    """
    ttl_seconds: int = CONFIG.get("GUEST_CHECK_TTL_SECONDS", 86400)
    max_attempts: int = CONFIG.get("GUEST_CHECK_MAX_ATTEMPTS", 5)

    r = get_redis()
    if r is not None:
        try:
            return await _redis_check_and_record(ip, ttl_seconds, max_attempts)
        except Exception as exc:
            logger.warning("Redis guest-limit error (%s) — falling back to in-memory", exc)
            mark_redis_unavailable()
    return _mem_check_and_record(ip, ttl_seconds, max_attempts)


def check_and_record_guest_attempt(ip: str) -> bool:
    """
    Sync wrapper — keeps the existing call-site contract intact.

    When called from an async context (FastAPI route), the event loop is
    already running so we schedule the coroutine. When called from a sync
    context, we fall back to in-memory directly.
    """
    ttl_seconds: int = CONFIG.get("GUEST_CHECK_TTL_SECONDS", 86400)
    max_attempts: int = CONFIG.get("GUEST_CHECK_MAX_ATTEMPTS", 5)

    r = get_redis()
    if r is not None:
        # We're inside an async event loop (FastAPI) — cannot use asyncio.run().
        # Return the in-memory result for now; callers should migrate to the async version.
        # This branch only triggers if someone calls the sync API from sync code.
        try:
            loop = asyncio.get_running_loop()
            # Running inside an event loop — caller should use async version
            logger.debug("Sync check_and_record_guest_attempt called inside event loop; using in-memory fallback. Migrate to async_check_and_record_guest_attempt.")
            return _mem_check_and_record(ip, ttl_seconds, max_attempts)
        except RuntimeError:
            # No event loop — safe to run synchronously
            return asyncio.run(_redis_check_and_record(ip, ttl_seconds, max_attempts))

    return _mem_check_and_record(ip, ttl_seconds, max_attempts)


async def async_get_remaining_guest_attempts(ip: str) -> Tuple[int, int]:
    """
    Read-only query: how many guest attempts remain for this IP.

    Returns (remaining, max_attempts) without consuming an attempt.
    """
    ttl_seconds: int = CONFIG.get("GUEST_CHECK_TTL_SECONDS", 86400)
    max_attempts: int = CONFIG.get("GUEST_CHECK_MAX_ATTEMPTS", 5)

    r = get_redis()
    if r is not None:
        try:
            key = f"{_REDIS_PREFIX}{ip}"
            val = await r.get(key)
            if val is not None:
                count = int(val)
                return max(0, max_attempts - count), max_attempts
            return max_attempts, max_attempts
        except Exception as exc:
            logger.warning("Redis guest-limit read error (%s) — falling back to in-memory", exc)
            mark_redis_unavailable()

    # In-memory fallback
    now = time.time()
    if ip in _mem_storage:
        window_start, count = _mem_storage[ip]
        if now - window_start < ttl_seconds:
            return max(0, max_attempts - count), max_attempts
    return max_attempts, max_attempts


def get_remaining_guest_attempts(ip: str) -> Tuple[int, int]:
    """
    Sync read-only query (backward-compatible).

    Returns (remaining, max_attempts) without consuming an attempt.
    """
    ttl_seconds: int = CONFIG.get("GUEST_CHECK_TTL_SECONDS", 86400)
    max_attempts: int = CONFIG.get("GUEST_CHECK_MAX_ATTEMPTS", 5)
    now = time.time()

    # For sync callers, use in-memory (Redis needs async)
    if ip in _mem_storage:
        window_start, count = _mem_storage[ip]
        if now - window_start < ttl_seconds:
            return max(0, max_attempts - count), max_attempts
    return max_attempts, max_attempts
