"""
Admin routes for Payment Gateway configuration management.
Allows enabling/disabling PayPal, Stripe, and Other payment methods.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from domain.entities.billing_models import PaymentProvider, PaymentGatewayConfig
from domain.entities.auth_models import AuthContext
from utils.security.rbac import rbac

router = APIRouter(tags=["Admin Payment Gateways"])
payment_service = None

# --- Pydantic Models ---

class PaymentGatewayConfigRequest(BaseModel):
    """Request model for creating/updating payment gateway config
    
    For PAYPAL/STRIPE: api_key, api_secret, webhook_secret are required
    For BITCOIN/BANK_TRANSFER: config_json contains manual payment details
    """
    provider: PaymentProvider
    is_enabled: bool = True
    display_name: Optional[str] = None
    api_key: Optional[str] = None  # Required for PAYPAL/STRIPE
    api_secret: Optional[str] = None  # Required for PAYPAL/STRIPE
    webhook_secret: Optional[str] = None  # Required for PAYPAL/STRIPE
    mode: str = "sandbox"  # "sandbox" or "live"
    config_json: Optional[str] = None  # Required for BITCOIN/BANK_TRANSFER (manual payment details)

class PaymentGatewayUpdateRequest(BaseModel):
    """Request model for updating payment gateway config (partial)
    
    For PAYPAL/STRIPE: api_key, api_secret, webhook_secret are used
    For BITCOIN/BANK_TRANSFER: config_json contains manual payment details
    """
    is_enabled: Optional[bool] = None
    display_name: Optional[str] = None
    api_key: Optional[str] = None  # For PAYPAL/STRIPE
    api_secret: Optional[str] = None  # For PAYPAL/STRIPE
    webhook_secret: Optional[str] = None  # For PAYPAL/STRIPE
    mode: Optional[str] = None
    config_json: Optional[str] = None  # For BITCOIN/BANK_TRANSFER (manual payment details)

class PaymentGatewayResponse(BaseModel):
    """Response model for payment gateway config"""
    id: int
    provider: str
    is_enabled: bool
    display_name: Optional[str]
    mode: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class PaymentGatewayDetailResponse(BaseModel):
    """Detailed response including sensitive fields (admin only)
    
    For PAYPAL/STRIPE: api_key, api_secret, webhook_secret contain credentials
    For BITCOIN/BANK_TRANSFER: these fields are null, config_json contains manual payment details
    """
    id: int
    provider: str
    is_enabled: bool
    display_name: Optional[str]
    api_key: Optional[str] = Field(None, description="API key for PAYPAL/STRIPE (masked)")
    api_secret: Optional[str] = Field(None, description="API secret for PAYPAL/STRIPE (masked)")
    webhook_secret: Optional[str] = Field(None, description="Webhook secret for PAYPAL/STRIPE (masked)")
    mode: str
    config_json: Optional[str] = Field(None, description="Manual payment details for BITCOIN/BANK_TRANSFER")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class PaymentGatewayStatusResponse(BaseModel):
    """Simple status response for UI selector"""
    provider: str
    display_name: str
    is_enabled: bool
    mode: str

class PaymentGatewayListResponse(BaseModel):
    """Response for listing all payment gateways"""
    gateways: List[PaymentGatewayStatusResponse]

# --- Helper Functions ---

def _mask_sensitive_value(value: Optional[str]) -> Optional[str]:
    """Mask sensitive values for display (show only last 4 chars)"""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]

def _config_to_response(config: PaymentGatewayConfig, mask_sensitive: bool = True) -> Dict[str, Any]:
    """Convert PaymentGatewayConfig to response dict"""
    response = {
        "id": config.id,
        "provider": config.provider.value if isinstance(config.provider, PaymentProvider) else config.provider,
        "is_enabled": config.is_enabled,
        "display_name": config.display_name,
        "mode": config.mode,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }
    
    if not mask_sensitive:
        response["api_key"] = config.api_key
        response["api_secret"] = config.api_secret
        response["webhook_secret"] = config.webhook_secret
        response["config_json"] = config.config_json
    else:
        response["api_key"] = _mask_sensitive_value(config.api_key)
        response["api_secret"] = _mask_sensitive_value(config.api_secret)
        response["webhook_secret"] = _mask_sensitive_value(config.webhook_secret)
        response["config_json"] = config.config_json  # JSON is not sensitive
    
    return response

# --- Admin Routes ---

@router.get("/", response_model=List[PaymentGatewayDetailResponse], dependencies=[Depends(rbac.require("admin:read"))])
async def list_payment_gateways():
    """
    List all payment gateway configurations (Admin only).
    Returns detailed information including API keys (masked).
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        configs = payment_service.data_persistence.get_payment_gateway_configs()
        return [_config_to_response(c, mask_sensitive=False) for c in configs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch payment gateways: {str(e)}")


@router.get("/{provider}", response_model=PaymentGatewayDetailResponse, dependencies=[Depends(rbac.require("admin:read"))])
async def get_payment_gateway(provider: PaymentProvider):
    """
    Get configuration for a specific payment gateway (Admin only).
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        config = payment_service.data_persistence.get_payment_gateway_config(provider)
        if not config:
            raise HTTPException(status_code=404, detail=f"Payment gateway {provider.value} not found")
        return _config_to_response(config, mask_sensitive=False)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch payment gateway: {str(e)}")


@router.post("/", response_model=PaymentGatewayDetailResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def create_payment_gateway(req: PaymentGatewayConfigRequest):
    """
    Create a new payment gateway configuration (Admin only).
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        # Check if config already exists
        existing = payment_service.data_persistence.get_payment_gateway_config(req.provider)
        if existing:
            raise HTTPException(
                status_code=409, 
                detail=f"Payment gateway {req.provider.value} already exists. Use PUT to update."
            )
        
        # Create new config
        config_entity = PaymentGatewayConfig(
            id=0,  # Auto-incremented by DB
            provider=req.provider,
            is_enabled=req.is_enabled,
            display_name=req.display_name or req.provider.value.title(),
            api_key=req.api_key,
            api_secret=req.api_secret,
            webhook_secret=req.webhook_secret,
            mode=req.mode,
            config_json=req.config_json
        )
        
        new_config = payment_service.data_persistence.create_payment_gateway_config(config_entity)
        return _config_to_response(new_config, mask_sensitive=False)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{provider}", response_model=PaymentGatewayDetailResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def update_payment_gateway(provider: PaymentProvider, req: PaymentGatewayUpdateRequest):
    """
    Update an existing payment gateway configuration (Admin only).
    Only updates fields that are provided (partial update).
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    update_data = req.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid update data provided")
    
    try:
        updated_config = payment_service.data_persistence.update_payment_gateway_config(provider, update_data)
        if not updated_config:
            raise HTTPException(status_code=404, detail=f"Payment gateway {provider.value} not found")
        
        return _config_to_response(updated_config, mask_sensitive=False)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{provider}/enable", response_model=PaymentGatewayResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def enable_payment_gateway(provider: PaymentProvider):
    """
    Enable a payment gateway (Admin only).
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        updated_config = payment_service.data_persistence.update_payment_gateway_config(
            provider, {"is_enabled": True}
        )
        if not updated_config:
            raise HTTPException(status_code=404, detail=f"Payment gateway {provider.value} not found")
        
        return _config_to_response(updated_config, mask_sensitive=True)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{provider}/disable", response_model=PaymentGatewayResponse, dependencies=[Depends(rbac.require("admin:write"))])
async def disable_payment_gateway(provider: PaymentProvider):
    """
    Disable a payment gateway (Admin only).
    """
    if not payment_service:
        raise HTTPException(status_code=500, detail="PaymentService not configured")
    
    try:
        updated_config = payment_service.data_persistence.update_payment_gateway_config(
            provider, {"is_enabled": False}
        )
        if not updated_config:
            raise HTTPException(status_code=404, detail=f"Payment gateway {provider.value} not found")
        
        return _config_to_response(updated_config, mask_sensitive=True)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Public Routes (for UI selector) ---

@router.get("/public/status", response_model=PaymentGatewayListResponse)
async def get_public_payment_gateway_status():
    """
    Get public status of payment gateways for UI selector.
    Returns only enabled/disabled status and display names (no sensitive data).
    """
    if not payment_service:
        # Return default status if payment service not configured
        return PaymentGatewayListResponse(gateways=[
            PaymentGatewayStatusResponse(
                provider="PAYPAL",
                display_name="PayPal",
                is_enabled=False,
                mode="sandbox"
            ),
            PaymentGatewayStatusResponse(
                provider="STRIPE",
                display_name="Stripe",
                is_enabled=False,
                mode="sandbox"
            ),
            PaymentGatewayStatusResponse(
                provider="BITCOIN",
                display_name="Bitcoin",
                is_enabled=False,
                mode="sandbox"
            ),
            PaymentGatewayStatusResponse(
                provider="BANK_TRANSFER",
                display_name="Bank Transfer",
                is_enabled=False,
                mode="sandbox"
            ),
        ])
    
    try:
        configs = payment_service.data_persistence.get_payment_gateway_configs()
        
        # If no configs exist, return defaults
        if not configs:
            return PaymentGatewayListResponse(gateways=[
                PaymentGatewayStatusResponse(
                    provider="PAYPAL",
                    display_name="PayPal",
                    is_enabled=False,
                    mode="sandbox"
                ),
                PaymentGatewayStatusResponse(
                    provider="STRIPE",
                    display_name="Stripe",
                    is_enabled=False,
                    mode="sandbox"
                ),
                PaymentGatewayStatusResponse(
                    provider="BITCOIN",
                    display_name="Bitcoin",
                    is_enabled=False,
                    mode="sandbox"
                ),
                PaymentGatewayStatusResponse(
                    provider="BANK_TRANSFER",
                    display_name="Bank Transfer",
                    is_enabled=False,
                    mode="sandbox"
                ),
            ])
        
        gateways = []
        for config in configs:
            provider_str = config.provider.value if isinstance(config.provider, PaymentProvider) else config.provider
            gateways.append(PaymentGatewayStatusResponse(
                provider=provider_str,
                display_name=config.display_name or provider_str.title(),
                is_enabled=config.is_enabled,
                mode=config.mode
            ))
        
        return PaymentGatewayListResponse(gateways=gateways)
        
    except Exception as e:
        # Return default status on error
        return PaymentGatewayListResponse(gateways=[
            PaymentGatewayStatusResponse(
                provider="PAYPAL",
                display_name="PayPal",
                is_enabled=False,
                mode="sandbox"
            ),
            PaymentGatewayStatusResponse(
                provider="STRIPE",
                display_name="Stripe",
                is_enabled=False,
                mode="sandbox"
            ),
            PaymentGatewayStatusResponse(
                provider="BITCOIN",
                display_name="Bitcoin",
                is_enabled=False,
                mode="sandbox"
            ),
            PaymentGatewayStatusResponse(
                provider="BANK_TRANSFER",
                display_name="Bank Transfer",
                is_enabled=False,
                mode="sandbox"
            ),
        ])
