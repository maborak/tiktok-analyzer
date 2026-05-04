from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from typing import List, Optional, Any
from pydantic import BaseModel, root_validator

from config import CONFIG
from domain.entities.auth_models import User, AuthContext
from domain.entities.billing_models import PaymentProvider, CreditPackage, Invoice
from routes.auth import get_current_user_swagger_compatible as get_current_user

router = APIRouter(tags=["Billing"])
payment_service = None

# --- Request/Response Models ---

class CreateOrderRequest(BaseModel):
    package_id: Optional[int] = None
    amount: float
    currency: str = "USD"
    provider: PaymentProvider
    
    @root_validator(pre=True)
    def check_amount_or_package(cls, values):
        if not values.get('package_id') and not values.get('amount'):
            raise ValueError("Must provide either an amount or a package_id")
        return values

class CreateOrderResponse(BaseModel):
    transaction_id: str
    provider_data: dict
    # Original order details
    package_id: Optional[int] = None
    amount: float = 0.0
    currency: str = "USD"
    # Provider configuration - returned from backend so UI doesn't need to hardcode
    paypal_client_id: Optional[str] = None
    stripe_publishable_key: Optional[str] = None
    mode: str = "sandbox"  # "sandbox" or "live"

class CaptureOrderRequest(BaseModel):
    order_id: str
    provider: PaymentProvider

class CaptureOrderResponse(BaseModel):
    transaction_id: str
    status: str
    credits_added: int
    invoice_id: Optional[str] = None
    message: str

class ManualPaymentRequest(BaseModel):
    package_id: Optional[int] = None
    amount: float
    currency: str = "USD"
    provider: PaymentProvider
    notes: Optional[str] = None  # User can add notes/proof of payment

class ManualPaymentResponse(BaseModel):
    transaction_id: str
    status: str
    provider: str
    amount: float
    currency: str
    instructions: str
    payment_details: dict
    message: str

# --- Routes ---

@router.get("/packages", response_model=List[dict])
async def get_packages(current_user: AuthContext = Depends(get_current_user)):
    """Get active credit packages available for purchase"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    packages = payment_service.get_active_credit_packages()
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "amount": p.amount,
            "currency": p.currency,
            "credits": p.credits
        } for p in packages
    ]

@router.post("/orders", response_model=CreateOrderResponse)
async def create_order(req: CreateOrderRequest, current_user: AuthContext = Depends(get_current_user)):
    """Initialize a payment order with a specific provider (PayPal/Stripe)"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    import os
    
    try:
        transaction_id, provider_data = payment_service.initialize_payment(
            user_id=current_user.user.id,
            provider=req.provider,
            amount=req.amount,
            currency=req.currency,
            package_id=req.package_id
        )
        
        # Get provider configuration from database first, then fall back to environment
        config = payment_service.data_persistence.get_payment_gateway_config(req.provider)
        
        # Determine mode from config or environment
        if config and config.mode:
            mode = config.mode
        else:
            # Fallback to environment variables
            if req.provider == PaymentProvider.PAYPAL:
                paypal_mode = os.getenv("PHOVEU_BACKEND_PAYPAL_MODE", "sandbox").lower()
                mode = "live" if paypal_mode == "live" else "sandbox"
            elif req.provider == PaymentProvider.STRIPE:
                stripe_mode = os.getenv("PHOVEU_BACKEND_STRIPE_MODE", "sandbox").lower()
                mode = "live" if stripe_mode == "live" else "sandbox"
            else:
                mode = "sandbox"
        
        response = CreateOrderResponse(
            transaction_id=transaction_id,
            provider_data=provider_data,
            package_id=req.package_id,
            amount=req.amount,
            currency=req.currency,
            mode=mode
        )
        
        # Include only the relevant provider's public key from database or environment
        if req.provider == PaymentProvider.PAYPAL:
            if config and config.api_key:
                response.paypal_client_id = config.api_key
            else:
                response.paypal_client_id = os.getenv("PHOVEU_BACKEND_PAYPAL_CLIENT_ID")
        elif req.provider == PaymentProvider.STRIPE:
            if config and config.api_key:
                response.stripe_publishable_key = config.api_key
            else:
                response.stripe_publishable_key = os.getenv("PHOVEU_BACKEND_STRIPE_PUBLISHABLE_KEY") or os.getenv("PHOVEU_BACKEND_STRIPE_SECRET_KEY", "").replace("sk_", "pk_")
        
        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/orders/{order_id}/resume", response_model=CreateOrderResponse)
async def resume_order(order_id: str, current_user: AuthContext = Depends(get_current_user)):
    """Resumes an existing AWAITING_PAYMENT transaction"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")

    import os
    
    try:
        # We need the transaction from DB to read the provider to get the config
        transaction = payment_service.data_persistence.get_payment_transaction_by_id(order_id)
        if not transaction or transaction.user_id != current_user.user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")

        provider_data = payment_service.resume_payment_order(
            user_id=current_user.user.id,
            transaction_id=order_id
        )

        config = payment_service.data_persistence.get_payment_gateway_config(transaction.provider)
        
        # Determine mode
        if config and config.mode:
            mode = config.mode
        else:
            if transaction.provider == PaymentProvider.PAYPAL:
                paypal_mode = os.getenv("PHOVEU_BACKEND_PAYPAL_MODE", "sandbox").lower()
                mode = "live" if paypal_mode == "live" else "sandbox"
            elif transaction.provider == PaymentProvider.STRIPE:
                stripe_mode = os.getenv("PHOVEU_BACKEND_STRIPE_MODE", "sandbox").lower()
                mode = "live" if stripe_mode == "live" else "sandbox"
            else:
                mode = "sandbox"

        response = CreateOrderResponse(
            transaction_id=order_id,
            provider_data=provider_data,
            package_id=transaction.package_id,
            amount=transaction.amount,
            currency=transaction.currency,
            mode=mode
        )
        
        if transaction.provider == PaymentProvider.PAYPAL:
            if config and config.api_key:
                response.paypal_client_id = config.api_key
            else:
                response.paypal_client_id = os.getenv("PHOVEU_BACKEND_PAYPAL_CLIENT_ID")
        elif transaction.provider == PaymentProvider.STRIPE:
            if config and config.api_key:
                response.stripe_publishable_key = config.api_key
            else:
                response.stripe_publishable_key = os.getenv("PHOVEU_BACKEND_STRIPE_PUBLISHABLE_KEY") or os.getenv("PHOVEU_BACKEND_STRIPE_SECRET_KEY", "").replace("sk_", "pk_")
                
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/capture", response_model=CaptureOrderResponse)
async def capture_order(req: CaptureOrderRequest, current_user: AuthContext = Depends(get_current_user)):
    """
    Synchronously capture a payment after user approval (PayPal/Stripe).
    This completes the payment immediately and provisions credits.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    try:
        transaction = payment_service.capture_payment(
            user_id=current_user.user.id,
            provider_order_id=req.order_id,
            provider=req.provider
        )
        
        # Calculate credits added from the transaction
        credits_added = 0
        if transaction.package_id:
            package = payment_service.data_persistence.get_credit_package_by_id(transaction.package_id)
            if package:
                credits_added = package.credits
        else:
            # For custom amounts, credits = amount
            credits_added = int(transaction.amount)
        
        # Get the invoice for this transaction
        invoice = payment_service.data_persistence.get_invoice_by_transaction_id(transaction.id)
        
        return CaptureOrderResponse(
            transaction_id=transaction.id,
            status=transaction.status.value if hasattr(transaction.status, 'value') else str(transaction.status),
            credits_added=credits_added,
            invoice_id=invoice.id if invoice else None,
            message="Payment captured successfully. Credits have been added to your account."
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to capture payment: {str(e)}")

@router.get("/orders", response_model=dict)
async def get_user_orders(
    page: int = 1,
    page_size: int = 20,
    current_user: AuthContext = Depends(get_current_user)
):
    """Get all payment transactions (orders) for the logged in user"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    return payment_service.get_user_transactions(current_user.user.id, page, page_size)

@router.get("/history", response_model=dict)
async def get_user_credit_history_route(
    page: int = 1,
    page_size: int = 20,
    current_user: AuthContext = Depends(get_current_user)
):
    """Get credit consumption and grant history for the logged in user"""
    if not payment_service or not payment_service.data_persistence:
        raise HTTPException(status_code=500, detail="Not configured")
        
    history_dict = payment_service.data_persistence.get_user_credit_history(
        current_user.user.id, page, page_size
    )
    
    # We must serialize to dict since we return dict instead of Pydantic model response
    items = []
    for entry in history_dict["items"]:
        items.append({
            "id": entry.id,
            "amount": entry.amount,
            "source": entry.source.value if hasattr(entry.source, 'value') else str(entry.source),
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
            "transaction_id": entry.transaction_id,
            "note": getattr(entry, 'note', None),
            "product_id": getattr(entry, 'product_id', None),
            "country_code": getattr(entry, 'country_code', None),
            "track_exists": getattr(entry, 'track_exists', None),
            "product_title": getattr(entry, 'product_title', None),
            "product_image": getattr(entry, 'product_image', None),
        })
        
    return {
        "success": True,
        "data": {
            "items": items,
            "pagination": history_dict["pagination"]
        }
    }

@router.get("/invoices", response_model=dict)
async def get_user_invoices(
    page: int = 1,
    page_size: int = 20,
    current_user: AuthContext = Depends(get_current_user)
):
    """Get standard invoice list for the logged in user"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    return payment_service.get_user_invoices(current_user.user.id, page, page_size)

@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, current_user: AuthContext = Depends(get_current_user)):
    """Get a specific invoice (JSON) with enterprise-grade details"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    invoice = payment_service.get_invoice_by_id(invoice_id)
    if not invoice or invoice.user_id != current_user.user.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "date": invoice.created_at.isoformat(),
        "total_amount": invoice.total_amount,
        "currency": invoice.currency,
        "billing_email": invoice.billing_email,
        "billing_name": invoice.billing_name,
        # Enterprise-grade fields
        "provider": invoice.provider.value if hasattr(invoice.provider, 'value') else str(invoice.provider),
        "provider_transaction_id": invoice.provider_transaction_id,
        "subtotal_amount": invoice.subtotal_amount,
        "tax_amount": invoice.tax_amount,
        "billing_address": {
            "line1": invoice.billing_address_line1,
            "line2": invoice.billing_address_line2,
            "city": invoice.billing_city,
            "state": invoice.billing_state,
            "postal_code": invoice.billing_postal_code,
            "country": invoice.billing_country
        },
        "line_items": invoice.line_items,
        "tax_rate": invoice.tax_rate,
        "tax_id": invoice.tax_id,
        "status": invoice.status,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "notes": invoice.notes
    }

@router.get("/payment-methods", response_model=dict)
async def get_payment_methods(current_user: AuthContext = Depends(get_current_user)):
    """
    Get available payment methods for the checkout page.
    Returns enabled gateways with their public configuration.
    For PAYPAL/STRIPE: returns API keys for SDK initialization.
    For BITCOIN/BANK_TRANSFER: returns manual payment instructions.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    import os
    import json
    from domain.entities.billing_models import PaymentProvider
    
    try:
        # Get gateway configs from database
        configs = payment_service.data_persistence.get_payment_gateway_configs()
        
        # Build response with only enabled gateways
        payment_methods = []
        for config in configs:
            if not config.is_enabled:
                continue
            
            provider_str = config.provider.value if isinstance(config.provider, PaymentProvider) else config.provider
            
            method = {
                "provider": provider_str,
                "name": config.display_name or provider_str.title().replace('_', ' '),
                "is_enabled": config.is_enabled,
                "mode": config.mode
            }
            
            # Add provider-specific configuration
            if config.provider == PaymentProvider.PAYPAL:
                method["client_id"] = config.api_key or os.getenv("PHOVEU_BACKEND_PAYPAL_CLIENT_ID")
            elif config.provider == PaymentProvider.STRIPE:
                method["publishable_key"] = config.api_key or os.getenv("PHOVEU_BACKEND_STRIPE_PUBLISHABLE_KEY")
            elif config.provider == PaymentProvider.BITCOIN:
                # Bitcoin manual payment
                method["type"] = "manual"
                method["description"] = "Pay with Bitcoin (BTC)"
                method["instructions"] = "Send BTC to the wallet address and contact support with your transaction ID"
                
                if config.config_json:
                    try:
                        btc_config = json.loads(config.config_json)
                        method["description"] = btc_config.get("description", method["description"])
                        method["instructions"] = btc_config.get("instructions", method["instructions"])
                        method["wallet_address"] = btc_config.get("wallet_address")
                        method["contact_info"] = btc_config.get("contact_info", CONFIG["APP_SUPPORT_EMAIL"])
                        method["qr_code_url"] = btc_config.get("qr_code_url")
                    except json.JSONDecodeError:
                        pass
            
            elif config.provider == PaymentProvider.BANK_TRANSFER:
                # Bank transfer manual payment
                method["type"] = "manual"
                method["description"] = "Pay via bank transfer"
                method["instructions"] = "Transfer the amount to our bank account and upload the receipt"
                
                if config.config_json:
                    try:
                        bank_config = json.loads(config.config_json)
                        method["description"] = bank_config.get("description", method["description"])
                        method["instructions"] = bank_config.get("instructions", method["instructions"])
                        method["bank_details"] = bank_config.get("bank_details")
                        method["account_name"] = bank_config.get("account_name")
                        method["account_number"] = bank_config.get("account_number")
                        method["routing_number"] = bank_config.get("routing_number")
                        method["swift_code"] = bank_config.get("swift_code")
                        method["contact_info"] = bank_config.get("contact_info", CONFIG["APP_SUPPORT_EMAIL"])
                    except json.JSONDecodeError:
                        pass
            
            payment_methods.append(method)
        
        # Determine global mode from first enabled gateway or default to sandbox
        global_mode = "sandbox"
        if configs:
            enabled_configs = [c for c in configs if c.is_enabled]
            if enabled_configs:
                global_mode = enabled_configs[0].mode
        
        return {
            "payment_methods": payment_methods,
            "mode": global_mode
        }
        
    except Exception as e:
        # Fallback to environment variables if database query fails
        paypal_client_id = os.getenv("PHOVEU_BACKEND_PAYPAL_CLIENT_ID")
        stripe_key = os.getenv("PHOVEU_BACKEND_STRIPE_PUBLISHABLE_KEY") or os.getenv("PHOVEU_BACKEND_STRIPE_SECRET_KEY", "").replace("sk_", "pk_")
        
        methods = []
        if paypal_client_id:
            methods.append({
                "provider": "PAYPAL",
                "name": "PayPal",
                "is_enabled": True,
                "mode": "sandbox",
                "client_id": paypal_client_id
            })
        if stripe_key:
            methods.append({
                "provider": "STRIPE",
                "name": "Stripe",
                "is_enabled": True,
                "mode": "sandbox",
                "publishable_key": stripe_key
            })
        
        return {
            "payment_methods": methods,
            "mode": "sandbox"
        }


@router.post("/manual-payment", response_model=ManualPaymentResponse)
async def create_manual_payment(req: ManualPaymentRequest, current_user: AuthContext = Depends(get_current_user)):
    """
    Create a pending payment for manual methods (Bitcoin/Bank Transfer).
    This creates a PENDING transaction that requires admin verification.
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    import json
    from domain.entities.billing_models import PaymentStatus
    
    # Validate provider is manual payment type
    if req.provider not in [PaymentProvider.BITCOIN, PaymentProvider.BANK_TRANSFER]:
        raise HTTPException(
            status_code=400, 
            detail=f"Provider {req.provider.value} is not a manual payment method. Use /orders for PayPal/Stripe."
        )
    
    try:
        # Get gateway config for instructions
        config = payment_service.data_persistence.get_payment_gateway_config(req.provider)
        if not config or not config.is_enabled:
            raise HTTPException(
                status_code=400,
                detail=f"Payment method {req.provider.value} is not available"
            )
        
        # Create a pending transaction
        transaction_id, _ = payment_service.initialize_payment(
            user_id=current_user.user.id,
            provider=req.provider,
            amount=req.amount,
            currency=req.currency,
            package_id=req.package_id
        )
        
        # Get the transaction to update status to pending
        transaction = payment_service.data_persistence.get_payment_transaction_by_id(transaction_id)
        if transaction:
            # Update status to pending (manual verification required)
            payment_service.data_persistence.update_payment_transaction_status(
                transaction_id, PaymentStatus.PENDING
            )
        
        # Build payment details from config
        payment_details = {}
        instructions = ""
        
        if req.provider == PaymentProvider.BITCOIN:
            instructions = "Send BTC to the wallet address and contact support with your transaction ID"
            if config.config_json:
                try:
                    btc_config = json.loads(config.config_json)
                    payment_details = {
                        "wallet_address": btc_config.get("wallet_address"),
                        "qr_code_url": btc_config.get("qr_code_url"),
                        "description": btc_config.get("description", "Pay with Bitcoin (BTC)"),
                        "contact_info": btc_config.get("contact_info", CONFIG["APP_SUPPORT_EMAIL"])
                    }
                    instructions = btc_config.get("instructions", instructions)
                except json.JSONDecodeError:
                    pass
        
        elif req.provider == PaymentProvider.BANK_TRANSFER:
            instructions = "Transfer the amount to our bank account and upload the receipt"
            if config.config_json:
                try:
                    bank_config = json.loads(config.config_json)
                    payment_details = {
                        "bank_details": bank_config.get("bank_details"),
                        "account_name": bank_config.get("account_name"),
                        "account_number": bank_config.get("account_number"),
                        "routing_number": bank_config.get("routing_number"),
                        "swift_code": bank_config.get("swift_code"),
                        "description": bank_config.get("description", "Pay via bank transfer"),
                        "contact_info": bank_config.get("contact_info", CONFIG["APP_SUPPORT_EMAIL"])
                    }
                    instructions = bank_config.get("instructions", instructions)
                except json.JSONDecodeError:
                    pass
        
        return ManualPaymentResponse(
            transaction_id=transaction_id,
            status="pending",
            provider=req.provider.value,
            amount=req.amount,
            currency=req.currency,
            instructions=instructions,
            payment_details=payment_details,
            message=f"Please complete the {req.provider.value.replace('_', ' ').title()} payment. Your transaction is pending verification."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create manual payment: {str(e)}")


@router.get("/invoices/{invoice_id}/html", response_class=HTMLResponse)
async def get_invoice_html(invoice_id: str, current_user: AuthContext = Depends(get_current_user)):
    """Renders an enterprise-grade HTML invoice template suitable for printing/PDF generation"""
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
        
    invoice = payment_service.get_invoice_by_id(invoice_id)
    if not invoice or invoice.user_id != current_user.user.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
        
    user = payment_service.data_persistence.get_user(current_user.user.id)
    
    # Parse line_items JSON if available
    import json
    line_items_html = ""
    try:
        if invoice.line_items:
            items = json.loads(invoice.line_items) if isinstance(invoice.line_items, str) else invoice.line_items
            if isinstance(items, list):
                for item in items:
                    name = item.get('name', 'Credit Purchase')
                    quantity = item.get('quantity', 1)
                    unit_price = item.get('unit_price', invoice.subtotal_amount)
                    total = item.get('total', unit_price * quantity)
                    line_items_html += f"""
                    <tr>
                        <td>{name} x {quantity}</td>
                        <td style="text-align: right;">${unit_price:.2f}</td>
                        <td style="text-align: right;">${total:.2f}</td>
                    </tr>
                    """
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Fallback to simple line item if parsing failed
    subtotal = invoice.subtotal_amount or invoice.total_amount or 0
    if not line_items_html:
        line_items_html = f"""
        <tr>
            <td>Credit Purchase</td>
            <td style="text-align: right;">1</td>
            <td style="text-align: right;">${subtotal:.2f}</td>
        </tr>
        """
    
    # Build billing address HTML
    billing_address_html = ""
    if invoice.billing_address_line1:
        billing_address_html += f"<p>{invoice.billing_address_line1}</p>"
    if invoice.billing_address_line2:
        billing_address_html += f"<p>{invoice.billing_address_line2}</p>"
    if invoice.billing_city or invoice.billing_state or invoice.billing_postal_code:
        city_state = ", ".join(filter(None, [invoice.billing_city, invoice.billing_state]))
        if invoice.billing_postal_code:
            city_state += f" {invoice.billing_postal_code}"
        billing_address_html += f"<p>{city_state}</p>"
    if invoice.billing_country:
        billing_address_html += f"<p>{invoice.billing_country}</p>"
    
    # Payment method display
    payment_method = "Credit Card"
    if invoice.provider:
        provider_str = invoice.provider.value if hasattr(invoice.provider, 'value') else str(invoice.provider)
        if provider_str.upper() == "PAYPAL":
            payment_method = "PayPal"
        elif provider_str.upper() == "STRIPE":
            payment_method = "Credit Card (Stripe)"
        elif provider_str.upper() == "BITCOIN":
            payment_method = "Bitcoin"
        elif provider_str.upper() == "BANK_TRANSFER":
            payment_method = "Bank Transfer"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Invoice {invoice.invoice_number}</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 40px; color: #333; max-width: 800px; margin: 0 auto; }}
            .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #eee; padding-bottom: 20px; }}
            .invoice-meta {{ text-align: right; }}
            .invoice-meta p {{ margin: 4px 0; color: #666; }}
            .details {{ margin-top: 40px; display: flex; justify-content: space-between; }}
            .billing-info {{ flex: 1; }}
            .company-info {{ text-align: right; }}
            .items {{ width: 100%; border-collapse: collapse; margin-top: 40px; }}
            .items th {{ background: #f8f9fa; font-weight: 600; }}
            .items th, .items td {{ border-bottom: 1px solid #eee; padding: 12px; text-align: left; }}
            .items td:last-child, .items th:last-child {{ text-align: right; }}
            .summary {{ margin-top: 30px; border-top: 2px solid #eee; padding-top: 20px; }}
            .summary-row {{ display: flex; justify-content: space-between; padding: 8px 0; }}
            .summary-row.total {{ font-size: 20px; font-weight: bold; border-top: 2px solid #333; margin-top: 10px; padding-top: 15px; }}
            .payment-info {{ margin-top: 40px; padding: 20px; background: #f8f9fa; border-radius: 8px; }}
            .footer {{ margin-top: 60px; text-align: center; color: #666; font-size: 12px; }}
            .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 4px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
            .status-paid {{ background: #d4edda; color: #155724; }}
            .status-pending {{ background: #fff3cd; color: #856404; }}
            .status-failed {{ background: #f8d7da; color: #721c24; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <h1>{CONFIG["APP_NAME"]}</h1>
                <p>Receipt / Tax Invoice</p>
            </div>
            <div class="invoice-meta">
                <h2>Invoice {invoice.invoice_number}</h2>
                <p><span class="status-badge status-{invoice.status or 'paid'}">{invoice.status or 'paid'}</span></p>
                <p>Date: {invoice.created_at.strftime('%B %d, %Y')}</p>
                {f"<p>Due Date: {invoice.due_date.strftime('%B %d, %Y')}</p>" if invoice.due_date else ""}
            </div>
        </div>
        
        <div class="details">
            <div class="billing-info">
                <h3>Billed To:</h3>
                <p><strong>{invoice.billing_name or (user.full_name if user else None) or (user.username if user else 'Customer')}</strong></p>
                <p>{invoice.billing_email}</p>
                {billing_address_html}
            </div>
            <div class="company-info">
                <h3>From:</h3>
                <p><strong>{CONFIG["APP_LEGAL_ENTITY"]}</strong></p>
                <p>{CONFIG["APP_SUPPORT_EMAIL"]}</p>
                {f"<p>Tax ID: {invoice.tax_id}</p>" if invoice.tax_id else ""}
            </div>
        </div>
        
        <table class="items">
            <thead>
                <tr>
                    <th>Description</th>
                    <th style="text-align: right;">Qty</th>
                    <th style="text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {line_items_html}
            </tbody>
        </table>
        
        <div class="summary">
            <div class="summary-row">
                <span>Subtotal:</span>
                <span>${(invoice.subtotal_amount or invoice.total_amount or 0):.2f} {invoice.currency or 'USD'}</span>
            </div>
            {f'<div class="summary-row"><span>Tax ({invoice.tax_rate or 0}%):</span><span>${(invoice.tax_amount or 0):.2f} {invoice.currency or 'USD'}</span></div>' if invoice.tax_amount and invoice.tax_amount > 0 else ""}
            <div class="summary-row total">
                <span>Total Paid:</span>
                <span>${(invoice.total_amount or 0):.2f} {invoice.currency or 'USD'}</span>
            </div>
        </div>
        
        <div class="payment-info">
            <p><strong>Payment Method:</strong> {payment_method}</p>
            <p><strong>Transaction ID:</strong> {invoice.provider_transaction_id or 'N/A'}</p>
            {f"<p><strong>Paid At:</strong> {invoice.paid_at.strftime('%B %d, %Y at %H:%M')}</p>" if invoice.paid_at else ""}
            {f"<p><strong>Notes:</strong> {invoice.notes}</p>" if invoice.notes else ""}
        </div>
        
        <div class="footer">
            <p>Thank you for your business!</p>
            <p>If you have any questions, please contact {CONFIG["APP_SUPPORT_EMAIL"]}</p>
        </div>
    </body>
    </html>
    """
    return html
