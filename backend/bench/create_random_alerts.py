import requests
import random
import uuid
import sys
import time
from typing import List, Dict, Any

# Configuration
BASE_URL = "http://192.168.0.40:9001"
USER_EMAIL = "maborak@maborak.com"
USER_PASSWORD = "4d4l1dc4mp30N2#"
ALERTS_COUNT = 500

TRIGGER_TYPES = [
    "value_up", "value_down", 
    "percent_up", "percent_down", 
    "time_interval", 
    "becomes_available", "becomes_unavailable"
]
TRIGGER_TARGETS = ["total_price", "base_price", "shipping_fee", "import_fees"]
LOGIC_OPERATORS = ["and", "or"]

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
    if not data.get("success"):
        print(f"Login unsuccessful: {data.get('message')}")
        sys.exit(1)
    
    token = data["data"]["tokens"]["access_token"]
    print("Login successful.")
    return token

def get_verified_recipient(token):
    print("Fetching recipients...")
    url = f"{BASE_URL}/user/account/recipients"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch recipients: {response.text}")
        sys.exit(1)
    
    data = response.json()
    recipients = data["data"]["recipients"]
    
    # Try to find a verified one
    verified = [r for r in recipients if r.get("is_verified")]
    if not verified:
        print("No verified recipients found. Trying to add current user email as recipient...")
        # Add the user's own email, which should auto-verify if the user is verified
        add_url = f"{BASE_URL}/user/account/recipients"
        add_payload = {
            "type": "email",
            "value": USER_EMAIL,
            "name": "Main Email"
        }
        add_resp = requests.post(add_url, json=add_payload, headers=headers)
        if add_resp.status_code == 200:
            add_data = add_resp.json()
            recipient_id = add_data["data"]["id"]
            if add_data["data"]["is_verified"]:
                print(f"Added and auto-verified recipient ID: {recipient_id}")
                return recipient_id
            else:
                print(f"Added recipient ID {recipient_id} but it's not verified. Cannot proceed with alerts.")
                sys.exit(1)
        else:
            print(f"Failed to add recipient: {add_resp.text}")
            sys.exit(1)
            
    recipient_id = verified[0]["id"]
    print(f"Using verified recipient ID: {recipient_id}")
    return recipient_id

def create_random_alert(token, recipient_id, index):
    url = f"{BASE_URL}/user/account/price-alerts"
    headers = {"Authorization": f"Bearer {token}"}
    
    name = f"Bench Alert {index+1} - {uuid.uuid4().hex[:8]}"
    num_triggers = random.randint(1, 3)
    triggers = []
    
    used_types = set()
    while len(triggers) < num_triggers:
        t_type = random.choice(TRIGGER_TYPES)
        if t_type in used_types:
            continue
        used_types.add(t_type)
        
        t_value = None
        if t_type in ["value_up", "value_down"]:
            t_value = round(random.uniform(10.0, 1000.0), 2)
        elif t_type in ["percent_up", "percent_down"]:
            t_value = round(random.uniform(1.0, 50.0), 1)
        elif t_type == "time_interval":
            t_value = random.choice([60, 120, 240, 480, 1440]) # minutes
            
        triggers.append({
            "trigger_type": t_type,
            "trigger_value": t_value,
            "target_field": random.choice(TRIGGER_TARGETS)
        })
        
    payload = {
        "name": name,
        "recipient_id": recipient_id,
        "triggers": triggers,
        "logic_operator": random.choice(LOGIC_OPERATORS),
        "is_active": True,
        "cooldown_minutes": random.randint(5, 1440)
    }
    
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        return True, response.json()["data"]["id"]
    else:
        return False, response.text

def main():
    token = login()
    recipient_id = get_verified_recipient(token)
    
    print(f"Starting creation of {ALERTS_COUNT} alerts...")
    success_count = 0
    start_time = time.time()
    
    for i in range(ALERTS_COUNT):
        success, info = create_random_alert(token, recipient_id, i)
        if success:
            success_count += 1
            if (i+1) % 50 == 0:
                print(f"Progress: {i+1}/{ALERTS_COUNT} alerts created.")
        else:
            print(f"Failed to create alert {i+1}: {info}")
            # We continue despite failures unless they are all failing
            
    end_time = time.time()
    duration = end_time - start_time
    print(f"\nFinished!")
    print(f"Successfully created {success_count} alerts.")
    print(f"Total time: {duration:.2f} seconds")
    print(f"Average time per alert: {duration/ALERTS_COUNT:.2f} seconds")

if __name__ == "__main__":
    main()
