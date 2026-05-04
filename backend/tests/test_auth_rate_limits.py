"""
Red-team security test suite for authentication rate limiting and progressive delay.

Tests the intersection of:
- IP-based rate limiting middleware (sliding window)
- Per-account progressive delay (attempts 4+ → exponential backoff, cap 300s)
- Rate limit bypass vectors (header spoofing, worker scatter)
- Endpoint-specific rate limit gaps

Methodology: OWASP ASVS V2.1.3, V4.2.1, OWASP A07:2021, CWE-645 (no hard lockout).
All tests run against the live API. No mocks.

Severity policy:
- HIGH findings → pytest.fail() (test goes RED, blocks CI)
- MEDIUM/LOW findings → findings_collector only (test passes, printed in summary)
"""
import pytest
import httpx
import asyncio
import time
import json
import sys
import os
from typing import Dict, Any, Optional, List

_test_dir = os.path.dirname(os.path.abspath(__file__))
if _test_dir not in sys.path:
    sys.path.insert(0, _test_dir)

import conftest

rand_tag = conftest.rand_tag
mask_secret = conftest.mask_secret
build_curl = conftest.build_curl
fail_with_details = conftest.fail_with_details
parse_json_safe = conftest.parse_json_safe
findings_collector = conftest.findings_collector
API_BASE_URL = conftest.API_BASE_URL
assert_no_stacktrace = conftest.assert_no_stacktrace
assert_status_not_500 = conftest.assert_status_not_500
RATE_LIMIT_BYPASS_KEY = conftest.RATE_LIMIT_BYPASS_KEY


# ============================================================================
# HELPERS
# ============================================================================

def _bypass_headers() -> dict:
    """Return rate limit bypass header if a bypass key is configured."""
    if RATE_LIMIT_BYPASS_KEY:
        return {"X-Rate-Limit-Bypass": RATE_LIMIT_BYPASS_KEY}
    return {}


async def register_user(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    """Register a user and wait for DB commit."""
    resp = await client.post("/auth/register", json={"email": email, "password": password})
    await asyncio.sleep(0.5)
    return resp


async def do_login(client: httpx.AsyncClient, email: str, password: str, **extra_headers) -> httpx.Response:
    """Fire a login request, optionally with extra headers."""
    headers = dict(extra_headers) if extra_headers else {}
    return await client.post("/auth/login", json={"email": email, "password": password}, headers=headers)


async def rapid_fire_login(
    client: httpx.AsyncClient,
    email: str,
    password: str,
    count: int,
    delay: float = 0.05,
    **extra_headers,
) -> List[httpx.Response]:
    """Send `count` login requests in rapid succession. Returns all responses."""
    responses = []
    for i in range(count):
        resp = await do_login(client, email, f"{password}_attempt_{i}", **extra_headers)
        responses.append(resp)
        if delay > 0:
            await asyncio.sleep(delay)
    return responses


# ============================================================================
# TEST GROUP RL: Rate Limiting on Auth Endpoints
# ============================================================================

class TestLoginRateLimiting:
    """
    Red-team tests for rate limiting on /auth/login.

    /auth/login MUST have a dedicated rate limit entry in CONFIG["RATE_LIMITS"].
    Without it the middleware passes all requests through with zero throttling.
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_login_has_rate_limit(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RL.1 [HIGH]: Verify /auth/login is rate-limited at all.

        Attack: send 80 rapid login attempts. With UVI_WORKERS=5 and limit=10/60s,
        each worker sees ~16 requests — enough to exceed the per-worker limit.
        Expected: at least one 429 response.
        """
        email = f"rl1+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        responses = await rapid_fire_login(http_client, email, password, count=80, delay=0.01)

        status_codes = [r.status_code for r in responses]
        got_429 = 429 in status_codes

        if not got_429:
            pytest.fail(
                f"[HIGH] No rate limiting on /auth/login after {len(responses)} rapid requests.\n"
                f"Status code counts: 401={status_codes.count(401)}, "
                f"429={status_codes.count(429)}\n"
                f"Expected at least one 429 (rate limit).\n"
                f"Fix: add '/auth/login' to CONFIG['RATE_LIMITS'] in config.py."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_token_endpoint_rate_limit(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RL.2 [HIGH]: Verify /auth/token IS rate-limited (config: 20/60s).

        Attack: send 150 rapid OAuth2 token requests with wrong credentials.
        With UVI_WORKERS=5 and limit=20/60s, each worker sees ~30 requests —
        enough to trigger on at least one worker.
        """
        email = f"rl2+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        responses = []
        for i in range(150):
            resp = await http_client.post(
                "/auth/token",
                data={"username": email, "password": f"wrong_{i}"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            responses.append(resp)
            await asyncio.sleep(0.01)

        status_codes = [r.status_code for r in responses]
        got_429 = 429 in status_codes

        if not got_429:
            pytest.fail(
                f"[HIGH] No rate limiting on /auth/token after {len(responses)} rapid requests.\n"
                f"Status code counts: 401={status_codes.count(401)}, "
                f"422={status_codes.count(422)}, 429={status_codes.count(429)}\n"
                f"/auth/token has a RATE_LIMITS entry (20/60s) but 429 was never returned.\n"
                f"Verify the middleware is correctly wired in api_main.py."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_register_rate_limit(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RL.3 [HIGH]: Verify /auth/register is rate-limited (config: 5/60s).

        Attack: send 40 rapid registration attempts.
        With UVI_WORKERS=5 and limit=5/60s, each worker sees ~8 requests —
        enough to exceed the per-worker limit. If none return 429,
        rate limiting is broken.
        """
        responses = []
        for i in range(40):
            resp = await http_client.post("/auth/register", json={
                "email": f"rl3_{test_tag}_{i}@mailrbp.com",
                "password": f"P@ssw0rd!_{test_tag}",
            })
            responses.append(resp)
            await asyncio.sleep(0.01)

        status_codes = [r.status_code for r in responses]
        got_429 = 429 in status_codes

        if not got_429:
            pytest.fail(
                f"[HIGH] No rate limiting on /auth/register after {len(responses)} rapid requests.\n"
                f"Status code counts: 200={status_codes.count(200)}, "
                f"422={status_codes.count(422)}, 429={status_codes.count(429)}\n"
                f"Config says 5/60s but 429 was never returned.\n"
                f"With {len(responses)} requests across 5 workers (~8/worker), "
                f"at least one worker should have exceeded the limit.\n"
                f"This allows mass account creation for spam or enumeration."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_password_reset_rate_limit(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RL.4 [MEDIUM]: Verify /auth/request-password-reset is rate-limited (config: 5/300s).

        Attack: send 40 rapid password reset requests.
        With 5 workers and limit 5/300s, each worker sees ~8 — enough to trigger.
        Expected: 429 fires before all 40 complete.
        """
        responses = []
        for i in range(40):
            resp = await http_client.post("/auth/request-password-reset", json={
                "email": f"rl4_{test_tag}_{i}@mailrbp.com",
            })
            responses.append(resp)
            await asyncio.sleep(0.02)

        status_codes = [r.status_code for r in responses]
        got_429 = 429 in status_codes

        if not got_429:
            findings_collector.add_finding(
                "/auth/request-password-reset",
                "No rate limiting detected on password reset after 40 rapid requests",
                "Medium",
                f"All status codes: {status_codes}",
                build_curl("POST", f"{API_BASE_URL}/auth/request-password-reset", None, None,
                           {"email": "victim@example.com"}),
                "/auth/request-password-reset config says 10/300s but 429 was never returned. "
                "This allows email bombing and password reset token enumeration.",
                asvs_control="V2.1.3",
                owasp_category="A07",
            )


# ============================================================================
# TEST GROUP PD: Progressive Delay (replaces hard account lockout)
# ============================================================================

class TestProgressiveDelay:
    """
    Red-team tests for the progressive delay mechanism.

    Progressive delay formula (per-account):
      Attempts 1-3: no delay
      Attempt 4+:  min(2^(attempts-3), 300) seconds

    The account is NEVER hard-locked. All failures return 401 with a generic
    "Invalid email or password" message — no 423, no timing info, no enumeration.
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_no_hard_lockout_after_many_failures(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        PD.1 [HIGH]: Verify hard lockout (423) is GONE — no amount of failures
        should produce a 423 status code.

        Attack: send 10 rapid failed logins. None should return 423.
        With progressive delay, all failures return 401 (generic message).
        """
        email = f"pd1+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # Bypass rate limiter — this test validates auth behavior, not rate limiting
        bypass = _bypass_headers()
        responses = await rapid_fire_login(http_client, email, "wrong", count=10, delay=0.1, **bypass)

        status_codes = [r.status_code for r in responses]
        # Filter out 429s that leak through when bypass key is not configured
        auth_codes = [c for c in status_codes if c != 429]
        got_423 = 423 in auth_codes

        if got_423:
            pytest.fail(
                f"[HIGH] Hard account lockout (423) still active — CWE-645 DoS vector.\n"
                f"Status codes: {auth_codes}\n"
                f"423 appeared at attempt {auth_codes.index(423) + 1}.\n"
                f"An attacker can lock ANY account with {auth_codes.index(423) + 1} bad passwords.\n"
                f"Fix: replace hard lockout with progressive delay (all failures → 401)."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_throttled_account_returns_generic_error(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        PD.2 [HIGH]: A throttled account must return 401 with the same generic
        message as a bad-password attempt — no enumeration oracle.

        Attack: fail 6 times (triggers progressive delay), then try again.
        Expected: 401 "Invalid email or password" — NOT 423, NOT a different message.
        """
        email = f"pd2+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # Bypass rate limiter — this test validates auth behavior, not rate limiting
        bypass = _bypass_headers()

        # Trigger progressive delay (6 failures → locked_until set)
        await rapid_fire_login(http_client, email, "wrong", count=6, delay=0.1, **bypass)

        # Immediately try again (within the delay window)
        resp = await do_login(http_client, email, "wrong_again", **bypass)

        body = parse_json_safe(resp.text)
        detail = (body.get("detail", "") if body else "").lower()

        if resp.status_code == 423:
            pytest.fail(
                f"[HIGH] Throttled account returns 423 instead of 401 — enumeration oracle.\n"
                f"An attacker sending bad passwords can distinguish existing accounts (423) "
                f"from non-existing ones (401). Must return 401 for all failures."
            )

        if resp.status_code != 401:
            pytest.fail(
                f"[HIGH] Unexpected status {resp.status_code} for throttled login attempt.\n"
                f"Expected 401. Body: {resp.text[:200]}"
            )

        # Check the message is generic — must NOT leak throttle state
        enumeration_leaks = ["locked", "throttled", "too many", "try again", "wait",
                             "minute", "second", "delay", "cooldown"]
        for leak in enumeration_leaks:
            if leak in detail:
                findings_collector.add_finding(
                    "/auth/login",
                    f"Throttle response leaks state via message containing '{leak}'",
                    "Medium",
                    f"401 detail: '{detail}' — contains '{leak}' which may confirm "
                    "account existence and reveal throttle state to an attacker.",
                    build_curl("POST", f"{API_BASE_URL}/auth/login", None, None,
                               {"email": email, "password": "wrong"}),
                    "Use identical 'Invalid email or password' for all 401 responses.",
                    asvs_control="V2.1.2",
                    owasp_category="A07",
                )
                break

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_correct_password_succeeds_after_delay_expires(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        PD.3 [HIGH]: Progressive delay must be TIME-BOUND — after the delay window
        expires, the correct password must succeed.

        We can only test the first delay tier (attempts 1-3 have no delay, attempt 4
        has a 2-second delay). After waiting 3 seconds, login with correct password
        must return 200.
        """
        email = f"pd3+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # Bypass rate limiter — this test validates auth behavior, not rate limiting
        bypass = _bypass_headers()

        # 4 failures → triggers 2-second delay (min(2^(4-3), 300) = 2s)
        for i in range(4):
            await do_login(http_client, email, f"wrong_{i}", **bypass)
            await asyncio.sleep(0.15)

        # Wait for the 2-second delay to expire
        await asyncio.sleep(3.0)

        # Correct password should now succeed
        resp = await do_login(http_client, email, password, **bypass)

        if resp.status_code != 200:
            body = parse_json_safe(resp.text)
            detail = body.get("detail", "") if body else ""
            pytest.fail(
                f"[HIGH] Correct password rejected after progressive delay expired.\n"
                f"4 failures → 2s delay. Waited 3s. Expected 200, got {resp.status_code}.\n"
                f"Detail: '{detail}'\n"
                f"If the delay window passed but login still fails, the account may be "
                f"permanently locked (CWE-645) instead of using progressive delay."
            )


# ============================================================================
# TEST GROUP BP: Rate Limit Bypass Vectors
# ============================================================================

class TestRateLimitBypass:
    """
    Red-team tests for rate limit bypass via header spoofing.

    With TRUST_PROXY_HEADERS=false (default), get_client_ip() ignores
    X-Forwarded-For and X-Real-IP, using request.client.host instead.
    These tests verify that spoofed headers do NOT create separate rate limit buckets.
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V4.2.1")
    @pytest.mark.owasp("A07")
    async def test_xforwarded_for_ip_rotation(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        BP.1 [HIGH]: Verify X-Forwarded-For rotation does NOT bypass rate limit.

        Attack: send 80 requests with different X-Forwarded-For IPs to /auth/login.
        Expected (with TRUST_PROXY_HEADERS=false): all requests share the same real IP
        bucket (10/60s, shared across workers via Redis), so 429 fires. If every
        request gets through without a 429, the server is trusting spoofed headers.
        """
        email = f"bp1+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        responses = []
        for i in range(80):
            spoofed_ip = f"10.0.{i // 256}.{i % 256}"
            resp = await http_client.post(
                "/auth/login",
                json={"email": email, "password": f"wrong_{i}"},
                headers={"X-Forwarded-For": spoofed_ip},
            )
            responses.append(resp)
            await asyncio.sleep(0.01)

        status_codes = [r.status_code for r in responses]
        count_429 = status_codes.count(429)
        count_401 = status_codes.count(401)

        # With the fix, spoofed IPs are ignored — all requests share one bucket.
        # We should see 429 before all 80 finish.
        if count_429 == 0:
            pytest.fail(
                f"[HIGH] Rate limit bypassed via X-Forwarded-For rotation.\n"
                f"Sent 80 requests with unique X-Forwarded-For IPs.\n"
                f"Got {count_401}x 401, {count_429}x 429.\n"
                f"Either TRUST_PROXY_HEADERS is true (should be false), "
                f"or the rate limit for /auth/login is not configured."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V4.2.1")
    @pytest.mark.owasp("A07")
    async def test_xrealip_spoofing(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        BP.2 [HIGH]: Verify X-Real-IP spoofing does NOT bypass rate limit.

        Same logic as BP.1 but using X-Real-IP header.
        """
        email = f"bp2+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        responses = []
        for i in range(80):
            spoofed_ip = f"172.16.{i // 256}.{i % 256}"
            resp = await http_client.post(
                "/auth/login",
                json={"email": email, "password": f"wrong_{i}"},
                headers={"X-Real-IP": spoofed_ip},
            )
            responses.append(resp)
            await asyncio.sleep(0.01)

        status_codes = [r.status_code for r in responses]
        count_429 = status_codes.count(429)
        count_401 = status_codes.count(401)

        if count_429 == 0:
            pytest.fail(
                f"[HIGH] Rate limit bypassed via X-Real-IP spoofing.\n"
                f"Sent 80 requests with unique X-Real-IP IPs.\n"
                f"Got {count_401}x 401, {count_429}x 429.\n"
                f"Either TRUST_PROXY_HEADERS is true (should be false), "
                f"or the rate limit for /auth/login is not configured."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V4.2.1")
    @pytest.mark.owasp("A07")
    async def test_credential_spray_across_accounts(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        BP.3 [HIGH]: Credential spray across multiple accounts.

        Attack: 4 bad logins per account across 15 accounts (60 total, each under
        lockout threshold). With TRUST_PROXY_HEADERS=false, all requests share the
        real IP, so the per-IP rate limit (10/60s) should fire. With 5 workers,
        ~12 requests/worker is enough to exceed the 10/60s limit.
        """
        accounts = []
        for i in range(15):
            email = f"bp3_{test_tag}_{i}@mailrbp.com"
            password = f"P@ssw0rd!_{test_tag}_{i}"
            await register_user(http_client, email, password)
            accounts.append(email)

        total_attempts = 0
        blocked_count = 0
        for email in accounts:
            for j in range(4):
                resp = await http_client.post(
                    "/auth/login",
                    json={"email": email, "password": f"wrong_{j}"},
                )
                total_attempts += 1
                if resp.status_code == 429:
                    blocked_count += 1
                await asyncio.sleep(0.01)

        if blocked_count == 0:
            pytest.fail(
                f"[HIGH] Credential spray attack viable.\n"
                f"Sent {total_attempts} requests across {len(accounts)} accounts, "
                f"4 per account (under lockout threshold).\n"
                f"Got {blocked_count} rate limit blocks (expected > 0).\n"
                f"The per-IP rate limit on /auth/login (10/60s) should fire before "
                f"{total_attempts} requests from the same IP."
            )


# ============================================================================
# TEST GROUP RS: Rate Limit Response Quality
# ============================================================================

class TestRateLimitResponseQuality:
    """
    Red-team tests for rate limit response quality and information leakage.
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V4.2.1")
    @pytest.mark.owasp("A07")
    async def test_429_includes_retry_after(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RS.1 [LOW]: When 429 fires, response MUST include Retry-After header (RFC 6585).
        """
        email = f"rs1+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # Hammer /auth/token (which has an explicit rate limit entry: 20/60s)
        responses = []
        for i in range(150):
            resp = await http_client.post(
                "/auth/token",
                data={"username": email, "password": f"wrong_{i}"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            responses.append(resp)
            await asyncio.sleep(0.01)

        rate_limited = [r for r in responses if r.status_code == 429]

        if not rate_limited:
            pytest.skip("No 429 response received — cannot test response quality")

        for resp in rate_limited:
            body = parse_json_safe(resp.text)

            # Check retry_after in body (the current implementation puts it there)
            has_retry_after_header = "Retry-After" in resp.headers or "retry-after" in resp.headers
            has_retry_after_body = body and "retry_after" in body

            if not has_retry_after_header and not has_retry_after_body:
                findings_collector.add_finding(
                    "/auth/token",
                    "429 response missing Retry-After information",
                    "Low",
                    f"Response headers: {dict(resp.headers)}. Body: {resp.text[:200]}",
                    build_curl("POST", f"{API_BASE_URL}/auth/token",
                               {"Content-Type": "application/x-www-form-urlencoded"},
                               None, None, {"username": email, "password": "wrong"}),
                    "Add Retry-After header to 429 responses per RFC 6585 S4. "
                    "The body already has retry_after, but the header is the standard.",
                    asvs_control="V4.2.1",
                    owasp_category="A07",
                )
                break

    @pytest.mark.asyncio
    @pytest.mark.asvs("V7.4.1")
    @pytest.mark.owasp("A07")
    async def test_429_no_debug_info_in_prod(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RS.2 [MEDIUM]: 429 response must not leak debug info (client IP, config, request counts)
        unless DEBUG_MODE is explicitly enabled.
        """
        email = f"rs2+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        responses = []
        for i in range(150):
            resp = await http_client.post(
                "/auth/token",
                data={"username": email, "password": f"wrong_{i}"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            responses.append(resp)
            await asyncio.sleep(0.02)

        rate_limited = [r for r in responses if r.status_code == 429]

        if not rate_limited:
            pytest.skip("No 429 response received — cannot test debug leakage")

        for resp in rate_limited:
            body = parse_json_safe(resp.text)
            if body and "debug" in body:
                debug_info = body["debug"]
                leaked_fields = list(debug_info.keys())
                findings_collector.add_finding(
                    "/auth/token",
                    "429 response leaks debug information (client_ip, rate limit config)",
                    "Medium",
                    f"Debug block present with fields: {leaked_fields}. "
                    f"Leaked data: {json.dumps(debug_info)[:300]}",
                    build_curl("POST", f"{API_BASE_URL}/auth/token",
                               {"Content-Type": "application/x-www-form-urlencoded"},
                               None, None, {"username": email, "password": "wrong"}),
                    "The rate limiter includes a debug block when CONFIG['DEBUG_MODE'] is True. "
                    "Ensure DEBUG_MODE is False in production. The debug block leaks: "
                    "client IP, endpoint path, max_requests, window_seconds, and full "
                    "rate_limit_config — useful for an attacker to calculate exact timing.",
                    asvs_control="V7.4.1",
                    owasp_category="A07",
                )
                break

    @pytest.mark.asyncio
    @pytest.mark.asvs("V7.4.1")
    @pytest.mark.owasp("A07")
    async def test_lockout_no_500_on_edge_cases(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RS.3 [HIGH]: Auth endpoints must not return 500 for any combination of bad input.
        """
        payloads = [
            {},
            {"email": "", "password": ""},
            {"email": None, "password": None},
            {"email": "x" * 10000, "password": "y" * 10000},
            {"email": "a@b.c", "password": "short"},
            {"email": "not-an-email", "password": "P@ssw0rd!_test"},
            {"email": f"test_{test_tag}@mailrbp.com"},  # missing password
            {"password": "P@ssw0rd!_test"},  # missing email
        ]

        for payload in payloads:
            resp = await http_client.post("/auth/login", json=payload)
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/login",
                "json": payload,
            }
            # assert_status_not_500 calls pytest.fail() internally — already hard-fails
            assert_status_not_500(resp, request_details, "/auth/login", f"payload: {payload}")
            assert_no_stacktrace(resp, request_details, "/auth/login")


# ============================================================================
# TEST GROUP VR: Verification Endpoint Rate Limits
# ============================================================================

class TestVerificationRateLimits:
    """
    Red-team tests for /auth/verify rate limiting (config says 5/3600s).
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_verify_endpoint_rate_limit(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        VR.1 [MEDIUM]: Verify /auth/verify is rate-limited (5 requests per hour).

        Attack: send 40 rapid verification attempts with bogus tokens.
        With 5 workers and limit 5/3600s, each worker sees ~8 — enough to trigger.
        """
        responses = []
        for i in range(40):
            resp = await http_client.post("/auth/verify", json={
                "token": f"bogus_token_{test_tag}_{i}",
            })
            responses.append(resp)
            await asyncio.sleep(0.02)

        status_codes = [r.status_code for r in responses]
        got_429 = 429 in status_codes

        if not got_429:
            # Could be a GET endpoint or different contract
            if all(s == 404 for s in status_codes):
                pytest.skip("/auth/verify returns 404 — endpoint may not exist")

            findings_collector.add_finding(
                "/auth/verify",
                "No rate limiting detected on /auth/verify after 40 rapid requests",
                "Medium",
                f"Config says 5 req/hour but got: {status_codes[:10]}...",
                build_curl("POST", f"{API_BASE_URL}/auth/verify", None, None,
                           {"token": "bogus_token"}),
                "Verify the rate limit is correctly applied. /auth/verify is sensitive — "
                "token enumeration at 5/hour is still too fast if tokens are short.",
                asvs_control="V2.1.3",
                owasp_category="A07",
            )


# ============================================================================
# TEST GROUP CO: Concurrent / Race Condition Tests
# ============================================================================

class TestConcurrentAuth:
    """
    Red-team tests for race conditions in auth rate limiting and progressive delay.
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_concurrent_login_no_500(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        CO.1 [HIGH]: Concurrent login attempts must not cause 500 errors.

        Attack: send 10 concurrent login attempts simultaneously.
        If the DB counter increment is not atomic, we may get 500s from
        concurrent writes to failed_login_attempts.
        """
        email = f"co1+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # Send 10 concurrent requests
        async def attempt(i: int) -> httpx.Response:
            async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
                return await client.post("/auth/login", json={
                    "email": email,
                    "password": f"wrong_{i}",
                })

        tasks = [attempt(i) for i in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_responses = [r for r in responses if isinstance(r, httpx.Response)]
        status_codes = [r.status_code for r in valid_responses]

        count_500 = status_codes.count(500)
        count_423 = status_codes.count(423)

        # 500s during concurrent auth = error handling issue → hard fail
        if count_500 > 0:
            pytest.fail(
                f"[HIGH] 500 Internal Server Error during concurrent login attempts.\n"
                f"Sent 10 concurrent logins, got {count_500}x 500.\n"
                f"Full status codes: {status_codes}\n"
                f"Database concurrency issue — the failed_login_attempts counter increment "
                f"may not be atomic. Use SELECT ... FOR UPDATE or optimistic locking."
            )

        # 423 should never appear (progressive delay returns 401)
        if count_423 > 0:
            pytest.fail(
                f"[HIGH] Hard lockout (423) still active during concurrent login test.\n"
                f"Status codes: {status_codes}\n"
                f"Progressive delay must return 401 for all failures, never 423."
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_progressive_delay_resets_on_success(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        CO.2 [HIGH]: After progressive delay expires and user logs in successfully,
        the failed attempt counter must reset. A subsequent bad password should
        NOT immediately trigger a delay (i.e., counter is back to 0).
        """
        email = f"co2+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # 4 failures → triggers 2-second delay
        for i in range(4):
            await do_login(http_client, email, f"wrong_{i}")
            await asyncio.sleep(0.15)

        # Wait for delay to expire
        await asyncio.sleep(3.0)

        # Successful login — should reset the counter
        resp = await do_login(http_client, email, password)
        if resp.status_code != 200:
            pytest.skip(f"Login failed with {resp.status_code} — cannot test counter reset")

        # Now fail once — should NOT trigger a delay (counter was reset)
        resp2 = await do_login(http_client, email, "wrong_after_reset")

        if resp2.status_code == 423:
            pytest.fail(
                f"[HIGH] Progressive delay counter not reset after successful login.\n"
                f"After 4 failures + successful login, a single bad password returned 423.\n"
                f"The counter should reset to 0 on success."
            )

        # Try correct password immediately — should succeed (no delay from just 1 failure)
        resp3 = await do_login(http_client, email, password)
        if resp3.status_code != 200:
            pytest.fail(
                f"[HIGH] Cannot login after counter reset — got {resp3.status_code}.\n"
                f"After successful login + 1 bad attempt, correct password should work.\n"
                f"Detail: {resp3.text[:200]}"
            )


# ============================================================================
# TEST GROUP RE: Refresh Token Rate Limits
# ============================================================================

class TestRefreshTokenRateLimits:
    """
    Red-team tests for /auth/refresh rate limiting (config says 40/60s).
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V3.5.1")
    @pytest.mark.owasp("A07")
    async def test_refresh_with_invalid_token_rate_limited(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        RE.1 [MEDIUM]: Verify /auth/refresh is rate-limited even with invalid tokens.

        Attack: spray refresh endpoint with random tokens to enumerate valid ones.
        Expected: 429 fires before 45 attempts (config says 40/60s).
        """
        responses = []
        for i in range(45):
            resp = await http_client.post(
                "/auth/refresh",
                json={"refresh_token": f"invalid_token_{test_tag}_{i}"},
            )
            responses.append(resp)
            await asyncio.sleep(0.02)

        status_codes = [r.status_code for r in responses]
        got_429 = 429 in status_codes

        # Also check if endpoint exists (might be different contract)
        if all(s == 404 for s in status_codes):
            pytest.skip("/auth/refresh returns 404 — endpoint may use different path")

        if not got_429:
            findings_collector.add_finding(
                "/auth/refresh",
                "No rate limiting detected on /auth/refresh after 45 rapid requests",
                "Medium",
                f"Config says 40 req/60s but got: {status_codes[:10]}...",
                build_curl("POST", f"{API_BASE_URL}/auth/refresh", None, None,
                           {"refresh_token": "invalid_token"}),
                "Refresh token endpoint should be rate-limited to prevent token enumeration.",
                asvs_control="V3.5.1",
                owasp_category="A07",
            )


# ============================================================================
# TEST GROUP CP: CAPTCHA on Login (defense-in-depth after progressive delay)
# ============================================================================

class TestLoginCaptcha:
    """
    Red-team tests for CAPTCHA enforcement on login after repeated failures.

    Backend behaviour:
      - After LOGIN_CAPTCHA_THRESHOLD failed attempts, 401 response includes
        `captcha_required: true` in a structured `detail` object.
      - When CAPTCHA_TYPE is "none", captcha_required is always false.
      - The 401 detail is an object `{"message": "...", "captcha_required": bool}`,
        NOT a plain string.
    """

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_401_response_is_structured_object(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        CP.1 [HIGH]: Login 401 detail must be a structured object, not a plain string.

        The CAPTCHA-on-login feature changed `detail` from a string to an object
        with `message` and `captcha_required` keys. Verify the contract.
        """
        email = f"cp1+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        resp = await do_login(http_client, email, "wrong_password")

        if resp.status_code != 401:
            pytest.skip(f"Expected 401, got {resp.status_code} — cannot test response structure")

        body = parse_json_safe(resp.text)
        detail = body.get("detail") if body else None

        if detail is None:
            pytest.fail(
                f"[HIGH] 401 response has no 'detail' field.\n"
                f"Body: {resp.text[:300]}"
            )

        if isinstance(detail, str):
            pytest.fail(
                f"[HIGH] 401 detail is a plain string, not a structured object.\n"
                f"detail: '{detail}'\n"
                f"Expected: {{\"message\": \"...\", \"captcha_required\": bool}}\n"
                f"The CAPTCHA-on-login feature requires a structured detail object."
            )

        if not isinstance(detail, dict):
            pytest.fail(
                f"[HIGH] 401 detail has unexpected type: {type(detail).__name__}.\n"
                f"Expected dict with 'message' and 'captcha_required' keys."
            )

        # Verify required keys
        if "message" not in detail:
            pytest.fail(
                f"[HIGH] 401 detail object missing 'message' key.\n"
                f"detail keys: {list(detail.keys())}"
            )
        if "captcha_required" not in detail:
            pytest.fail(
                f"[HIGH] 401 detail object missing 'captcha_required' key.\n"
                f"detail keys: {list(detail.keys())}"
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_captcha_not_required_below_threshold(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        CP.2 [HIGH]: First few failures must NOT set captcha_required=true.

        A fresh account with 1-2 failures should have captcha_required=false,
        regardless of server CAPTCHA config. This prevents CAPTCHA from being
        an annoyance on the first typo.
        """
        email = f"cp2+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # First failure — should never require CAPTCHA
        resp = await do_login(http_client, email, "wrong_password_1")

        if resp.status_code != 401:
            pytest.skip(f"Expected 401, got {resp.status_code}")

        body = parse_json_safe(resp.text)
        detail = body.get("detail") if body else None

        if isinstance(detail, dict) and detail.get("captcha_required") is True:
            pytest.fail(
                f"[HIGH] captcha_required=true on FIRST failed login attempt.\n"
                f"CAPTCHA should only trigger after LOGIN_CAPTCHA_THRESHOLD failures.\n"
                f"detail: {detail}"
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_captcha_required_after_threshold(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        CP.3 [MEDIUM]: After exceeding LOGIN_CAPTCHA_THRESHOLD failures,
        captcha_required should be true (if CAPTCHA_TYPE != "none").

        This test sends 6 failures (exceeds default threshold of 3), then checks
        the captcha_required flag. If CAPTCHA_TYPE is "none" on the server,
        captcha_required will be false — that's OK, it's a config-dependent test.
        """
        email = f"cp3+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # 6 failures to exceed default threshold (3)
        for i in range(6):
            await do_login(http_client, email, f"wrong_{i}")
            await asyncio.sleep(0.15)

        # Check the next response
        resp = await do_login(http_client, email, "wrong_final")

        if resp.status_code != 401:
            pytest.skip(f"Expected 401, got {resp.status_code}")

        body = parse_json_safe(resp.text)
        detail = body.get("detail") if body else None

        if not isinstance(detail, dict):
            pytest.fail(
                f"[MEDIUM] 401 detail is not a structured object after 7 failures.\n"
                f"detail type: {type(detail).__name__}, value: {detail}"
            )

        captcha_flag = detail.get("captcha_required")

        if captcha_flag is True:
            # CAPTCHA is enabled and threshold exceeded — expected behaviour
            pass
        elif captcha_flag is False:
            # Could mean CAPTCHA_TYPE=none on server — record as finding, not failure
            findings_collector.add_finding(
                "/auth/login",
                "captcha_required=false after 7 failures — server may have CAPTCHA disabled",
                "Medium",
                f"After 7 failed logins, detail.captcha_required={captcha_flag}. "
                f"If CAPTCHA_TYPE='none', this is expected. Otherwise it's a bug.",
                build_curl("POST", f"{API_BASE_URL}/auth/login", None, None,
                           {"email": email, "password": "wrong"}),
                "Set PHOVEU_BACKEND_CAPTCHA_TYPE=recaptcha_v3 or turnstile and "
                "PHOVEU_BACKEND_LOGIN_CAPTCHA_THRESHOLD=3 to enable CAPTCHA on login.",
                asvs_control="V2.1.3",
                owasp_category="A07",
            )
        else:
            pytest.fail(
                f"[MEDIUM] captcha_required has unexpected value: {captcha_flag} "
                f"(type: {type(captcha_flag).__name__})\n"
                f"Expected bool. Full detail: {detail}"
            )

    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_captcha_required_resets_on_success(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        CP.4 [HIGH]: After successful login, the failed attempt counter resets,
        so the next failure should NOT require CAPTCHA.
        """
        email = f"cp4+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        await register_user(http_client, email, password)

        # 4 failures to exceed threshold
        for i in range(4):
            await do_login(http_client, email, f"wrong_{i}")
            await asyncio.sleep(0.15)

        # Wait for progressive delay to expire, then login successfully
        await asyncio.sleep(3.0)
        resp = await do_login(http_client, email, password)
        if resp.status_code != 200:
            pytest.skip(f"Could not login successfully — got {resp.status_code}")

        # Now fail once — counter should be reset, so captcha_required should be false
        resp2 = await do_login(http_client, email, "wrong_after_reset")

        if resp2.status_code != 401:
            pytest.skip(f"Expected 401, got {resp2.status_code}")

        body = parse_json_safe(resp2.text)
        detail = body.get("detail") if body else None

        if isinstance(detail, dict) and detail.get("captcha_required") is True:
            pytest.fail(
                f"[HIGH] captcha_required=true on first failure AFTER successful login.\n"
                f"The failed_login_attempts counter should reset on success.\n"
                f"detail: {detail}"
            )
