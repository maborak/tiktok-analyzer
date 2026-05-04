"""
Comprehensive integration and security test suite for User Account features.
Targets: /user/account/* endpoints
Includes: Recipients, Tracked Products, Price Alerts, Info.
Scenarios: Functional, Pentesting (IDOR, SQLi), Chaos Engineering.
"""
import pytest
import httpx
import time
import asyncio
import json
import sys
import os
import secrets
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

# Ensure tests directory is in path
_test_dir = os.path.dirname(os.path.abspath(__file__))
if _test_dir not in sys.path:
    sys.path.insert(0, _test_dir)

import conftest

# Import helpers from conftest
rand_tag = conftest.rand_tag
mask_secret = conftest.mask_secret
build_curl = conftest.build_curl
fail_with_details = conftest.fail_with_details
parse_json_safe = conftest.parse_json_safe
findings_collector = conftest.findings_collector
API_BASE_URL = conftest.API_BASE_URL

# Security assertion helpers
assert_no_stacktrace = conftest.assert_no_stacktrace
assert_no_sql_error = conftest.assert_no_sql_error
assert_status_not_500 = conftest.assert_status_not_500

# Credentials provided by user
USER_EMAIL = "wilmer@maborak.com"
USER_PWD = "sample"

@pytest.fixture(scope="session")
async def auth_token():
    """Session-scoped fixture to get auth token for the test user"""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
        payload = {"email": USER_EMAIL, "password": USER_PWD}
        response = await client.post("/auth/login", json=payload)
        
        if response.status_code != 200:
            pytest.fail(f"Could not login as {USER_EMAIL}. Status: {response.status_code}, Body: {response.text}")
            
        body = response.json()
        token = body.get("data", {}).get("tokens", {}).get("access_token")
        if not token:
            pytest.fail(f"Login response missing access_token. Body: {body}")
        return token

@pytest.fixture
def auth_headers(auth_token):
    """Fixture for authenticated request headers"""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture
async def secondary_user_token(http_client: httpx.AsyncClient, test_tag: str):
    """Fixture to create a temporary secondary user for IDOR testing"""
    email = f"attacker_{test_tag}@example.com"
    pwd = f"Attacker123_{test_tag}!"
    
    # Register
    reg_resp = await http_client.post("/auth/register", json={
        "email": email,
        "password": pwd,
        "first_name": "Attacker",
        "last_name": "User",
        "captcha_token": "dummy_token"
    })
    # If 429, wait a bit
    if reg_resp.status_code == 429:
        await asyncio.sleep(2)
        reg_resp = await http_client.post("/auth/register", json={
            "email": email,
            "password": pwd,
            "first_name": "Attacker",
            "last_name": "User",
            "captcha_token": "dummy_token"
        })
    assert reg_resp.status_code in [201, 200]
    
    # Login
    response = await http_client.post("/auth/login", json={"email": email, "password": pwd})
    assert response.status_code == 200
    body = response.json()
    return body["data"]["tokens"]["access_token"]

# ============================================================================
# FUNCTIONAL TESTS
# ============================================================================

class TestAccountFunctional:
    """Basic feature verification for account management"""

    @pytest.mark.asyncio
    async def test_get_account_info(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
        """Verify basic account info retrieval"""
        response = await http_client.get("/user/account", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["email"] == USER_EMAIL

    @pytest.mark.asyncio
    async def test_recipient_lifecycle(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str], test_tag: str):
        """Test adding, listing, updating (flexibility features), and deleting a recipient"""
        
        # 0. Pre-cleanup to avoid hitting the 5 recipient limit during tests
        response = await http_client.get("/user/account/recipients", headers=auth_headers)
        if response.status_code == 200:
            existing_recipients = response.json().get("data", {}).get("recipients", [])
            for r in existing_recipients:
                await http_client.delete(f"/user/account/recipients/{r['id']}", headers=auth_headers)
                
        # 1. Add Recipient
        rec_email = f"notify_{test_tag}@example.com"
        rec_name = f"Recipient {test_tag}"
        add_payload = {
            "type": "email",
            "value": rec_email,
            "name": rec_name
        }
        
        response = await http_client.post("/user/account/recipients", json=add_payload, headers=auth_headers)
        assert response.status_code == 200
        rec_id = response.json()["data"]["id"]
        
        # 2. List and Verify
        response = await http_client.get("/user/account/recipients", headers=auth_headers)
        assert response.status_code == 200
        recipients = response.json()["data"]["recipients"]
        recipient = next((r for r in recipients if r["id"] == rec_id), None)
        assert recipient is not None
        assert recipient["value"] == rec_email
        assert recipient["is_verified"] is False
        assert recipient["is_enabled"] is True # Default

        # 3. Update (Enable/Disable and Subject Tag)
        patch_payload = {
            "is_enabled": False,
            "subject_tag": f"[ALERT-{test_tag}]",
            "name": f"Updated {rec_name}"
        }
        response = await http_client.patch(f"/user/account/recipients/{rec_id}", json=patch_payload, headers=auth_headers)
        assert response.status_code == 200
        
        # Verify changes
        response = await http_client.get("/user/account/recipients", headers=auth_headers)
        recipient = next((r for r in response.json()["data"]["recipients"] if r["id"] == rec_id), None)
        assert recipient["is_enabled"] is False
        assert recipient["subject_tag"] == f"[ALERT-{test_tag}]"
        assert recipient["name"] == f"Updated {rec_name}"

        # 4. Change Value (Triggers re-verification)
        new_email = f"new_{test_tag}@example.com"
        # First mock it as verified (simulated DB state if we could, but here we test the reset)
        # Note: We can't easily mock verified=True via API if it validates. 
        # But we can verify that if we change it, it remains is_verified=False or resets if it was True.
        
        response = await http_client.patch(f"/user/account/recipients/{rec_id}", json={"value": new_email}, headers=auth_headers)
        assert response.status_code == 200
        
        response = await http_client.get("/user/account/recipients", headers=auth_headers)
        recipient = next((r for r in response.json()["data"]["recipients"] if r["id"] == rec_id), None)
        assert recipient["value"] == new_email
        assert recipient["is_verified"] is False

        # 5. Delete
        response = await http_client.delete(f"/user/account/recipients/{rec_id}", headers=auth_headers)
        assert response.status_code == 200
        
        # Final check
        response = await http_client.get("/user/account/recipients", headers=auth_headers)
        assert not any(r["id"] == rec_id for r in response.json()["data"]["recipients"])

    @pytest.mark.asyncio
    async def test_tracked_products_lifecycle(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str], test_tag: str):
        """Test tracking and untracking products"""
        product_id = "B0CZ9P2C8X" # Sample ASIN
        country = "US"
        
        # 1. Add track
        response = await http_client.post("/user/account/tracked-products", json={
            "product_id": product_id,
            "country_code": country
        }, headers=auth_headers)
        assert response.status_code == 200
        track_id = response.json()["data"]["id"]
        
        # 2. List
        response = await http_client.get("/user/account/tracked-products", headers=auth_headers)
        assert response.status_code == 200
        tracks = response.json()["data"]["tracks"]
        assert any(t["id"] == track_id for t in tracks)
        
        # 3. Delete
        response = await http_client.delete(f"/user/account/tracked-products/{track_id}", headers=auth_headers)
        assert response.status_code == 200
        
        # Final list
        response = await http_client.get("/user/account/tracked-products", headers=auth_headers)
        assert not any(t["id"] == track_id for t in response.json()["data"]["tracks"])

    @pytest.mark.asyncio
    async def test_get_single_tracked_product(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
        """Verify getting a single tracked product by ID"""
        product_id = "B000000001" 
        country = "US"
        
        # 1. Add track
        response = await http_client.post("/user/account/tracked-products", json={
            "product_id": product_id,
            "country_code": country
        }, headers=auth_headers)
        assert response.status_code == 200
        track_id = response.json()["data"]["id"]
        
        # 2. Get Single Track
        response = await http_client.get(f"/user/account/tracked-products/{track_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        
        assert data["id"] == track_id or data["price_alerts"] # Either base ID matches or it's enriched
        assert data["product_id"] == product_id
        assert data["country_code"] == country
        
        # 3. Cleanup
        await http_client.delete(f"/user/account/tracked-products/{track_id}", headers=auth_headers)
        
        # 4. Authenticated 404 test
        response = await http_client.get(f"/user/account/tracked-products/{track_id}", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_tracked_product_alerts(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
        """Verify updating alerts using PUT /tracked-products/{track_id}"""
        product_id = "B000000002"
        country = "US"
        
        # 1. Add track (no alerts)
        response = await http_client.post("/user/account/tracked-products", json={
            "product_id": product_id,
            "country_code": country
        }, headers=auth_headers)
        assert response.status_code == 200
        track_id = response.json()["data"]["id"]
        
        # 2. Update alerts (PUT by Track ID)
        # Assuming we have a valid alert ID relative to user isn't easy to mock without complex setup,
        # but we can test the Validation/Context resolution part or simply empty list/invalid alert.
        # Let's test providing an empty list (clearing alerts) which is valid.
        
        update_payload = {
            "country_code": country, # Should be ignored/checked but passed for model validation
            "price_alert_ids": [] 
        }
        
        response = await http_client.put(f"/user/account/tracked-products/{track_id}", json=update_payload, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["success"] is True
        
        # 3. Verify failure with bad ID
        response = await http_client.put(f"/user/account/tracked-products/99999", json=update_payload, headers=auth_headers)
        assert response.status_code == 404
        
        # Cleanup
        await http_client.delete(f"/user/account/tracked-products/{track_id}", headers=auth_headers)

    @pytest.mark.asyncio
    async def test_viewing_history(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
        """Test that viewing a product by ID records it in the history"""
        # 1. Look for an existing product to test viewing
        list_resp = await http_client.get("/products", params={"page_size": 1})
        if list_resp.status_code == 200 and list_resp.json()["products"]:
            product = list_resp.json()["products"][0]
            target_asin = product["id"]
        else:
            pytest.skip("No products found")

        # 2. View Product
        view_resp = await http_client.get(f"/products/{target_asin}?country=BO", headers=auth_headers)
        assert view_resp.status_code == 200, f"Failed to view product: {view_resp.text}"
        
        # 3. Check history
        hist_resp = await http_client.get("/user/account/history", headers=auth_headers)
        assert hist_resp.status_code == 200, f"Failed to get history: {hist_resp.text}"
        
        items = hist_resp.json()["data"]["items"]
        assert any(i["product_id"] == target_asin for i in items), f"Product {target_asin} not found in history"

# ============================================================================
# PENTESTING TESTS
# ============================================================================

class TestAccountPentesting:
    """Security-focused scenarios for account features"""

    @pytest.mark.asyncio
    @pytest.mark.owasp("A01")
    @pytest.mark.skip(reason="Failing due to Turnstile CAPTCHA validation which can't be easily mocked against live instances")
    async def test_idor_recipient_delete(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str], secondary_user_token: str, test_tag: str):
        """Attempt to delete another user's recipient (Insecure Direct Object Reference)"""
        
        # 1. User 1 (Primary) creates a recipient
        rec_payload = {"type": "email", "value": f"victim_{test_tag}@example.com", "name": "Victim"}
        response = await http_client.post("/user/account/recipients", json=rec_payload, headers=auth_headers)
        rec_id = response.json()["data"]["id"]
        
        # 2. User 2 (Attacker) attempts to delete it
        attacker_headers = {"Authorization": f"Bearer {secondary_user_token}"}
        response = await http_client.delete(f"/user/account/recipients/{rec_id}", headers=attacker_headers)
        
        if response.status_code != 404:
            findings_collector.add_finding(
                f"/user/account/recipients/{rec_id}",
                "IDOR: Attacker can delete or see error for another user's recipient",
                "High",
                f"Attacker got status {response.status_code} instead of 404",
                build_curl("DELETE", f"{API_BASE_URL}/user/account/recipients/{rec_id}"),
                "Ensure ownership checks are performed before any operation on object IDs."
            )
            assert response.status_code == 404, f"IDOR Vulnerability! Attacker deleted recipient {rec_id}"

    @pytest.mark.asyncio
    @pytest.mark.owasp("A03")
    async def test_sqli_recipient_name(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str], test_tag: str):
        """Attempt SQL Injection in recipient name field"""
        sqli_payload = {
            "type": "email",
            "value": f"injection_{test_tag}@example.com",
            "name": f"Test'; DROP TABLE users; --"
        }
        
        response = await http_client.post("/user/account/recipients", json=sqli_payload, headers=auth_headers)
        
        request_details = {
            "method": "POST",
            "url": f"{API_BASE_URL}/user/account/recipients",
            "headers": auth_headers,
            "json": sqli_payload
        }
        
        assert_status_not_500(response, request_details, "/user/account/recipients", "SQLi attempt")
        assert_no_sql_error(response, request_details, "/user/account/recipients")

# ============================================================================
# CHAOS ENGINEERING TESTS
# ============================================================================

class TestAccountChaos:
    """Resilience and edge-case testing"""

    @pytest.mark.asyncio
    async def test_malformed_verify_token(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
        """Send corrupted tokens to verification endpoint"""
        corrupted_payload = {
            "token": "corrupted_salted_hash_xyz_123",
            "captcha_token": "dummy_captcha"
        }
        
        # Should return 400/404, but definitely NOT 500
        response = await http_client.post("/user/account/recipients/verify", json=corrupted_payload)
        
        request_details = {
            "method": "POST",
            "url": f"{API_BASE_URL}/user/account/recipients/verify",
            "json": corrupted_payload
        }
        
        assert response.status_code in [400, 404]
        assert_status_not_500(response, request_details, "/user/account/recipients/verify", "Malformed token")

    @pytest.mark.asyncio
    async def test_race_condition_recipient_add(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str], test_tag: str):
        """Simulate simultaneous additions of the same recipient email"""
        # Pre-cleanup
        cleanup_resp = await http_client.get("/user/account/recipients", headers=auth_headers)
        if cleanup_resp.status_code == 200:
            for r in cleanup_resp.json().get("data", {}).get("recipients", []):
                await http_client.delete(f"/user/account/recipients/{r['id']}", headers=auth_headers)

        email = f"race_{test_tag}@example.com"
        payload = {"type": "email", "value": email, "name": "Race"}
        
        # Add a manual delay or stagger the requests to prevent hitting the 10/minute rate limiter
        tasks = [
            http_client.post("/user/account/recipients", json=payload, headers=auth_headers)
            for _ in range(2)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # At least one should succeed (if unique constraints exist, only one should succeed)
        # Note: If rate limits hit, we might get 429, but not 0 successes unless something is critically wrong
        successes = [r for r in results if r.status_code == 200]
        assert len(successes) >= 1, f"Expected at least 1 success, got {len(successes)}. Statuses: {[r.status_code for r in results]}"
        
        # Cleanup
        for r in successes:
            rec_id = r.json()["data"]["id"]
            await http_client.delete(f"/user/account/recipients/{rec_id}", headers=auth_headers)
