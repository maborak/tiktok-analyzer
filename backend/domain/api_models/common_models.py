"""
Common API Models

Shared Pydantic models used across all API endpoints.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime

class ApiResponse(BaseModel):
    """Generic API response wrapper"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"key": "value"}
            }
        }
    )
    
    success: bool = Field(
        ...,
        description="Whether the operation was successful"
    )
    message: str = Field(
        ...,
        description="Human-readable message about the operation result",
        examples=["Operation completed successfully"]
    )
    data: Optional[Dict[str, Any]] = Field(
        None,
        description="Response data (optional)",
        examples=[{"key": "value"}]
    )

class ErrorResponse(BaseModel):
    """Error response model"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Product not found or URL is invalid",
                "type": "validation_error",
                "timestamp": "2024-01-15T14:30:00Z"
            }
        }
    )
    
    detail: str = Field(
        ...,
        description="Error message describing what went wrong"
    )
    type: str = Field(
        "error",
        description="Type of error that occurred"
    )
    timestamp: str = Field(
        ...,
        description="Timestamp when the error occurred",
        examples=["2024-01-15T14:30:00Z"]
    ) 