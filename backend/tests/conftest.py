"""
Pytest configuration and shared fixtures for security testing.

This module provides:
- Helper functions for test data generation (rand_tag, mask_secret)
- Request/response utilities (build_curl, fail_with_details, parse_json_safe)
- Findings collector for security issues
- HTTP client fixtures
- Configuration from environment variables
"""
import os
import sys
import secrets
import string
import json
import pytest
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
import httpx
from urllib.parse import urlencode

# Load environment variables from .env file before reading config
try:
    from dotenv import load_dotenv
    # Look for .env file in project root (parent of tests directory)
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env file from: {env_path}", file=sys.stderr)
    else:
        # Try to load from current directory as fallback
        result = load_dotenv()
        if result:
            print("✅ Loaded .env file from current directory", file=sys.stderr)
except ImportError:
    # python-dotenv is optional
    pass
except Exception as e:
    print(f"⚠️  Could not load .env file: {e}", file=sys.stderr)

# Configuration from environment variables
# Construct API_BASE_URL from PHOVEU_BACKEND_UVI_HOST and PHOVEU_BACKEND_UVI_PORT
# If PHOVEU_BACKEND_API_BASE_URL is explicitly set, use it; otherwise construct from host/port
_api_base_url = os.getenv("PHOVEU_BACKEND_API_BASE_URL")
if not _api_base_url:
    _uvi_host = os.getenv("PHOVEU_BACKEND_UVI_HOST", "0.0.0.0")
    _uvi_port = os.getenv("PHOVEU_BACKEND_UVI_PORT", "9000")
    # Convert 0.0.0.0 to localhost for API URL (0.0.0.0 is not valid for HTTP requests)
    if _uvi_host == "0.0.0.0":
        _api_host = "localhost"
    else:
        _api_host = _uvi_host
    _api_base_url = f"http://{_api_host}:{_uvi_port}"
API_BASE_URL = _api_base_url
TEST_EMAIL = os.getenv("PHOVEU_BACKEND_TEST_EMAIL")
TEST_PASSWORD = os.getenv("PHOVEU_BACKEND_TEST_PASSWORD")
RATE_LIMIT_BYPASS_KEY = os.getenv("PHOVEU_BACKEND_RATE_LIMIT_BYPASS_KEY", "")

# Print to stderr so it's visible even when pytest suppresses stdout
print(f"API_BASE_URL: {API_BASE_URL}", file=sys.stderr)

class SecurityFinding:
    """Represents a security finding discovered during testing"""
    
    def __init__(
        self,
        endpoint: str,
        title: str,
        risk_level: str,
        evidence: str,
        curl_repro: str,
        recommendation: str,
        asvs_control: Optional[str] = None,
        owasp_category: Optional[str] = None,
        rfc_reference: Optional[str] = None
    ):
        self.endpoint = endpoint
        self.title = title
        self.risk_level = risk_level  # Low, Medium, High
        self.evidence = evidence
        self.curl_repro = curl_repro
        self.recommendation = recommendation
        self.asvs_control = asvs_control  # e.g., "V2.1.2"
        self.owasp_category = owasp_category  # e.g., "A07"
        self.rfc_reference = rfc_reference  # e.g., "6750"
        self.timestamp = datetime.now().isoformat()
    
    def __repr__(self):
        return f"<SecurityFinding: {self.title} ({self.risk_level})>"


class FindingsCollector:
    """Collects security findings during test execution"""
    
    def __init__(self):
        self.findings: List[SecurityFinding] = []
    
    def add_finding(
        self,
        endpoint: str,
        title: str,
        risk_level: str,
        evidence: str,
        curl_repro: str,
        recommendation: str,
        asvs_control: Optional[str] = None,
        owasp_category: Optional[str] = None,
        rfc_reference: Optional[str] = None
    ):
        """Add a security finding"""
        finding = SecurityFinding(
            endpoint=endpoint,
            title=title,
            risk_level=risk_level,
            evidence=evidence,
            curl_repro=curl_repro,
            recommendation=recommendation,
            asvs_control=asvs_control,
            owasp_category=owasp_category,
            rfc_reference=rfc_reference
        )
        self.findings.append(finding)
    
    def get_findings(self) -> List[SecurityFinding]:
        """Get all collected findings"""
        return self.findings
    
    def clear(self):
        """Clear all findings"""
        self.findings.clear()
    
    def print_summary(self):
        """Print a summary of all findings grouped by OWASP category and risk level"""
        if not self.findings:
            return
        
        print("\n" + "=" * 80)
        print("SECURITY FINDINGS SUMMARY (OWASP-ALIGNED)")
        print("=" * 80)
        
        # Group by OWASP category, then by risk level
        by_owasp = {}
        by_risk = {"High": [], "Medium": [], "Low": []}
        
        for finding in self.findings:
            # Group by risk
            by_risk[finding.risk_level].append(finding)
            
            # Group by OWASP category
            category = finding.owasp_category or "Other"
            if category not in by_owasp:
                by_owasp[category] = []
            by_owasp[category].append(finding)
        
        # Print by OWASP category
        print("\n[BY OWASP TOP 10 CATEGORY]")
        print("-" * 80)
        for category in sorted(by_owasp.keys()):
            findings = by_owasp[category]
            print(f"\n{category}: {len(findings)} finding(s)")
            for finding in findings:
                asvs_ref = f" (ASVS {finding.asvs_control})" if finding.asvs_control else ""
                print(f"  - {finding.title}{asvs_ref} [{finding.risk_level}]")
        
        # Print by risk level
        print("\n[BY RISK LEVEL]")
        print("-" * 80)
        for risk_level in ["High", "Medium", "Low"]:
            findings = by_risk[risk_level]
            if not findings:
                continue
            
            print(f"\n[{risk_level} RISK] - {len(findings)} finding(s)")
            print("-" * 80)
            
            for i, finding in enumerate(findings, 1):
                print(f"\n{i}. {finding.title}")
                print(f"   Endpoint: {finding.endpoint}")
                if finding.owasp_category:
                    print(f"   OWASP: {finding.owasp_category}")
                if finding.asvs_control:
                    print(f"   ASVS: {finding.asvs_control}")
                if finding.rfc_reference:
                    print(f"   RFC: {finding.rfc_reference}")
                print(f"   Evidence: {finding.evidence}")
                print(f"   CURL Repro: {finding.curl_repro}")
                print(f"   Recommendation: {finding.recommendation}")
        
        # Summary statistics
        print("\n" + "=" * 80)
        print(f"Total findings: {len(self.findings)}")
        print(f"  High: {len(by_risk['High'])}, Medium: {len(by_risk['Medium'])}, Low: {len(by_risk['Low'])}")
        print("=" * 80 + "\n")


# Global findings collector (session-scoped)
_findings_collector = FindingsCollector()

# Export for direct import in tests
findings_collector = _findings_collector


def rand_tag() -> str:
    """
    Generate a secure 5-letter random tag (lowercase).
    
    Uses secrets.choice() for cryptographically secure randomness.
    This ensures each test run uses unique data to avoid false positives
    from previously injected test data in the database.
    
    Returns:
        str: 5 lowercase letters (e.g., "abcde")
    """
    alphabet = string.ascii_lowercase
    return ''.join(secrets.choice(alphabet) for _ in range(5))


def mask_secret(s: str, show_last: int = 3) -> str:
    """
    Mask a secret value for safe logging.
    
    Args:
        s: The secret string to mask
        show_last: Number of characters to show at the end (default: 3)
    
    Returns:
        str: Masked string (e.g., "***xyz" for "passwordxyz")
    """
    if not s or len(s) <= show_last:
        return "***"
    return "*" * (len(s) - show_last) + s[-show_last:]


def parse_json_safe(text: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort JSON parsing with fallback.
    
    Args:
        text: Text that might be JSON
    
    Returns:
        Parsed JSON dict, or None if parsing fails
    """
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def build_curl(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    form_data: Optional[Dict[str, str]] = None
) -> str:
    """
    Build a reproducible curl command string.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: Base URL
        headers: HTTP headers dict
        params: Query parameters dict
        json_data: JSON body data
        form_data: Form data (application/x-www-form-urlencoded)
    
    Returns:
        str: curl command string that can be executed
    """
    parts = ["curl", "-X", method]
    
    # Add headers
    if headers:
        for key, value in headers.items():
            # Mask Authorization tokens in curl output
            if key.lower() == "authorization" and value.startswith("Bearer "):
                masked = f"Bearer {mask_secret(value[7:])}"
                parts.append(f"-H '{key}: {masked}'")
            else:
                # Escape single quotes in header values
                escaped_value = value.replace("'", "'\\''")
                parts.append(f"-H '{key}: {escaped_value}'")
    
    # Add query parameters
    if params:
        query_string = urlencode(params)
        url = f"{url}?{query_string}"
    
    # Add body
    if json_data:
        json_str = json.dumps(json_data, separators=(',', ':'))
        # Escape single quotes and newlines
        json_str = json_str.replace("'", "'\\''").replace("\n", "\\n")
        parts.append("-H 'Content-Type: application/json'")
        parts.append(f"-d '{json_str}'")
    elif form_data:
        form_str = urlencode(form_data)
        parts.append("-H 'Content-Type: application/x-www-form-urlencoded'")
        parts.append(f"-d '{form_str}'")
    
    parts.append(f"'{url}'")
    
    return " \\\n  ".join(parts)


def fail_with_details(
    title: str,
    request_details: Dict[str, Any],
    response_details: Dict[str, Any],
    recommendation: str
):
    """
    Fail a test with detailed request/response information and curl repro.
    
    Args:
        title: Test failure title
        request_details: Dict with method, url, headers, params, json/form data
        response_details: Dict with status, headers, body, elapsed_time
        recommendation: Security recommendation
    """
    method = request_details.get("method", "UNKNOWN")
    url = request_details.get("url", "")
    headers = request_details.get("headers", {})
    params = request_details.get("params")
    json_data = request_details.get("json")
    form_data = request_details.get("form")
    
    status = response_details.get("status", "UNKNOWN")
    response_headers = response_details.get("headers", {})
    response_body = response_details.get("body", "")
    elapsed = response_details.get("elapsed_time", 0)
    
    # Build curl command
    curl_cmd = build_curl(method, url, headers, params, json_data, form_data)
    
    # Parse response body if JSON
    response_json = parse_json_safe(response_body)
    if response_json:
        response_body_pretty = json.dumps(response_json, indent=2)
    else:
        response_body_pretty = response_body[:500]  # Truncate if too long
    
    # Build failure message
    msg = f"""
{'=' * 80}
TEST FAILURE: {title}
{'=' * 80}

REQUEST DETAILS:
  Method: {method}
  URL: {url}
  Headers:
{chr(10).join(f'    {k}: {mask_secret(v) if "authorization" in k.lower() or "token" in k.lower() else v}' for k, v in headers.items())}
  Query Params: {params or 'None'}
  JSON Body: {json.dumps(json_data, indent=2) if json_data else 'None'}
  Form Data: {form_data or 'None'}

RESPONSE DETAILS:
  Status: {status}
  Elapsed Time: {elapsed:.3f}s
  Headers:
{chr(10).join(f'    {k}: {v}' for k, v in response_headers.items())}
  Body:
{response_body_pretty}

CURL REPRODUCTION:
{curl_cmd}

SECURITY RECOMMENDATION:
{recommendation}
{'=' * 80}
"""
    
    pytest.fail(msg)


# ============================================================================
# Security Assertion Helpers (OWASP-aligned)
# ============================================================================

def assert_no_stacktrace(
    response: httpx.Response,
    request_details: Dict[str, Any],
    endpoint: str,
    asvs_control: str = "V7.4.1"
):
    """
    Assert that error response does not contain stack traces or ORM errors.
    
    OWASP ASVS V7.4.1: Verify that all error responses are generic and do not
    reveal implementation details.
    
    Args:
        response: HTTP response object
        request_details: Request details dict for fail_with_details
        endpoint: Endpoint path for findings
        asvs_control: OWASP ASVS control identifier
    """
    body_lower = response.text.lower()
    stacktrace_indicators = [
        "traceback", "stack trace", "file \"", "line ", "exception:",
        "sqlalchemy", "orm", "database error", "query failed"
    ]
    
    for indicator in stacktrace_indicators:
        if indicator in body_lower:
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds() if hasattr(response, 'elapsed') else 0
            }
            fail_with_details(
                f"Stack trace or ORM error exposed in {endpoint} response",
                request_details,
                response_details,
                f"Error responses must not expose stack traces or ORM errors per OWASP ASVS {asvs_control}. "
                f"Use generic error messages and log detailed errors server-side only."
            )


def assert_no_sql_error(
    response: httpx.Response,
    request_details: Dict[str, Any],
    endpoint: str,
    asvs_control: str = "V5.3.1"
):
    """
    Assert that response does not contain SQL error text.
    
    OWASP ASVS V5.3.1: Verify that the application handles SQL errors safely.
    
    Args:
        response: HTTP response object
        request_details: Request details dict for fail_with_details
        endpoint: Endpoint path for findings
        asvs_control: OWASP ASVS control identifier
    """
    body_lower = response.text.lower()
    sql_error_indicators = [
        "sql", "syntax error", "database error", "query failed",
        "sqlite", "mysql", "postgresql", "constraint", "foreign key"
    ]
    
    for indicator in sql_error_indicators:
        if indicator in body_lower:
            response_details = {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "elapsed_time": response.elapsed.total_seconds() if hasattr(response, 'elapsed') else 0
            }
            fail_with_details(
                f"SQL error text exposed in {endpoint} response",
                request_details,
                response_details,
                f"Never expose SQL error messages to clients per OWASP ASVS {asvs_control}. "
                f"Use parameterized queries and generic error messages."
            )


def assert_generic_auth_error(
    response: httpx.Response,
    request_details: Dict[str, Any],
    endpoint: str,
    asvs_control: str = "V2.1.2"
):
    """
    Assert that authentication error messages are generic.
    
    OWASP ASVS V2.1.2: Verify that authentication error responses are generic.
    
    Args:
        response: HTTP response object
        request_details: Request details dict for fail_with_details
        endpoint: Endpoint path for findings
        asvs_control: OWASP ASVS control identifier
    """
    if response.status_code in [401, 403]:
        body = parse_json_safe(response.text)
        if body:
            detail = body.get("detail", body.get("message", ""))
            if detail:
                # Check for overly specific error messages
                specific_indicators = [
                    "user not found", "invalid user", "user does not exist",
                    "password incorrect", "wrong password", "invalid password"
                ]
                detail_lower = detail.lower()
                for indicator in specific_indicators:
                    if indicator in detail_lower:
                        response_details = {
                            "status": response.status_code,
                            "headers": dict(response.headers),
                            "body": response.text,
                            "elapsed_time": response.elapsed.total_seconds() if hasattr(response, 'elapsed') else 0
                        }
                        findings_collector.add_finding(
                            endpoint,
                            f"Specific authentication error message may enable enumeration",
                            "Medium",
                            f"Error message: '{detail}'",
                            build_curl(
                                request_details.get("method", "POST"),
                                request_details.get("url", ""),
                                request_details.get("headers"),
                                request_details.get("params"),
                                request_details.get("json"),
                                request_details.get("form")
                            ),
                            f"Use generic error messages like 'Invalid email or password' per OWASP ASVS {asvs_control} "
                            f"to prevent user enumeration attacks.",
                            asvs_control=asvs_control,
                            owasp_category="A07"
                        )


def assert_cache_control_no_store(
    response: httpx.Response,
    request_details: Dict[str, Any],
    endpoint: str,
    asvs_control: str = "V3.4.1"
):
    """
    Assert that responses containing tokens include Cache-Control: no-store.
    
    OWASP ASVS V3.4.1: Verify that sensitive data is not cached.
    
    Args:
        response: HTTP response object
        request_details: Request details dict for findings
        endpoint: Endpoint path for findings
        asvs_control: OWASP ASVS control identifier
    """
    body = parse_json_safe(response.text)
    if body and ("token" in json.dumps(body).lower() or "access_token" in json.dumps(body).lower()):
        if "Cache-Control" not in response.headers:
            findings_collector.add_finding(
                endpoint,
                "Missing Cache-Control header in response containing tokens",
                "Medium",
                "Response contains tokens but no Cache-Control header",
                build_curl(
                    request_details.get("method", "GET"),
                    request_details.get("url", ""),
                    request_details.get("headers"),
                    request_details.get("params"),
                    request_details.get("json"),
                    request_details.get("form")
                ),
                f"Add Cache-Control: no-store header to responses containing tokens per OWASP ASVS {asvs_control}.",
                asvs_control=asvs_control,
                owasp_category="A02"
            )


def assert_status_not_500(
    response: httpx.Response,
    request_details: Dict[str, Any],
    endpoint: str,
    context: str = "error handling",
    asvs_control: str = "V7.4.1"
):
    """
    Assert that response status is not 500 (internal server error).
    
    OWASP ASVS V7.4.1: Verify that error responses are handled gracefully.
    
    Args:
        response: HTTP response object
        request_details: Request details dict for fail_with_details
        endpoint: Endpoint path for findings
        context: Context description for error message
        asvs_control: OWASP ASVS control identifier
    """
    if response.status_code == 500:
        response_details = {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": response.text,
            "elapsed_time": response.elapsed.total_seconds() if hasattr(response, 'elapsed') else 0
        }
        fail_with_details(
            f"{endpoint} returns 500 Internal Server Error for {context}",
            request_details,
            response_details,
            f"Invalid input should return 4xx (400/401/422), not 500 per OWASP ASVS {asvs_control}. "
            f"Check error handling and input validation."
        )


def pytest_configure(config):  # noqa: ARG001
    """Pytest hook to print configuration when tests start"""
    print(f"\n🔧 API_BASE_URL: {API_BASE_URL}", file=sys.stderr)


@pytest.fixture(scope="session")
def findings_collector_fixture() -> FindingsCollector:
    """Session-scoped findings collector"""
    return _findings_collector


@pytest.fixture(scope="session", autouse=True)
def print_findings_summary(findings_collector_fixture: FindingsCollector):  # noqa: F811
    """Print findings summary at end of test session"""
    yield
    findings_collector_fixture.print_summary()


@pytest.fixture
def http_client() -> httpx.AsyncClient:
    """Create an async HTTP client for testing"""
    return httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0)


@pytest.fixture
def test_tag() -> str:
    """Generate a unique tag for this test run"""
    return rand_tag()


@pytest.fixture
def existing_user_credentials() -> Optional[Dict[str, str]]:
    """Get existing user credentials from environment if available"""
    if TEST_EMAIL and TEST_PASSWORD:
        return {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    return None
