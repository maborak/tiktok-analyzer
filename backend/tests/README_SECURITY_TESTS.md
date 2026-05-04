# Security Test Suite for Phoveus API

## Overview

This is a comprehensive pentest-grade pytest suite for testing authentication endpoints. The suite implements OWASP ASVS / OWASP Top 10 security checks and validates RFC compliance.

## Test Coverage

### Test Groups

- **A. Registration** (`/auth/register`)
  - Unique user creation with tag-embedded data
  - Duplicate registration handling
  - Apostrophe email handling (RFC 5322)

- **B. Login** (`/auth/login`)
  - User enumeration prevention
  - Brute-force / lockout protection

- **C. OAuth2 Token** (`/auth/token`)
  - Token generation with correct credentials (RFC 6749)
  - Unauthorized handling (RFC 6750)

- **D. Authenticated Endpoints** (`/auth/me`)
  - Unauthenticated access (401)
  - Valid token handling
  - Malformed token handling

- **E. Refresh Token** (`/auth/refresh`)
  - Valid refresh token
  - Access token used as refresh token
  - Random token handling

- **F. Logout** (`/auth/logout`)
  - Token invalidation

- **G. Change Password** (`/auth/change-password`)
  - Unauthenticated access
  - Wrong current password
  - Successful password change

- **H. API Keys** (`/auth/api-keys`)
  - Unauthenticated access
  - API key creation
  - Invalid rate_limit handling

- **I & J. Password Reset** (`/auth/request-password-reset`, `/auth/reset-password`)
  - User enumeration prevention
  - Random token handling

- **K. Email Verification** (`/auth/verify`)
  - Random token handling

- **SQL Injection Prevention**
  - SQLi-like probes in registration and login
  - No SQL error text exposure

## Configuration

### Environment Variables

- `API_BASE_URL` (default: `http://localhost:8000`): Base URL of the API
- `TEST_EMAIL` (optional): Existing user email for tests
- `TEST_PASSWORD` (optional): Existing user password for tests

### Example

```bash
export API_BASE_URL="http://localhost:8000"
pytest tests/test_auth_security.py -v
```

## Running Tests

### Basic Run

```bash
pytest tests/test_auth_security.py -v
```

### With Parallel Execution (pytest-xdist)

```bash
pytest tests/test_auth_security.py -v -n auto
```

### Run Specific Test Group

```bash
# Registration tests only
pytest tests/test_auth_security.py::TestRegistrationSecurity -v

# Login tests only
pytest tests/test_auth_security.py::TestLoginSecurity -v
```

### Run with Markers

```bash
# All API tests
pytest -m api -v
```

## Test Features

### Unique Tags

Every test run uses a unique 5-letter random tag (generated with `secrets.choice()`) to:
- Avoid database false positives from previously injected test data
- Enable parallel test execution
- Ensure test isolation

Tags are embedded in:
- Email addresses: `securitytest+<tag>@example.com`
- Passwords: `P@ssw0rd!_<tag>`
- Names: `Sec<tag>`, `Test<tag>`
- API key names: `test_key_<tag>`

### Security Findings Collector

The test suite includes a findings collector that:
- Stores security issues discovered during testing
- Categorizes findings by risk level (Low, Medium, High)
- Provides curl commands for reproduction
- Includes security recommendations
- Prints a summary at the end of the test session

### Detailed Failure Reporting

When a test fails, the output includes:
1. **Request Details**: Method, URL, headers, query params, JSON/form body
2. **Response Details**: Status code, headers, body (pretty JSON if possible), elapsed time
3. **CURL Reproduction**: Executable curl command to reproduce the issue
4. **Security Recommendation**: How to fix and why it matters

## RFC Compliance

The test suite validates compliance with:

- **RFC 9110/9111**: HTTP semantics
- **RFC 6750**: Bearer token usage (WWW-Authenticate challenge, 401 behavior)
- **RFC 6749**: OAuth2 password flow
- **RFC 7519**: JWT (if tokens are JWT)
- **RFC 5322**: Email format (apostrophe in local-part)

## OWASP Alignment

Tests align with:

- **OWASP ASVS V2.1.2**: User enumeration prevention
- **OWASP ASVS V2.1.3**: Account lockout / rate limiting
- **OWASP ASVS V3.4.1**: Cache-Control headers for tokens
- **OWASP Top 10**: SQL injection prevention, authentication bypass

## Example Output

```
tests/test_auth_security.py::TestRegistrationSecurity::test_register_unique_user PASSED
tests/test_auth_security.py::TestLoginSecurity::test_login_user_enumeration PASSED

================================================================================
SECURITY FINDINGS SUMMARY
================================================================================

[Medium RISK] - 2 finding(s)
--------------------------------------------------------------------------------

1. User enumeration via different status codes
   Endpoint: /auth/login
   Evidence: Existing user wrong password: 401, Non-existing user: 401
   CURL Repro: curl -X POST 'http://localhost:8000/auth/login' ...
   Recommendation: Return identical status codes (401) and generic error messages...

2. Missing WWW-Authenticate header in 401 response
   Endpoint: /auth/me
   Evidence: 401 response without WWW-Authenticate header
   CURL Repro: curl -X GET 'http://localhost:8000/auth/me' ...
   Recommendation: Add WWW-Authenticate: Bearer header to 401 responses...

================================================================================
Total findings: 2
================================================================================
```

## Notes

- Tests are designed to be **non-destructive** - they create test users but use unique tags
- Tests are **pytest-xdist friendly** - safe for parallel execution
- All payloads include unique tags to avoid database conflicts
- SQL injection tests are **probes only** - they verify robust handling, not exploitation
- Findings are collected but don't fail tests (unless critical issues like 500 errors)

## Dependencies

Required packages (already in `requirements.txt`):
- `pytest>=9.0.2`
- `pytest-asyncio>=1.3.0`
- `httpx>=0.28.1`

Optional for parallel execution:
- `pytest-xdist` (install separately: `pip install pytest-xdist`)
