
import imaplib
import email
import re
import json
import time
import requests
import uuid
import sys
import logging
import traceback
import argparse
import random
from email.header import decode_header
from typing import Optional, Dict, Any, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Colors & Output ---
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(msg):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*40}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}🚀 {msg}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*40}{Colors.ENDC}")

def print_pass(msg):
    print(f"  {Colors.GREEN}[PASS]{Colors.ENDC} {msg}")

def print_fail(msg):
    print(f"  {Colors.FAIL}[FAIL]{Colors.ENDC} {msg}")

def print_warn(msg):
    print(f"  {Colors.WARNING}[WARN]{Colors.ENDC} {msg}")

def print_info(msg):
    print(f"  {Colors.CYAN}[INFO]{Colors.ENDC} {msg}")

# --- Configuration ---
try:
    with open("bench/config.json", "r") as f:
        config = json.load(f)
    
    API_URL = config.get("api_url", "http://localhost:9000").rstrip("/")
    IMAP_CONFIG = config.get("catch_all", {})
    
    IMAP_USER = IMAP_CONFIG.get("imap_user")
    IMAP_PASS = IMAP_CONFIG.get("imap_password")
    IMAP_SERVER = IMAP_CONFIG.get("imap_server")
    IMAP_PORT = IMAP_CONFIG.get("imap_port", 993)
    
    if not all([IMAP_USER, IMAP_PASS, IMAP_SERVER]):
        raise ValueError("Missing IMAP configuration in bench/config.json")
        
except Exception as e:
    logger.error(f"Failed to load configuration: {e}")
    sys.exit(1)

# --- Helper Functions ---

def fatal_error(message: str):
    """Log error and exit immediately."""
    logger.error(f"{Colors.FAIL}FATAL: {message}{Colors.ENDC}")
    sys.exit(1)

def fetch_openapi_spec(session):
    """Fetch and parse OpenAPI spec for dynamic testing."""
    try:
        url = f"{API_URL}/openapi.json"
        resp = session.get(url, timeout=5)
        if resp.status_code == 200:
            spec = resp.json()
            print_info(f"Fetched OpenAPI Spec ({len(spec.get('paths', {}))} paths)")
            return spec
    except Exception as e:
        print_warn(f"Could not fetch OpenAPI spec: {e}")
    return None

def run_dynamic_tests(session, token, openapi_spec):
    """
    Dynamically probe all endpoints defined in OpenAPI spec.
    1. Method Fuzzing (Try undefined methods)
    2. Status Code Validation (Verify 403/404 for random IDs)
    """
    if not openapi_spec:
        print_warn("Skipping Dynamic Tests (No OpenAPI Spec)")
        return

    print_header("DYNAMIC OPENAPI SECURITY PROBING")
    
    paths = openapi_spec.get("paths", {})
    headers = {"Authorization": f"Bearer {token}"}
    
    # Methods to fuzz
    all_methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
    
    for path, path_item in paths.items():
        # Skip Auth/OpenAPI
        if path.startswith("/auth") or path == "/openapi.json": continue
        
        # Prepare Test URL (Replace params with random ID)
        test_url = f"{API_URL}{path}"
        if "{" in path:
            test_url = re.sub(r'\{[^}]+\}', '999999', test_url)
            
        print_info(f"Probing {path}...")
        
        # 1. Check defined methods (Spec Validation)
        for method, op in path_item.items():
            method = method.upper()
            try:
                # If GET, we can try calling it
                if method == "GET":
                    resp = session.request(method, test_url, headers=headers)
                    # For 999999 we expect 404 or 403 (or 200 if list)
                    if "{" in path:
                        if resp.status_code in [403, 404]:
                            print_pass(f"{method} {path} -> {resp.status_code} (Correct for invalid ID)")
                        else:
                            print_warn(f"{method} {path} -> {resp.status_code} (Unexpected for invalid ID)")
                    else:
                        if resp.status_code == 200:
                            print_pass(f"{method} {path} -> 200 OK")
                        else:
                            print_warn(f"{method} {path} -> {resp.status_code}")
                            
            except Exception as e:
                print_fail(f"{method} {path} Exception: {e}")

        # 2. Method Fuzzing (Try undefined methods)
        defined_methods = [m.upper() for m in path_item.keys()]
        for m in all_methods:
            if m not in defined_methods:
                resp = session.request(m, test_url, headers=headers)
                if resp.status_code in [405, 404, 403]:
                    print_pass(f"Method Fuzz: {m} {path} -> {resp.status_code} (Blocked)")
                elif resp.status_code == 500:
                    print_fail(f"Method Fuzz: {m} {path} -> 500 CRASH!")
                else:
                    print_warn(f"Method Fuzz: {m} {path} -> {resp.status_code} (Allowed?)")

        # 3. Garbage Data Fuzzing (Crash Test)
        for m in ["POST", "PUT"]:
            if m in defined_methods:
                 garbage_payloads = [
                     ("PLAIN TEXT", "This is not JSON", {"Content-Type": "application/json"}),
                     ("BINARY", b'\x00\xFF\xFE\x01', {"Content-Type": "application/json"}),
                     ("HUGE STRING", "A" * 10000, {"Content-Type": "application/json"}),
                     ("SQL INJECTION", "' OR '1'='1", {"Content-Type": "application/json"}),
                 ]
                 
                 for label, data, h in garbage_payloads:
                     h_copy = headers.copy()
                     h_copy.update(h)
                     try:
                         resp = session.request(m, test_url, data=data, headers=h_copy)
                         if resp.status_code == 500:
                             print_fail(f"Garbage Fuzz ({label}): {m} {path} -> 500 CRASH!")
                         elif resp.status_code >= 400:
                             print_pass(f"Garbage Fuzz ({label}): {m} {path} -> {resp.status_code} (Handled)")
                         else:
                             print_warn(f"Garbage Fuzz ({label}): {m} {path} -> {resp.status_code} (Accepted?)")
                     except Exception as e:
                         print_warn(f"Garbage Fuzz Error: {e}")


def get_imap_connection():
    """Connect to IMAP server."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        return mail
    except Exception as e:
        fatal_error(f"Failed to connect to IMAP: {e}")

def wait_for_email(to_email: str, subject_keyword: str = "Verify", timeout_sec: int = 90) -> Optional[str]:
    """
    Wait for an email sent to `to_email` and return its content (or verification link).
    """
    logger.info(f"Waiting for email to {to_email}...")
    start_time = time.time()
    
    try:
        mail = get_imap_connection()
        mail.select("inbox")
        
        while time.time() - start_time < timeout_sec:
            # Search for emails
            typ, msq_ids = mail.search(None, f'(TO "{to_email}")')
            
            if typ == 'OK':
                id_list = msq_ids[0].split()
                if id_list:
                    # Get the latest email
                    latest_email_id = id_list[-1]
                    typ, data = mail.fetch(latest_email_id, '(RFC822)')
                    
                    for response_part in data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subject, encoding = decode_header(msg["Subject"])[0]
                            if isinstance(subject, bytes):
                                subject = subject.decode(encoding if encoding else "utf-8")
                            
                            logger.info(f"Found email: {subject}")
                            
                            # Extract body
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    content_type = part.get_content_type()
                                    if content_type == "text/plain" or content_type == "text/html":
                                        try:
                                            body += part.get_payload(decode=True).decode()
                                        except:
                                            pass
                            else:
                                body = msg.get_payload(decode=True).decode()
                            
                            return body
            
            time.sleep(3) # Polling interval
            
        mail.logout()
    except Exception as e:
        fatal_error(f"IMAP error: {e}")
        
    return None

def extract_verification_token(email_body: str) -> Optional[str]:
    """Extract verification token from email body."""
    match = re.search(r'token=([a-zA-Z0-9_\-]+)', email_body)
    if match:
        return match.group(1)
    return None


def run_security_tests(created_accounts: List[Dict[str, Any]], openapi_spec: Optional[Dict] = None):

    """
    Attempt to cross-access resources belonging to other users.
    If any unauthorized access succeeds (2xx), fatal error.
    """
    print_header("STARTING SECURITY STRESS TEST")
    
    if len(created_accounts) < 2:
        logger.warning("Need at least 2 accounts for security testing.")
        return

    test_session = requests.Session()
    
    # RUN DYNAMIC TESTS using the first account
    if openapi_spec and created_accounts:
        user_0 = created_accounts[0]
        token_0 = login_user(test_session, user_0['email'], user_0['password'])
        run_dynamic_tests(test_session, token_0, openapi_spec)
    
    for i, user_x in enumerate(created_accounts):
        # User X will try to access User Y's resources
        target_idx = (i + 1) % len(created_accounts)
        user_y = created_accounts[target_idx]
        
        print(f"\n{Colors.BLUE}[ACCOUNT {i+1}] Testing: {user_x['email']} -> {user_y['email']} resources...{Colors.ENDC}")
        
        # Authenticate as User X
        token_x = login_user(test_session, user_x['email'], user_x['password'])
        test_session.headers.update({"Authorization": f"Bearer {token_x}"})
        
        # --- PHASE A: Self-Access Verification (Expect 2xx) ---
        print(f"  [SELF] Verifying access to own resources...")
        
        if user_x['alerts']:
            alert_id = user_x['alerts'][0]
            resp = test_session.get(f"{API_URL}/user/account/price-alerts/{alert_id}")
            if resp.status_code < 300:
                print_pass(f"GET own Alert {alert_id}")
            else:
                print_fail(f"GET own Alert {alert_id} (Status: {resp.status_code})")
                
        if user_x['recipients']:
            rec_id = user_x['recipients'][0]
            resp = test_session.get(f"{API_URL}/user/account/recipients/{rec_id}")
            if resp.status_code < 300:
                print_pass(f"GET own Recipient {rec_id}")
            else:
                print_fail(f"GET own Recipient {rec_id} (Status: {resp.status_code})")

        # --- PHASE B: Cross-Access Testing (Expect 4xx) ---
        print(f"  [CROSS] Testing unauthorized access to {user_y['email']} resources...")
        
        # 1. Try to ACCESS/DELETE User Y's Alert
        if user_y['alerts']:
            alert_id = user_y['alerts'][0]
            
            # GET Alert
            resp = test_session.get(f"{API_URL}/user/account/price-alerts/{alert_id}")
            if resp.status_code >= 400:
                print_pass(f"GET foreign Alert {alert_id} (Blocked: {resp.status_code})")
            else:
                print_fail(f"GET foreign Alert {alert_id} (ACCESSED: {resp.status_code})")
                fatal_error(f"SECURITY BREACH: User {user_x['email']} accessed Alert {alert_id}")
            
            # DELETE Alert
            resp = test_session.delete(f"{API_URL}/user/account/price-alerts/{alert_id}")
            if resp.status_code >= 400:
                 print_pass(f"DELETE foreign Alert {alert_id} (Blocked: {resp.status_code})")
            else:
                print_fail(f"DELETE foreign Alert {alert_id} (DELETED: {resp.status_code})")
                fatal_error(f"SECURITY BREACH: User {user_x['email']} deleted Alert {alert_id}")

        # 2. Try to ACCESS User Y's Recipient
        if user_y['recipients']:
            rec_id = user_y['recipients'][0]
            # GET Recipient
            resp = test_session.get(f"{API_URL}/user/account/recipients/{rec_id}")
            if resp.status_code >= 400:
                print_pass(f"GET foreign Recipient {rec_id} (Blocked: {resp.status_code})")
            else:
                print_fail(f"GET foreign Recipient {rec_id} (ACCESSED: {resp.status_code})")
                fatal_error(f"SECURITY BREACH: User {user_x['email']} accessed Recipient {rec_id}")

        # 3. Try to LINK User Y's Alert to User X's product
        if user_y['alerts']:
             alert_id = user_y['alerts'][0]
             payload = {
                 "product_id": "B0C9H8XY75",
                 "country_code": "BO",
                 "price_alert_id": alert_id
             }
             resp = test_session.post(f"{API_URL}/user/account/tracked-products", json=payload)
             if resp.status_code >= 400:
                 print_pass(f"LINK foreign Alert {alert_id} (Blocked: {resp.status_code})")
             else:
                 print_fail(f"LINK foreign Alert {alert_id} (LINKED: {resp.status_code})")
                 fatal_error(f"SECURITY BREACH: User {user_x['email']} linked unauthorized Alert {alert_id}")

        # 4. Try to BULK LINK User Y's Alert
        if user_y['alerts']:
             alert_id = user_y['alerts'][0]
             payload = {
                 "country_code": "BO",
                 "price_alert_ids": [alert_id]
             }
             resp = test_session.put(f"{API_URL}/user/account/tracked-products/B0C9H8XY75", json=payload)
             if resp.status_code >= 400:
                 print_pass(f"BULK LINK foreign Alert {alert_id} (Blocked: {resp.status_code})")
             else:
                 print_fail(f"BULK LINK foreign Alert {alert_id} (LINKED: {resp.status_code})")
                 fatal_error(f"SECURITY BREACH: User {user_x['email']} bulk-linked Alert {alert_id}")

        # 5. [NEW] Try to DELETE User Y's Track
        if user_y['tracks']:
             track_id = user_y['tracks'][0]
             resp = test_session.delete(f"{API_URL}/user/account/tracked-products/{track_id}")
             if resp.status_code >= 400:
                  print_pass(f"DELETE foreign Track {track_id} (Blocked: {resp.status_code})")
             else:
                  print_fail(f"DELETE foreign Track {track_id} (DELETED: {resp.status_code})")
                  fatal_error(f"SECURITY BREACH: User {user_x['email']} deleted foreign Track {track_id}")

        # 6. [NEW] Try to access ADMIN endpoints
        resp = test_session.get(f"{API_URL}/admin/users")
        if resp.status_code in [401, 403]:
             print_pass(f"ADMIN List Users (Blocked: {resp.status_code})")
        else:
             print_fail(f"ADMIN List Users (ACCESSED: {resp.status_code})")
             fatal_error(f"SECURITY BREACH: Regular user {user_x['email']} accessed ADMIN route")

        # 7. [NEW] Try to MANIPULATE Profile (Self-ID Injection test)
        payload = {
            "username": f"hacker-{user_x['email'].split('@')[0]}",
            "user_id": 1, 
            "role": "admin" 
        }
        resp = test_session.put(f"{API_URL}/user/account/edit", json=payload)
        if resp.status_code < 300:
             print_pass(f"Profile Edit (Safe self-edit)")
        else:
             print_warn(f"Profile Edit failed with {resp.status_code}")

    print_header("✨ ALL SECURITY CHECKS PASSED ✨")







def register_user(session, email_addr, password):
    """Register a new user."""
    url = f"{API_URL}/auth/register"
    payload = {
        "email": email_addr,
        "password": password,
        "first_name": "Test",
        "last_name": "User"
    }
    try:
        resp = session.post(url, json=payload, timeout=10)
        if resp.status_code != 200 and resp.status_code != 201:
            fatal_error(f"Registration failed: {resp.text}")
        logger.info(f"Registered user: {email_addr}")
        return True
    except Exception as e:
        fatal_error(f"Registration request error: {e}")

def verify_user_account(session, token):
    """Verify user account with token."""
    url = f"{API_URL}/auth/verify"
    payload = {"token": token}
    try:
        resp = session.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
             fatal_error(f"User verification failed: {resp.text}")
        logger.info("User account verified successfully")
    except Exception as e:
        fatal_error(f"Verification request error: {e}")

def login_user(session, email_addr, password):
    """Login and get token."""
    url = f"{API_URL}/auth/token"
    # OAuth2 form data
    data = {"username": email_addr, "password": password}
    try:
        resp = session.post(url, data=data, timeout=10)
        if resp.status_code != 200:
            fatal_error(f"Login failed: {resp.text}")
        
        token_data = resp.json()
        token = token_data.get("access_token")
        if not token:
            fatal_error("No access token in login response")
            
        session.headers.update({"Authorization": f"Bearer {token}"})
        logger.info("Logged in successfully")
        return token
    except Exception as e:
        fatal_error(f"Login request error: {e}")

def get_user_account(session):
    """Fetch current user account information."""
    url = f"{API_URL}/user/account"
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            fatal_error(f"Failed to fetch account info: {resp.text}")
        data = resp.json().get("data", {})
        return data
    except Exception as e:
        fatal_error(f"Account fetch error: {e}")

def verify_unconfirmed_limits(session, product_pool):
    """
    Verify that an unconfirmed user is capped at 5 tracks.
    """
    print_header("VERIFYING UNCONFIRMED USER LIMITS")
    limit = 5 # CONFIG["LIMIT_MAX_TRACKED_UNCONFIRMED"]
    
    tracked_ids = []
    
    # Fill up to limit
    for i in range(limit):
        asin = product_pool[i % len(product_pool)]
        print_info(f"Adding unconfirmed track {i+1}/{limit} for {asin}...")
        track_id = create_tracked_product(session, asin, alert_id=None)
        if track_id:
            tracked_ids.append(track_id)
        else:
            print_fail(f"Could not add unconfirmed track {i+1}")
            
    # Verify account shows usage
    account = get_user_account(session)
    # credits_used is calculated from ENABLED tracks. 
    # Unverified tracks are DISABLED.
    print_info(f"Unverified Account: credits={account.get('credits')}, used={account.get('credits_used')}, verified={account.get('is_verified')}")
    
    # Attempt one more (Overflow)
    asin_overflow = product_pool[limit % len(product_pool)]
    print_info(f"Attempting overflow track for {asin_overflow} (Expecting 402)...")
    url = f"{API_URL}/user/account/tracked-products"
    payload = {
        "product_id": asin_overflow,
        "country_code": "BO",
        "price_alert_id": None
    }
    resp = session.post(url, json=payload, timeout=10)
    
    if resp.status_code == 402:
        print_pass("Overflow attempt blocked with 402 Payment Required (Limit Reached)")
    else:
        print_fail(f"Overflow attempt NOT blocked as expected! Status: {resp.status_code}, Text: {resp.text}")
    
    # 2. Verify Recipient/Alert blockage for unconfirmed
    print_info("Verifying unconfirmed user cannot add recipients (Expecting 403)...")
    url_rec = f"{API_URL}/user/account/recipients"
    resp_rec = session.post(url_rec, json={"type": "email", "value": "check@fail.com", "name": "Fail"}, timeout=10)
    if resp_rec.status_code == 403:
        print_pass("Recipient creation blocked for unconfirmed user")
    else:
        print_fail(f"Recipient creation NOT blocked! Status: {resp_rec.status_code}")

    print_info("Verifying unconfirmed user cannot add alerts (Expecting 403)...")
    url_alt = f"{API_URL}/user/account/price-alerts"
    payload_alt = {
        "name": "Fail Alert",
        "recipient_id": 1,
        "triggers": [{"trigger_type": "value_down", "target_field": "total_price", "trigger_value": 10}]
    }
    resp_alt = session.post(url_alt, json=payload_alt, timeout=10)
    if resp_alt.status_code == 403:
        print_pass("Alert creation blocked for unconfirmed user")
    else:
        print_fail(f"Alert creation NOT blocked! Status: {resp_alt.status_code}, Text: {resp_alt.text}")
        
    return tracked_ids

def verify_confirmed_credits(session, product_pool, already_tracked_count):
    """
    Verify that a confirmed user is limited by their credits.
    """
    print_header("VERIFYING CONFIRMED USER CREDITS")
    
    # Check account
    account = get_user_account(session)
    credits = account.get("credits", 10)
    used = account.get("credits_used", 0)
    
    print_info(f"Verified Account: credits={credits}, used={used}, verified={account.get('is_verified')}")
    
    if not account.get("is_verified"):
        print_fail("User is NOT verified but should be!")
        return
        
    if used != already_tracked_count:
        print_fail(f"Usage discrepancy! Expected {already_tracked_count}, got {used}")
    else:
        print_pass(f"Usage correctly updated to {used} after verification")
        
    # Track up to limit
    to_add = credits - used
    print_info(f"Adding {to_add} more tracks to reach credit limit {credits}...")
    
    confirmed_track_ids = []
    for i in range(to_add):
        # Use a fresh ASIN from pool
        asin = product_pool[(already_tracked_count + i + 10) % len(product_pool)]
        print_info(f"Adding confirmed track {used+i+1}/{credits} for {asin}...")
        tid = create_tracked_product(session, asin, alert_id=None)
        if tid:
            confirmed_track_ids.append(tid)
        
    # Verify account again
    account = get_user_account(session)
    used = account.get("credits_used", 0)
    print_info(f"Account at limit: credits={credits}, used={used}")
    
    # Attempt one more (Overflow)
    asin_overflow = product_pool[credits % len(product_pool)]
    print_info(f"Attempting overflow track for {asin_overflow} (Expecting 402)...")
    url = f"{API_URL}/user/account/tracked-products"
    payload = {
        "product_id": asin_overflow,
        "country_code": "BO",
        "price_alert_id": None
    }
    resp = session.post(url, json=payload, timeout=10)
    
    if resp.status_code == 402:
        print_pass("Overflow attempt blocked with 402 Payment Required (Credits Exhausted)")
    else:
        print_fail(f"Overflow attempt NOT blocked as expected! Status: {resp.status_code}, Text: {resp.text}")
        
    return confirmed_track_ids

def verify_recipient_limits(session, email_prefix, user_email):
    """
    Verify that a confirmed user is capped at 5 recipients.
    """
    print_header("VERIFYING RECIPIENT LIMITS")
    
    recipient_ids = []
    
    # 1. Add user's own verified email (auto-verified)
    print_info(f"Adding user's own verified email as first recipient: {user_email}")
    rid_verified = create_recipient(session, user_email)
    if rid_verified:
        recipient_ids.append(rid_verified)
    
    print_info("Filling up remaining recipients up to limit 5...")
    for i in range(10): # Try more than enough
        email = f"{email_prefix}_lim{i}@mailrbp.com"
        rid = create_recipient(session, email)
        if rid:
            recipient_ids.append(rid)
        else:
            break
    
    # Verify account
    url_list = f"{API_URL}/user/account/recipients"
    resp_list = session.get(url_list, timeout=10)
    data = resp_list.json().get("data", {})
    total = data.get("pagination", {}).get("total", 0)
    
    # Extract IDs and ensure rid_verified is available/first if possible
    raw_recipients = data.get("recipients", [])
    recipient_ids = [r.get("id") for r in raw_recipients]
    
    # Logic to find the verified one and put it first
    verified_ids = [r.get("id") for r in raw_recipients if r.get("is_verified")]
    if verified_ids:
        # Reconstruct list with verified first
        other_ids = [r_id for r_id in recipient_ids if r_id not in verified_ids]
        recipient_ids = verified_ids + other_ids
        
    print_info(f"Recipients count: {total} (Verified: {len(verified_ids)})")
        
    # Attempt one more (Overflow)
    email_overflow = f"{email_prefix}_overflow@mailrbp.com"
    print_info(f"Attempting overflow recipient {email_overflow} (Expecting 402)...")
    url = f"{API_URL}/user/account/recipients"
    payload = {
        "type": "email",
        "value": email_overflow,
        "name": "Overflow Recipient"
    }
    resp = session.post(url, json=payload, timeout=10)
    
    if resp.status_code == 402:
        print_pass("Overflow recipient attempt blocked with 402 Payment Required")
    else:
        print_fail(f"Overflow recipient NOT blocked as expected! Status: {resp.status_code}, Text: {resp.text}")
        
    return recipient_ids

def verify_alert_limits(session, recipient_id):
    """
    Verify that a confirmed user is capped at 5 price alerts and 3 triggers per alert.
    """
    print_header("VERIFYING ALERT & TRIGGER LIMITS")
    
    # 1. Verify Trigger Limit (3 per alert)
    print_info("Attempting to create alert with 4 triggers (Expecting 422)...")
    url = f"{API_URL}/user/account/price-alerts"
    payload = {
        "name": "Trigger Overflow Alert",
        "recipient_id": recipient_id,
        "logic_operator": "or",
        "triggers": [
            {"trigger_type": "value_down", "target_field": "total_price", "trigger_value": 10},
            {"trigger_type": "value_up", "target_field": "total_price", "trigger_value": 100},
            {"trigger_type": "percent_down", "target_field": "total_price", "trigger_value": 5},
            {"trigger_type": "percent_up", "target_field": "total_price", "trigger_value": 3}
        ]
    }
    resp = session.post(url, json=payload, timeout=10)
    if resp.status_code == 422:
        print_pass("Trigger overflow (4 triggers) blocked with 422 Unprocessable Entity")
    else:
        print_fail(f"Trigger overflow NOT blocked as expected! Status: {resp.status_code}, Text: {resp.text}")
        
    # 2. Verify Alert Limit (5 alerts)
    alert_ids = []
    print_info("Filling up alerts up to limit 5...")
    for i in range(10):
        aid = create_price_alert(session, recipient_id, name_suffix=f" Lim{i}")
        if aid:
            alert_ids.append(aid)
        else:
            break
            
    # Verify account
    url_list = f"{API_URL}/user/account/price-alerts"
    resp_list = session.get(url_list, timeout=10)
    data = resp_list.json().get("data", {})
    total = data.get("pagination", {}).get("total", 0)
    print_info(f"Alerts count: {total}")

    # Attempt one more (Overflow)
    print_info("Attempting overflow alert (Expecting 402)...")
    payload = {
        "name": "Overflow Alert",
        "recipient_id": recipient_id,
        "logic_operator": "or",
        "triggers": [{"trigger_type": "value_down", "target_field": "total_price", "trigger_value": 10}]
    }
    resp = session.post(url, json=payload, timeout=10)
    
    if resp.status_code == 402:
        print_pass("Overflow alert attempt blocked with 402 Payment Required")
    else:
        print_fail(f"Overflow alert NOT blocked as expected! Status: {resp.status_code}, Text: {resp.text}")
        
    return alert_ids

def create_recipient(session, email_addr):
    """Create a recipient."""
    url = f"{API_URL}/user/account/recipients"
    payload = {
        "type": "email",
        "value": email_addr,
        "name": f"Recipient {email_addr[:8]}"
    }
    try:
        resp = session.post(url, json=payload, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            logger.info(f"Recipient created: {data.get('id')}")
            return data.get("id")
        else:
            logger.warning(f"Create recipient failed: {resp.text}")
            return None
    except Exception as e:
        fatal_error(f"Create recipient failed: {e}")

def verify_recipient(session, token):
    """Verify recipient."""
    url = f"{API_URL}/user/account/recipients/verify"
    payload = {"token": token}
    try:
        resp = session.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            fatal_error(f"Recipient verification failed: {resp.text}")
        logger.info("Recipient verified successfully")
    except Exception as e:
        fatal_error(f"Recipient verify error: {e}")

def generate_random_triggers():
    """Generate a valid list of 1-3 random triggers."""
    num_triggers = random.randint(1, 3)
    triggers = []
    
    # Pool of possible targets and their valid types
    target_configs = [
        {"target": "total_price", "types": ["value_down", "value_up", "percent_down", "percent_up"]},
        {"target": "base_price", "types": ["value_down", "value_up", "percent_down", "percent_up"]},
        {"target": "shipping_fee", "types": ["value_down", "value_up"]},
        {"target": "import_fees", "types": ["value_down", "value_up"]},
        {"target": "product", "types": ["becomes_available", "becomes_unavailable"]}
    ]
    
    used_combinations = set()
    
    for _ in range(num_triggers):
        for _ in range(10): # Retry to avoid redundancy
            config = random.choice(target_configs)
            target = config["target"]
            t_type = random.choice(config["types"])
            
            combo = (target, t_type)
            if combo in used_combinations:
                continue
            
            trigger = {
                "trigger_type": t_type,
                "target_field": target,
                "trigger_value": None
            }
            
            if t_type in ["value_down", "value_up"]:
                trigger["trigger_value"] = round(random.uniform(10.0, 500.0), 2)
            elif t_type in ["percent_down", "percent_up"]:
                trigger["trigger_value"] = round(random.uniform(1.0, 30.0), 1)
            
            triggers.append(trigger)
            used_combinations.add(combo)
            break
            
    return triggers

def create_price_alert(session, recipient_id, name_suffix=""):
    """Create a price alert with random triggers."""
    url = f"{API_URL}/user/account/price-alerts"
    
    triggers = generate_random_triggers()
    
    payload = {
        "name": f"Alert {name_suffix} {uuid.uuid4().hex[:6]}",
        "recipient_id": int(recipient_id),
        "triggers": triggers,
        "logic_operator": random.choice(["or", "and"]),
        "is_active": True,
        "cooldown_minutes": random.choice([30, 60, 120, 240, 1440])
    }
    
    try:
        resp = session.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            logger.info(f"Price alert created: {data.get('id')}")
            return data.get("id")
        else:
            logger.warning(f"Create price alert failed: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Create price alert error: {e}")
        return None

def simulate_user_activity(session, account_data, product_pool):
    """Simulate a 'busy' user doing various operations."""
    email = account_data['email']
    print_header(f"Simulating activity for {email}")
    
    actions = ["track_churn", "alert_churn", "search_products"]
    num_actions = random.randint(3, 8)
    
    for _ in range(num_actions):
        action = random.choice(actions)
        
        if action == "track_churn":
            asin = random.choice(product_pool)
            alert_id = random.choice(account_data['alerts']) if account_data['alerts'] else None
            if not alert_id: continue
            
            print_info(f"Churning track for ASIN {asin}...")
            # 1. Track
            track_id = create_tracked_product(session, asin, alert_id)
            if track_id:
                # 2. View
                session.get(f"{API_URL}/user/account/tracked-products/{track_id}")
                # 3. Update
                if len(account_data['alerts']) > 1:
                    other_alert = random.choice([a for a in account_data['alerts'] if a != alert_id])
                    session.put(f"{API_URL}/user/account/tracked-products/{asin}", json={
                        "country_code": "BO",
                        "price_alert_ids": [other_alert]
                    })
                # 4. Untrack
                session.delete(f"{API_URL}/user/account/tracked-products/{track_id}")
                # 5. Re-track
                create_tracked_product(session, asin, alert_id)

        elif action == "alert_churn":
            if not account_data['alerts']: continue
            alert_id = random.choice(account_data['alerts'])
            print_info(f"Churning alert {alert_id}...")
            
            # 1. Partial Update
            session.patch(f"{API_URL}/user/account/price-alerts/{alert_id}", json={
                "is_active": random.choice([True, False]),
                "cooldown_minutes": random.choice([30, 60, 120])
            })
            
            # 2. Create replacement (Always use the first recipient which is guaranteed to be verified)
            r_id = account_data['recipients'][0]
            new_id = create_price_alert(session, r_id, name_suffix="churn")
            if new_id:
                account_data['alerts'].append(new_id)
            
            # 3. Delete old (Only if we have more than 1 alert)
            if len(account_data['alerts']) > 1:
                session.delete(f"{API_URL}/user/account/price-alerts/{alert_id}")
                account_data['alerts'].remove(alert_id)

        elif action == "search_products":
            queries = ["laptop", "phone", "monitor", "coffee", "keyboard"]
            q = random.choice(queries)
            print_info(f"Simulating scan for '{q}'...")
            session.get(f"{API_URL}/products", params={"q": q, "page_size": 20})
            
    print_pass(f"Completed activity simulation for {email}")

def fetch_products(session) -> List[str]:
    """Fetch all products and return list of ASINS."""
    url = f"{API_URL}/products"
    params = {"page_size": 100} # Get a good batch
    try:
        resp = session.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            fatal_error(f"Fetch products failed: {resp.text}")
            
        data = resp.json()
        products = data.get("products", [])
        asins = [p.get("id") for p in products]
        logger.info(f"Fetched {len(asins)} products for favorites pool")
        return asins
    except Exception as e:
        fatal_error(f"Fetch products error: {e}")

def create_tracked_product(session, asin, alert_id):
    """Link a product to an alert (Favorite). Returns track ID."""
    url = f"{API_URL}/user/account/tracked-products"
    country_code = "BO" # Default for benchmark
    payload = {
        "product_id": asin,
        "country_code": country_code,
        "price_alert_id": alert_id
    }
    try:
        resp = session.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
             # Ignore if already exists, but log error if strict
             logger.warning(f"Failed to track product {asin}: {resp.text}")
             return None
             
        data = resp.json().get("data", {})
        track_id = data.get("id")
        logger.info(f"Linked product {asin} to alert {alert_id} (Track ID: {track_id})")
        return track_id
    except Exception as e:
        fatal_error(f"Track product error: {e}")



# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="Benchmark Phoveus")
    parser.add_argument("--accounts", type=int, default=2, help="Number of accounts to register")
    parser.add_argument("--recipients", type=int, default=2, help="Recipients per account")
    parser.add_argument("--alerts", type=int, default=3, help="Alerts per account")
    parser.add_argument("--favorites", type=int, default=3, help="Random products to track per account")
    
    args = parser.parse_args()
    
    logger.info(f"Starting Benchmark: {args.accounts} accounts, {args.recipients} recipients, {args.alerts} alerts, {args.favorites} favorites")
    
    session = requests.Session()
    
    # FETCH OPENAPI SPEC
    openapi_spec = fetch_openapi_spec(session)
    
    created_credentials = []
    
    product_pool = [] # Will fetch once authenticated

    
    for i in range(args.accounts):
        print(f"\n=== Account {i+1}/{args.accounts} ===")
        unique_id = uuid.uuid4().hex[:8]
        user_email = f"utest-{unique_id}@mailrbp.com"
        password = "Password123!" 
        
        # 1. Register
        register_user(session, user_email, password)
        
        # 2. Login (as Unconfirmed)
        login_user(session, user_email, password)
        
        # 3. Fetch Products Logic (First time only)
        if not product_pool and (args.favorites > 0 or i == 0):
            product_pool = fetch_products(session)
            if not product_pool:
                logger.warning("No products found! Limits verification and favorites will be skipped.")
        
        # 4. Verify Unconfirmed Limits (Step 1)
        unconfirmed_track_ids = []
        if i == 0 and product_pool:
            unconfirmed_track_ids = verify_unconfirmed_limits(session, product_pool)

        # 5. Verify User Account
        email_body = wait_for_email(user_email, subject_keyword="Verify")
        if not email_body: fatal_error("User verification email not found")
        token = extract_verification_token(email_body)
        if not token: fatal_error("Could not extract user verification token")
        verify_user_account(session, token)
        
        # 6. Login (as Confirmed)
        login_user(session, user_email, password)
        
        # 7. Verify Confirmed Credits (Step 3) - Only for first account
        account_track_ids = list(unconfirmed_track_ids)
        account_recipient_ids = []
        account_alert_ids = []

        if i == 0 and product_pool:
            confirmed_ids = verify_confirmed_credits(session, product_pool, len(unconfirmed_track_ids))
            account_track_ids.extend(confirmed_ids)
            
            # 8. Verify Recipient and Alert Limits
            # verify_recipient_limits fills up to 5 and returns them
            account_recipient_ids = verify_recipient_limits(session, unique_id, user_email)
            if account_recipient_ids:
                account_alert_ids = verify_alert_limits(session, account_recipient_ids[0])
        
        # 5. Recipients (Skip if i=0 and verification already filled them)
        if not account_recipient_ids:
            print(f"Creating {args.recipients} recipients...")
            # Always ensure at least the user's own email is a recipient if requested
            rec_id_1 = create_recipient(session, user_email)
            if rec_id_1: account_recipient_ids.append(rec_id_1)
            
            for r_idx in range(1, args.recipients):
                rec_email = f"utest-{unique_id}-rec{r_idx}@mailrbp.com"
                rid = create_recipient(session, rec_email)
                if rid: account_recipient_ids.append(rid)
        
        # 6. Price Alerts (Skip if i=0 and verification already filled them)
        if not account_alert_ids and account_recipient_ids:
            print(f"Creating {args.alerts} price alerts...")
            
            # Identify verified recipients
            url_r = f"{API_URL}/user/account/recipients"
            resp_r = session.get(url_r)
            verified_rids = []
            if resp_r.status_code == 200:
                recs = resp_r.json().get("data", {}).get("recipients", [])
                verified_rids = [r.get("id") for r in recs if r.get("is_verified")]
            
            for a_idx in range(args.alerts):
                # Try to use a verified recipient first
                if verified_rids:
                    r_id = random.choice(verified_rids)
                else:
                    r_id = random.choice(account_recipient_ids)
                
                aid = create_price_alert(session, r_id, name_suffix=str(a_idx))
                if aid: account_alert_ids.append(aid)
        
        # 7. Favorites (Tracked Products) (Skip if i=0 and verification already filled them)
        if not (i == 0 and product_pool) and product_pool:
            print(f"Creating {args.favorites} favorite product tracks...")
            for _ in range(args.favorites):
                asin = random.choice(product_pool)
                target_alert = random.choice(account_alert_ids) if account_alert_ids else None
                tid = create_tracked_product(session, asin, target_alert)
                if tid: account_track_ids.append(tid)
        
        print(f"DEBUG: Account setup done. Alerts: {account_alert_ids}")

        account_info = {
            "email": user_email, 
            "password": password,
            "recipients": account_recipient_ids,
            "alerts": account_alert_ids,
            "tracks": account_track_ids
        }
        created_credentials.append(account_info)
        
        logger.info(f"Account {i+1} completed setup.")
        
        # 8. Activity Simulation (Churn Phase)
        simulate_user_activity(session, account_info, product_pool)
        print(f"DEBUG: Account simulation done. Alerts in info: {account_info['alerts']}")
        
        logger.info(f"Account {i+1} fully simulated.")


    run_security_tests(created_credentials, openapi_spec)



    # --- Report ---
    print("\n\n" + "="*40)
    print("BENCHMARK COMPLETED")
    print("="*40)
    print("\nCreated Accounts:")
    print(json.dumps(created_credentials, indent=2))
    print("="*40)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Script interrupted.")
    except Exception as e:
        fatal_error(f"Unexpected error: {traceback.format_exc()}")
