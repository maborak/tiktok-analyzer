from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional
import logging
from pydantic import BaseModel, Field, ConfigDict, EmailStr

from domain.entities.auth_models import AuthContext
from utils.database.force_write import require_write_db
from utils.security.rbac import rbac
from .models import UserAccountResponse, user_to_response

# Injected by parent
data_persistence_adapter = None
auth_service = None

logger = logging.getLogger(__name__)
router = APIRouter()

class UserAccountEditRequest(BaseModel):
    """Request model for editing user account"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "johndoe",
                "email": "john.doe@example.com",
                "first_name": "John",
                "last_name": "Doe"
            }
        }
    )

    username: Optional[str] = Field(None, min_length=3, max_length=50, description="Username (unique)")
    email: Optional[EmailStr] = Field(None, description="Email address (unique)")
    first_name: Optional[str] = Field(None, max_length=100, description="First name")
    last_name: Optional[str] = Field(None, max_length=100, description="Last name")

@router.put("/account/edit",
         tags=["User"],
         summary="Edit User Account",
         description="Edit the current authenticated user's account.",
         response_model=UserAccountResponse)
@require_write_db
async def edit_account(
    account_data: UserAccountEditRequest,
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    try:
        if not any([account_data.username, account_data.email,
                    account_data.first_name is not None, account_data.last_name is not None]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one field must be provided for update"
            )

        updates = {}
        if account_data.username:
            updates["username"] = account_data.username
        if account_data.email:
            updates["email"] = account_data.email
        if account_data.first_name is not None:
            updates["first_name"] = account_data.first_name or None
        if account_data.last_name is not None:
            updates["last_name"] = account_data.last_name or None

        try:
            updated_user = auth_service.update_user_profile(current_user.user.id, updates)
        except ValueError as e:
            detail = str(e)
            if "already taken" in detail or "already in use" in detail:
                raise HTTPException(status.HTTP_409_CONFLICT, detail=detail)
            raise

        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User account not found"
            )

        return user_to_response(updated_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating user account: %s", e, exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update account")
