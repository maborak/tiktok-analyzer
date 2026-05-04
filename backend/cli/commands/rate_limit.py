#!/usr/bin/env python3
"""
CLI command to test rate limiting functionality
"""

import click
import requests
import os
import time
from typing import Dict, Any
from config import get_api_url, settings

@click.command()
@click.option('--enable/--disable', 'enable_rate_limit', default=None, help='Enable or disable rate limiting')
@click.option('--requests', default=None, type=int, help='Number of requests per window')
@click.option('--window', default=None, type=int, help='Time window in seconds')
@click.option('--bypass-key', default=None, help='Bypass key for testing')
@click.option('--test-requests', default=5, type=int, help='Number of test requests to make')
@click.option('--username', default='testuser_rate_limit', help='Test username')
@click.option('--password', default='TestPassword123!', help='Test password')
def rate_limit_test(enable_rate_limit, requests, window, bypass_key, test_requests, username, password):
    """Test rate limiting functionality"""
    
    base_url = get_api_url()
    
    print("🔄 Rate Limiting Test")
    print("=" * 40)
    print(f"🌐 API URL: {base_url}")
    
    # Show current configuration
    print(f"\n📊 Current Configuration:")
    print(f"   • Enabled: {settings('RATE_LIMIT_ENABLED', True)}")
    print(f"   • Requests: {settings('RATE_LIMIT_REQUESTS', 20)}")
    print(f"   • Window: {settings('RATE_LIMIT_WINDOW', 60)}s")
    print(f"   • Bypass Key: {settings('RATE_LIMIT_BYPASS_KEY')}")
    
    # Update configuration if provided
    if enable_rate_limit is not None:
        # Update environment variable
        os.environ["PHOVEU_BACKEND_RATE_LIMIT_ENABLED"] = str(enable_rate_limit).lower()
        print(f"   ✅ Updated enabled: {enable_rate_limit}")
    
    if requests is not None:
        os.environ["PHOVEU_BACKEND_RATE_LIMIT_REQUESTS"] = str(requests)
        print(f"   ✅ Updated requests: {requests}")
    
    if window is not None:
        os.environ["PHOVEU_BACKEND_RATE_LIMIT_WINDOW"] = str(window)
        print(f"   ✅ Updated window: {window}s")
    
    if bypass_key is not None:
        if bypass_key == "":
            os.environ.pop("PHOVEU_BACKEND_RATE_LIMIT_BYPASS_KEY", None)
            print("   ✅ Removed bypass key")
        else:
            os.environ["PHOVEU_BACKEND_RATE_LIMIT_BYPASS_KEY"] = bypass_key
            print(f"   ✅ Updated bypass key: {bypass_key}")
    
    # Show updated configuration
    print(f"\n📊 Updated Configuration:")
    print(f"🌐 API URL: {get_api_url()}")
    print(f"✅ Enabled: {settings('RATE_LIMIT_ENABLED', True)}")
    print(f"📈 Requests: {settings('RATE_LIMIT_REQUESTS', 20)} per {settings('RATE_LIMIT_WINDOW', 60)} seconds")
    print(f"🔑 Bypass Key: {settings('RATE_LIMIT_BYPASS_KEY') or 'None'}")
    
    # Test requests
    print(f"\n🧪 Testing {test_requests} requests...")
    
    headers = {}
    if bypass_key:
        headers["X-Rate-Limit-Bypass"] = bypass_key
    
    for i in range(test_requests):
        try:
            response = requests.post(f"{base_url}/auth/login", 
                                  json={"username": username, "password": password},
                                  headers=headers)
            print(f"   Request {i+1}: Status {response.status_code}")
            
            if response.status_code == 429:
                print("   ✅ Rate limiting kicked in!")
                break
            elif response.status_code == 200:
                print("   ✅ Request successful")
            else:
                print(f"   ⚠️ Unexpected status: {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print("\n✅ Rate limiting test completed!")

@click.command()
def rate_limit_status():
    """Show current rate limiting status"""
    
    print("📊 Rate Limiting Status")
    print("=" * 30)
    
    print(f"🌐 API URL: {get_api_url()}")
    print(f"✅ Enabled: {settings('RATE_LIMIT_ENABLED', True)}")
    print(f"📈 Requests: {settings('RATE_LIMIT_REQUESTS', 20)} per {settings('RATE_LIMIT_WINDOW', 60)} seconds")
    print(f"🔑 Bypass Key: {settings('RATE_LIMIT_BYPASS_KEY') or 'None'}")
    
    # Test current configuration
    print(f"\n🧪 Testing current configuration...")
    
    try:
        response = requests.post(f"{get_api_url()}/auth/login", 
                              json={"username": "testuser", "password": "password"})
        print(f"   Test request: Status {response.status_code}")
        
        if response.status_code == 429:
            print("   ✅ Rate limiting is active")
        elif response.status_code == 401:
            print("   ✅ Authentication working (expected 401 for invalid credentials)")
        else:
            print(f"   ⚠️ Unexpected response: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Error testing: {e}")

@click.group()
def rate_limit():
    """Rate limiting test commands"""
    pass

rate_limit.add_command(rate_limit_test, name='test')
rate_limit.add_command(rate_limit_status, name='status')

if __name__ == '__main__':
    rate_limit() 