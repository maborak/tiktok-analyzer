import pytest
import httpx
from typing import Dict
import os
import sys

# Ensure tests directory is in path
_test_dir = os.path.dirname(os.path.abspath(__file__))
if _test_dir not in sys.path:
    sys.path.insert(0, _test_dir)

import conftest

@pytest.fixture(scope="session")
async def auth_token():
    """Session-scoped fixture to get auth token for the test user"""
    async with httpx.AsyncClient(base_url=conftest.API_BASE_URL, timeout=30.0) as client:
        payload = {"email": "wilmer@maborak.com", "password": "sample"}
        response = await client.post("/auth/login", json=payload)
        
        if response.status_code != 200:
            pytest.fail(f"Could not login. Status: {response.status_code}")
            
        body = response.json()
        token = body.get("data", {}).get("tokens", {}).get("access_token")
        if not token:
            pytest.fail(f"Login response missing access_token. Body: {body}")
        return token

@pytest.fixture
def auth_headers(auth_token):
    """Fixture for authenticated request headers"""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.mark.asyncio
async def test_viewing_history(http_client: httpx.AsyncClient, auth_headers: Dict[str, str]):
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
