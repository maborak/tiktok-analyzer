"""
User OAuth Account Management Routes

Endpoints for listing, unlinking OAuth accounts, and setting password for OAuth-only users.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from typing import Optional, List
import logging

from domain.entities.auth_models import AuthContext
from utils.security.rbac import rbac
from utils.database.force_write import require_write_db
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter()

# Injected by setup in __init__.py
oauth_service = None
auth_service = None


# --- Response Models ---

class OAuthAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    provider: str
    provider_user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class OAuthAccountsListResponse(BaseModel):
    accounts: List[OAuthAccountResponse]
    has_password: bool


class SetPasswordRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    password: str = Field(..., min_length=8, max_length=200, description="New password (min 8 chars)")
    password_confirmation: str = Field(..., min_length=8, max_length=200)


# --- Endpoints ---

@router.get("/oauth",
    summary="List Linked OAuth Accounts",
    description="Get all OAuth accounts linked to the current user",
    response_model=OAuthAccountsListResponse)
async def list_oauth_accounts(
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    if not oauth_service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth not configured")

    accounts = oauth_service.get_oauth_accounts_for_user(current_user.user.id)

    # Fresh DB check — auth context user may have stale has_password after set-password
    fresh_user = oauth_service.user_management_port.get_user_by_id(current_user.user.id)
    has_password = getattr(fresh_user, "has_password", True) if fresh_user else True

    return OAuthAccountsListResponse(
        accounts=[
            OAuthAccountResponse(
                provider=a.provider,
                provider_user_id=a.provider_user_id,
                email=a.email,
                name=a.name,
                avatar_url=a.avatar_url,
            )
            for a in accounts
        ],
        has_password=has_password,
    )


class LinkOAuthRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    provider: str = Field(..., max_length=50)
    token_or_code: str = Field(..., max_length=5000)
    redirect_uri: Optional[str] = Field(None, max_length=500)
    confirmed: bool = Field(default=False, description="Set to true to confirm email mismatch linking")


@router.post("/oauth/link",
    summary="Link OAuth Provider",
    description="Link an OAuth provider to the current authenticated user's account.",
    status_code=200)
@require_write_db
async def link_oauth_provider(
    request: LinkOAuthRequest,
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    if not oauth_service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth not configured")

    # Always commit the link — authorization codes (GitHub/Facebook) can only be used once,
    # so dry-run is not possible for redirect-based providers.
    result = oauth_service.link_provider(
        user_id=current_user.user.id,
        provider=request.provider,
        token=request.token_or_code,
        redirect_uri=request.redirect_uri,
        dry_run=False,
    )

    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error", "Linking failed"))

    return {
        "success": True,
        "message": f"{request.provider.title()} account connected",
        "provider_email": result.get("provider_email"),
        "email_mismatch": result.get("email_mismatch", False),
        "already_linked": result.get("already_linked", False),
    }


@router.delete("/oauth/{provider}",
    summary="Unlink OAuth Provider",
    description="Remove an OAuth provider link from the current user. Must retain at least one auth method.",
    status_code=200)
@require_write_db
async def unlink_oauth_provider(
    provider: str,
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    if not oauth_service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth not configured")

    success = oauth_service.unlink_oauth_account(current_user.user.id, provider)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot unlink this provider. You must have at least one sign-in method (password or another OAuth provider)."
        )

    return {"success": True, "message": f"{provider.title()} account unlinked"}


@router.post("/set-password",
    summary="Set Password",
    description="Set a password for OAuth-only users who don't have one yet",
    status_code=200)
@require_write_db
async def set_password(
    request: SetPasswordRequest,
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    if not auth_service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not configured")

    if request.password != request.password_confirmation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")

    # Fresh DB check — auth context may be stale
    fresh_user = auth_service.user_management_port.get_user_by_id(current_user.user.id)
    has_password = getattr(fresh_user, "has_password", True) if fresh_user else True
    if has_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account already has a password. Use the change-password flow instead."
        )

    try:
        from database.auth.utils import generate_salt, hash_password
        salt = generate_salt()
        password_hash = hash_password(request.password, salt)

        auth_service.user_management_port.update_user(current_user.user.id, {
            "password_hash": password_hash,
            "salt": salt,
        })

        return {"success": True, "message": "Password set successfully"}

    except Exception as e:
        logger.error("Set password error for user %d: %s", current_user.user.id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set password"
        ) from e
