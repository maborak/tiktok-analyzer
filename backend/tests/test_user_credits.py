"""
Integration tests for User Credit System.
Verifies credit limits, auto-linking, and usage calculation.
"""
import pytest
import httpx
import os
import sys
from typing import Dict, Any

# Ensure tests directory is in path
_test_dir = os.path.dirname(os.path.abspath(__file__))
if _test_dir not in sys.path:
    sys.path.insert(0, _test_dir)

import conftest
from conftest import API_BASE_URL

# Credentials provided by user
@pytest.fixture(scope="session")
async def auth_token():
    """Session-scoped fixture to get auth token for the test user"""
    # Use pre-created user (run tests/create_test_user_script.py if needed)
    email = "test_user_credits@example.com"
    password = "TestPassword123!"
    
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
        # Login
        # Try JSON first
        login_resp = await client.post("/auth/login", json={"email": email, "password": password})
        if login_resp.status_code != 200:
             # Try form data as fallback
             login_resp = await client.post("/auth/login", data={"username": email, "password": password})
        
        if login_resp.status_code != 200:
            print(f"Login failed: {login_resp.status_code} - {login_resp.text}")
            pytest.fail(f"Could not login. Ensure 'python tests/create_test_user_script.py' has been run.")
            
        body = login_resp.json()
        token = body.get("data", {}).get("tokens", {}).get("access_token")
        if not token:
             token = body.get("access_token") 
             
        return token

@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.mark.asyncio
class TestUserCredits:
    
    async def clear_user_tracks(self, client, headers):
        """Helper to clear all tracks for the user"""
        count = 0
        # 1. Clear tracked products (loop until all are gone)
        while True:
            resp = await client.get("/user/account/tracked-products?page=1&page_size=100", headers=headers)
            if resp.status_code != 200:
                print(f"[DEBUG] Failed to list tracks for cleanup: {resp.status_code}")
                break
                
            tracks = resp.json().get("data", {}).get("tracks", [])
            if not tracks:
                break
                
            print(f"[DEBUG] Cleaning up {len(tracks)} grouped tracks...")
            for track in tracks:
                asin = track.get("product_id")
                country = track.get("country_code")
                # Use /by-product to clear ALL tracks (alerts + favorite) for this product
                url = f"/user/account/tracked-products/by-product?product_id={asin}&country_code={country}"
                del_resp = await client.delete(url, headers=headers)
                print(f"[DEBUG] DELETE {asin}/{country} status: {del_resp.status_code}")
                if del_resp.status_code >= 400:
                   print(f"[DEBUG] DELETE FAILED: {del_resp.text}")
            
            # Safety break to avoid infinite loop if deletion fails to reflect in next GET
            import time
            time.sleep(0.1) # Small delay for DB consistency (sqlite is usually fine)
            count += 1
            if count > 5:
                print("[DEBUG] Safety break reached! Cleanup might be stuck.")
                break
        
        # 2. Clear user products (My ASINs)
        resp = await client.get("/user/account/products?page=1&page_size=100", headers=headers)
        if resp.status_code == 200:
            products = resp.json().get("data", {}).get("products", [])
            if products:
                print(f"[DEBUG] Cleaning up {len(products)} user products...")
                # Unfortunately there is no bulk delete by product in UserProducts yet
                # but tracked-products is what matters for credits.
            # Deleting from user_products table is usually not exposed, 
            # but for tests, as long as it's not in tracked-products, it's fine.
            pass

    @pytest.mark.asyncio
    async def test_credit_enforcement_flow(self, http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
        """
        Verify the entire flow:
        1. Check initial credits
        2. Track products until limit
        3. Verify limit reached error
        4. Untrack and verify processing
        """
        # 0. Cleanup existing tracks to start fresh
        await self.clear_user_tracks(http_client, auth_headers)
        
        # 1. Check Account Info
        response = await http_client.get("/user/account", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        initial_credits = data.get("credits", 10)
        initial_usage = data.get("credits_used", 0)
        remaining = initial_credits - initial_usage
        
        print(f"Initial: Credits={initial_credits}, Usage={initial_usage}, Remaining={remaining}")
        
        # 2. Add Tracks
        # We need distinct ASINs. Since we mock or scrape, we need valid format ASINs.
        # B000000001, B000000002...
        
        added_tracks = []
        
        for i in range(remaining):
            asin = f"B0TS{i:06d}" # 10 chars: B0TS000000
            payload = {"product_id": asin, "country_code": "US"}
            
            resp = await http_client.post("/user/account/tracked-products", json=payload, headers=auth_headers)
            if resp.status_code == 200:
                added_tracks.append(resp.json()["data"]["id"])
            elif resp.status_code == 402:
                # Should not happen if we calculated remaining correctly
                 pytest.fail(f"Premature credit limit reached at {i}")
            else:
                 pytest.fail(f"Could not track product {asin}: {resp.status_code} - {resp.text}")

        # 3. Verify Usage Updated
        response = await http_client.get("/user/account", headers=auth_headers)
        new_usage = response.json()["data"]["credits_used"]
        assert new_usage == initial_credits
        
        # 4. Try to add one more -> Should Fail 402
        fail_asin = "B0FAIL0001"
        resp = await http_client.post("/user/account/tracked-products", json={"product_id": fail_asin, "country_code": "BO"}, headers=auth_headers)
        assert resp.status_code == 402
        
        # 5. Cleanup (Untrack)
        for track_id in added_tracks:
            await http_client.delete(f"/user/account/tracked-products/{track_id}", headers=auth_headers)
            
        # 6. Verify usage dropped
        response = await http_client.get("/user/account", headers=auth_headers)
        final_usage = response.json()["data"]["credits_used"]
        assert final_usage == initial_usage


