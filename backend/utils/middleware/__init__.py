"""
HTTP Middleware for FastAPI Application

This module contains HTTP middleware functions following hexagonal architecture principles.
Middleware is infrastructure/adapters concern and should be separated from the application entry point.
"""

from .rate_limiting import create_rate_limiting_middleware
from .security_headers import create_security_headers_middleware
from .gzip_request import CompressedRequestMiddleware, GZipRequestMiddleware
from .perf_tracer import PerfTracerMiddleware

__all__ = [
    "create_rate_limiting_middleware",
    "create_security_headers_middleware",
    "CompressedRequestMiddleware",
    "GZipRequestMiddleware",  # backward-compatible alias
    "PerfTracerMiddleware",
]
