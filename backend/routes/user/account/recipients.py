"""
Recipient Management Routes
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional, Any
import logging
import secrets
from datetime import datetime, timedelta, timezone

from domain.entities.auth_models import AuthContext
from utils.database.force_write import require_read_db, require_write_db
from utils.security.rbac import rbac
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from domain.entities.recipient_models import RecipientType, Recipient
from domain.api_models import ApiResponse
from ports.hooks import hook_manager, HookEvent, HookEventType

data_persistence_adapter = None

logger = logging.getLogger(__name__)
router = APIRouter()

class RecipientCreate(BaseModel):
    type: RecipientType
    value: str = Field(..., min_length=1, max_length=320)
    name: Optional[str] = Field(None, max_length=100)

    @model_validator(mode='after')
    def validate_email_value(self):
        if self.type == RecipientType.EMAIL:
            # Basic email format check
            import re
            if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', self.value):
                raise ValueError('Invalid email address format for EMAIL recipient')
        return self

class RecipientResponse(BaseModel):
    id: int
    type: RecipientType
    value: str
    is_verified: bool
    is_enabled: bool
    name: Optional[str]
    subject_tag: Optional[str] = None
    alert_count: int = 0

class RecipientVerifyRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=500)

class RecipientUpdateRequest(BaseModel):
    type: Optional[RecipientType] = None
    value: Optional[str] = Field(None, min_length=1, max_length=320)
    name: Optional[str] = Field(None, max_length=100)
    is_enabled: Optional[bool] = None
    subject_tag: Optional[str] = Field(None, max_length=100)

@router.post("/recipients",
             tags=["Recipients"],
             summary="Add Recipient",
             response_model=ApiResponse)
@require_write_db
async def add_recipient(
    data: RecipientCreate,
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    try:
        from config import CONFIG
        
        # Check if user is verified
        if not current_user.user.is_verified:
            raise HTTPException(
                status_code=403,
                detail="Only confirmed users can add recipients"
            )

        # Check total recipients limit
        page_size = 10
        result = data_persistence_adapter.get_user_recipients(
            current_user.user.id,
            page=1,
            page_size=page_size
        )
        # Fetch actual total from pagination metadata instead of len(items)
        total_recipients = result.get("pagination", {}).get("total", len(result.get("items", [])))
        
        if total_recipients >= CONFIG["LIMIT_MAX_RECIPIENTS_CONFIRMED"]:
            raise HTTPException(
                status_code=402,
                detail=f"Maximum limit of {CONFIG['LIMIT_MAX_RECIPIENTS_CONFIRMED']} recipients reached"
            )

        # Check if already exists
        existing_result = data_persistence_adapter.get_user_recipients(
            current_user.user.id,
            search=data.value,
            recipient_type=data.type.value
        )
        for r in existing_result["items"]:
            if r.type == data.type and r.value == data.value:
                return ApiResponse(
                    success=True,
                    message="Recipient already exists",
                    data=RecipientResponse(
                        id=r.id,
                        type=r.type,
                        value=r.value,
                        is_verified=r.is_verified,
                        is_enabled=r.is_enabled,
                        name=r.name,
                        subject_tag=r.subject_tag,
                        alert_count=r.alert_count
                    ).model_dump()
                )

        recipient = Recipient(
            id=0,
            user_id=current_user.user.id,
            type=data.type,
            value=data.value,
            is_verified=False,
            name=data.name
        )
        
        # Auto-verify if it's the user's own verified email
        if data.type == RecipientType.EMAIL and data.value.lower() == current_user.user.email.lower() and current_user.user.is_verified:
            recipient.is_verified = True
            
        recipient.id = data_persistence_adapter.create_recipient(recipient)
        
        if not recipient.is_verified and data.type == RecipientType.EMAIL:
            # Generate verification token
            token = secrets.token_hex(16)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            data_persistence_adapter.create_recipient_verification(recipient.id, token, expires_at)
            
            # Send verification email via hook
            try:
                hook_event = HookEvent(
                    event_type=HookEventType.USER_VERIFICATION_REQUESTED,
                    data={
                        "email": data.value,
                        "verification_token": token,
                        "expires_in_days": 1,
                        # Add user info if available from current_user
                        "username": current_user.user.username,
                        "first_name": current_user.user.first_name,
                        "last_name": current_user.user.last_name
                    },
                    source="recipients_route"
                )
                hook_manager.fire(hook_event)
                logger.info(f"Verification email hook fired for {data.value}")
            except Exception as e:
                logger.error(f"Failed to fire verification hook: {e}")
        
        return ApiResponse(
            success=True,
            message="Recipient added successfully",
            data=RecipientResponse(
                id=recipient.id,
                type=recipient.type,
                value=recipient.value,
                is_verified=recipient.is_verified,
                is_enabled=recipient.is_enabled,
                name=recipient.name,
                subject_tag=recipient.subject_tag
            ).model_dump()
        )
        return ApiResponse(
            success=True,
            message="Recipient added successfully",
            data=RecipientResponse(
                id=recipient.id,
                type=recipient.type,
                value=recipient.value,
                is_verified=recipient.is_verified,
                is_enabled=recipient.is_enabled,
                name=recipient.name,
                subject_tag=recipient.subject_tag
            ).model_dump()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recipients",
            tags=["Recipients"],
            summary="List Recipients",
            response_model=ApiResponse)
@require_read_db
async def list_recipients(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: Optional[str] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    recipient_type: Optional[str] = None,
    is_verified: Optional[bool] = None,
    current_user: AuthContext = Depends(rbac.authenticated_read_only()),
):
    try:
        result = data_persistence_adapter.get_user_recipients(
            current_user.user.id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            recipient_type=recipient_type,
            is_verified=is_verified
        )
        recs = result["items"]
        pagination = result["pagination"]
        
        return ApiResponse(
            success=True,
            message="Recipients retrieved successfully",
            data={
                "recipients": [RecipientResponse(
                    id=r.id,
                    type=r.type,
                    value=r.value,
                    is_verified=r.is_verified,
                    is_enabled=r.is_enabled,
                    name=r.name,
                    subject_tag=r.subject_tag,
                    alert_count=r.alert_count
                ).model_dump() for r in recs],
                "pagination": pagination
            }
        )
    except Exception as e:
        logger.error(f"Error listing recipients: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recipients/{id}",
            tags=["Recipients"],
            summary="Get Recipient",
            response_model=ApiResponse)
async def get_recipient(
    id: int,
    current_user: AuthContext = Depends(rbac.authenticated())
):
    try:
        recipient = data_persistence_adapter.get_recipient(id)
        if not recipient or recipient.user_id != current_user.user.id:
            raise HTTPException(status_code=404, detail="Recipient not found")
            
        return ApiResponse(
            success=True,
            message="Recipient retrieved successfully",
            data=RecipientResponse(
                id=recipient.id,
                type=recipient.type,
                value=recipient.value,
                is_verified=recipient.is_verified,
                is_enabled=recipient.is_enabled,
                name=recipient.name,
                subject_tag=recipient.subject_tag,
                alert_count=recipient.alert_count
            ).model_dump()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/recipients/verify",
             tags=["Recipients"],
             summary="Verify Recipient",
             response_model=ApiResponse)
@require_write_db
async def verify_recipient(
    request_data: RecipientVerifyRequest,
):
    try:
        recipient_id = data_persistence_adapter.get_recipient_id_by_token(request_data.token)
        if not recipient_id:
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")
        
        success = data_persistence_adapter.update_recipient_verified(recipient_id, True)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to verify recipient")
            
        return ApiResponse(success=True, message="Recipient verified successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/recipients/{id}/resend-verification",
             tags=["Recipients"],
             summary="Resend Verification Email",
             response_model=ApiResponse)
@require_write_db
async def resend_verification(
    id: int,
    current_user: AuthContext = Depends(rbac.authenticated())
):
    try:
        # Verify ownership
        recipient = data_persistence_adapter.get_recipient(id)
        if not recipient or recipient.user_id != current_user.user.id:
            recipient = None
        
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")
        
        if recipient.is_verified:
            return ApiResponse(success=False, message="Recipient is already verified")
            
        if recipient.type != RecipientType.EMAIL:
            raise HTTPException(status_code=400, detail="Resend only supported for Email recipients")

        from utils.middleware.progressive_rate_limiter import (
            check_progressive_limit, record_attempt
        )
        from config import CONFIG

        prl_result = await check_progressive_limit(
            "resend_verif",
            f"{current_user.user.id}:{id}",
            CONFIG["PRL_RESEND_VERIFICATION"]
        )

        if not prl_result.allowed:
            raise HTTPException(
                status_code=429,
                detail=prl_result.to_error_dict(),
                headers=prl_result.to_headers(),
            )

        # Generate new token
        token = secrets.token_hex(16)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        data_persistence_adapter.create_recipient_verification(recipient.id, token, expires_at)
        
        # Send verification email via hook
        try:
            hook_event = HookEvent(
                event_type=HookEventType.USER_VERIFICATION_REQUESTED,
                data={
                    "email": recipient.value,
                    "verification_token": token,
                    "expires_in_days": 1,
                    # Add user info
                    "username": current_user.user.username,
                    "first_name": current_user.user.first_name,
                    "last_name": current_user.user.last_name
                },
                source="recipients_route"
            )
            hook_manager.fire(hook_event)
            logger.info(f"Verification email hook fired for {recipient.value} (resent)")
        except Exception as e:
            logger.error(f"Failed to fire verification hook: {e}")

        await record_attempt("resend_verif", f"{current_user.user.id}:{id}")

        return ApiResponse(success=True, message="Verification email resent")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resending verification: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/recipients/{id}",
               tags=["Recipients"],
               summary="Delete Recipient",
               response_model=ApiResponse)
@require_write_db
async def delete_recipient(
    id: int,
    current_user: AuthContext = Depends(rbac.authenticated())
):
    try:
        # Verify ownership
        # Verify ownership
        recipient = data_persistence_adapter.get_recipient(id)
        if not recipient or recipient.user_id != current_user.user.id:
            recipient = None
        
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")

        success = data_persistence_adapter.delete_recipient(id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete recipient")
            
        return ApiResponse(success=True, message="Recipient deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@router.patch("/recipients/{id}",
              tags=["Recipients"],
              summary="Update Recipient",
              response_model=ApiResponse)
@require_write_db
async def update_recipient(
    id: int,
    request_data: RecipientUpdateRequest,
    current_user: AuthContext = Depends(rbac.authenticated())
):
    try:
        # Verify ownership
        # Verify ownership
        recipient = data_persistence_adapter.get_recipient(id)
        if not recipient or recipient.user_id != current_user.user.id:
            recipient = None
        
        if not recipient:
            raise HTTPException(status_code=404, detail="Recipient not found")

        # Track if verification needs to be reset
        value_changed = False
        if request_data.value is not None and request_data.value != recipient.value:
            value_changed = True
            recipient.value = request_data.value
            recipient.is_verified = False  # Reset verification on value change

        if request_data.type is not None:
            recipient.type = request_data.type
        
        if request_data.name is not None:
            recipient.name = request_data.name
            
        if request_data.is_enabled is not None:
            recipient.is_enabled = request_data.is_enabled
            
        if request_data.subject_tag is not None:
            # Handle empty string as None/Clear
            recipient.subject_tag = request_data.subject_tag if request_data.subject_tag.strip() else None

        success = data_persistence_adapter.update_recipient(recipient)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update recipient")
            
        # If value changed and it's email, trigger new verification
        if value_changed and recipient.type == RecipientType.EMAIL:
            token = secrets.token_hex(16)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            data_persistence_adapter.create_recipient_verification(recipient.id, token, expires_at)
            # Send verification email via hook
            try:
                hook_event = HookEvent(
                    event_type=HookEventType.USER_VERIFICATION_REQUESTED,
                    data={
                        "email": recipient.value,
                        "verification_token": token,
                        "expires_in_days": 1,
                        "username": current_user.user.username,
                        "first_name": current_user.user.first_name,
                        "last_name": current_user.user.last_name
                    },
                    source="recipients_route"
                )
                hook_manager.fire(hook_event)
                logger.info(f"Verification email hook fired for {recipient.value} (updated)")
            except Exception as e:
                logger.error(f"Failed to fire verification hook: {e}")

        return ApiResponse(success=True, message="Recipient updated successfully")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating recipient: {e}")
        raise HTTPException(status_code=500, detail=str(e))
