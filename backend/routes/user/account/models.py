from pydantic import BaseModel, ConfigDict
from typing import Optional, Any
from datetime import datetime

class UserAccountResponse(BaseModel):
    """User account response model"""
    model_config = ConfigDict(from_attributes=True)

    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str
    is_active: bool
    is_verified: bool
    credits: int
    last_login: Optional[datetime] = None
    has_password: bool = True  # False for OAuth-only users

class MessageResponse(BaseModel):
    """Simple message response"""
    message: str
    success: bool = True

def user_to_response(
    user: Any,
    credits: int = 0,
) -> UserAccountResponse:
    """Convert domain User entity to response model"""
    return UserAccountResponse(
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        credits=credits,
        last_login=user.last_login,
        has_password=getattr(user, 'has_password', True),
    )
