from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, func, Text
from sqlalchemy.orm import relationship, backref

from database.core.base import Base
from domain.entities.billing_models import PaymentProvider, PaymentStatus, LedgerSource


class CreditPackageModel(Base):
    __tablename__ = "credit_packages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    credits = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)


class PaymentTransactionModel(Base):
    __tablename__ = "payment_transactions"

    id = Column(String(36), primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    package_id = Column(Integer, ForeignKey('credit_packages.id', ondelete='SET NULL'), nullable=True)

    provider = Column(Enum(PaymentProvider), nullable=False, index=True)
    provider_transaction_id = Column(String(255), nullable=True, unique=True, index=True)
    status = Column(Enum(PaymentStatus), nullable=False, index=True)

    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)

    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)

    # Relationships
    user = relationship("User", backref=backref("payment_transactions", passive_deletes=True))
    package = relationship("CreditPackageModel")
    invoice = relationship("InvoiceModel", back_populates="transaction", uselist=False, cascade="all, delete-orphan")
    ledger_entries = relationship("CreditLedgerModel", back_populates="transaction")


class CreditLedgerModel(Base):
    """
    Capacity blocks valid for one month.
    """
    __tablename__ = "credit_ledgers"

    id = Column(String(36), primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    source = Column(Enum(LedgerSource), nullable=False)

    # Nullable because REGISTRATION sources might not have a transaction
    transaction_id = Column(String(36), ForeignKey('payment_transactions.id', ondelete='SET NULL'), nullable=True, index=True)

    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    note = Column(String(500), nullable=True)  # e.g. "B0F6NYKCFR/US" for track_product entries

    # Relationships
    user = relationship("User", backref=backref("credit_ledgers", passive_deletes=True))
    transaction = relationship("PaymentTransactionModel", back_populates="ledger_entries")


class InvoiceModel(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True) # UUID
    transaction_id = Column(String(36), ForeignKey('payment_transactions.id', ondelete='CASCADE'), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)

    invoice_number = Column(String(100), nullable=False, unique=True, index=True)

    # Payment Information
    provider = Column(Enum(PaymentProvider, native_enum=False, create_constraint=False, 
                          length=20), nullable=False, index=True)
    provider_transaction_id = Column(String(255), nullable=True, index=True)

    # Amount Breakdown
    subtotal_amount = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False, server_default="0.0")
    total_amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)

    # Billing Information
    billing_email = Column(String(255), nullable=False)
    billing_name = Column(String(255), nullable=True)
    billing_address_line1 = Column(String(255), nullable=True)
    billing_address_line2 = Column(String(255), nullable=True)
    billing_city = Column(String(100), nullable=True)
    billing_state = Column(String(100), nullable=True)
    billing_postal_code = Column(String(20), nullable=True)
    billing_country = Column(String(2), nullable=True)

    # Line Items (JSON)
    line_items = Column(String(2000), nullable=False)

    # Tax & Business Information
    tax_rate = Column(Float, nullable=True)
    tax_id = Column(String(50), nullable=True)

    # Invoice Status & Dates
    status = Column(String(20), nullable=False, server_default="paid", index=True)
    invoice_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Metadata
    notes = Column(String(1000), nullable=True)

    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    # Relationships
    transaction = relationship("PaymentTransactionModel", back_populates="invoice")
    user = relationship("User", backref=backref("invoices", passive_deletes=True))


class PaymentGatewayConfigModel(Base):
    """
    Configuration for payment gateway providers (PayPal, Stripe, Other).
    Stores API credentials and enable/disable status.
    """
    __tablename__ = "payment_gateway_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Provider type - STRIPE, PAYPAL, or OTHER
    provider = Column(Enum(PaymentProvider), nullable=False, unique=True, index=True)
    
    # Enable/disable flag
    is_enabled = Column(Boolean, default=False, nullable=False, index=True)
    
    # Display name (useful for "OTHER" gateway or custom branding)
    display_name = Column(String(100), nullable=True)
    
    # API Credentials
    api_key = Column(String(500), nullable=True)  # Public key / Client ID (encrypted)
    api_secret = Column(String(500), nullable=True)  # Secret key (encrypted)
    webhook_secret = Column(String(500), nullable=True)  # Webhook verification secret (encrypted)
    
    # Mode: sandbox or live
    mode = Column(String(20), default="sandbox", nullable=False)
    
    # Additional provider-specific configuration as JSON
    config_json = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
