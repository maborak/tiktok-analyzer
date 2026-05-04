"""
General API routes - Root and health check endpoints
"""

from fastapi import APIRouter, HTTPException, status, Depends
from datetime import datetime
from config import CONFIG
from utils.security.rbac import rbac

router = APIRouter()

def debug_return(message: str = "1", status_code: int = 200):
    """
    Simple debug function to quickly return a message and exit
    
    Usage:
        debug_return("test message")  # Returns 200 with message
        debug_return("error", 500)    # Returns 500 with error message
    """
    raise HTTPException(
        status_code=status_code,
        detail={
            "debug_message": message,
            "timestamp": datetime.now().isoformat(),
            "status": "debug_return"
        }
    )

@router.get("/",
         tags=["General"],
         summary="API Root",
         description="Welcome endpoint with basic API information")
async def root(_ = Depends(rbac.public())):  # noqa: ARG001
    """
    Root endpoint with basic API information.

    **Available endpoints:**
    - `/docs` - Interactive API documentation (Swagger UI)
    - `/redoc` - Alternative API documentation
    - `/health` - Health check endpoint
    """
    return {
        "message": f"{CONFIG.get('APP_NAME', 'Phoveus')} API",
        "version": "1.0.0",
        "documentation": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }

@router.get("/health",
         tags=["General"],
         summary="Health Check",
         description="Check if the API is running and healthy",
         responses={
             200: {
                 "description": "API is healthy",
                 "content": {
                     "application/json": {
                         "example": {
                             "status": "healthy",
                             "timestamp": "2024-01-15T14:30:00Z",
                             "version": "1.2.0"
                         }
                     }
                 }
             }
         })
async def health_check(_ = Depends(rbac.public())):  # noqa: ARG001
    """
    ## Health Check Endpoint 💚
    
    Returns the current health status of the API including:
    - Service status
    - Current timestamp
    - API version
    
    This endpoint is useful for:
    - Load balancer health checks
    - Monitoring systems
    - Uptime verification
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.2.0"
    }


@router.get("/config/public",
         tags=["General"],
         summary="Public Configuration",
         description="Public-facing configuration values for the frontend")
async def public_config(_ = Depends(rbac.public())):  # noqa: ARG001
    """
    Returns non-sensitive configuration values needed by the frontend.
    """
    return {
        "registration_credits": CONFIG.get("REGISTRATION_CREDITS", 5),
        "app_name": CONFIG.get("APP_NAME", "Phoveus"),
    }