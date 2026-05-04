"""
Payment Gateway Port Interface

Contract definition for external payment gateways (Stripe, PayPal)
to implement in order to process transactions and handle webhooks securely.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class PaymentGatewayPort(ABC):
    
    @abstractmethod
    def create_order(self, amount: float, currency: str, reference_id: str) -> Dict[str, str]:
        """
        Initializes an order or payment intent with the external provider.
        Returns a dictionary containing provider-specific keys (e.g., 'id', 'client_secret').
        """
        pass

    @abstractmethod
    def capture_order(self, provider_order_id: str) -> bool:
        """
        Synchronously attempts to capture a user-approved order.
        Returns True if funds were successfully captured, False otherwise.
        """
        pass

    @abstractmethod
    def resume_order(self, provider_order_id: str) -> Dict[str, str]:
        """
        Fetches an existing order or payment intent from the provider.
        Returns a dictionary containing provider-specific keys (e.g., 'id', 'client_secret').
        """
        pass

    @abstractmethod
    def validate_webhook_signature(self, headers: Dict[str, str], payload: bytes) -> Dict[str, Any]:
        """
        Cryptographically validates that the incoming webhook payload 
        came from the trusted provider. Returns the parsed JSON event.
        Raises ValueError if signature is invalid.
        """
        pass

    @abstractmethod
    def extract_transaction_id_from_webhook(self, event_data: Dict[str, Any]) -> Optional[str]:
        """
        Given a validated webhook event payload, extracts the 
        Provider Transaction ID (e.g. pi_123 or PAYPAL_ORDER_ID).
        """
        pass

    @abstractmethod
    def is_webhook_payment_successful(self, event_data: Dict[str, Any]) -> bool:
        """
        Returns True if the event signifies the funds were successfully captured.
        """
        pass

    @abstractmethod
    def is_webhook_payment_failed(self, event_data: Dict[str, Any]) -> bool:
        """
        Returns True if the event signifies the payment failed or was declined.
        """
        pass
