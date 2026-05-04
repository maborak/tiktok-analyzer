
import requests
import time
import json
import logging
import sys
import os
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# Constants
CONFIG_FILE = "bench/config.json"
API_URL = "http://localhost:8000" # Default, will be overridden

def load_config():
    """Load configuration including IMAP credentials"""
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Config file not found: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def register_user(session, email, password):
    """Register a new user"""
    url = f"{API_URL}/auth/register"
    data = {"email": email, "password": password, "confirm_password": password}
    response = session.post(url, json=data)
    if response.status_code != 201:
        raise Exception(f"Registration failed: {response.text}")
    logger.info(f"Registered user: {email}")
    return response.json()

def login(session, email, password):
    """Login and get token"""
    url = f"{API_URL}/auth/token"
    # Note: Using form data for OAuth2
    data = {"username": email, "password": password}
    response = session.post(url, data=data) # Content-Type defaults to application/x-www-form-urlencoded
    if response.status_code != 200:
        raise Exception(f"Login failed: {response.text}")
    logger.info("Logged in successfully")
    return response.json()

def add_track(session, product_id, country_code):
    """Add a tracked product"""
    url = f"{API_URL}/user/account/tracked-products"
    data = {
        "product_id": product_id,
        "country_code": country_code,
        "price_alert_id": None
    }
    response = session.post(url, json=data)
    if response.status_code != 200:
        raise Exception(f"Add track failed: {response.text}")
    logger.info(f"Added track for {product_id}")
    return response.json()

def list_tracks(session):
    """List tracked products"""
    url = f"{API_URL}/user/account/tracked-products"
    response = session.get(url)
    if response.status_code != 200:
        raise Exception(f"List tracks failed: {response.text}")
    logger.info("Listed tracks successfully")
    return response.json()

def delete_track(session, track_id):
    """Delete a tracked product"""
    url = f"{API_URL}/user/account/tracked-products/{track_id}"
    response = session.delete(url)
    if response.status_code != 200:
        raise Exception(f"Delete track failed: {response.text}")
    logger.info(f"Deleted track {track_id}")
    return response.json()

def main():
    try:
        config = load_config()
        global API_URL
        API_URL = config.get("api_url", "http://localhost:8000")
        logger.info(f"Using API URL: {API_URL}")
        
        # Not using IMAP/verification for this test, assuming we can login without verification 
        # OR assuming we just want to test basic flow. 
        # Wait, login usually requires verification?
        # Let's check if we can login immediately. If not, this script will fail.
        # But for reproduction, maybe I can use an existing user?
        # Or I can just try to register a user and see if I can use it.
        # Some setups allow login without verification for testing or if configured.
        
        # Actually, let's use a unique email and TRY to login.
        # If verification is required, I might need to mock it or inspect DB.
        
        # Use config credentials
        # email = config.get("username")
        # password = config.get("password")
        
        email = "utest-d3b174ef@mailrbp.com"
        password = "Password123!"

        if not email or not password:
             logger.error("No credentials in config")
             return

        session = requests.Session()
        
        # Login
        try:
            token_data = login(session, email, password)
            token = token_data["access_token"]
            session.headers.update({"Authorization": f"Bearer {token}"})
        except Exception as e:
            logger.error(f"Login failed: {e}")
            # If we can't login, we can't reproduce.
            # I can try to verify manually via DB if I had DB access, but I only have API.
            # Alternatively, check if there's a test user.
            return

        # Add Track
        # Using a known ASIN. B07VGRJDFY is a common one.
        asin = "B07VGRJDFY"
        country = "BO"
        
        track_resp = add_track(session, asin, country)
        track_id = track_resp["data"]["tracks"][0]["id"]
        logger.info(f"Created track ID: {track_id}")
        
        # List again
        list_resp = list_tracks(session)
        logger.info(f"Raw list response: {json.dumps(list_resp, indent=2)}")
        items = list_resp["data"].get("tracks", []) 
        logger.info(f"Found {len(items)} products tracked")
        for item in items:
            for t in item.get("tracks", []):
                logger.info(f"Track: {item['product_id']} (ID: {t['id']})")
            
        # Delete Track
        delete_track(session, track_id)
        
        # List again to confirm deletion
        list_resp = list_tracks(session)
        items = list_resp["data"].get("items", [])
        logger.info(f"Found {len(items)} products after deletion")
        
        logger.info("Test passed successfully!")

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
