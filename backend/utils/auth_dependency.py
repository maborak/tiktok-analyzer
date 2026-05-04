"""
Authentication Dependency Helper

Provides a configuration-based authentication dependency system.
Routes can use this helper to determine if authentication is required based on config.
"""

import re
import logging

# Don't import FastAPI here - import it lazily to avoid circular imports
# from fastapi import Depends, Request
# from domain.entities.auth_models import AuthContext
import config

logger = logging.getLogger(__name__)


def _match_path_pattern(path: str, pattern: str) -> bool:
    """
    Check if a path matches a pattern.
    Supports exact matches and wildcard patterns (e.g., "/products/*")
    
    Args:
        path: The actual path to check
        pattern: The pattern to match against (supports * wildcard)
    
    Returns:
        True if path matches pattern, False otherwise
    """
    # Convert pattern to regex
    # Escape special regex characters except *
    pattern_regex = pattern.replace("*", ".*")
    pattern_regex = re.escape(pattern_regex).replace(r"\*", ".*")
    
    # Match from start of string
    pattern_regex = f"^{pattern_regex}$"
    
    return bool(re.match(pattern_regex, path))


def _check_auth_required(path: str) -> bool:
    """
    Check if authentication is required for a given path based on configuration.
    
    Args:
        path: The request path (e.g., "/products", "/products/B0DS2X13PH")
    
    Returns:
        True if authentication is required, False otherwise
    """
    auth_config = config.settings("AUTH_REQUIRED", {})
    default_auth = config.settings("AUTH_REQUIRED_DEFAULT", True)
    
    # Check exact match first
    if path in auth_config:
        return auth_config[path]
    
    # Check pattern matches (e.g., "/products/*")
    for pattern, required in auth_config.items():
        if "*" in pattern and _match_path_pattern(path, pattern):
            return required
    
    # Check prefix matches (e.g., "/products" matches "/products/123")
    for pattern, required in auth_config.items():
        if "*" not in pattern and path.startswith(pattern):
            # Make sure it's a proper prefix match (not partial)
            # e.g., "/product" should not match "/products"
            if path == pattern or path.startswith(pattern + "/"):
                return required
    
    # Return default if no match found
    return default_auth


def create_auth_dependency(path: str):
    """
    Create an authentication dependency for a route based on configuration.
    
    This function returns the appropriate dependency based on the path configuration.
    If auth is required, it returns Depends(get_current_user_swagger_compatible).
    If auth is not required, it returns a dependency that returns None.
    
    The auth requirement is checked at runtime (when the request is made),
    so changes to AUTH_REQUIRED config will be reflected immediately.
    
    Args:
        path: The route path (e.g., "/products", "/products/{product_id}")
    
    Returns:
        FastAPI Depends object
    
    Example:
        @router.get("/products")
        async def get_products(
            current_user: Optional[AuthContext] = create_auth_dependency("/products")
        ):
            if current_user:
                # Authenticated user
            else:
                # Public access or auth not required
    """
    # Import Depends lazily to avoid issues at definition time
    from fastapi import Depends, Request
    from typing import Optional
    from domain.entities.auth_models import AuthContext
    
    # Store path in closure - check auth requirement at runtime
    _path = path
    
    # Create a dependency function that checks config at runtime
    async def _get_auth_dependency(request: Request) -> Optional[AuthContext]:
        # Check auth requirement at runtime (when request is made)
        # This allows config changes to be reflected immediately
        # Import here to avoid circular imports - only at runtime
        from routes.auth import (
            get_current_user_swagger_compatible,
            oauth2_scheme_optional,
            bearer_security_optional,
            get_auth_service
        )
        from fastapi.security import HTTPAuthorizationCredentials
        from fastapi import HTTPException, status
        
        # Extract tokens from request using the security schemes
        oauth2_token: Optional[str] = None
        bearer_credentials: Optional[HTTPAuthorizationCredentials] = None
        
        # Try to get OAuth2 token (for Swagger UI)
        try:
            oauth2_token = await oauth2_scheme_optional(request)
        except Exception:  # pylint: disable=broad-except
            pass
        
        # Try to get Bearer token (for programmatic access)
        try:
            bearer_credentials = await bearer_security_optional(request)
        except Exception:  # pylint: disable=broad-except
            pass
        
        # Check if we have any credentials
        has_credentials = oauth2_token is not None or bearer_credentials is not None
        
        # Check if authentication is required
        is_required = _check_auth_required(_path)
        
        # Logic:
        # 1. If we have credentials, ALWAYS try to authenticate (even if optional)
        #    - If valid -> Return User
        #    - If invalid -> Raise 401 (don't fail silently for bad tokens)
        # 2. If NO credentials:
        #    - If required -> Raise 401 (via get_current_user_swagger_compatible)
        #    - If optional -> Return None
        
        if has_credentials or is_required:
            # Get auth service instance
            auth_service_instance = get_auth_service()
            
            # Call the authentication function
            return await get_current_user_swagger_compatible(
                request=request,
                oauth2_token=oauth2_token,
                bearer_credentials=bearer_credentials,
                auth_service_instance=auth_service_instance
            )
        else:
            # No credentials and not required -> Return None
            return None
    
    # Return Depends with the dependency function
    # FastAPI will inject Request automatically
    return Depends(_get_auth_dependency)


def is_auth_required(path: str) -> bool:
    """
    Check if authentication is required for a path (without creating a dependency).
    Useful for middleware or other non-route code.
    
    Args:
        path: The request path
    
    Returns:
        True if authentication is required, False otherwise
    """
    return _check_auth_required(path)

