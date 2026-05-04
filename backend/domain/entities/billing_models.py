"""
Domain models for the Billing and Invoicing system.
Follows strict Hexagonal Architecture principles (no dependencies on adapters or database).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class PaymentProvider(str, Enum):
    STRIPE = "STRIPE"
    PAYPAL = "PAYPAL"
    OTHER = "OTHER"
    BITCOIN = "BITCOIN"
    BANK_TRANSFER = "BANK_TRANSFER"

class PaymentStatus(str, Enum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class LedgerSource(str, Enum):
    REGISTRATION = "registration"
    PURCHASE = "purchase"
    ADMIN_GRANT = "admin_grant"
    TRACK_PRODUCT = "track_product"

@dataclass
class CreditPackage:
    id: int
    name: str
    description: Optional[str]
    amount: float
    currency: str
    credits: int
    is_active: bool
    created_at: Optional[datetime] = None

@dataclass
class PaymentTransaction:
    id: str  # UUID
    user_id: int
    package_id: int
    provider: PaymentProvider
    provider_transaction_id: str  # Stripe Intent ID or PayPal Order ID
    status: PaymentStatus
    amount: float
    currency: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class Invoice:
    id: str  # UUID
    transaction_id: str
    user_id: int
    invoice_number: str
    
    # Payment Information
    provider: PaymentProvider  # STRIPE or PAYPAL
    provider_transaction_id: str  # Stripe Payment Intent ID or PayPal Order ID
    
    # Amount Breakdown
    subtotal_amount: float
    tax_amount: float
    total_amount: float
    currency: str
    
    # Billing Information
    billing_email: str
    billing_name: Optional[str]
    
    # Line Items (JSON string or structured data)
    line_items: str  # JSON array of line items with name, description, quantity, unit_price
    
    # Billing Address (optional fields with defaults)
    billing_address_line1: Optional[str] = None
    billing_address_line2: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_country: Optional[str] = None
    
    # Tax & Business Information
    tax_rate: Optional[float] = None  # e.g., 0.08 for 8%
    tax_id: Optional[str] = None  # VAT/GST number if applicable
    
    # Invoice Status & Dates
    status: str = "paid"  # paid, refunded, void
    invoice_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    
    # Metadata
    notes: Optional[str] = None  # Internal notes
    created_at: Optional[datetime] = None

@dataclass
class CreditLedgerEntry:
    id: str  # UUID
    user_id: int
    amount: int
    source: LedgerSource
    transaction_id: Optional[str]  # Nullable if source is REGISTRATION
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    note: Optional[str] = None  # e.g. "B0F6NYKCFR/US" for track_product entries


@dataclass
class PaymentGatewayConfig:
    """Configuration for a payment gateway provider"""
    id: int
    provider: PaymentProvider
    is_enabled: bool
    display_name: Optional[str] = None  # For custom "OTHER" gateway naming
    api_key: Optional[str] = None  # Public key / Client ID
    api_secret: Optional[str] = None  # Secret key (encrypted at rest)
    webhook_secret: Optional[str] = None  # Webhook verification secret
    mode: str = "sandbox"  # "sandbox" or "live"
    config_json: Optional[str] = None  # Additional provider-specific config as JSON
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
