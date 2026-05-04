"""
Stripe Adapter integrating with the Stripe REST API.
Implements the PaymentGatewayPort.
"""
import os
import time
import hmac
import hashlib
import requests
import logging
from typing import Dict, Any, Optional
import json

from ports.payment_gateway import PaymentGatewayPort

logger = logging.getLogger(__name__)

class StripePaymentAdapter(PaymentGatewayPort):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # Support both database config and legacy env vars for backward compatibility
        if config:
            self.secret_key = config.get('api_secret')  # Stored as api_secret in DB
            self.webhook_secret = config.get('webhook_secret')  # Stored as webhook_secret in DB
        else:
            # Fallback to environment variables (legacy support)
            self.secret_key = os.getenv("PHOVEU_BACKEND_STRIPE_SECRET_KEY")
            self.webhook_secret = os.getenv("PHOVEU_BACKEND_STRIPE_WEBHOOK_SECRET")
        
        self.base_url = "https://api.stripe.com"

    def create_order(self, amount: float, currency: str, reference_id: str) -> Dict[str, str]:
        """
        Creates a Stripe PaymentIntent.
        """
        url = f"{self.base_url}/v1/payment_intents"
        
        # Stripe expects integer amounts in the smallest currency unit (e.g., cents for USD)
        int_amount = int(amount * 100)
        
        data = {
            "amount": int_amount,
            "currency": currency.lower(),
            "metadata[reference_id]": reference_id,
            "automatic_payment_methods[enabled]": "true"
        }
        
        response = requests.post(url, data=data, auth=(self.secret_key, ''))
        response.raise_for_status()
        
        intent = response.json()
        
        return {
            "id": intent["id"],
            "client_secret": intent["client_secret"] # Needed by frontend Stripe Elements
        }

    def resume_order(self, provider_order_id: str) -> Dict[str, str]:
        """
        Fetches an existing Stripe PaymentIntent.
        """
        url = f"{self.base_url}/v1/payment_intents/{provider_order_id}"
        response = requests.get(url, auth=(self.secret_key, ''))
        response.raise_for_status()
        
        intent = response.json()
        
        return {
            "id": intent["id"],
            "client_secret": intent["client_secret"]
        }

    def capture_order(self, provider_order_id: str) -> bool:
        """
        For Stripe, if we use automatic_payment_methods, capture usually happens automatically 
        on the frontend via Stripe Elements. We can fetch the intent to verify status.
        """
        url = f"{self.base_url}/v1/payment_intents/{provider_order_id}"
        response = requests.get(url, auth=(self.secret_key, ''))
        
        if response.status_code == 200:
            intent = response.json()
            if intent["status"] == "succeeded":
                return True
                
        return False

    def validate_webhook_signature(self, headers: Dict[str, str], payload: bytes) -> Dict[str, Any]:
        """
        Cryptographically validates Stripe webhook signature.
        Header: Stripe-Signature: t=161123,v1=sig1,v0=sig2
        """
        # Ensure we have the exact raw bytes of the payload
        sig_header = None
        for k, v in headers.items():
            if k.lower() == "stripe-signature":
                sig_header = v
                break
                
        if not sig_header:
            raise ValueError("Missing Stripe signature header")

        # Parse signature header
        parsed_sigs = {}
        for item in sig_header.split(','):
            k, v = item.split('=', 1)
            parsed_sigs.setdefault(k, []).append(v)

        timestamp = parsed_sigs.get('t', [''])[0]
        signatures = parsed_sigs.get('v1', [])

        if not timestamp or not signatures:
            raise ValueError("Malformed Stripe signature header")

        # Compute expected signature
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        mac = hmac.new(
            self.webhook_secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        )
        expected_sig = mac.hexdigest()

        # Compare securely
        is_valid = any(hmac.compare_digest(expected_sig, sig) for sig in signatures)
        
        if not is_valid:
            raise ValueError("Stripe Signature Verification Failed")
            
        # Reject webhook events older than 2 minutes to limit replay window
        if time.time() - int(timestamp) > 120:
            raise ValueError("Stripe Webhook Signature is too old")

        return json.loads(payload.decode('utf-8'))

    def extract_transaction_id_from_webhook(self, event_data: Dict[str, Any]) -> Optional[str]:
        # We care about payment_intent events
        try:
            return event_data["data"]["object"]["id"]
        except KeyError:
            return None

    def is_webhook_payment_successful(self, event_data: Dict[str, Any]) -> bool:
        return event_data.get("type") == "payment_intent.succeeded"

    def is_webhook_payment_failed(self, event_data: Dict[str, Any]) -> bool:
        return event_data.get("type") == "payment_intent.payment_failed"
