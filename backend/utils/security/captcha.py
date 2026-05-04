"""
Configurable CAPTCHA Validation

Supports multiple CAPTCHA providers:
- none: No validation (development)
- recaptcha_v3: Google reCAPTCHA v3
- turnstile: Cloudflare Turnstile

Trust registry: Redis when available, in-memory fallback.
"""

import logging
import httpx
import time
from typing import Optional, Dict

from config import CONFIG
from utils.redis_client import get_redis, mark_redis_unavailable

logger = logging.getLogger(__name__)


class CaptchaValidator:
    """CAPTCHA validation with support for multiple providers and trusted sessions"""

    def __init__(self):
        self.captcha_type = CONFIG.get("CAPTCHA_TYPE", "none").lower()
        self.recaptcha_secret = CONFIG.get("RECAPTCHA_V3_SECRET_KEY", "")
        self.turnstile_secret = CONFIG.get("TURNSTILE_SECRET_KEY", "")
        self.trust_window = CONFIG.get("CAPTCHA_TRUST_WINDOW", 300)
        # In-memory fallback for trust registry
        self._mem_trust: Dict[str, float] = {}

    def _get_trust_key(self, identifier: Optional[str], remote_ip: Optional[str]) -> Optional[str]:
        """Generate a unique key for tracking trust"""
        if identifier:
            return f"user_{identifier}"
        if remote_ip:
            return f"ip_{remote_ip}"
        return None

    async def _check_trust(self, trust_key: str) -> bool:
        """Check if a trust entry exists (Redis or in-memory)."""
        r = get_redis()
        if r is not None:
            try:
                redis_key = f"captcha_trust:{trust_key}"
                val = await r.get(redis_key)
                return val is not None
            except Exception as exc:
                logger.warning("Redis CAPTCHA trust check error (%s) — falling back to in-memory", exc)
                mark_redis_unavailable()

        # In-memory fallback
        if trust_key in self._mem_trust:
            if time.time() - self._mem_trust[trust_key] < self.trust_window:
                return True
            del self._mem_trust[trust_key]
        return False

    async def _grant_trust(self, trust_key: str) -> None:
        """Record a trust entry with TTL (Redis or in-memory)."""
        r = get_redis()
        if r is not None:
            try:
                redis_key = f"captcha_trust:{trust_key}"
                await r.set(redis_key, "1", ex=self.trust_window)
                return
            except Exception as exc:
                logger.warning("Redis CAPTCHA trust grant error (%s) — falling back to in-memory", exc)
                mark_redis_unavailable()

        # In-memory fallback
        self._mem_trust[trust_key] = time.time()

    async def validate(self, token: str, remote_ip: Optional[str] = None, identifier: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        Validate CAPTCHA token with trusted session support.

        Args:
            token: CAPTCHA token from client
            remote_ip: Optional IP address of the user
            identifier: Optional unique identifier (user_id or session_id) for trust tracking

        Returns:
            Tuple of (is_valid, error_message)
        """
        ip_info = f" (IP: {remote_ip})" if remote_ip else ""
        trust_key = self._get_trust_key(identifier, remote_ip)

        if self.captcha_type == "none":
            logger.info("CAPTCHA validation disabled (type=none)%s", ip_info)
            return True, None

        # Check for trusted session
        if trust_key and await self._check_trust(trust_key):
            logger.info("CAPTCHA bypassed: Trusted session active for %s%s", trust_key, ip_info)
            return True, None

        if not token:
            logger.info("CAPTCHA validation failed: token missing%s", ip_info)
            return False, "CAPTCHA token is required"

        # Route to appropriate provider
        success = False
        error = None

        if self.captcha_type == "recaptcha_v3":
            if not self.recaptcha_secret:
                logger.warning("reCAPTCHA v3 configured but RECAPTCHA_V3_SECRET_KEY missing%s", ip_info)
                return False, "CAPTCHA validation not properly configured"
            logger.info("Validating reCAPTCHA v3 token%s", ip_info)
            success, error = await self._validate_recaptcha_v3(token, remote_ip)
        elif self.captcha_type == "turnstile":
            if not self.turnstile_secret:
                logger.warning("Turnstile configured but TURNSTILE_SECRET_KEY missing%s", ip_info)
                return False, "CAPTCHA validation not properly configured"
            logger.info("Validating Turnstile token%s", ip_info)
            success, error = await self._validate_turnstile(token, remote_ip)
        else:
            logger.error("Unknown CAPTCHA type: %s%s", self.captcha_type, ip_info)
            return False, f"Unknown CAPTCHA provider: {self.captcha_type}"

        if success and trust_key:
            await self._grant_trust(trust_key)
            logger.info("CAPTCHA validated and trust granted for %s%s", trust_key, ip_info)

        return success, error

    async def _validate_recaptcha_v3(self, token: str, remote_ip: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Validate Google reCAPTCHA v3 token"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                data = {
                    "secret": self.recaptcha_secret,
                    "response": token
                }
                if remote_ip:
                    data["remoteip"] = remote_ip

                response = await client.post(
                    "https://www.google.com/recaptcha/api/siteverify",
                    data=data
                )
                response.raise_for_status()
                result = response.json()

                if result.get("success"):
                    score = result.get("score", 0.0)
                    threshold = CONFIG.get("RECAPTCHA_V3_THRESHOLD", 0.5)

                    if score < threshold:
                        logger.info("reCAPTCHA v3 score too low: %.2f (threshold: %.2f)", score, threshold)
                        return False, "CAPTCHA verification failed"

                    logger.info("reCAPTCHA v3 validation successful (score: %.2f, threshold: %.2f)", score, threshold)
                    return True, None
                else:
                    error_codes = result.get("error-codes", [])
                    logger.info("reCAPTCHA v3 validation failed: error_codes=%s", error_codes)
                    return False, "CAPTCHA verification failed"

        except httpx.TimeoutException:
            logger.error("reCAPTCHA v3 validation timeout")
            return False, "CAPTCHA validation timeout"
        except Exception as e:
            logger.error("reCAPTCHA v3 validation error: %s", e)
            return False, "CAPTCHA validation error"

    async def _validate_turnstile(self, token: str, remote_ip: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Validate Cloudflare Turnstile token"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                data = {
                    "secret": self.turnstile_secret,
                    "response": token
                }
                if remote_ip:
                    data["remoteip"] = remote_ip

                response = await client.post(
                    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                    data=data
                )
                response.raise_for_status()
                result = response.json()

                if result.get("success"):
                    logger.info("Turnstile validation successful")
                    return True, None
                else:
                    error_codes = result.get("error-codes", [])
                    logger.info("Turnstile validation failed: error_codes=%s", error_codes)
                    return False, "CAPTCHA verification failed"

        except httpx.TimeoutException:
            logger.error("Turnstile validation timeout")
            return False, "CAPTCHA validation timeout"
        except Exception as e:
            logger.error("Turnstile validation error: %s", e)
            return False, "CAPTCHA validation error"


# Global validator instance
_captcha_validator: Optional[CaptchaValidator] = None


def get_captcha_validator() -> CaptchaValidator:
    """Get the global CAPTCHA validator instance"""
    global _captcha_validator
    if _captcha_validator is None:
        _captcha_validator = CaptchaValidator()
    return _captcha_validator


async def validate_captcha(token: str, remote_ip: Optional[str] = None, identifier: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    Convenience function to validate CAPTCHA token.

    Args:
        token: CAPTCHA token from client
        remote_ip: Optional IP address of the user
        identifier: Optional unique identifier for trust tracking

    Returns:
        Tuple of (is_valid, error_message)
    """
    validator = get_captcha_validator()
    return await validator.validate(token, remote_ip, identifier)
