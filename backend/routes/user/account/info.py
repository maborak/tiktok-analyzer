from fastapi import APIRouter, HTTPException, status, Depends
import logging

from domain.entities.auth_models import AuthContext
from utils.database.force_write import require_read_db
from utils.security.rbac import rbac
from domain.api_models import ApiResponse
from .models import UserAccountResponse, user_to_response

# Injected by parent
data_persistence_adapter = None
auth_service = None

logger = logging.getLogger(__name__)
router = APIRouter()

from domain.services.credit_service import CreditService

@router.get("/account",
         tags=["User"],
         summary="Get Current User Account",
         description="Get the current authenticated user's account information.",
         response_model=ApiResponse)
@require_read_db
async def get_account(
    current_user: AuthContext = Depends(rbac.authenticated_read_only()),
):
    try:
        credit_service = CreditService(data_persistence_adapter)

        user = auth_service.get_user_profile(current_user.user.id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User account not found"
            )

        credits = credit_service.get_credit_balance(user.id)

        return ApiResponse(
            success=True,
            message="Account details retrieved successfully",
            data=user_to_response(
                user,
                credits=credits,
            ).model_dump()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting user account: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user account"
        )

