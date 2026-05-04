"""
Pentest-grade security test suite for Phoveus API authentication endpoints.

This test suite implements OWASP ASVS / OWASP Top 10 security checks and validates
RFC compliance for:
- HTTP semantics (RFC 9110/9111)
- Bearer token usage (RFC 6750)
- OAuth2 password flow (RFC 6749)
- JWT (RFC 7519)

All tests use unique 5-letter tags to avoid database false positives.
"""
import pytest
import httpx
import time
import asyncio
import json
import sys
import os
from typing import Dict, Any, Optional

# Import conftest - pytest makes it available when running tests
# We need to handle both cases: when run as module and when run directly
_test_dir = os.path.dirname(os.path.abspath(__file__))
if _test_dir not in sys.path:
    sys.path.insert(0, _test_dir)

# Import conftest module
import conftest

# Import functions and variables from conftest
rand_tag = conftest.rand_tag
mask_secret = conftest.mask_secret
build_curl = conftest.build_curl
fail_with_details = conftest.fail_with_details
parse_json_safe = conftest.parse_json_safe
findings_collector = conftest.findings_collector
API_BASE_URL = conftest.API_BASE_URL
# Import security assertion helpers
assert_no_stacktrace = conftest.assert_no_stacktrace
assert_no_sql_error = conftest.assert_no_sql_error
assert_generic_auth_error = conftest.assert_generic_auth_error
assert_cache_control_no_store = conftest.assert_cache_control_no_store
assert_status_not_500 = conftest.assert_status_not_500


# ============================================================================
# TEST GROUP A: Registration (/auth/register)
# ============================================================================

class TestRegistrationSecurity:
    """Security tests for user registration endpoint"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.1")
    @pytest.mark.owasp("A07")
    async def test_register_unique_user(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        A.1: Registration creates unique user with tag-embedded data.
        
        OWASP ASVS V2.1.1: Verify that user registration requires email address verification.
        OWASP A07:2021 - Identification and Authentication Failures
        
        Verifies:
        - Registration succeeds with unique email
        - Password is not echoed in response
        - Response structure is correct
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        first_name = f"Sec{test_tag}"
        last_name = f"Test{test_tag}"
        
        payload = {
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name
        }
        
        try:
            response = await http_client.post("/auth/register", json=payload)
            
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/register",
                "headers": dict(response.request.headers),
                "json": payload
            }
            
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds()
            }
            
            if response.status_code not in [200, 201]:
                fail_with_details(
                    "Registration failed for unique user",
                    request_details,
                    response_details,
                    "Registration should succeed (200/201) for valid unique email. Check password requirements and email validation."
                )
            
            # Verify password is not in response
            body = parse_json_safe(response.text)
            if body:
                body_str = json.dumps(body).lower()
                if password.lower() in body_str:
                    findings_collector.add_finding(
                        "/auth/register",
                        "Password echoed in registration response",
                        "High",
                        f"Response contains password: {mask_secret(password)}",
                        build_curl("POST", f"{API_BASE_URL}/auth/register", None, None, payload),
                        "Never include passwords in API responses. Remove password from response body.",
                        asvs_control="V8.2.1",
                        owasp_category="A02"
                    )
            
            # Verify response structure
            if body and not body.get("success"):
                fail_with_details(
                    "Registration response missing success field",
                    request_details,
                    response_details,
                    "Registration response should include 'success: true' field per API contract."
                )
        
        except httpx.HTTPError as e:
            pytest.fail(f"HTTP error during registration: {e}")
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.2")
    @pytest.mark.owasp("A07")
    async def test_register_duplicate_email(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        A.2: Duplicate registration handling.
        
        OWASP ASVS V2.1.2: Verify that authentication error responses are generic.
        OWASP A07:2021 - Identification and Authentication Failures
        
        Verifies:
        - Duplicate email returns 409 (or 4xx)
        - Error message doesn't leak extra information
        - Response is consistent with invalid input errors
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # First registration
        payload1 = {"email": email, "password": password}
        await http_client.post("/auth/register", json=payload1)
        
        # Wait a bit to ensure first request completes
        await asyncio.sleep(0.5)
        
        # Attempt duplicate registration
        payload2 = {"email": email, "password": f"Different_{test_tag}"}
        
        try:
            response = await http_client.post("/auth/register", json=payload2)
            
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/register",
                "headers": dict(response.request.headers),
                "json": payload2
            }
            
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds()
            }
            
            # Should be 409 Conflict or 4xx
            assert_status_not_500(
                response,
                request_details,
                "/auth/register",
                "duplicate registration",
                "V7.4.1"
            )
            
            if response.status_code not in [400, 409]:
                findings_collector.add_finding(
                    "/auth/register",
                    f"Unexpected status code for duplicate registration: {response.status_code}",
                    "Medium",
                    f"Expected 409 or 400, got {response.status_code}",
                    build_curl("POST", f"{API_BASE_URL}/auth/register", None, None, payload2),
                    "Return 409 Conflict for duplicate email per HTTP semantics (RFC 9110)."
                )
            
            # Check for information leakage
            body = parse_json_safe(response.text)
            if body:
                body_str = json.dumps(body).lower()
                # Should not reveal database structure or internal details
                sensitive_terms = ["sql", "database", "constraint", "unique", "duplicate key"]
                for term in sensitive_terms:
                    if term in body_str:
                        findings_collector.add_finding(
                            "/auth/register",
                            f"Information leakage in duplicate registration error: contains '{term}'",
                            "Medium",
                            f"Response body: {response.text[:200]}",
                            build_curl("POST", f"{API_BASE_URL}/auth/register", None, None, payload2),
                            "Error messages should be generic and not reveal database structure or internal implementation details.",
                            asvs_control="V7.4.1",
                            owasp_category="A09"
                        )
        
        except httpx.HTTPError as e:
            pytest.fail(f"HTTP error during duplicate registration test: {e}")
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V5.3.1")
    @pytest.mark.owasp("A03")
    @pytest.mark.rfc("5322")
    async def test_register_apostrophe_email(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        A.3: Apostrophe email handling (RFC-compatible local-part).
        
        OWASP ASVS V5.3.1: Verify that the application handles SQL errors safely.
        OWASP A03:2021 - Injection
        RFC 5322: Email address format
        
        Verifies:
        - Apostrophe in email is handled gracefully
        - If rejected, returns clean 4xx (not 500)
        - Error message is consistent
        """
        # RFC 5322 allows apostrophes in local-part: "o'brien@mailrbp.com" is valid
        email = f"utest_o'{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        payload = {
            "email": email,
            "password": password,
            "first_name": f"Sec{test_tag}",
            "last_name": f"Test{test_tag}"
        }
        
        try:
            response = await http_client.post("/auth/register", json=payload)
            
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/register",
                "headers": dict(response.request.headers),
                "json": payload
            }
            
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds()
            }
            
            assert_status_not_500(
                response,
                request_details,
                "/auth/register",
                "apostrophe email input",
                "V5.3.1"
            )
            assert_no_sql_error(response, request_details, "/auth/register", "V5.3.1")
            
            if response.status_code not in [200, 201, 400, 422]:
                findings_collector.add_finding(
                    "/auth/register",
                    f"Unexpected status for apostrophe email: {response.status_code}",
                    "Low",
                    f"Email with apostrophe returned {response.status_code}",
                    build_curl("POST", f"{API_BASE_URL}/auth/register", None, None, payload),
                    "If apostrophe emails are not supported, document this clearly and return 422. If supported (RFC 5322), ensure proper escaping to prevent SQL injection."
                )
        
        except httpx.HTTPError as e:
            pytest.fail(f"HTTP error during apostrophe email test: {e}")


# ============================================================================
# TEST GROUP B: Login (/auth/login)
# ============================================================================

class TestLoginSecurity:
    """Security tests for login endpoint"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.2")
    @pytest.mark.owasp("A07")
    async def test_login_user_enumeration(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        B.1: User enumeration prevention.
        
        OWASP ASVS V2.1.2: Verify that authentication error responses are generic.
        OWASP A07:2021 - Identification and Authentication Failures
        
        Verifies:
        - Wrong password for existing user vs non-existing user
        - Response codes/messages/timing should be similar
        - No information leakage about user existence
        """
        # First, register a user
        existing_email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        await http_client.post("/auth/register", json={
            "email": existing_email,
            "password": password
        })
        await asyncio.sleep(0.5)
        
        # Test 1: Wrong password for existing user
        wrong_password = f"Wrong_{test_tag}"
        start1 = time.time()
        response1 = await http_client.post("/auth/login", json={
            "email": existing_email,
            "password": wrong_password
        })
        elapsed1 = time.time() - start1
        
        # Test 2: Login for non-existing user
        non_existing_email = f"utest_nonexist{test_tag}@mailrbp.com"
        start2 = time.time()
        response2 = await http_client.post("/auth/login", json={
            "email": non_existing_email,
            "password": wrong_password
        })
        elapsed2 = time.time() - start2
        
        # Compare responses
        status_diff = response1.status_code != response2.status_code
        body1 = parse_json_safe(response1.text)
        body2 = parse_json_safe(response2.text)
        
        # Check for timing differences (best effort)
        timing_diff = abs(elapsed1 - elapsed2)
        timing_threshold = 0.5  # 500ms difference might indicate enumeration
        
        if status_diff:
            findings_collector.add_finding(
                "/auth/login",
                "User enumeration via different status codes",
                "Medium",
                f"Existing user wrong password: {response1.status_code}, Non-existing user: {response2.status_code}",
                build_curl("POST", f"{API_BASE_URL}/auth/login", None, None, {"email": existing_email, "password": wrong_password}),
                "Return identical status codes (401) and generic error messages for both invalid credentials and non-existing users to prevent enumeration (OWASP ASVS V2.1.2).",
                asvs_control="V2.1.2",
                owasp_category="A07"
            )
        
        if timing_diff > timing_threshold:
            findings_collector.add_finding(
                "/auth/login",
                "Potential user enumeration via timing differences",
                "Low",
                f"Timing difference: {timing_diff:.3f}s (existing: {elapsed1:.3f}s, non-existing: {elapsed2:.3f}s)",
                build_curl("POST", f"{API_BASE_URL}/auth/login", None, None, {"email": existing_email, "password": wrong_password}),
                "Ensure constant-time password verification and identical processing paths for existing/non-existing users to prevent timing attacks.",
                asvs_control="V2.1.2",
                owasp_category="A07"
            )
        
        # Check message similarity
        msg1 = body1.get("detail", body1.get("message", "")) if body1 else response1.text
        msg2 = body2.get("detail", body2.get("message", "")) if body2 else response2.text
        
        if msg1 != msg2 and len(msg1) > 0 and len(msg2) > 0:
            findings_collector.add_finding(
                "/auth/login",
                "User enumeration via different error messages",
                "Medium",
                f"Existing user message: '{msg1[:50]}', Non-existing: '{msg2[:50]}'",
                build_curl("POST", f"{API_BASE_URL}/auth/login", None, None, {"email": existing_email, "password": wrong_password}),
                "Use identical generic error messages for both cases: 'Invalid email or password' (OWASP ASVS V2.1.2).",
                asvs_control="V2.1.2",
                owasp_category="A07"
            )
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V2.1.3")
    @pytest.mark.owasp("A07")
    async def test_login_brute_force_protection(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        B.2: Brute-force / lockout protection.
        
        OWASP ASVS V2.1.3: Verify that the application implements account lockout protection.
        OWASP A07:2021 - Identification and Authentication Failures
        
        Verifies:
        - After N failed attempts, account is locked (423) or rate limited (429)
        - Rate limit headers are present
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register user
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        # Attempt multiple failed logins
        failed_attempts = 0
        lockout_detected = False
        rate_limit_detected = False
        
        for i in range(12):  # Try 12 failed attempts
            response = await http_client.post("/auth/login", json={
                "email": email,
                "password": f"Wrong_{test_tag}_{i}"
            })
            
            if response.status_code == 423:
                lockout_detected = True
                failed_attempts = i + 1
                break
            
            if response.status_code == 429:
                rate_limit_detected = True
                # Check for rate limit headers
                if "Retry-After" in response.headers or "X-RateLimit-Remaining" in response.headers:
                    failed_attempts = i + 1
                    break
            
            await asyncio.sleep(0.1)  # Small delay between attempts
        
        if not lockout_detected and not rate_limit_detected:
            findings_collector.add_finding(
                "/auth/login",
                "No brute-force protection detected",
                "High",
                f"Attempted {failed_attempts} failed logins without lockout (423) or rate limiting (429)",
                build_curl("POST", f"{API_BASE_URL}/auth/login", None, None, {"email": email, "password": "wrong"}),
                "Implement account lockout after 5 failed attempts (423 Locked) or rate limiting (429 Too Many Requests) with Retry-After header per OWASP ASVS V2.1.3.",
                asvs_control="V2.1.3",
                owasp_category="A07"
            )


# ============================================================================
# TEST GROUP C: OAuth2 Token Endpoint (/auth/token)
# ============================================================================

class TestOAuth2TokenSecurity:
    """Security tests for OAuth2 token endpoint (RFC 6749)"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V3.1.1")
    @pytest.mark.owasp("A01")
    @pytest.mark.rfc("6749")
    async def test_oauth2_token_success(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        C.1: OAuth2 token generation with correct credentials.
        
        OWASP ASVS V3.1.1: Verify that session tokens are generated using approved random number generators.
        OWASP A01:2021 - Broken Access Control
        RFC 6749: OAuth2 Authorization Framework
        
        Verifies:
        - Returns 200 with access_token, token_type, expires_in
        - May include refresh_token
        - Token type is "bearer" per RFC 6750
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register user
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        # Request token via OAuth2 form
        form_data = {
            "username": email,  # OAuth2 uses "username" but API treats it as email
            "password": password,
            "grant_type": "password",
            "scope": ""
        }
        
        try:
            response = await http_client.post("/auth/token", data=form_data)
            
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/token",
                "headers": dict(response.request.headers),
                "form": form_data
            }
            
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds()
            }
            
            if response.status_code != 200:
                fail_with_details(
                    "OAuth2 token request failed with valid credentials",
                    request_details,
                    response_details,
                    "OAuth2 token endpoint should return 200 OK with valid credentials per RFC 6749 Section 5.1."
                )
            
            body = parse_json_safe(response.text)
            if not body:
                fail_with_details(
                    "OAuth2 token response is not JSON",
                    request_details,
                    response_details,
                    "OAuth2 token response must be JSON per RFC 6749 Section 5.1."
                )
            
            # Verify required fields per RFC 6749
            if "access_token" not in body:
                fail_with_details(
                    "OAuth2 token response missing access_token",
                    request_details,
                    response_details,
                    "OAuth2 token response must include 'access_token' field per RFC 6749 Section 5.1."
                )
            
            if "token_type" not in body:
                fail_with_details(
                    "OAuth2 token response missing token_type",
                    request_details,
                    response_details,
                    "OAuth2 token response must include 'token_type' field per RFC 6749 Section 5.1."
                )
            
            if body.get("token_type", "").lower() != "bearer":
                findings_collector.add_finding(
                    "/auth/token",
                    f"OAuth2 token_type is not 'bearer': {body.get('token_type')}",
                    "Low",
                    f"Token type: {body.get('token_type')}",
                    build_curl("POST", f"{API_BASE_URL}/auth/token", None, None, None, form_data),
                    "OAuth2 token_type should be 'bearer' per RFC 6750 Section 2.1."
                )
        
        except httpx.HTTPError as e:
            pytest.fail(f"HTTP error during OAuth2 token test: {e}")
    
    @pytest.mark.asyncio
    async def test_oauth2_token_unauthorized(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        C.2: OAuth2 token with wrong credentials.
        
        Verifies:
        - Returns 401 (not 500) for invalid credentials
        - WWW-Authenticate header may be present (RFC 6750)
        """
        form_data = {
            "username": f"utest_wrong{test_tag}@mailrbp.com",
            "password": f"Wrong_{test_tag}",
            "grant_type": "password"
        }
        
        try:
            response = await http_client.post("/auth/token", data=form_data)
            
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/token",
                "headers": dict(response.request.headers),
                "form": form_data
            }
            
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds()
            }
            
            if response.status_code == 500:
                fail_with_details(
                    "OAuth2 token endpoint returns 500 for invalid credentials",
                    request_details,
                    response_details,
                    "Invalid credentials should return 401 Unauthorized, not 500 Internal Server Error. Check error handling."
                )
            
            if response.status_code != 401:
                findings_collector.add_finding(
                    "/auth/token",
                    f"OAuth2 token endpoint returns {response.status_code} instead of 401 for invalid credentials",
                    "Medium",
                    f"Status: {response.status_code}",
                    build_curl("POST", f"{API_BASE_URL}/auth/token", None, None, None, form_data),
                    "OAuth2 token endpoint should return 401 Unauthorized for invalid credentials per RFC 6749 Section 5.2."
                )
            
            # Check for WWW-Authenticate header (RFC 6750 Section 3)
            if "WWW-Authenticate" not in response.headers:
                findings_collector.add_finding(
                    "/auth/token",
                    "OAuth2 token endpoint missing WWW-Authenticate header",
                    "Low",
                    "401 response without WWW-Authenticate header",
                    build_curl("POST", f"{API_BASE_URL}/auth/token", None, None, None, form_data),
                    "Consider adding WWW-Authenticate: Bearer header to 401 responses per RFC 6750 Section 3 (optional but recommended)."
                )
        
        except httpx.HTTPError as e:
            pytest.fail(f"HTTP error during OAuth2 unauthorized test: {e}")


# ============================================================================
# TEST GROUP D: Authenticated Endpoints (/auth/me)
# ============================================================================

class TestAuthenticatedEndpointsSecurity:
    """Security tests for authenticated endpoints"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V3.2.1")
    @pytest.mark.owasp("A01")
    @pytest.mark.rfc("6750")
    async def test_me_without_token(self, http_client: httpx.AsyncClient):
        """
        D.1: /auth/me without token returns 401.
        
        OWASP ASVS V3.2.1: Verify that session tokens are invalidated when user logs out.
        OWASP A01:2021 - Broken Access Control
        RFC 6750: OAuth 2.0 Authorization Framework: Bearer Token Usage
        
        Verifies:
        - 401 Unauthorized without token
        - WWW-Authenticate header present (RFC 6750)
        """
        try:
            response = await http_client.get("/auth/me")
            
            request_details = {
                "method": "GET",
                "url": f"{API_BASE_URL}/auth/me",
                "headers": dict(response.request.headers)
            }
            
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds()
            }
            
            if response.status_code != 401:
                fail_with_details(
                    "/auth/me returns non-401 without token",
                    request_details,
                    response_details,
                    "Authenticated endpoints must return 401 Unauthorized when no token is provided per RFC 6750 Section 3."
                )
            
            # Check for WWW-Authenticate header (RFC 6750)
            if "WWW-Authenticate" not in response.headers:
                findings_collector.add_finding(
                    "/auth/me",
                    "Missing WWW-Authenticate header in 401 response",
                    "Low",
                    "401 response without WWW-Authenticate header",
                    build_curl("GET", f"{API_BASE_URL}/auth/me", None, None, None),
                    "Add WWW-Authenticate: Bearer header to 401 responses per RFC 6750 Section 3."
                )
        
        except httpx.HTTPError as e:
            pytest.fail(f"HTTP error during /auth/me test: {e}")
    
    @pytest.mark.asyncio
    async def test_me_with_valid_token(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        D.2: /auth/me with valid Bearer token returns 200.
        
        Verifies:
        - Returns 200 with user data
        - Response includes Cache-Control: no-store if tokens are present
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        
        # Call /auth/me with token
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await http_client.get("/auth/me", headers=headers)
        
        if response.status_code != 200:
            request_details = {
                "method": "GET",
                "url": f"{API_BASE_URL}/auth/me",
                "headers": headers
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "/auth/me returns non-200 with valid token",
                request_details,
                response_details,
                "Authenticated endpoint should return 200 OK with valid Bearer token."
            )
        
        # Check for Cache-Control header if response contains tokens
        body = parse_json_safe(response.text)
        if body and ("token" in json.dumps(body).lower() or "access_token" in json.dumps(body).lower()):
            if "Cache-Control" not in response.headers:
                findings_collector.add_finding(
                    "/auth/me",
                    "Missing Cache-Control header in response containing tokens",
                    "Medium",
                    "Response contains tokens but no Cache-Control header",
                    build_curl("GET", f"{API_BASE_URL}/auth/me", headers, None, None),
                    "Add Cache-Control: no-store header to responses containing tokens to prevent caching per OWASP ASVS V3.4.1."
                )
    
    @pytest.mark.asyncio
    async def test_me_malformed_tokens(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        D.3: Malformed token handling.
        
        Verifies:
        - "Bearer abc" -> 401 (not 500)
        - "Bearer <short>" -> 401 (not 500)
        - "Bearer <corrupted-jwt>" -> 401 (not 500)
        """
        malformed_tokens = [
            ("Bearer abc", "Short token"),
            (f"Bearer {test_tag}", "Tag-only token"),
            ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid", "Corrupted JWT")
        ]
        
        for token_header, description in malformed_tokens:
            headers = {"Authorization": token_header}
            response = await http_client.get("/auth/me", headers=headers)
            
            if response.status_code == 500:
                request_details = {
                    "method": "GET",
                    "url": f"{API_BASE_URL}/auth/me",
                    "headers": headers
                }
                response_details = {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text
                }
                fail_with_details(
                    f"Malformed token causes 500: {description}",
                    request_details,
                    response_details,
                    f"Malformed tokens should return 401 Unauthorized, not 500. Check token validation error handling for: {description}."
                )


# ============================================================================
# TEST GROUP E: Refresh Token (/auth/refresh)
# ============================================================================

class TestRefreshTokenSecurity:
    """Security tests for refresh token endpoint"""
    
    @pytest.mark.asyncio
    async def test_refresh_valid_token(self, http_client: httpx.AsyncClient, test_tag: str):
        """E.1: Valid refresh token returns 200 with new tokens"""
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("refresh_token"):
            pytest.skip("Could not obtain refresh token for test")
        
        refresh_token = login_body["data"]["tokens"]["refresh_token"]
        
        # Refresh token
        params = {"refresh_token": refresh_token}
        response = await http_client.post("/auth/refresh", params=params)
        
        if response.status_code != 200:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/refresh",
                "params": params
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Refresh token failed with valid token",
                request_details,
                response_details,
                "Valid refresh token should return 200 OK with new access and refresh tokens."
            )
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V3.1.2")
    @pytest.mark.owasp("A01")
    async def test_refresh_access_token_as_refresh(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        E.2: Access token used as refresh token returns 401
        
        OWASP ASVS V3.1.2: Verify that session tokens are unique and cannot be guessed.
        OWASP A01:2021 - Broken Access Control
        
        Verifies that access tokens cannot be used as refresh tokens (token type confusion prevention).
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        
        # Try to use access token as refresh token
        params = {"refresh_token": access_token}
        response = await http_client.post("/auth/refresh", params=params)
        
        if response.status_code != 401:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/refresh",
                "params": params
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Refresh endpoint accepts access token as refresh token",
                request_details,
                response_details,
                "Refresh endpoint must reject access tokens used as refresh tokens. Return 401 Unauthorized."
            )
    
    @pytest.mark.asyncio
    async def test_refresh_random_token(self, http_client: httpx.AsyncClient, test_tag: str):
        """E.3: Random refresh token returns 401 (not 500)"""
        params = {"refresh_token": f"random_{test_tag}_token"}
        response = await http_client.post("/auth/refresh", params=params)
        
        if response.status_code == 500:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/refresh",
                "params": params
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Random refresh token causes 500 error",
                request_details,
                response_details,
                "Invalid refresh tokens should return 401 Unauthorized, not 500. Check token validation error handling."
            )


# ============================================================================
# TEST GROUP F: Logout (/auth/logout)
# ============================================================================

class TestLogoutSecurity:
    """Security tests for logout endpoint"""
    
    @pytest.mark.asyncio
    async def test_logout_invalidates_token(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        F.1: Logout invalidates token.
        
        Verifies:
        - Logout with valid token returns 200
        - Token is invalidated (subsequent /auth/me returns 401)
        - If token still works, report finding (stateless JWT may be expected)
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Verify token works before logout
        me_response = await http_client.get("/auth/me", headers=headers)
        if me_response.status_code != 200:
            pytest.skip("Token not valid before logout test")
        
        # Logout
        logout_response = await http_client.post("/auth/logout", headers=headers)
        if logout_response.status_code != 200:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/logout",
                "headers": headers
            }
            response_details = {
                "status": logout_response.status_code,
                "headers": dict(logout_response.headers),
                "body": logout_response.text
            }
            fail_with_details(
                "Logout failed",
                request_details,
                response_details,
                "Logout should return 200 OK."
            )
        
        # Try to use token after logout
        await asyncio.sleep(0.5)
        me_response_after = await http_client.get("/auth/me", headers=headers)
        
        if me_response_after.status_code == 200:
            findings_collector.add_finding(
                "/auth/logout",
                "Token remains valid after logout",
                "Medium",
                "Token still works after logout (stateless JWT may be expected)",
                build_curl("GET", f"{API_BASE_URL}/auth/me", headers, None, None),
                "If using stateless JWTs, implement token blacklist or use short expiration with refresh tokens. Alternatively, use stateful sessions that can be invalidated on logout."
            )


# ============================================================================
# TEST GROUP G: Change Password (/auth/change-password)
# ============================================================================

class TestChangePasswordSecurity:
    """Security tests for change password endpoint"""
    
    @pytest.mark.asyncio
    async def test_change_password_without_token(self, http_client: httpx.AsyncClient):
        """G.1: Change password without token returns 401"""
        payload = {"current_password": "old", "new_password": "new"}
        response = await http_client.post("/auth/change-password", json=payload)
        
        if response.status_code != 401:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/change-password",
                "json": payload
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Change password allows unauthenticated access",
                request_details,
                response_details,
                "Change password endpoint must require authentication (401 Unauthorized)."
            )
    
    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, http_client: httpx.AsyncClient, test_tag: str):
        """G.2: Wrong current password returns 400/401 (not 500)"""
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Try to change password with wrong current password
        payload = {
            "current_password": f"Wrong_{test_tag}",
            "new_password": f"New_{test_tag}"
        }
        response = await http_client.post("/auth/change-password", json=payload, headers=headers)
        
        if response.status_code == 500:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/change-password",
                "headers": headers,
                "json": payload
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Change password returns 500 for wrong current password",
                request_details,
                response_details,
                "Wrong current password should return 400 Bad Request or 401 Unauthorized, not 500. Check password verification error handling."
            )
        
        # Check for information leakage
        body = parse_json_safe(response.text)
        if body:
            body_str = json.dumps(body).lower()
            if "password" in body_str and "hash" in body_str:
                findings_collector.add_finding(
                    "/auth/change-password",
                    "Information leakage in change password error",
                    "Low",
                    "Error response may contain password-related details",
                    build_curl("POST", f"{API_BASE_URL}/auth/change-password", headers, None, payload),
                    "Ensure error messages don't reveal password hashing details or internal validation logic."
                )
    
    @pytest.mark.asyncio
    async def test_change_password_success(self, http_client: httpx.AsyncClient, test_tag: str):
        """G.3: Valid password change works, old password fails, new password succeeds"""
        email = f"utest+{test_tag}@mailrbp.com"
        old_password = f"P@ssw0rd!_{test_tag}"
        new_password = f"NewP@ss1_{test_tag}"  # Must include numbers per password requirements
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": old_password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": old_password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Change password
        payload = {
            "current_password": old_password,
            "new_password": new_password
        }
        change_response = await http_client.post("/auth/change-password", json=payload, headers=headers)
        
        if change_response.status_code != 200:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/change-password",
                "headers": headers,
                "json": payload
            }
            response_details = {
                "status": change_response.status_code,
                "headers": dict(change_response.headers),
                "body": change_response.text
            }
            fail_with_details(
                "Password change failed with valid credentials",
                request_details,
                response_details,
                "Password change should succeed (200 OK) with valid current password."
            )
        
        await asyncio.sleep(0.5)
        
        # Old password should fail
        old_login = await http_client.post("/auth/login", json={"email": email, "password": old_password})
        if old_login.status_code == 200:
            findings_collector.add_finding(
                "/auth/change-password",
                "Old password still works after password change",
                "High",
                "Old password accepted after change",
                build_curl("POST", f"{API_BASE_URL}/auth/login", None, None, {"email": email, "password": old_password}),
                "Ensure password change immediately invalidates old password. Verify password hash is updated in database."
            )
        
        # New password should succeed
        new_login = await http_client.post("/auth/login", json={"email": email, "password": new_password})
        if new_login.status_code != 200:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/login",
                "json": {"email": email, "password": new_password}
            }
            response_details = {
                "status": new_login.status_code,
                "headers": dict(new_login.headers),
                "body": new_login.text
            }
            fail_with_details(
                "New password does not work after change",
                request_details,
                response_details,
                "New password should work immediately after password change. Verify password hash update."
            )


# ============================================================================
# TEST GROUP H: API Keys (/auth/api-keys)
# ============================================================================

class TestApiKeysSecurity:
    """Security tests for API keys endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_api_keys_without_token(self, http_client: httpx.AsyncClient):
        """H.1: GET /auth/api-keys without token returns 401"""
        response = await http_client.get("/auth/api-keys")
        
        if response.status_code != 401:
            request_details = {
                "method": "GET",
                "url": f"{API_BASE_URL}/auth/api-keys"
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "GET /auth/api-keys allows unauthenticated access",
                request_details,
                response_details,
                "API keys endpoint must require authentication (401 Unauthorized)."
            )
    
    @pytest.mark.asyncio
    async def test_create_api_key(self, http_client: httpx.AsyncClient, test_tag: str):
        """H.2: Create API key with tag-embedded name"""
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Create API key
        # Note: permissions is expected as a JSON string, not an array
        payload = {
            "key_name": f"test_key_{test_tag}",
            "permissions": '["read"]',  # JSON string format as expected by API
            "rate_limit": 100
        }
        response = await http_client.post("/auth/api-keys", json=payload, headers=headers)
        
        if response.status_code not in [200, 201]:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/api-keys",
                "headers": headers,
                "json": payload
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "API key creation failed",
                request_details,
                response_details,
                "API key creation should succeed (200/201) with valid authentication and payload."
            )
        
        # Check if full key is returned (may be expected for initial display)
        body = parse_json_safe(response.text)
        if body and body.get("data", {}).get("full_key"):
            # This is expected - API keys are typically shown once
            pass
    
    @pytest.mark.asyncio
    async def test_create_api_key_invalid_rate_limit(self, http_client: httpx.AsyncClient, test_tag: str):
        """H.3: Invalid rate_limit types return 4xx (not 500)"""
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register and login
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        login_body = parse_json_safe(login_response.text)
        
        if not login_body or not login_body.get("data", {}).get("tokens", {}).get("access_token"):
            pytest.skip("Could not obtain access token for test")
        
        access_token = login_body["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Try invalid rate_limit types
        invalid_payloads = [
            {"key_name": f"test_{test_tag}", "rate_limit": "not_a_number"},
            {"key_name": f"test_{test_tag}", "rate_limit": -1},
            {"key_name": f"test_{test_tag}", "rate_limit": None}
        ]
        
        for payload in invalid_payloads:
            response = await http_client.post("/auth/api-keys", json=payload, headers=headers)
            
            if response.status_code == 500:
                request_details = {
                    "method": "POST",
                    "url": f"{API_BASE_URL}/auth/api-keys",
                    "headers": headers,
                    "json": payload
                }
                response_details = {
                    "status": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text
                }
                fail_with_details(
                    f"Invalid rate_limit causes 500: {payload['rate_limit']}",
                    request_details,
                    response_details,
                    "Invalid rate_limit should return 400 Bad Request or 422 Unprocessable Entity, not 500. Check input validation."
                )


# ============================================================================
# TEST GROUP I & J: Password Reset
# ============================================================================

class TestPasswordResetSecurity:
    """Security tests for password reset endpoints"""
    
    @pytest.mark.asyncio
    async def test_request_password_reset_enumeration(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        I.1: Password reset request enumeration prevention.
        
        Verifies:
        - Request for existing vs non-existing email
        - Responses should be identical/generic
        """
        # Register a user
        existing_email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        await http_client.post("/auth/register", json={"email": existing_email, "password": password})
        await asyncio.sleep(0.5)
        
        # Request reset for existing email
        payload1 = {"email": existing_email}
        response1 = await http_client.post("/auth/request-password-reset", json=payload1)
        
        # Request reset for non-existing email
        non_existing_email = f"utest_nonexist{test_tag}@mailrbp.com"
        payload2 = {"email": non_existing_email}
        response2 = await http_client.post("/auth/request-password-reset", json=payload2)
        
        # Compare responses
        if response1.status_code != response2.status_code:
            findings_collector.add_finding(
                "/auth/request-password-reset",
                "User enumeration via different status codes",
                "Medium",
                f"Existing email: {response1.status_code}, Non-existing: {response2.status_code}",
                build_curl("POST", f"{API_BASE_URL}/auth/request-password-reset", None, None, payload1),
                "Return identical status codes (200) and generic messages for both existing and non-existing emails to prevent enumeration (OWASP ASVS V2.1.2)."
            )
        
        body1 = parse_json_safe(response1.text)
        body2 = parse_json_safe(response2.text)
        
        msg1 = body1.get("message", "") if body1 else response1.text
        msg2 = body2.get("message", "") if body2 else response2.text
        
        if msg1 != msg2:
            findings_collector.add_finding(
                "/auth/request-password-reset",
                "User enumeration via different error messages",
                "Medium",
                f"Existing: '{msg1[:50]}', Non-existing: '{msg2[:50]}'",
                build_curl("POST", f"{API_BASE_URL}/auth/request-password-reset", None, None, payload1),
                "Use identical generic message: 'If the email exists, a reset link has been sent.' (OWASP ASVS V2.1.2)."
            )
    
    @pytest.mark.asyncio
    async def test_reset_password_random_token(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        J.1: Reset password with random token returns 400/422 (not 500).
        
        Verifies:
        - Random token is handled gracefully
        - Returns 4xx, not 500
        """
        params = {
            "token": f"random_{test_tag}_token",
            "new_password": f"NewP@ss1_{test_tag}"  # Must include numbers per password requirements
        }
        response = await http_client.post("/auth/reset-password", params=params)
        
        if response.status_code == 500:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/reset-password",
                "params": params
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Random reset token causes 500 error",
                request_details,
                response_details,
                "Invalid reset tokens should return 400 Bad Request or 422 Unprocessable Entity, not 500. Check token validation error handling."
            )


# ============================================================================
# TEST GROUP K: Email Verification (/auth/verify)
# ============================================================================

class TestEmailVerificationSecurity:
    """Security tests for email verification endpoint"""
    
    @pytest.mark.asyncio
    async def test_verify_random_token(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        K.1: Random verification token returns 400/404/422 (not 500).
        
        Verifies:
        - Random token is handled gracefully
        - Returns 4xx, not 500
        """
        params = {"token": f"random_{test_tag}_token"}
        response = await http_client.get("/auth/verify", params=params)
        
        if response.status_code == 500:
            request_details = {
                "method": "GET",
                "url": f"{API_BASE_URL}/auth/verify",
                "params": params
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "Random verification token causes 500 error",
                request_details,
                response_details,
                "Invalid verification tokens should return 400 Bad Request, 404 Not Found, or 422 Unprocessable Entity, not 500. Check token validation error handling."
            )


# ============================================================================
# SQL Injection Prevention Tests (Payload Rules)
# ============================================================================

class TestSQLInjectionPrevention:
    """Tests for SQL injection prevention (not exploitation, just robust handling)"""
    
    @pytest.mark.asyncio
    async def test_sqli_like_probes_register(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        SQLi-like probes in registration.
        
        Verifies:
        - No 500 errors
        - No SQL error text in response
        """
        # Test apostrophe email (already tested, but also SQLi-like)
        email = f"utest_test'{test_tag}@mailrbp.com"
        password = f"x' OR '1'='1_{test_tag}"
        
        payload = {
            "email": email,
            "password": password,
            "first_name": f"Sec{test_tag}",
            "last_name": f"Test{test_tag}"
        }
        
        response = await http_client.post("/auth/register", json=payload)
        
        if response.status_code == 500:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/register",
                "json": payload
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "SQLi-like probe causes 500 error in registration",
                request_details,
                response_details,
                "SQLi-like input should be handled gracefully (400/422), not cause 500. Ensure parameterized queries and input sanitization."
            )
        
        # Check for SQL error text
        body_lower = response.text.lower()
        sql_error_indicators = ["sql", "syntax error", "database error", "query failed", "sqlite", "mysql", "postgresql"]
        for indicator in sql_error_indicators:
            if indicator in body_lower:
                findings_collector.add_finding(
                    "/auth/register",
                    f"SQL error text in response: contains '{indicator}'",
                    "High",
                    f"Response contains SQL error indicator: {response.text[:200]}",
                    build_curl("POST", f"{API_BASE_URL}/auth/register", None, None, payload),
                    "Never expose SQL error messages to clients. Use parameterized queries and generic error messages."
                )
    
    @pytest.mark.asyncio
    async def test_sqli_like_probes_login(self, http_client: httpx.AsyncClient, test_tag: str):
        """SQLi-like probes in login"""
        email = f"utest_test'{test_tag}@mailrbp.com"
        password = f"x' OR '1'='1_{test_tag}"
        
        payload = {"email": email, "password": password}
        response = await http_client.post("/auth/login", json=payload)
        
        if response.status_code == 500:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/login",
                "json": payload
            }
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }
            fail_with_details(
                "SQLi-like probe causes 500 error in login",
                request_details,
                response_details,
                "SQLi-like input should be handled gracefully (401), not cause 500. Ensure parameterized queries."
            )
        
        # Check for SQL error text
        body_lower = response.text.lower()
        sql_error_indicators = ["sql", "syntax error", "database error"]
        for indicator in sql_error_indicators:
            if indicator in body_lower:
                findings_collector.add_finding(
                    "/auth/login",
                    f"SQL error text in response: contains '{indicator}'",
                    "High",
                    f"Response contains SQL error indicator: {response.text[:200]}",
                    build_curl("POST", f"{API_BASE_URL}/auth/login", None, None, payload),
                    "Never expose SQL error messages to clients. Use parameterized queries.",
                    asvs_control="V5.3.1",
                    owasp_category="A03"
                )


# ============================================================================
# ADDITIONAL OWASP TEST CASES
# ============================================================================

class TestOWASPInputHandling:
    """OWASP ASVS V5 / OWASP A03:2021 - Injection - Input handling tests"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V5.3.1")
    @pytest.mark.owasp("A03")
    async def test_type_confusion_email_array(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        Type confusion: Send array instead of string for email field.
        
        OWASP ASVS V5.3.1: Verify that the application handles SQL errors safely.
        OWASP A03:2021 - Injection
        
        Verifies:
        - Sending array for email field returns 4xx, never 500
        - No stack traces or ORM errors exposed
        """
        payload = {
            "email": ["not", "a", "string"],  # Type confusion: array instead of string
            "password": f"P@ssw0rd!_{test_tag}"
        }
        
        response = await http_client.post("/auth/register", json=payload)
        
        request_details = {
            "method": "POST",
            "url": f"{API_BASE_URL}/auth/register",
            "headers": dict(response.request.headers),
            "json": payload
        }
        
        assert_status_not_500(
            response,
            request_details,
            "/auth/register",
            "type confusion (array for email)",
            "V5.3.1"
        )
        assert_no_stacktrace(response, request_details, "/auth/register", "V7.4.1")
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V5.3.1")
    @pytest.mark.owasp("A03")
    async def test_type_confusion_password_object(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        Type confusion: Send object instead of string for password field.
        
        OWASP ASVS V5.3.1: Verify that the application handles SQL errors safely.
        OWASP A03:2021 - Injection
        
        Verifies:
        - Sending object for password field returns 4xx, never 500
        - No stack traces exposed
        """
        payload = {
            "email": f"utest+{test_tag}@mailrbp.com",
            "password": {"key": "value"}  # Type confusion: object instead of string
        }
        
        response = await http_client.post("/auth/register", json=payload)
        
        request_details = {
            "method": "POST",
            "url": f"{API_BASE_URL}/auth/register",
            "headers": dict(response.request.headers),
            "json": payload
        }
        
        assert_status_not_500(
            response,
            request_details,
            "/auth/register",
            "type confusion (object for password)",
            "V5.3.1"
        )
        assert_no_stacktrace(response, request_details, "/auth/register", "V7.4.1")


class TestOWASPErrorHandling:
    """OWASP ASVS V7 / OWASP A09:2021 - Security Logging and Monitoring Failures"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V7.4.1")
    @pytest.mark.owasp("A09")
    async def test_no_stacktrace_in_auth_errors(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        Verify all auth endpoints return generic errors without stack traces.
        
        OWASP ASVS V7.4.1: Verify that all error responses are generic.
        OWASP A09:2021 - Security Logging and Monitoring Failures
        
        Tests multiple auth endpoints for stack trace exposure.
        """
        endpoints_to_test = [
            ("/auth/login", {"email": "invalid", "password": "invalid"}, None),
            ("/auth/register", {"email": "invalid", "password": "short"}, None),  # Too short password
            ("/auth/refresh", None, {"refresh_token": "invalid_token"}),
        ]
        
        for endpoint, json_payload, params in endpoints_to_test:
            if json_payload:
                response = await http_client.post(endpoint, json=json_payload)
            elif params:
                response = await http_client.post(endpoint, params=params)
            else:
                continue
            
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}{endpoint}",
                "headers": dict(response.request.headers),
                "json": json_payload if json_payload else None,
                "params": params if params else None
            }
            
            # Only check if we got an error response
            if response.status_code >= 400:
                assert_no_stacktrace(response, request_details, endpoint, "V7.4.1")
                assert_no_sql_error(response, request_details, endpoint, "V5.3.1")


class TestOWASPDataProtection:
    """OWASP ASVS V8 / OWASP A02:2021 - Cryptographic Failures"""
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V8.2.1")
    @pytest.mark.owasp("A02")
    async def test_tokens_not_echoed_in_errors(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        Verify tokens are not echoed in error responses.
        
        OWASP ASVS V8.2.1: Verify that sensitive data is not exposed in error messages.
        OWASP A02:2021 - Cryptographic Failures
        
        Verifies:
        - Invalid token errors don't echo the token back
        - Access tokens not in error response body
        """
        # Test with invalid token
        invalid_token = f"invalid_token_{test_tag}"
        headers = {"Authorization": f"Bearer {invalid_token}"}
        response = await http_client.get("/auth/me", headers=headers)
        
        if response.status_code >= 400:
            body_lower = response.text.lower()
            if invalid_token.lower() in body_lower:
                request_details = {
                    "method": "GET",
                    "url": f"{API_BASE_URL}/auth/me",
                    "headers": headers
                }
                findings_collector.add_finding(
                    "/auth/me",
                    "Token echoed in error response",
                    "Medium",
                    f"Error response contains submitted token",
                    build_curl("GET", f"{API_BASE_URL}/auth/me", headers, None, None),
                    "Never echo tokens or sensitive data in error responses per OWASP ASVS V8.2.1.",
                    asvs_control="V8.2.1",
                    owasp_category="A02"
                )
    
    @pytest.mark.asyncio
    @pytest.mark.asvs("V3.4.1")
    @pytest.mark.owasp("A02")
    async def test_all_token_responses_have_cache_control(self, http_client: httpx.AsyncClient, test_tag: str):
        """
        Verify all responses containing tokens include Cache-Control: no-store.
        
        OWASP ASVS V3.4.1: Verify that sensitive data is not cached.
        OWASP A02:2021 - Cryptographic Failures
        
        Tests login and token endpoints.
        """
        email = f"utest+{test_tag}@mailrbp.com"
        password = f"P@ssw0rd!_{test_tag}"
        
        # Register user
        await http_client.post("/auth/register", json={"email": email, "password": password})
        await asyncio.sleep(0.5)
        
        # Test login response
        login_response = await http_client.post("/auth/login", json={"email": email, "password": password})
        if login_response.status_code == 200:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/login",
                "headers": dict(login_response.request.headers),
                "json": {"email": email, "password": password}
            }
            assert_cache_control_no_store(login_response, request_details, "/auth/login", "V3.4.1")
        
        # Test OAuth2 token response
        form_data = {
            "username": email,
            "password": password,
            "grant_type": "password"
        }
        token_response = await http_client.post("/auth/token", data=form_data)
        if token_response.status_code == 200:
            request_details = {
                "method": "POST",
                "url": f"{API_BASE_URL}/auth/token",
                "headers": dict(token_response.request.headers),
                "form": form_data
            }
            assert_cache_control_no_store(token_response, request_details, "/auth/token", "V3.4.1")
