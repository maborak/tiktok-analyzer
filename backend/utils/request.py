"""
Request Utilities

Centralized utilities for extracting request metadata like IP address and User-Agent.
"""

from fastapi import Request
from typing import Tuple, Optional

from config import CONFIG


def get_client_ip(request: Request) -> Optional[str]:
    """
    Extract client IP address from request.

    Behavior depends on TRUST_PROXY_HEADERS config:
    - True:  reads X-Forwarded-For / X-Real-IP (use when behind a trusted reverse proxy)
    - False: uses request.client.host only (safe default — prevents IP spoofing)

    Args:
        request: FastAPI Request object

    Returns:
        Client IP address string or None if unavailable
    """
    trust_proxy = CONFIG.get("TRUST_PROXY_HEADERS", False)

    if trust_proxy:
        # Prefer X-Real-IP — set authoritatively by ingress controllers (nginx, ALB)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        # X-Forwarded-For: proxies APPEND the connecting client's IP to the right.
        # An attacker can PREPEND fake IPs, but cannot control what trusted proxies append.
        # TRUSTED_PROXY_DEPTH = number of trusted proxies in the chain.
        # We read ips[len - depth] = the IP the outermost trusted proxy saw connecting to it.
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            depth = CONFIG.get("TRUSTED_PROXY_DEPTH", 1)
            idx = len(ips) - depth
            if 0 <= idx < len(ips):
                return ips[idx]

    # Fall back to direct client connection
    if request.client:
        return request.client.host

    return None


def get_user_agent(request: Request) -> Optional[str]:
    """
    Extract User-Agent from request headers.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        User-Agent string or None if header is missing
    """
    return request.headers.get("user-agent")


def get_request_metadata(request: Request) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract both IP address and User-Agent from request in one call.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Tuple of (ip_address, user_agent)
    """
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    return ip_address, user_agent

