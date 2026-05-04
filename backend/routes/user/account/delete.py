from fastapi import APIRouter, HTTPException, status, Depends
import logging

from domain.entities.auth_models import AuthContext
from utils.database.force_write import require_write_db
from utils.security.rbac import rbac
from .models import MessageResponse

# Injected by parent
data_persistence_adapter = None
auth_service = None

logger = logging.getLogger(__name__)
router = APIRouter()

@router.delete("/account/delete",
            tags=["User"],
            summary="Delete User Account",
            response_model=MessageResponse)
@require_write_db
async def delete_account(
    current_user: AuthContext = Depends(rbac.authenticated()),
):
    try:
        username = current_user.user.username
        success = auth_service.delete_user_account(current_user.user.id)

        if not success:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

        return MessageResponse(message=f"Account '{username}' deleted", success=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting account: %s", e, exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete account")
