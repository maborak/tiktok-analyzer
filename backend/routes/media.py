from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import FileResponse
from typing import Optional
import hmac
import logging
from utils.path import resolve_storage_path
from config import settings
from utils.auth_provider import get_auth_service
from domain.services.auth_service import AuthService
from utils.request import get_request_metadata

logger = logging.getLogger(__name__)

router = APIRouter()

# Injected by routes/main.py
ticket_service = None

@router.get("/tickets/{file_path:path}",
            responses={
                401: {"description": "Authentication required — pass JWT via `?token=` query param or `Authorization: Bearer` header"},
                400: {"description": "Invalid file path"},
                404: {"description": "File not found"},
            })
async def get_ticket_media(
    file_path: str,
    request: Request,
    token: str = Query(None),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Serve a ticket attachment. Requires authentication via query token or Authorization header."""
    # Extract token from header if not in query
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    ip_address, _ = get_request_metadata(request)

    try:
        # Do NOT pass user_agent here - browsers & PDF viewers change the UA string
        # when loading embedded resources vs. the original login request, causing
        # false "User-Agent mismatch" rejections. The JWT token itself is sufficient.
        auth_context = auth_service.get_auth_context(token, ip_address=ip_address)
        if not auth_context or not auth_context.user:
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Media auth error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

    storage_dir = resolve_storage_path(settings("TICKET_UPLOAD_STORAGE_PATH", "data/uploads/tickets"))

    # Reject obvious traversal attempts early
    if ".." in file_path or file_path.startswith("/") or "\x00" in file_path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    full_path = (storage_dir / file_path).resolve()

    # Verify resolved path is inside storage directory
    if not str(full_path).startswith(str(storage_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=full_path)


@router.get("/livechat/{file_path:path}",
            responses={
                401: {"description": "Authentication required — pass JWT via `?token=` or `?session_token=` query param, or `Authorization: Bearer` header"},
                400: {"description": "Invalid file path"},
                404: {"description": "File not found"},
            })
async def get_livechat_media(
    file_path: str,
    request: Request,
    token: Optional[str] = Query(None, description="JWT access token"),
    session_token: Optional[str] = Query(None, description="Livechat session token"),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Serve a livechat attachment with dual-auth.
    Authenticated users pass JWT via ?token= or Authorization header.
    Anonymous guests pass their livechat session token via ?session_token=.
    """
    # Path traversal protection
    if ".." in file_path or file_path.startswith("/") or "\x00" in file_path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    # Look up the attachment in DB to get session ownership
    if not ticket_service:
        raise HTTPException(status_code=500, detail="Service unavailable")

    file_url = f"/media/livechat/{file_path}"
    attachment = ticket_service.get_livechat_attachment_by_file_url(file_url)
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found")

    # Auth check 1: JWT token (query param or Authorization header)
    jwt_token = token
    if not jwt_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            jwt_token = auth_header.split(" ")[1]

    authorized = False

    if jwt_token:
        try:
            ip_address, _ = get_request_metadata(request)
            auth_context = auth_service.get_auth_context(jwt_token, ip_address=ip_address)
            if auth_context and auth_context.user:
                authorized = True
        except Exception:
            pass  # JWT invalid — fall through to session token check

    # Auth check 2: Livechat session token
    if not authorized and session_token:
        session = ticket_service.get_chat_session(attachment.session_id)
        if session and session.session_token:
            if hmac.compare_digest(session.session_token, session_token):
                authorized = True

    if not authorized:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Serve the file
    storage_dir = resolve_storage_path(settings("LIVECHAT_UPLOAD_STORAGE_PATH", "data/uploads/livechat"))
    full_path = (storage_dir / file_path).resolve()

    if not str(full_path).startswith(str(storage_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=full_path)
