"""
Example: Using Configuration-Based Authentication

This file shows examples of how to use the auth_dependency helper
in your routes instead of hardcoding authentication dependencies.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from domain.entities.auth_models import AuthContext
from utils.auth_dependency import create_auth_dependency

router = APIRouter()


# Example 1: Protected Route (auth required)
@router.get("/products")
async def list_products(
    current_user: Optional[AuthContext] = create_auth_dependency("/products")
):
    """
    List products - requires authentication based on config.
    
    If AUTH_REQUIRED["/products"] is True, current_user will be set.
    If False, current_user will be None.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    return {"message": "Products list", "user": current_user.user.username}


# Example 2: Public Route (no auth required)
@router.get("/health")
async def health_check(
    current_user: Optional[AuthContext] = create_auth_dependency("/health")
):
    """
    Health check - public endpoint.
    
    current_user will always be None for public routes.
    """
    return {"status": "healthy"}


# Example 3: Optional Auth Route
@router.get("/products/{product_id}")
async def get_product(
    product_id: str,
    current_user: Optional[AuthContext] = create_auth_dependency("/products/{product_id}")
):
    """
    Get product - can work with or without authentication.
    
    If authenticated, return full data.
    If not authenticated, return limited data.
    """
    if current_user:
        # Authenticated users get full data
        return {
            "product_id": product_id,
            "full_data": True,
            "user": current_user.user.username
        }
    else:
        # Public users get limited data
        return {
            "product_id": product_id,
            "full_data": False,
            "message": "Limited data for public access"
        }


# Example 4: Route with Wildcard Pattern
@router.get("/items/{item_id}/history")
async def get_item_history(
    item_id: str,
    current_user: Optional[AuthContext] = create_auth_dependency("/items/*")
):
    """
    Get item history - uses wildcard pattern matching.

    If AUTH_REQUIRED["/items/*"] is True, all /items/* routes require auth.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    return {
        "item_id": item_id,
        "history": [],
        "user": current_user.user.username
    }

