"""
Admin Security Routes

Routes for managing account lockouts and security-related admin operations.
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone
import logging
import math

from database.auth.models import User as UserModel
from domain.entities.auth_models import AuthContext
from utils.database.database_session import get_db_session
from utils.database.force_write import require_read_db, require_write_db
from utils.security.rbac import rbac
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Response Models ---

class LockedUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool
    is_verified: bool
    failed_login_attempts: int
    locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None


class LockoutsListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    users: List[LockedUserResponse]


class UnlockResponse(BaseModel):
    success: bool
    message: str
    unlocked_count: int = 0


# --- Endpoints ---

@router.get("/security/lockouts",
         tags=["Admin"],
         summary="List Locked-Out Users",
         description="Get a paginated list of users with failed login attempts > 0.",
         response_model=LockoutsListResponse)
@require_read_db
async def list_lockouts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=100),
    sort_by: str = Query("failed_login_attempts", description="Sort field"),
    sort_order: str = Query("desc"),
    current_user: AuthContext = Depends(rbac.require("admin:write")),
):
    try:
        valid_sort_fields = {
            "id": UserModel.id,
            "email": UserModel.email,
            "username": UserModel.username,
            "failed_login_attempts": UserModel.failed_login_attempts,
            "locked_until": UserModel.locked_until,
            "last_login": UserModel.last_login,
        }

        if sort_by not in valid_sort_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_by: {sort_by}. Must be one of: {', '.join(valid_sort_fields)}"
            )

        if sort_order.lower() not in ("asc", "desc"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sort_order must be 'asc' or 'desc'"
            )

        with get_db_session() as session:
            query = session.query(UserModel).filter(UserModel.failed_login_attempts > 0)

            if search:
                term = f"%{search}%"
                query = query.filter(
                    (UserModel.email.ilike(term)) |
                    (UserModel.username.ilike(term)) |
                    (UserModel.first_name.ilike(term)) |
                    (UserModel.last_name.ilike(term))
                )

            total = query.count()

            col = valid_sort_fields[sort_by]
            order = col.desc() if sort_order.lower() == "desc" else col.asc()
            query = query.order_by(order)

            offset = (page - 1) * page_size
            users = query.offset(offset).limit(page_size).all()

            return LockoutsListResponse(
                total=total,
                page=page,
                page_size=page_size,
                total_pages=max(1, math.ceil(total / page_size)),
                users=[
                    LockedUserResponse(
                        id=u.id,
                        username=u.username or "",
                        email=u.email,
                        first_name=u.first_name,
                        last_name=u.last_name,
                        is_active=u.is_active,
                        is_verified=u.is_verified,
                        failed_login_attempts=u.failed_login_attempts,
                        locked_until=u.locked_until,
                        last_login=u.last_login,
                    )
                    for u in users
                ],
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing lockouts: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list locked-out users"
        ) from e


@router.post("/security/lockouts/{user_id}/unlock",
          tags=["Admin"],
          summary="Unlock User",
          description="Reset failed login attempts and lockout for a specific user.",
          response_model=UnlockResponse)
@require_write_db
async def unlock_user(
    user_id: int,
    current_user: AuthContext = Depends(rbac.require("admin:write")),
):
    try:
        with get_db_session() as session:
            user = session.query(UserModel).filter(UserModel.id == user_id).first()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with ID {user_id} not found"
                )

            if user.failed_login_attempts == 0 and user.locked_until is None:
                return UnlockResponse(
                    success=True,
                    message="User is not locked out",
                    unlocked_count=0,
                )

            user.failed_login_attempts = 0
            user.locked_until = None
            session.commit()

            logger.info(
                "Admin %s (id=%s) unlocked user %s (id=%s)",
                current_user.user.email, current_user.user.id,
                user.email, user.id,
            )

            return UnlockResponse(
                success=True,
                message=f"User {user.email} has been unlocked",
                unlocked_count=1,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error unlocking user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unlock user"
        ) from e


@router.post("/security/lockouts/unlock-all",
          tags=["Admin"],
          summary="Unlock All Users",
          description="Reset failed login attempts and lockout for ALL locked-out users.",
          response_model=UnlockResponse)
@require_write_db
async def unlock_all_users(
    current_user: AuthContext = Depends(rbac.require("admin:write")),
):
    try:
        with get_db_session() as session:
            count = session.query(UserModel).filter(
                UserModel.failed_login_attempts > 0
            ).update({
                UserModel.failed_login_attempts: 0,
                UserModel.locked_until: None,
            })
            session.commit()

            logger.info(
                "Admin %s (id=%s) unlocked all users (%d accounts)",
                current_user.user.email, current_user.user.id, count,
            )

            return UnlockResponse(
                success=True,
                message=f"Unlocked {count} user(s)",
                unlocked_count=count,
            )

    except Exception as e:
        logger.error("Error unlocking all users: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unlock all users"
        ) from e
