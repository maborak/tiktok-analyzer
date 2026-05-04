"""
Admin routes for Billing Management.
Allows admins to:
1. View and approve pending manual payments (Bitcoin/Bank Transfer)
2. Generate invoices for clients to pay later
3. View all transactions and their status
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from enum import Enum

from domain.entities.billing_models import PaymentProvider, PaymentStatus, PaymentTransaction, Invoice, CreditPackage
from domain.entities.auth_models import AuthContext
from utils.security.rbac import rbac

router = APIRouter(tags=["Admin Billing"])
payment_service = None

# --- Pydantic Models ---

class TransactionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"

class ManualPaymentAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"

class PendingTransactionResponse(BaseModel):
    """Response model for pending manual payment transactions"""
    id: str
    user_id: int
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    provider: str
    amount: float
    currency: str
    status: str
    package_id: Optional[int] = None
    package_name: Optional[str] = None
    credits: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    notes: Optional[str] = None

class ApproveManualPaymentRequest(BaseModel):
    """Request to approve or reject a manual payment"""
    action: ManualPaymentAction
    notes: Optional[str] = Field(None, description="Admin notes about the decision")

class ApproveManualPaymentResponse(BaseModel):
    """Response after approving/rejecting a manual payment"""
    transaction_id: str
    status: str
    credits_added: int
    invoice_id: Optional[str] = None
    message: str

class GenerateInvoiceRequest(BaseModel):
    """Request to generate an invoice for a client"""
    user_id: int
    amount: float
    currency: str = "USD"
    description: Optional[str] = "Custom Invoice"
    package_id: Optional[int] = None
    due_date_days: int = Field(7, description="Number of days until invoice is due")
    notes: Optional[str] = None

class GeneratedInvoiceResponse(BaseModel):
    """Response after generating an invoice"""
    transaction_id: str
    invoice_id: str
    invoice_number: str
    user_id: int
    amount: float
    currency: str
    status: str
    due_date: Optional[str] = None
    payment_url: Optional[str] = None
    message: str

class TransactionListResponse(BaseModel):
    """Response for listing transactions"""
    transactions: List[PendingTransactionResponse]
    total: int
    page: int
    page_size: int

class ExpireTransactionsResponse(BaseModel):
    """Response after expiring old pending transactions"""
    expired_count: int
    message: str


# --- Credit Package Management Models ---

class CreditPackageResponse(BaseModel):
    """Response model for credit packages"""
    id: int
    name: str
    description: Optional[str] = None
    amount: float
    currency: str
    credits: int
    is_active: bool
    created_at: Optional[str] = None

class CreateCreditPackageRequest(BaseModel):
    """Request to create a new credit package"""
    name: str = Field(..., min_length=1, max_length=255, description="Package name")
    description: Optional[str] = Field(None, max_length=500, description="Package description")
    amount: float = Field(..., gt=0, description="Price amount")
    currency: str = Field(default="USD", max_length=10, description="Currency code (e.g., USD, EUR)")
    credits: int = Field(..., gt=0, description="Number of credits included")
    is_active: bool = Field(default=True, description="Whether the package is available for purchase")

class UpdateCreditPackageRequest(BaseModel):
    """Request to update an existing credit package"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    amount: Optional[float] = Field(None, gt=0)
    currency: Optional[str] = Field(None, max_length=10)
    credits: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None

class CreditPackageListResponse(BaseModel):
    """Response for listing credit packages"""
    packages: List[CreditPackageResponse]
    total: int

# --- Admin Routes for Manual Payment Verification ---

@router.get("/pending-payments", response_model=TransactionListResponse, dependencies=[Depends(rbac.require("admin:read"))])
async def list_pending_manual_payments(
    provider: Optional[PaymentProvider] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """
    List all pending manual payment transactions (Bitcoin/Bank Transfer).
    These require admin verification before credits are provisioned.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Get all transactions with PENDING status
        # Filter by manual payment providers if no specific provider requested
        providers = [provider] if provider else [PaymentProvider.BITCOIN, PaymentProvider.BANK_TRANSFER]
        
        result = payment_service.data_persistence.get_payment_transactions(
            status=PaymentStatus.PENDING,
            provider=providers,
            page=page,
            page_size=page_size
        )
        
        transactions = []
        for tx in result.get("items", []):
            transactions.append(PendingTransactionResponse(
                id=tx["id"],
                user_id=tx["user_id"],
                user_email=tx.get("user_email"),
                user_name=tx.get("user_name"),
                provider=tx["provider"],
                amount=tx["amount"],
                currency=tx["currency"],
                status=tx["status"],
                package_id=tx.get("package_id"),
                created_at=tx.get("created_at"),
                updated_at=tx.get("updated_at")
            ))
        
        return TransactionListResponse(
            transactions=transactions,
            total=result.get("total", 0),
            page=result.get("page", page),
            page_size=result.get("page_size", page_size)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch pending payments: {str(e)}")


@router.post("/pending-payments/{transaction_id}/verify", response_model=ApproveManualPaymentResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def verify_manual_payment(
    transaction_id: str,
    req: ApproveManualPaymentRequest
):
    """
    Approve or reject a pending manual payment (Bitcoin/Bank Transfer).
    
    - APPROVE: Marks transaction as completed, provisions credits, creates invoice
    - REJECT: Marks transaction as failed, no credits provisioned
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Get the transaction
        transaction = payment_service.data_persistence.get_payment_transaction_by_id(transaction_id)
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")
        
        # Verify it's a manual payment
        if transaction.provider not in [PaymentProvider.BITCOIN, PaymentProvider.BANK_TRANSFER]:
            raise HTTPException(
                status_code=400, 
                detail=f"Transaction {transaction_id} is not a manual payment (provider: {transaction.provider.value})"
            )
        
        # Verify it's pending
        if transaction.status != PaymentStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Transaction {transaction_id} is not pending (status: {transaction.status.value})"
            )
        
        if req.action == ManualPaymentAction.APPROVE:
            # Approve the payment
            return await _approve_manual_payment(transaction, req.notes)
        else:
            # Reject the payment
            return await _reject_manual_payment(transaction, req.notes)
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify payment: {str(e)}")


async def _approve_manual_payment(transaction: PaymentTransaction, notes: Optional[str]) -> ApproveManualPaymentResponse:
    """Helper to approve a manual payment and provision credits"""
    
    # 1. Update transaction status to COMPLETED
    transaction.status = PaymentStatus.COMPLETED
    payment_service.data_persistence.update_payment_transaction(transaction)
    
    # 2. Calculate credits
    credits = 0
    package = None
    if transaction.package_id:
        package = payment_service.data_persistence.get_credit_package_by_id(transaction.package_id)
        if package:
            credits = package.credits
    else:
        # For custom amounts, credits = amount
        credits = int(transaction.amount)
    
    # 3. Create ledger entry (provision credits)
    payment_service.data_persistence.create_ledger_entry_from_purchase(transaction.id, credits)

    # 3b. Fire CREDIT_PURCHASED event
    from ports.hooks import hook_manager
    from ports.hooks.base_handler import HookEvent, HookEventType
    hook_manager.fire(HookEvent(
        event_type=HookEventType.CREDIT_PURCHASED,
        data={
            "user_id": transaction.user_id,
            "credits": credits,
            "amount": float(transaction.amount),
            "currency": transaction.currency,
            "provider": transaction.provider.value if hasattr(transaction.provider, "value") else str(transaction.provider),
            "package_id": transaction.package_id,
        },
        source="admin_billing",
    ))

    # 4. Check if an invoice already exists for this transaction (e.g. admin generated invoice)
    existing_invoice = payment_service.data_persistence.get_invoice_by_transaction_id(transaction.id)
    provider_tx_id = transaction.provider_transaction_id or f"MANUAL-{transaction.id[:8]}"
    
    if existing_invoice:
        # Just update the existing invoice to 'paid'
        from datetime import datetime
        payment_service.data_persistence.update_invoice_to_paid(
            invoice_id=existing_invoice.id, 
            provider_transaction_id=provider_tx_id, 
            paid_at=datetime.utcnow()
        )
        invoice_id = existing_invoice.id
    else:
        # Create a new invoice
        invoice = payment_service._create_enterprise_invoice(
            transaction=transaction,
            package=package,
            credits=credits,
            provider=transaction.provider,
            provider_transaction_id=provider_tx_id
        )
        invoice_id = invoice.id if invoice else None
    
    # Add admin notes if provided
    if notes:
        # In production, you might want to store admin notes separately
        pass
    
    return ApproveManualPaymentResponse(
        transaction_id=transaction.id,
        status="completed",
        credits_added=credits,
        invoice_id=invoice_id,
        message=f"Payment approved. {credits} credits added to user {transaction.user_id}."
    )


async def _reject_manual_payment(transaction: PaymentTransaction, notes: Optional[str]) -> ApproveManualPaymentResponse:
    """Helper to reject a manual payment"""
    
    # Update transaction status to FAILED
    transaction.status = PaymentStatus.FAILED
    payment_service.data_persistence.update_payment_transaction(transaction)
    
    # Also cancel the associated invoice if it exists (e.g. from generate-invoice)
    invoice = payment_service.data_persistence.get_invoice_by_transaction_id(transaction.id)
    if invoice:
        payment_service.data_persistence.update_invoice_status(invoice.id, "cancelled")
    
    return ApproveManualPaymentResponse(
        transaction_id=transaction.id,
        status="failed",
        credits_added=0,
        invoice_id=None,
        message=f"Payment rejected. No credits added. Reason: {notes or 'No reason provided'}"
    )


# --- Admin Routes for Invoice Generation ---

@router.post("/generate-invoice", response_model=GeneratedInvoiceResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def generate_invoice_for_client(req: GenerateInvoiceRequest):
    """
    Generate an invoice for a client to pay later.
    Creates a pending transaction that the client can pay via any enabled provider.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Validate user exists
        user = payment_service.data_persistence.get_user(req.user_id)
        if not user:
            raise HTTPException(status_code=404, detail=f"User {req.user_id} not found")
        
        # Validate package if provided
        package = None
        if req.package_id:
            package = payment_service.data_persistence.get_credit_package_by_id(req.package_id)
            if not package:
                raise HTTPException(status_code=404, detail=f"Credit package {req.package_id} not found")
        
        # Create a pending transaction for the invoice
        # This is a special "invoice" transaction that doesn't have a provider yet
        # The user will select the provider when paying
        transaction = PaymentTransaction(
            id="",  # Generated by persistence
            user_id=req.user_id,
            package_id=req.package_id,
            provider=PaymentProvider.BANK_TRANSFER,  # Placeholder, user will select when paying
            provider_transaction_id=None,  # Will be set when paid
            status=PaymentStatus.PENDING,
            amount=req.amount,
            currency=req.currency
        )
        
        transaction_id = payment_service.data_persistence.create_payment_transaction(transaction)
        transaction.id = transaction_id
        
        # Calculate due date
        due_date = datetime.utcnow() + timedelta(days=req.due_date_days)
        
        # Create the invoice
        invoice = payment_service.create_pending_invoice(
            transaction=transaction, 
            package=package, 
            description=req.description, 
            due_date=due_date, 
            notes=req.notes
        )
        
        # Generate payment URL (this would be a link to the user's billing page)
        payment_url = f"/billing/invoices/{invoice.id}"
        
        return GeneratedInvoiceResponse(
            transaction_id=transaction.id,
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            user_id=req.user_id,
            amount=req.amount,
            currency=req.currency,
            status="pending",
            due_date=due_date.isoformat(),
            payment_url=payment_url,
            message=f"Invoice {invoice.invoice_number} generated for user {req.user_id}. Due date: {due_date.strftime('%Y-%m-%d')}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate invoice: {str(e)}")


# (Removed _create_pending_invoice as it was moved to PaymentService)


# --- Admin Routes for Transaction Management ---

@router.get("/transactions", response_model=TransactionListResponse, dependencies=[Depends(rbac.require("admin:read"))])
async def list_all_transactions(
    status: Optional[TransactionStatus] = None,
    provider: Optional[PaymentProvider] = None,
    user_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """
    List all transactions with optional filtering.
    Admin can filter by status, provider, or user.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # This would need a new method in data_persistence
        # For now, return empty list
        # In production: implement get_transactions_filtered()
        
        transactions = []
        
        return TransactionListResponse(
            transactions=transactions,
            total=0,
            page=page,
            page_size=page_size
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch transactions: {str(e)}")


@router.post("/cleanup-expired", response_model=ExpireTransactionsResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def cleanup_expired_pending_transactions(
    days: int = Query(7, ge=1, description="Expire pending transactions older than this many days")
):
    """
    Clean up (expire) pending transactions that are older than specified days.
    This handles incomplete payments that were never completed.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # This would need a new method in data_persistence
        # For now, return placeholder
        # In production: implement expire_old_pending_transactions(cutoff_date)
        
        expired_count = 0
        
        return ExpireTransactionsResponse(
            expired_count=expired_count,
            message=f"Expired {expired_count} pending transactions older than {days} days."
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup expired transactions: {str(e)}")


@router.get("/stats", response_model=Dict[str, Any], dependencies=[Depends(rbac.require("admin:read"))])
async def get_billing_stats():
    """
    Get billing statistics for admin dashboard.
    Includes counts by status, provider breakdown, revenue totals, etc.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # This would need new methods in data_persistence
        # For now, return placeholder stats
        
        return {
            "total_transactions": 0,
            "pending_verification": 0,  # Manual payments awaiting admin approval
            "completed_today": 0,
            "failed_today": 0,
            "revenue_today": 0.0,
            "revenue_this_month": 0.0,
            "provider_breakdown": {},
            "pending_invoices": 0  # Admin-generated invoices awaiting payment
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch billing stats: {str(e)}")


# --- Admin Routes for Credit Package Management ---

@router.get("/packages", response_model=CreditPackageListResponse, dependencies=[Depends(rbac.require("admin:read"))])
async def list_credit_packages(
    include_inactive: bool = Query(False, description="Include inactive packages"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100)
):
    """
    List all credit packages.
    By default, only shows active packages. Set include_inactive=true to see all.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Get packages based on filter
        if include_inactive:
            all_packages = payment_service.data_persistence.get_all_credit_packages()
        else:
            all_packages = payment_service.data_persistence.get_active_credit_packages()
        
        # Calculate pagination
        total = len(all_packages)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_packages = all_packages[start_idx:end_idx]
        
        # Convert to response model
        packages_response = []
        for p in paginated_packages:
            packages_response.append(CreditPackageResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                amount=p.amount,
                currency=p.currency,
                credits=p.credits,
                is_active=p.is_active,
                created_at=p.created_at.isoformat() if hasattr(p, 'created_at') and p.created_at else None
            ))
        
        return CreditPackageListResponse(
            packages=packages_response,
            total=total
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch credit packages: {str(e)}")


@router.post("/packages", response_model=CreditPackageResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def create_credit_package(req: CreateCreditPackageRequest):
    """
    Create a new credit package.
    Packages define credit bundles that users can purchase.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Create the package domain object
        new_package = CreditPackage(
            id=0,  # Will be assigned by database
            name=req.name,
            description=req.description,
            amount=req.amount,
            currency=req.currency,
            credits=req.credits,
            is_active=req.is_active
        )
        
        # Persist the package
        created_package = payment_service.data_persistence.create_credit_package(new_package)
        
        return CreditPackageResponse(
            id=created_package.id,
            name=created_package.name,
            description=created_package.description,
            amount=created_package.amount,
            currency=created_package.currency,
            credits=created_package.credits,
            is_active=created_package.is_active,
            created_at=created_package.created_at.isoformat() if hasattr(created_package, 'created_at') and created_package.created_at else None
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create credit package: {str(e)}")


@router.put("/packages/{package_id}", response_model=CreditPackageResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def update_credit_package(package_id: int, req: UpdateCreditPackageRequest):
    """
    Update an existing credit package.
    Only provided fields will be updated.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Verify package exists
        existing = payment_service.data_persistence.get_credit_package_by_id(package_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Credit package {package_id} not found")
        
        # Build update data (only include provided fields)
        update_data = {}
        if req.name is not None:
            update_data["name"] = req.name
        if req.description is not None:
            update_data["description"] = req.description
        if req.amount is not None:
            update_data["amount"] = req.amount
        if req.currency is not None:
            update_data["currency"] = req.currency
        if req.credits is not None:
            update_data["credits"] = req.credits
        if req.is_active is not None:
            update_data["is_active"] = req.is_active
        
        # Update the package
        updated_package = payment_service.data_persistence.update_credit_package(package_id, update_data)
        
        if not updated_package:
            raise HTTPException(status_code=500, detail="Failed to update credit package")
        
        return CreditPackageResponse(
            id=updated_package.id,
            name=updated_package.name,
            description=updated_package.description,
            amount=updated_package.amount,
            currency=updated_package.currency,
            credits=updated_package.credits,
            is_active=updated_package.is_active,
            created_at=updated_package.created_at.isoformat() if hasattr(updated_package, 'created_at') and updated_package.created_at else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update credit package: {str(e)}")


@router.delete("/packages/{package_id}", dependencies=[Depends(rbac.require("admin:write"))])
async def delete_credit_package(package_id: int, hard_delete: bool = Query(False, description="Permanently delete instead of deactivating")):
    """
    Delete or deactivate a credit package.
    By default, performs a soft delete (sets is_active=false).
    Set hard_delete=true to permanently remove from database.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Verify package exists
        existing = payment_service.data_persistence.get_credit_package_by_id(package_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Credit package {package_id} not found")
        
        if hard_delete:
            # Permanent deletion
            success = payment_service.data_persistence.delete_credit_package(package_id)
            if not success:
                raise HTTPException(status_code=500, detail="Failed to delete credit package")
            return {"message": f"Credit package {package_id} permanently deleted"}
        else:
            # Soft delete - just deactivate
            update_data = {"is_active": False}
            updated = payment_service.data_persistence.update_credit_package(package_id, update_data)
            if not updated:
                raise HTTPException(status_code=500, detail="Failed to deactivate credit package")
            return {"message": f"Credit package {package_id} deactivated. Set is_active=false"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete credit package: {str(e)}")
