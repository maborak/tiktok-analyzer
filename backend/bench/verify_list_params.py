import requests
import sys

# Configuration
BASE_URL = "http://localhost:9001"
USER_EMAIL = "maborak@maborak.com"
USER_PASSWORD = "4d4l1dc4mp30N2#"

def login():
    print(f"Logging in as {USER_EMAIL}...")
    url = f"{BASE_URL}/auth/login"
    payload = {
        "email": USER_EMAIL,
        "password": USER_PASSWORD,
        "remember_me": False
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"Login failed: {response.text}")
        sys.exit(1)
    
    data = response.json()
    token = data["data"]["tokens"]["access_token"]
    return token

def test_endpoint(endpoint, token, params=None):
    print(f"\nTesting GET {endpoint} with params: {params}")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            pagination = data["data"].get("pagination")
            items_key = list(data["data"].keys())[0] if len(data["data"].keys()) > 0 else "N/A"
            if items_key == "pagination":
                items_key = list(data["data"].keys())[1] if len(data["data"].keys()) > 1 else "N/A"
            
            items = data["data"].get(items_key, [])
            count = len(items)
            
            print(f"Success! Found {count} items.")
            if pagination:
                print(f"Pagination: {pagination}")
            else:
                print("No pagination metadata found.")
            
            if count > 0:
                print(f"First item sample: {items[0].get('name') or items[0].get('product_id') or items[0].get('id')}")
        else:
            print(f"API Error: {data.get('message')}")
    else:
        print(f"HTTP Error {response.status_code}: {response.text}")

def main():
    try:
        token = login()
    except Exception as e:
        print(f"Could not connect to API: {e}")
        return

    endpoints = ["/user/account/price-alerts", "/user/account/recipients", "/user/account/tracked-products"]

    for ep in endpoints:
        print(f"\n--- Testing {ep} ---")
        # Default
        test_endpoint(ep, token)
        
        # Pagination
        test_endpoint(ep, token, {"page": 1, "page_size": 2})
        
        # Search (if possible)
        test_endpoint(ep, token, {"search": "Bench"})
        
        # Sort
        test_endpoint(ep, token, {"sort_by": "id", "sort_order": "desc"})

if __name__ == "__main__":
    main()
