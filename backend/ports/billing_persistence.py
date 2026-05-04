from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class BillingPersistencePort(ABC):
    """Port for billing, credit, and payment persistence operations"""

    # --- Credit Packages ---
    @abstractmethod
    def get_credit_package_by_id(self, package_id: int) -> Optional[Any]:
        """Get a credit package by ID"""
        pass

    @abstractmethod
    def get_active_credit_packages(self) -> List[Any]:
        """Get all active available credit packages for purchase"""
        pass

    @abstractmethod
    def get_all_credit_packages(self) -> List[Any]:
        """Get all credit packages (active and inactive)"""
        pass

    @abstractmethod
    def create_credit_package(self, package: Any) -> Any:
        """Create a new credit package"""
        pass

    @abstractmethod
    def update_credit_package(self, package_id: int, package_data: dict) -> Optional[Any]:
        """Update an existing credit package"""
        pass

    @abstractmethod
    def delete_credit_package(self, package_id: int) -> bool:
        """Soft delete or deactivate a credit package"""
        pass

    # --- Payment Transactions ---
    @abstractmethod
    def create_payment_transaction(self, transaction: Any) -> str:
        """Create a new payment transaction. Returns generated ID."""
        pass

    @abstractmethod
    def update_payment_transaction(self, transaction: Any) -> bool:
        """Update an existing payment transaction"""
        pass

    @abstractmethod
    def update_payment_transaction_status(self, transaction_id: str, status: Any) -> bool:
        """Update only the status of a payment transaction"""
        pass

    @abstractmethod
    def get_payment_transaction_by_provider_id(self, provider_transaction_id: str) -> Optional[Any]:
        """Get a payment transaction by its gateway provider ID"""
        pass

    @abstractmethod
    def get_payment_transaction_by_id(self, transaction_id: str) -> Optional[Any]:
        """Get a payment transaction by its internal ID"""
        pass

    @abstractmethod
    def get_payment_transactions(self, status: Optional[Any] = None, provider: Optional[Any] = None, user_id: Optional[int] = None, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get paginated payment transactions"""
        pass

    # --- Credit Ledger ---
    @abstractmethod
    def create_ledger_entry_from_purchase(self, transaction_id: str, amount: int) -> str:
        """Creates a new CreditLedgerEntry from a completed transaction"""
        pass

    @abstractmethod
    def get_valid_ledgers_for_user(self, user_id: int) -> List[Any]:
        """Get all unexpired credit ledger entries for a user."""
        pass

    @abstractmethod
    def add_credit_ledger_entry(self, entry: Any) -> str:
        """Add a manual credit ledger entry"""
        pass

    @abstractmethod
    def get_user_credit_history(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get paginated credit ledger history for a user"""
        pass

    # --- Invoices ---
    @abstractmethod
    def create_invoice(self, invoice: Any) -> str:
        """Create a new invoice linked to a successful transaction."""
        pass

    @abstractmethod
    def get_invoice_by_id(self, invoice_id: str) -> Optional[Any]:
        """Get an invoice by ID."""
        pass

    @abstractmethod
    def get_invoice_by_transaction_id(self, transaction_id: str) -> Optional[Any]:
        """Get an invoice by its associated transaction ID."""
        pass

    @abstractmethod
    def update_invoice_status(self, invoice_id: str, status: str) -> bool:
        """Update the status of an invoice."""
        pass

    @abstractmethod
    def update_invoice_to_paid(self, invoice_id: str, provider_transaction_id: str, paid_at: Any) -> bool:
        """Update an invoice status to paid and update payment details."""
        pass

    @abstractmethod
    def get_user_invoices(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get paginated invoices for a user."""
        pass

    # --- User (billing context) ---
    @abstractmethod
    def get_user(self, user_id: int) -> Optional[Any]:
        """Get user details (needed for invoice generation)."""
        pass

    # --- Payment Gateway Configuration ---
    @abstractmethod
    def get_payment_gateway_configs(self) -> List[Any]:
        """Get all payment gateway configurations."""
        pass

    @abstractmethod
    def get_payment_gateway_config(self, provider: Any) -> Optional[Any]:
        """Get configuration for a specific payment gateway provider."""
        pass

    @abstractmethod
    def create_payment_gateway_config(self, config: Any) -> Any:
        """Create a new payment gateway configuration."""
        pass

    @abstractmethod
    def update_payment_gateway_config(self, provider: Any, config_data: dict) -> Optional[Any]:
        """Update an existing payment gateway configuration."""
        pass
