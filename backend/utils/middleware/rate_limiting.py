"""
Rate Limiting Middleware

Implements IP-based rate limiting with sliding window algorithm.
Supports per-endpoint configuration and bypass keys for testing.

Storage: Redis sorted sets when available, in-memory dict fallback.
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from typing import Dict, Callable
import time
import fnmatch
import uuid
from collections import defaultdict

from config import CONFIG
from utils.request import get_client_ip
from utils.redis_client import get_redis, mark_redis_unavailable

import logging

logger = logging.getLogger(__name__)

# Fallback in-memory storage (per-process only — used when Redis is unavailable)
# Key: "ip:path", Value: list of request timestamps
_mem_storage: Dict[str, list] = defaultdict(list)
_MEM_MAX_KEYS = 10_000  # Eviction cap to prevent unbounded memory growth


async def _redis_check_rate_limit(key: str, window: int, max_requests: int, now: float) -> tuple:
    """
    Check and record a request using Redis sorted sets.

    Returns (allowed: bool, current_count: int, oldest_ts: float|None).
    """
    r = get_redis()
    window_start = now - window

    pipe = r.pipeline()
    # Remove expired entries
    pipe.zremrangebyscore(key, "-inf", window_start)
    # Count remaining entries
    pipe.zcard(key)
    # Add new entry (unique member via uuid to avoid dedup)
    pipe.zadd(key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
    # Set key expiry slightly beyond the window to auto-cleanup
    pipe.expire(key, window + 10)
    results = await pipe.execute()

    current_count = results[1]  # ZCARD result (before adding current)

    if current_count >= max_requests:
        # Over limit — remove the entry we just added
        # (we added optimistically; undo it)
        await r.zremrangebyscore(key, now, now + 0.001)
        # Get the oldest entry for retry-after calculation
        oldest = await r.zrange(key, 0, 0, withscores=True)
        oldest_ts = oldest[0][1] if oldest else now
        return False, current_count, oldest_ts

    return True, current_count + 1, None


def _mem_check_rate_limit(key: str, window: int, max_requests: int, now: float) -> tuple:
    """
    In-memory fallback: same sliding-window logic.

    Returns (allowed: bool, current_count: int, oldest_ts: float|None).
    """
    # Evict oldest keys if storage exceeds cap (prevent unbounded growth)
    if len(_mem_storage) > _MEM_MAX_KEYS:
        keys_to_remove = list(_mem_storage.keys())[:_MEM_MAX_KEYS // 5]
        for k in keys_to_remove:
            del _mem_storage[k]

    # Clean expired entries
    _mem_storage[key] = [
        ts for ts in _mem_storage[key]
        if now - ts < window
    ]

    if len(_mem_storage[key]) >= max_requests:
        oldest_ts = _mem_storage[key][0] if _mem_storage[key] else now
        return False, len(_mem_storage[key]), oldest_ts

    _mem_storage[key].append(now)
    return True, len(_mem_storage[key]), None


def create_rate_limiting_middleware(
    rate_limit_enabled: bool,
    rate_limit_bypass_key: str = None,
    test_mode: bool = False
) -> Callable:
    """
    Create rate limiting middleware function

    Args:
        rate_limit_enabled: Whether rate limiting is enabled
        rate_limit_bypass_key: Optional bypass key for testing
        test_mode: Whether test mode is enabled (disables rate limiting)

    Returns:
        Middleware function that can be registered with FastAPI app
    """

    async def rate_limiting_middleware(request: Request, call_next):
        """Rate limiting middleware"""
        # Check if test mode is enabled
        if test_mode:
            response = await call_next(request)
            return response

        # Check if rate limiting is enabled
        if not rate_limit_enabled:
            response = await call_next(request)
            return response

        # Check for bypass key
        if rate_limit_bypass_key and request.headers.get("X-Rate-Limit-Bypass") == rate_limit_bypass_key:
            response = await call_next(request)
            return response

        # Never rate-limit OPTIONS preflight — it must reach CORSMiddleware and return 200
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response

        # Get client IP (handles proxy headers: X-Forwarded-For, X-Real-IP)
        client_ip = get_client_ip(request) or "unknown"

        # Skip rate limiting for excluded paths (Swagger UI, docs, health checks, etc.)
        path = request.url.path
        excluded_paths = CONFIG.get("RATE_LIMIT_EXCLUDED_PATHS", [])
        if any(path == excluded or path.startswith(excluded) for excluded in excluded_paths):
            response = await call_next(request)
            return response

        # Skip rate limiting for bypass paths (supports exact match and wildcard patterns)
        bypass_paths = CONFIG.get("RATE_LIMIT_BYPASS_PATHS", [])
        for bypass_path in bypass_paths:
            if path == bypass_path:
                response = await call_next(request)
                return response
            elif '*' in bypass_path or '?' in bypass_path:
                if fnmatch.fnmatch(path, bypass_path):
                    response = await call_next(request)
                    return response

        # Get rate limits from config
        rate_limits = CONFIG.get("RATE_LIMITS", {})

        # Check if endpoint has rate limiting (exact match or prefix match)
        limit_config = None
        matched_path = None
        for rate_limit_path, config in rate_limits.items():
            if path == rate_limit_path:
                limit_config = config
                matched_path = rate_limit_path
                break
            elif rate_limit_path.endswith("/") and path.startswith(rate_limit_path):
                limit_config = config
                matched_path = rate_limit_path
                break

        # Default catch-all: apply global rate limit to any unmatched path
        if not limit_config:
            limit_config = {
                "max_requests": CONFIG.get("RATE_LIMIT_REQUESTS", 60),
                "window": CONFIG.get("RATE_LIMIT_WINDOW", 60),
            }
            matched_path = "_default"

        current_time = time.time()
        window = limit_config["window"]
        max_requests = limit_config["max_requests"]

        # Unique key per IP + rate-limit rule
        rate_limit_key = f"{client_ip}:{matched_path}"

        r = get_redis()
        if r is not None:
            redis_key = f"rl:{rate_limit_key}"
            try:
                allowed, count, oldest_ts = await _redis_check_rate_limit(
                    redis_key, window, max_requests, current_time
                )
            except Exception as exc:
                logger.warning("Redis rate-limit error (%s) — falling back to in-memory", exc)
                mark_redis_unavailable()
                allowed, count, oldest_ts = _mem_check_rate_limit(
                    rate_limit_key, window, max_requests, current_time
                )
        else:
            allowed, count, oldest_ts = _mem_check_rate_limit(
                rate_limit_key, window, max_requests, current_time
            )

        if not allowed:
            retry_after = int(window - (current_time - oldest_ts)) if oldest_ts else 0
            retry_after = max(0, retry_after)

            logger.warning(
                "Rate limited: ip=%s path=%s matched=%s count=%d/%d storage=%s",
                client_ip, path, matched_path, count, max_requests,
                "redis" if r is not None else "memory"
            )

            error_response = {
                "detail": "Too many requests. Please try again later.",
                "retry_after": retry_after
            }

            debug_mode_enabled = CONFIG.get("DEBUG_MODE", False)
            if debug_mode_enabled:
                error_response["debug"] = {
                    "client_ip": client_ip,
                    "endpoint": path,
                    "current_requests": count,
                    "max_requests": max_requests,
                    "window_seconds": window,
                    "retry_after_seconds": retry_after,
                    "rate_limit_config": limit_config,
                    "storage": "redis" if r is not None else "memory",
                }

            # Build CORS headers so the browser doesn't block the 429
            cors_headers = {
                "Retry-After": str(retry_after),
            }
            origin = request.headers.get("origin")
            if origin:
                allowed_origins = CONFIG.get("CORS_ORIGINS", ["*"])
                if "*" in allowed_origins or origin in allowed_origins:
                    cors_headers["access-control-allow-origin"] = origin if "*" not in allowed_origins else "*"
                    if CONFIG.get("CORS_ALLOW_CREDENTIALS", False) and "*" not in allowed_origins:
                        cors_headers["access-control-allow-credentials"] = "true"

            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=error_response,
                headers=cors_headers,
            )

        response = await call_next(request)
        return response

    return rate_limiting_middleware
