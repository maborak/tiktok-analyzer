"""
Security Headers Middleware

Adds security headers to all HTTP responses.
Different headers for Swagger UI vs API endpoints.
"""

from fastapi import Request
from typing import Callable


def create_security_headers_middleware() -> Callable:
    """
    Create security headers middleware function

    Returns:
        Middleware function that can be registered with FastAPI app
    """

    async def security_headers_middleware(request: Request, call_next):
        """Add security headers to all responses"""
        response = await call_next(request)

        # Check if this is a Swagger UI request
        path = request.url.path
        is_swagger = any(swagger_path in path for swagger_path in ["/docs", "/redoc", "/openapi.json"])
        is_auth_endpoint = path.startswith("/auth")

        if is_swagger:
            # More permissive headers for Swagger UI
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            # Strict security headers for API endpoints
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        if is_auth_endpoint:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"

        return response

    return security_headers_middleware
