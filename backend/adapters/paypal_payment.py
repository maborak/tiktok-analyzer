"""
PayPal Adapter integrating with the official PayPal REST API v2.
Implements the PaymentGatewayPort.
"""
import os
import requests
import logging
from typing import Dict, Any, Optional

from config import CONFIG
from ports.payment_gateway import PaymentGatewayPort

logger = logging.getLogger(__name__)

class PayPalPaymentAdapter(PaymentGatewayPort):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # Support both database config and legacy env vars for backward compatibility
        if config:
            self.client_id = config.get('api_key')  # Stored as api_key in DB
            self.secret = config.get('api_secret')    # Stored as api_secret in DB
            self.webhook_id = config.get('webhook_secret')  # Stored as webhook_secret in DB
            mode = config.get('mode', 'sandbox').lower()
        else:
            # Fallback to environment variables (legacy support)
            self.client_id = os.getenv("PHOVEU_BACKEND_PAYPAL_CLIENT_ID")
            self.secret = os.getenv("PHOVEU_BACKEND_PAYPAL_SECRET")
            self.webhook_id = os.getenv("PHOVEU_BACKEND_PAYPAL_WEBHOOK_ID")
            mode = os.getenv("PHOVEU_BACKEND_PAYPAL_MODE", "sandbox").lower()
        
        if mode == "live":
            self.base_url = "https://api-m.paypal.com"
        else:
            self.base_url = "https://api-m.sandbox.paypal.com"

    def _get_access_token(self) -> str:
        url = f"{self.base_url}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US"
        }
        data = {
            "grant_type": "client_credentials"
        }
        response = requests.post(url, headers=headers, data=data, auth=(self.client_id, self.secret))
        response.raise_for_status()
        return response.json()["access_token"]

    def create_order(self, amount: float, currency: str, reference_id: str) -> Dict[str, str]:
        token = self._get_access_token()
        url = f"{self.base_url}/v2/checkout/orders"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        # PayPal expects string amounts formatted safely
        safe_amount = f"{amount:.2f}"
        
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": safe_amount
                    },
                    "description": f"{CONFIG['APP_NAME']} Credits"
                }
            ],
            "application_context": {
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW"
            }
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        # We need the order ID for the frontend to launch standard popup
        return {
            "id": data["id"],
            "status": data["status"]
        }

    def resume_order(self, provider_order_id: str) -> Dict[str, str]:
        token = self._get_access_token()
        url = f"{self.base_url}/v2/checkout/orders/{provider_order_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        return {
            "id": data["id"],
            "status": data["status"]
        }

    def capture_order(self, provider_order_id: str) -> bool:
        token = self._get_access_token()
        url = f"{self.base_url}/v2/checkout/orders/{provider_order_id}/capture"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.post(url, headers=headers)
        
        if response.status_code in (200, 201):
            data = response.json()
            if data["status"] == "COMPLETED":
                return True
                
        logger.error(f"PayPal Capture Failed: {response.status_code} - {response.text}")
        return False

    def validate_webhook_signature(self, headers: Dict[str, str], payload: bytes) -> Dict[str, Any]:
        """
        Calls PayPal API to cryptographically verify the signature.
        PayPal sends multiple headers that must be forwarded to the /verify-webhook-signature endpoint.
        """
        token = self._get_access_token()
        url = f"{self.base_url}/v1/notifications/verify-webhook-signature"
        
        # Format expects string json, we get bytes payload
        import json
        event_dict = json.loads(payload.decode('utf-8'))
        
        # Standardize matching headers (case-insensitive in HTTP, but dict keys are case-sensitive)
        header_map = {k.lower(): v for k, v in headers.items()}

        # Validate cert URL belongs to PayPal to prevent MITM attacks
        cert_url = header_map.get("paypal-cert-url", "")
        if not cert_url or not cert_url.startswith("https://api."):
            raise ValueError("Invalid or missing PayPal certificate URL")

        verify_payload = {
            "auth_algo": header_map.get("paypal-auth-algo"),
            "cert_url": cert_url,
            "transmission_id": header_map.get("paypal-transmission-id"),
            "transmission_sig": header_map.get("paypal-transmission-sig"),
            "transmission_time": header_map.get("paypal-transmission-time"),
            "webhook_id": self.webhook_id,
            "webhook_event": event_dict
        }
        
        req_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.post(url, headers=req_headers, json=verify_payload)
        response.raise_for_status()
        
        verification = response.json()
        if verification.get("verification_status") != "SUCCESS":
            raise ValueError("PayPal Signature Verification Failed")
            
        return event_dict

    def extract_transaction_id_from_webhook(self, event_data: Dict[str, Any]) -> Optional[str]:
        # Based on event type
        event_type = event_data.get("event_type")
        resource = event_data.get("resource", {})
        
        if event_type == "CHECKOUT.ORDER.APPROVED":
            return resource.get("id")
        elif event_type == "PAYMENT.CAPTURE.COMPLETED":
            # For captures, the resource ID is the CAPTURE ID, but there might be a link to the order ID
            supplementary = resource.get("supplementary_data", {})
            related_ids = supplementary.get("related_ids", {})
            return related_ids.get("order_id")
            
        return None

    def is_webhook_payment_successful(self, event_data: Dict[str, Any]) -> bool:
        evt = event_data.get("event_type")
        return evt in ("CHECKOUT.ORDER.APPROVED", "PAYMENT.CAPTURE.COMPLETED")

    def is_webhook_payment_failed(self, event_data: Dict[str, Any]) -> bool:
        evt = event_data.get("event_type")
        return evt in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED")
