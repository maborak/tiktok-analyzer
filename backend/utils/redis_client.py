"""
Redis Client — Shared State for Multi-Worker Deployments

Provides an async Redis connection used by:
- Rate limiter (sliding window via sorted sets)
- CAPTCHA trust registry (keys with TTL)
- Guest product-check limits (INCR + TTL)
- Per-IP login failure tracking (INCR + TTL)

When REDIS_URL is empty or Redis is unreachable the module exposes
``get_redis() → None`` so callers can fall back to in-memory storage.

On post-startup connection loss, ``mark_redis_unavailable()`` sets the flag
to ``False`` and callers fall back immediately. The background health-check
loop (or ``try_reconnect()``) restores the flag when Redis comes back.
"""

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

from config import CONFIG

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None
_redis_available: bool = False
_redis_url: str = ""
_main_loop: Optional["asyncio.AbstractEventLoop"] = None


async def init_redis() -> None:
    """
    Initialise the module-level Redis connection.

    Call once at application startup (e.g. FastAPI lifespan).
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _redis_client, _redis_available, _redis_url, _main_loop

    _main_loop = asyncio.get_running_loop()
    url = CONFIG.get("REDIS_URL", "")
    if not url:
        logger.info("REDIS_URL not configured — using in-memory fallback")
        return

    _redis_url = url

    try:
        _redis_client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        # Verify connectivity
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis connected: %s", url.split("@")[-1] if "@" in url else url)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — falling back to in-memory", exc)
        _redis_client = None
        _redis_available = False


async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        _redis_available = False
        logger.info("Redis connection closed")


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Return the main event loop captured at init_redis() time.

    Used by sync code running in thread pools (e.g. hook handlers) to
    submit coroutines to the FastAPI event loop via run_coroutine_threadsafe.
    """
    return _main_loop


def get_redis() -> Optional[aioredis.Redis]:
    """
    Return the active Redis client, or ``None`` when Redis is not available.

    Callers must handle the ``None`` case by falling back to in-memory storage.
    """
    return _redis_client if _redis_available else None


def is_redis_available() -> bool:
    """Check whether a healthy Redis connection exists."""
    return _redis_available


def mark_redis_unavailable() -> None:
    """
    Mark Redis as unavailable after a connection failure.

    Called by consumers (rate limiter, CAPTCHA, guest limits) when a Redis
    command raises a connection error. This ensures subsequent calls to
    ``get_redis()`` return ``None`` immediately instead of attempting
    commands on a broken connection.
    """
    global _redis_available
    if _redis_available:
        _redis_available = False
        logger.warning("Redis marked unavailable — falling back to in-memory")


async def try_reconnect() -> bool:
    """
    Attempt to re-establish Redis connectivity.

    Call from a periodic background task (e.g. health-check loop).
    Returns True if reconnection succeeded.
    """
    global _redis_client, _redis_available

    if _redis_available:
        return True

    if not _redis_url:
        return False

    try:
        if _redis_client is None:
            _redis_client = aioredis.from_url(
                _redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis reconnected successfully")
        return True
    except Exception as exc:
        logger.debug("Redis reconnect attempt failed: %s", exc)
        return False
