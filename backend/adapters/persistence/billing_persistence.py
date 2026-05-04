"""
Billing persistence adapter — implements BillingPersistencePort.

Extracted from adapters/database_persistence.py. Handles:
    - Credit packages (CRUD)
    - Payment transactions (CRUD, status updates, paginated listing)
    - Credit ledger (entries, balance queries, enriched history)
    - Invoices (CRUD, status updates, paginated listing)
    - User lookup (billing context)
    - Payment gateway configuration (CRUD)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc
import uuid
import logging

from ports.billing_persistence import BillingPersistencePort
from adapters.persistence._base import BasePersistenceAdapter

from domain.entities.auth_models import User as AuthUser, UserRole
from domain.entities.billing_models import (
    CreditPackage, PaymentTransaction, CreditLedgerEntry, Invoice,
    PaymentProvider, PaymentStatus, LedgerSource
)
from database.auth.models import User as UserModel

logger = logging.getLogger(__name__)


class DatabaseBillingPersistenceAdapter(BasePersistenceAdapter, BillingPersistencePort):
    """Implements BillingPersistencePort — billing, credit, invoice, and payment persistence."""

    # ------------------------------------------------------------------
    # User (billing context)
    # ------------------------------------------------------------------

    def get_user(self, user_id: int) -> Optional[AuthUser]:
        def _get(db_session: Session):
            u = db_session.query(UserModel).filter(UserModel.id == user_id).first()
            if not u: return None
            return AuthUser(
                id=u.id, username=u.username, email=u.email, first_name=u.first_name,
                last_name=u.last_name, role=UserRole(u.role_name) if hasattr(u, 'role_name') else UserRole.USER,
                is_active=u.is_active, is_verified=u.is_verified
            )
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Credit Packages
    # ------------------------------------------------------------------

    def get_credit_package_by_id(self, package_id: int) -> Optional[CreditPackage]:
        def _get(db_session: Session):
            from database.billing.models import CreditPackageModel
            p = db_session.query(CreditPackageModel).filter(CreditPackageModel.id == package_id).first()
            if not p: return None
            return CreditPackage(
                id=p.id, name=p.name, description=p.description,
                amount=p.amount, currency=p.currency, credits=p.credits,
                is_active=p.is_active, created_at=p.created_at
            )
        return self._execute_with_retry(_get)

    def get_active_credit_packages(self) -> List[CreditPackage]:
        def _get(db_session: Session):
            from database.billing.models import CreditPackageModel
            packages = db_session.query(CreditPackageModel).filter(CreditPackageModel.is_active == True).all()
            return [CreditPackage(
                id=p.id, name=p.name, description=p.description,
                amount=p.amount, currency=p.currency, credits=p.credits,
                is_active=p.is_active, created_at=p.created_at
            ) for p in packages]
        return self._execute_with_retry(_get)

    def get_all_credit_packages(self) -> List[CreditPackage]:
        """Get all credit packages (active and inactive)"""
        def _get(db_session: Session):
            from database.billing.models import CreditPackageModel
            packages = db_session.query(CreditPackageModel).all()
            return [CreditPackage(
                id=p.id, name=p.name, description=p.description,
                amount=p.amount, currency=p.currency, credits=p.credits,
                is_active=p.is_active, created_at=p.created_at
            ) for p in packages]
        return self._execute_with_retry(_get)

    def create_credit_package(self, package: CreditPackage) -> CreditPackage:
        def _create(db_session: Session):
            from database.billing.models import CreditPackageModel
            db_pkg = CreditPackageModel(
                name=package.name,
                description=package.description,
                amount=package.amount,
                currency=package.currency,
                credits=package.credits,
                is_active=package.is_active
            )
            db_session.add(db_pkg)
            db_session.flush()
            return CreditPackage(
                id=db_pkg.id, name=db_pkg.name, description=db_pkg.description,
                amount=db_pkg.amount, currency=db_pkg.currency, credits=db_pkg.credits,
                is_active=db_pkg.is_active, created_at=db_pkg.created_at
            )
        return self._execute_with_retry(_create)

    def update_credit_package(self, package_id: int, package_data: dict) -> Optional[CreditPackage]:
        def _update(db_session: Session):
            from database.billing.models import CreditPackageModel
            pkg = db_session.query(CreditPackageModel).filter(CreditPackageModel.id == package_id).first()
            if not pkg: return None
            for key, value in package_data.items():
                if hasattr(pkg, key):
                    setattr(pkg, key, value)
            db_session.flush()
            return CreditPackage(
                id=pkg.id, name=pkg.name, description=pkg.description,
                amount=pkg.amount, currency=pkg.currency, credits=pkg.credits,
                is_active=pkg.is_active, created_at=pkg.created_at
            )
        return self._execute_with_retry(_update)

    def delete_credit_package(self, package_id: int) -> bool:
        def _delete(db_session: Session):
            from database.billing.models import CreditPackageModel
            pkg = db_session.query(CreditPackageModel).filter(CreditPackageModel.id == package_id).first()
            if not pkg: return False
            db_session.delete(pkg)
            return True
        return self._execute_with_retry(_delete)

    # ------------------------------------------------------------------
    # Payment Transactions
    # ------------------------------------------------------------------

    def create_payment_transaction(self, transaction: PaymentTransaction) -> str:
        def _create(db_session: Session):
            from database.billing.models import PaymentTransactionModel
            new_id = str(uuid.uuid4())
            db_tx = PaymentTransactionModel(
                id=new_id,
                user_id=transaction.user_id,
                package_id=transaction.package_id,
                provider=transaction.provider,
                provider_transaction_id=transaction.provider_transaction_id,
                status=transaction.status,
                amount=transaction.amount,
                currency=transaction.currency
            )
            db_session.add(db_tx)
            db_session.flush()
            transaction.id = new_id
            return new_id
        return self._execute_with_retry(_create)

    def update_payment_transaction(self, transaction: PaymentTransaction) -> bool:
        def _update(db_session: Session):
            from database.billing.models import PaymentTransactionModel
            t = db_session.query(PaymentTransactionModel).filter(PaymentTransactionModel.id == transaction.id).first()
            if not t: return False
            t.status = transaction.status
            return True
        return self._execute_with_retry(_update)

    def update_payment_transaction_status(self, transaction_id: str, status: PaymentStatus) -> bool:
        """Update only the status of a payment transaction (for manual payment verification)"""
        def _update(db_session: Session):
            from database.billing.models import PaymentTransactionModel
            t = db_session.query(PaymentTransactionModel).filter(PaymentTransactionModel.id == transaction_id).first()
            if not t:
                return False
            t.status = status
            t.updated_at = datetime.now(timezone.utc)
            return True
        return self._execute_with_retry(_update)

    def get_payment_transaction_by_provider_id(self, provider_transaction_id: str) -> Optional[PaymentTransaction]:
        def _get(db_session: Session):
            from database.billing.models import PaymentTransactionModel
            t = db_session.query(PaymentTransactionModel).filter(PaymentTransactionModel.provider_transaction_id == provider_transaction_id).first()
            if not t: return None
            return PaymentTransaction(
                id=t.id, user_id=t.user_id, package_id=t.package_id,
                provider=PaymentProvider(t.provider.value),
                provider_transaction_id=t.provider_transaction_id,
                status=PaymentStatus(t.status.value),
                amount=t.amount, currency=t.currency,
                created_at=t.created_at, updated_at=t.updated_at
            )
        return self._execute_with_retry(_get)

    def get_payment_transaction_by_id(self, transaction_id: str) -> Optional[PaymentTransaction]:
        def _get(db_session: Session):
            from database.billing.models import PaymentTransactionModel
            t = db_session.query(PaymentTransactionModel).filter(PaymentTransactionModel.id == transaction_id).first()
            if not t: return None
            return PaymentTransaction(
                id=t.id, user_id=t.user_id, package_id=t.package_id,
                provider=PaymentProvider(t.provider.value) if hasattr(t.provider, 'value') else PaymentProvider(t.provider),
                provider_transaction_id=t.provider_transaction_id,
                status=PaymentStatus(t.status.value) if hasattr(t.status, 'value') else PaymentStatus(t.status),
                amount=t.amount, currency=t.currency,
                created_at=t.created_at, updated_at=t.updated_at
            )
        return self._execute_with_retry(_get)

    def get_payment_transactions(self, status: Optional[Any] = None, provider: Optional[Any] = None, user_id: Optional[int] = None, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        def _get(db_session: Session):
            from database.billing.models import PaymentTransactionModel, InvoiceModel
            from database.auth.models import User

            query = db_session.query(PaymentTransactionModel, User.email, User.first_name, User.last_name, InvoiceModel).outerjoin(
                User, PaymentTransactionModel.user_id == User.id
            ).outerjoin(
                InvoiceModel, PaymentTransactionModel.id == InvoiceModel.transaction_id
            )

            if status:
                status_val = status.value if hasattr(status, 'value') else status
                query = query.filter(PaymentTransactionModel.status == status_val)

            if provider:
                if isinstance(provider, list):
                    provider_vals = [p.value if hasattr(p, 'value') else p for p in provider]
                    query = query.filter(PaymentTransactionModel.provider.in_(provider_vals))
                else:
                    provider_val = provider.value if hasattr(provider, 'value') else provider
                    query = query.filter(PaymentTransactionModel.provider == provider_val)

            if user_id:
                query = query.filter(PaymentTransactionModel.user_id == user_id)

            total = query.count()
            offset = (page - 1) * page_size
            results = query.order_by(desc(PaymentTransactionModel.created_at)).offset(offset).limit(page_size).all()

            transactions = []
            for tx, email, first_name, last_name, invoice in results:
                name_parts = [p for p in [first_name, last_name] if p]
                tx_dict = {
                    "id": tx.id,
                    "user_id": tx.user_id,
                    "user_email": email,
                    "user_name": " ".join(name_parts) if name_parts else None,
                    "provider": tx.provider.value if hasattr(tx.provider, 'value') else str(tx.provider),
                    "provider_transaction_id": tx.provider_transaction_id,
                    "amount": tx.amount,
                    "currency": tx.currency,
                    "status": tx.status.value if hasattr(tx.status, 'value') else str(tx.status),
                    "package_id": tx.package_id,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                    "updated_at": tx.updated_at.isoformat() if tx.updated_at else None,
                    "invoice": {
                        "id": invoice.id,
                        "invoice_number": invoice.invoice_number,
                        "status": invoice.status,
                        "total_amount": invoice.total_amount,
                        "currency": invoice.currency,
                        "created_at": invoice.created_at.isoformat() if invoice.created_at else None
                    } if invoice else None
                }
                transactions.append(tx_dict)

            return {
                "items": transactions,
                "total": total,
                "page": page,
                "page_size": page_size
            }
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Credit Ledger
    # ------------------------------------------------------------------

    def create_ledger_entry_from_purchase(self, transaction_id: str, amount: int) -> str:
        def _create(db_session: Session):
            from database.billing.models import CreditLedgerModel, PaymentTransactionModel
            t = db_session.query(PaymentTransactionModel).filter(PaymentTransactionModel.id == transaction_id).first()
            if not t: raise ValueError("Transaction not found")

            new_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            # Valid for exactly 1 month
            expires = now + timedelta(days=30)

            ledger = CreditLedgerModel(
                id=new_id,
                user_id=t.user_id,
                amount=amount,
                source=LedgerSource.PURCHASE,
                transaction_id=transaction_id,
                created_at=now,
                expires_at=expires
            )
            db_session.add(ledger)
            db_session.flush()
            return new_id
        return self._execute_with_retry(_create)

    def get_valid_ledgers_for_user(self, user_id: int) -> List[CreditLedgerEntry]:
        def _get(db_session: Session):
            from database.billing.models import CreditLedgerModel
            now = datetime.now(timezone.utc)
            ledgers = db_session.query(CreditLedgerModel).filter(
                CreditLedgerModel.user_id == user_id,
                CreditLedgerModel.expires_at > now
            ).all()

            return [CreditLedgerEntry(
                id=l.id, user_id=l.user_id, amount=l.amount,
                source=LedgerSource(l.source.value) if hasattr(l.source, 'value') else l.source,
                transaction_id=l.transaction_id,
                created_at=l.created_at, expires_at=l.expires_at
            ) for l in ledgers]
        return self._execute_with_retry(_get)

    def add_credit_ledger_entry(self, entry: CreditLedgerEntry) -> str:
        def _add(db_session: Session):
            from database.billing.models import CreditLedgerModel
            new_id = str(uuid.uuid4())
            db_entry = CreditLedgerModel(
                id=new_id,
                user_id=entry.user_id,
                amount=entry.amount,
                source=entry.source,
                transaction_id=entry.transaction_id,
                expires_at=entry.expires_at,
                note=getattr(entry, 'note', None)
            )
            db_session.add(db_entry)
            db_session.flush()
            entry.id = new_id
            return new_id
        return self._execute_with_retry(_add)

    def get_user_credit_history(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get paginated credit ledger history for a user, showing both positive and negative entries."""
        def _get(db_session: Session):
            from database.billing.models import CreditLedgerModel
            from domain.entities.billing_models import CreditLedgerEntry, LedgerSource
            from sqlalchemy import desc

            query = db_session.query(CreditLedgerModel).filter(
                CreditLedgerModel.user_id == user_id
            ).order_by(desc(CreditLedgerModel.created_at))

            total = query.count()
            offset = (page - 1) * page_size
            db_records = query.offset(offset).limit(page_size).all()

            # Parse notes for product_id / country_code (product models removed)
            parsed_notes: Dict[str, tuple] = {}  # id -> (product_id, country_code)
            for r in db_records:
                note = getattr(r, 'note', None)
                if note and '/' in note:
                    parts = note.split('/', 1)
                    pid, cc = parts[0] or None, parts[1] or None
                    if pid:
                        parsed_notes[r.id] = (pid, cc)

            items = []
            for r in db_records:
                note = getattr(r, 'note', None)
                product_id = None
                country_code = None
                track_exists = None
                product_title = None
                product_image = None

                if r.id in parsed_notes:
                    product_id, country_code = parsed_notes[r.id]

                entry = CreditLedgerEntry(
                    id=r.id,
                    user_id=r.user_id,
                    amount=r.amount,
                    source=LedgerSource(r.source.value) if hasattr(r.source, 'value') else r.source,
                    transaction_id=r.transaction_id,
                    created_at=r.created_at,
                    expires_at=r.expires_at,
                    note=note,
                )
                entry.product_id = product_id
                entry.country_code = country_code
                entry.track_exists = track_exists
                entry.product_title = product_title
                entry.product_image = product_image
                items.append(entry)

            return {
                "items": items,
                "pagination": {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0
                }
            }
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    def create_invoice(self, invoice: Invoice) -> str:
        def _create(db_session: Session):
            from database.billing.models import InvoiceModel
            new_id = str(uuid.uuid4())
            db_inv = InvoiceModel(
                id=new_id,
                transaction_id=invoice.transaction_id,
                user_id=invoice.user_id,
                invoice_number=invoice.invoice_number,
                provider=invoice.provider,
                provider_transaction_id=invoice.provider_transaction_id,
                subtotal_amount=invoice.subtotal_amount,
                tax_amount=invoice.tax_amount,
                total_amount=invoice.total_amount,
                currency=invoice.currency,
                billing_email=invoice.billing_email,
                billing_name=invoice.billing_name,
                billing_address_line1=invoice.billing_address_line1,
                billing_address_line2=invoice.billing_address_line2,
                billing_city=invoice.billing_city,
                billing_state=invoice.billing_state,
                billing_postal_code=invoice.billing_postal_code,
                billing_country=invoice.billing_country,
                line_items=invoice.line_items,
                tax_rate=invoice.tax_rate,
                tax_id=invoice.tax_id,
                status=invoice.status,
                invoice_date=invoice.invoice_date,
                due_date=invoice.due_date,
                paid_at=invoice.paid_at,
                notes=invoice.notes
            )
            db_session.add(db_inv)
            db_session.flush()
            invoice.id = new_id
            return new_id
        return self._execute_with_retry(_create)

    def get_invoice_by_id(self, invoice_id: str) -> Optional[Invoice]:
        def _get(db_session: Session):
            from database.billing.models import InvoiceModel
            i = db_session.query(InvoiceModel).filter(InvoiceModel.id == invoice_id).first()
            if not i: return None
            return Invoice(
                id=i.id,
                transaction_id=i.transaction_id,
                user_id=i.user_id,
                invoice_number=i.invoice_number,
                provider=i.provider,
                provider_transaction_id=i.provider_transaction_id,
                subtotal_amount=i.subtotal_amount,
                tax_amount=i.tax_amount,
                total_amount=i.total_amount,
                currency=i.currency,
                billing_email=i.billing_email,
                billing_name=i.billing_name,
                billing_address_line1=i.billing_address_line1,
                billing_address_line2=i.billing_address_line2,
                billing_city=i.billing_city,
                billing_state=i.billing_state,
                billing_postal_code=i.billing_postal_code,
                billing_country=i.billing_country,
                line_items=i.line_items,
                tax_rate=i.tax_rate,
                tax_id=i.tax_id,
                status=i.status,
                invoice_date=i.invoice_date,
                due_date=i.due_date,
                paid_at=i.paid_at,
                notes=i.notes,
                created_at=i.created_at
            )
        return self._execute_with_retry(_get)

    def get_invoice_by_transaction_id(self, transaction_id: str) -> Optional[Invoice]:
        """Get an invoice by its associated transaction ID."""
        def _get(db_session: Session):
            from database.billing.models import InvoiceModel
            i = db_session.query(InvoiceModel).filter(InvoiceModel.transaction_id == transaction_id).first()
            if not i: return None
            return Invoice(
                id=i.id,
                transaction_id=i.transaction_id,
                user_id=i.user_id,
                invoice_number=i.invoice_number,
                provider=i.provider,
                provider_transaction_id=i.provider_transaction_id,
                subtotal_amount=i.subtotal_amount,
                tax_amount=i.tax_amount,
                total_amount=i.total_amount,
                currency=i.currency,
                billing_email=i.billing_email,
                billing_name=i.billing_name,
                billing_address_line1=i.billing_address_line1,
                billing_address_line2=i.billing_address_line2,
                billing_city=i.billing_city,
                billing_state=i.billing_state,
                billing_postal_code=i.billing_postal_code,
                billing_country=i.billing_country,
                line_items=i.line_items,
                tax_rate=i.tax_rate,
                tax_id=i.tax_id,
                status=i.status,
                invoice_date=i.invoice_date,
                due_date=i.due_date,
                paid_at=i.paid_at,
                notes=i.notes,
                created_at=i.created_at
            )
        return self._execute_with_retry(_get)

    def update_invoice_status(self, invoice_id: str, status: str) -> bool:
        def _update(db_session: Session):
            from database.billing.models import InvoiceModel
            inv = db_session.query(InvoiceModel).filter(InvoiceModel.id == invoice_id).first()
            if not inv: return False
            inv.status = status
            return True
        return self._execute_with_retry(_update)

    def update_invoice_to_paid(self, invoice_id: str, provider_transaction_id: str, paid_at: datetime) -> bool:
        def _update(db_session: Session):
            from database.billing.models import InvoiceModel
            inv = db_session.query(InvoiceModel).filter(InvoiceModel.id == invoice_id).first()
            if not inv: return False
            inv.status = "paid"
            inv.provider_transaction_id = provider_transaction_id
            inv.paid_at = paid_at
            return True
        return self._execute_with_retry(_update)

    def get_user_invoices(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        def _get(db_session: Session):
            from database.billing.models import InvoiceModel
            query = db_session.query(InvoiceModel).filter(InvoiceModel.user_id == user_id).order_by(desc(InvoiceModel.created_at))
            total = query.count()
            offset = (page - 1) * page_size
            results = query.offset(offset).limit(page_size).all()

            items = [Invoice(
                id=i.id,
                transaction_id=i.transaction_id,
                user_id=i.user_id,
                invoice_number=i.invoice_number,
                provider=i.provider,
                provider_transaction_id=i.provider_transaction_id,
                subtotal_amount=i.subtotal_amount,
                tax_amount=i.tax_amount,
                total_amount=i.total_amount,
                currency=i.currency,
                billing_email=i.billing_email,
                billing_name=i.billing_name,
                billing_address_line1=i.billing_address_line1,
                billing_address_line2=i.billing_address_line2,
                billing_city=i.billing_city,
                billing_state=i.billing_state,
                billing_postal_code=i.billing_postal_code,
                billing_country=i.billing_country,
                line_items=i.line_items,
                tax_rate=i.tax_rate,
                tax_id=i.tax_id,
                status=i.status,
                invoice_date=i.invoice_date,
                due_date=i.due_date,
                paid_at=i.paid_at,
                notes=i.notes,
                created_at=i.created_at
            ) for i in results]

            return {
                "items": items,
                "pagination": {
                    "total": total,
                    "page": page,
                    "page_size": page_size
                }
            }
        return self._execute_with_retry(_get)

    # ------------------------------------------------------------------
    # Payment Gateway Configuration
    # ------------------------------------------------------------------

    def get_payment_gateway_configs(self) -> List[Any]:
        """Get all payment gateway configurations."""
        def _get(db_session: Session):
            from database.billing.models import PaymentGatewayConfigModel
            from domain.entities.billing_models import PaymentGatewayConfig, PaymentProvider

            configs = db_session.query(PaymentGatewayConfigModel).all()
            return [
                PaymentGatewayConfig(
                    id=c.id,
                    provider=PaymentProvider(c.provider),
                    is_enabled=c.is_enabled,
                    display_name=c.display_name,
                    api_key=c.api_key,
                    api_secret=c.api_secret,
                    webhook_secret=c.webhook_secret,
                    mode=c.mode,
                    config_json=c.config_json,
                    created_at=c.created_at,
                    updated_at=c.updated_at
                )
                for c in configs
            ]
        return self._execute_with_retry(_get)

    def get_payment_gateway_config(self, provider: Any) -> Optional[Any]:
        """Get configuration for a specific payment gateway provider."""
        def _get(db_session: Session):
            from database.billing.models import PaymentGatewayConfigModel
            from domain.entities.billing_models import PaymentGatewayConfig, PaymentProvider

            c = db_session.query(PaymentGatewayConfigModel).filter(
                PaymentGatewayConfigModel.provider == provider.value
            ).first()

            if not c:
                return None

            return PaymentGatewayConfig(
                id=c.id,
                provider=PaymentProvider(c.provider),
                is_enabled=c.is_enabled,
                display_name=c.display_name,
                api_key=c.api_key,
                api_secret=c.api_secret,
                webhook_secret=c.webhook_secret,
                mode=c.mode,
                config_json=c.config_json,
                created_at=c.created_at,
                updated_at=c.updated_at
            )
        return self._execute_with_retry(_get)

    def create_payment_gateway_config(self, config: Any) -> Any:
        """Create a new payment gateway configuration."""
        def _create(db_session: Session):
            from database.billing.models import PaymentGatewayConfigModel

            db_config = PaymentGatewayConfigModel(
                provider=config.provider.value,
                is_enabled=config.is_enabled,
                display_name=config.display_name,
                api_key=config.api_key,
                api_secret=config.api_secret,
                webhook_secret=config.webhook_secret,
                mode=config.mode,
                config_json=config.config_json
            )
            db_session.add(db_config)
            db_session.flush()
            db_session.refresh(db_config)

            # Return the created config with ID
            from domain.entities.billing_models import PaymentGatewayConfig, PaymentProvider
            return PaymentGatewayConfig(
                id=db_config.id,
                provider=PaymentProvider(db_config.provider),
                is_enabled=db_config.is_enabled,
                display_name=db_config.display_name,
                api_key=db_config.api_key,
                api_secret=db_config.api_secret,
                webhook_secret=db_config.webhook_secret,
                mode=db_config.mode,
                config_json=db_config.config_json,
                created_at=db_config.created_at,
                updated_at=db_config.updated_at
            )
        return self._execute_with_retry(_create)

    def update_payment_gateway_config(self, provider: Any, config_data: dict) -> Optional[Any]:
        """Update an existing payment gateway configuration."""
        def _update(db_session: Session):
            from database.billing.models import PaymentGatewayConfigModel
            from domain.entities.billing_models import PaymentGatewayConfig, PaymentProvider

            config = db_session.query(PaymentGatewayConfigModel).filter(
                PaymentGatewayConfigModel.provider == provider.value
            ).first()

            if not config:
                return None

            # Update fields
            for key, value in config_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            db_session.flush()
            db_session.refresh(config)

            return PaymentGatewayConfig(
                id=config.id,
                provider=PaymentProvider(config.provider),
                is_enabled=config.is_enabled,
                display_name=config.display_name,
                api_key=config.api_key,
                api_secret=config.api_secret,
                webhook_secret=config.webhook_secret,
                mode=config.mode,
                config_json=config.config_json,
                created_at=config.created_at,
                updated_at=config.updated_at
            )
        return self._execute_with_retry(_update)
