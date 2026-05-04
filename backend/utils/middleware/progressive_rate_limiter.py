"""
Progressive Rate Limiter

Generic escalation-ladder rate limiter with configurable wait times
and optional CAPTCHA gates. Strategy defined as a comma-separated string:
  "1,5,30,C,C60" → wait 1s, wait 5s, wait 30s, captcha only, wait 60s + captcha
Last tier repeats forever.

Storage: Redis JSON values with 24h TTL, in-memory dict fallback.
Key space: prl:{scope}:{identifier}
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any

from config import CONFIG
from utils.redis_client import get_redis, mark_redis_unavailable

logger = logging.getLogger(__name__)

_mem_storage: Dict[str, Dict[str, Any]] = {}


@dataclass
class RateLimitTier:
    wait_seconds: int
    requires_captcha: bool


@dataclass
class ProgressiveRateLimitResult:
    allowed: bool
    attempt: int
    retry_after: int
    requires_captcha: bool
    captcha_provider: Optional[str]
    tier_index: int
    total_tiers: int

    def to_error_dict(self) -> dict:
        """Format for HTTP error response. Uses `captcha_required` (not `requires_captcha`)
        to match the existing frontend login form convention."""
        return {
            "retry_after": self.retry_after,
            "captcha_required": self.requires_captcha,
            "captcha_provider": self.captcha_provider,
            "attempt": self.attempt,
        }

    def to_headers(self) -> Dict[str, str]:
        return {
            "X-PRL-Attempt": str(self.attempt),
            "X-PRL-RetryAfter": str(self.retry_after),
            "X-PRL-RequiresCaptcha": str(self.requires_captcha).lower(),
        }


def parse_strategy(strategy: str) -> List[RateLimitTier]:
    tiers = []
    for token in strategy.split(","):
        token = token.strip()
        if not token:
            continue
        if token.upper().startswith("C"):
            rest = token[1:]
            wait = int(rest) if rest else 0
            tiers.append(RateLimitTier(wait_seconds=wait, requires_captcha=True))
        else:
            tiers.append(RateLimitTier(wait_seconds=int(token), requires_captcha=False))
    return tiers


def _get_captcha_provider() -> Optional[str]:
    ct = CONFIG.get("CAPTCHA_TYPE", "none")
    return ct if ct != "none" else None


def _make_key(scope: str, identifier: str) -> str:
    return f"prl:{scope}:{identifier}"


async def _redis_get_state(key: str) -> Optional[Dict[str, Any]]:
    r = get_redis()
    if not r:
        return None
    try:
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
        return None
    except Exception as exc:
        logger.warning("Redis read error for PRL (%s): %s", key, exc)
        mark_redis_unavailable()
        return None


async def _redis_set_state(key: str, state: Dict[str, Any], ttl: int = 86400) -> bool:
    r = get_redis()
    if not r:
        return False
    try:
        await r.set(key, json.dumps(state), ex=ttl)
        return True
    except Exception as exc:
        logger.warning("Redis write error for PRL (%s): %s", key, exc)
        mark_redis_unavailable()
        return False


async def _redis_delete(key: str) -> bool:
    r = get_redis()
    if not r:
        return False
    try:
        await r.delete(key)
        return True
    except Exception as exc:
        logger.warning("Redis delete error for PRL (%s): %s", key, exc)
        mark_redis_unavailable()
        return False


async def check_progressive_limit(
    scope: str, identifier: str, strategy: str
) -> ProgressiveRateLimitResult:
    tiers = parse_strategy(strategy)
    if not tiers:
        return ProgressiveRateLimitResult(
            allowed=True, attempt=0, retry_after=0,
            requires_captcha=False, captcha_provider=None,
            tier_index=0, total_tiers=0,
        )

    key = _make_key(scope, identifier)
    now = time.time()

    state = await _redis_get_state(key)
    if state is None:
        state = _mem_storage.get(key)

    count = state.get("count", 0) if state else 0
    last_attempt = state.get("last_attempt_at", 0.0) if state else 0.0

    if count == 0:
        return ProgressiveRateLimitResult(
            allowed=True, attempt=1, retry_after=0,
            requires_captcha=False, captcha_provider=None,
            tier_index=0, total_tiers=len(tiers),
        )

    tier_idx = min(count - 1, len(tiers) - 1)
    tier = tiers[tier_idx]

    elapsed = now - last_attempt
    remaining = tier.wait_seconds - int(elapsed)

    if remaining > 0:
        return ProgressiveRateLimitResult(
            allowed=False, attempt=count + 1, retry_after=remaining,
            requires_captcha=tier.requires_captcha,
            captcha_provider=_get_captcha_provider() if tier.requires_captcha else None,
            tier_index=tier_idx, total_tiers=len(tiers),
        )

    return ProgressiveRateLimitResult(
        allowed=True, attempt=count + 1, retry_after=0,
        requires_captcha=tier.requires_captcha,
        captcha_provider=_get_captcha_provider() if tier.requires_captcha else None,
        tier_index=tier_idx, total_tiers=len(tiers),
    )


async def record_attempt(scope: str, identifier: str, strategy: str = "") -> ProgressiveRateLimitResult:
    key = _make_key(scope, identifier)
    now = time.time()

    state = await _redis_get_state(key)
    if state is None:
        state = _mem_storage.get(key)

    count = (state.get("count", 0) if state else 0) + 1
    new_state = {"count": count, "last_attempt_at": now}

    if not await _redis_set_state(key, new_state):
        _mem_storage[key] = new_state

    # Return the next tier's state so callers can include it in the response
    tiers = parse_strategy(strategy) if strategy else []
    if tiers:
        tier_idx = min(count - 1, len(tiers) - 1)
        tier = tiers[tier_idx]
        return ProgressiveRateLimitResult(
            allowed=False, attempt=count, retry_after=tier.wait_seconds,
            requires_captcha=tier.requires_captcha,
            captcha_provider=_get_captcha_provider() if tier.requires_captcha else None,
            tier_index=tier_idx, total_tiers=len(tiers),
        )

    return ProgressiveRateLimitResult(
        allowed=False, attempt=count, retry_after=0,
        requires_captcha=False, captcha_provider=None,
        tier_index=0, total_tiers=0,
    )


async def reset_attempts(scope: str, identifier: str) -> None:
    key = _make_key(scope, identifier)
    if not await _redis_delete(key):
        _mem_storage.pop(key, None)
