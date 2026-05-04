from fastapi import APIRouter, Depends, HTTPException, status, Header, Request, File, UploadFile, Query
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from domain.entities.ticket_models import LiveChatSenderType, LiveChatStatus
from domain.entities.auth_models import AuthContext
from utils.security.rbac import rbac
from utils.request import get_client_ip

router = APIRouter(tags=["LiveChat"])

# Dependency placeholder
ticket_service = None

# --- Models ---

class StartSessionRequest(BaseModel):
    # Optional identifying info if starting anonymously
    name: Optional[str] = None
    email: Optional[str] = None
    initial_message: Optional[str] = None
    is_proactive: bool = False
    source_url: Optional[str] = None
    client_metadata: Optional[dict] = None

class SessionResponse(BaseModel):
    id: str
    session_token: Optional[str]
    status: str
    created_at: str

class SessionMetadataResponse(BaseModel):
    id: str
    status: str
    created_at: str
    ended_at: Optional[datetime]
    agent_id: Optional[int]
    ticket_id: Optional[str]
    is_authenticated_user: bool
    user_id: Optional[int]
    initial_context: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    current_url: Optional[str] = None
    is_proactive: bool = False

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    context: Optional[dict] = None

class LiveChatAttachmentResponse(BaseModel):
    id: str
    file_name: str
    file_url: str
    content_type: str
    file_size: int
    created_at: str

class ChatMessageResponse(BaseModel):
    id: str
    sender_type: str
    message: str
    created_at: str
    sender_id: Optional[int]
    attachments: List[LiveChatAttachmentResponse] = []
    context: Optional[dict] = None

class ActivityUpdateRequest(BaseModel):
    current_url: Optional[str] = None
    is_typing: Optional[bool] = None

class ConvertToTicketRequest(BaseModel):
    subject: str = Field(..., min_length=3)
    category_id: str

class ConvertToTicketResponse(BaseModel):
    ticket_id: str

# --- Helpers ---

def _verify_session_access(session, x_session_token: Optional[str], current_user: Optional[AuthContext]):
    """
    Centralized session access validation logic (Dual-Auth).
    Allows access if:
    1. x_session_token matches the session token in the DB.
    2. current_user is the owner of the session (for authenticated users).
    3. current_user is an agent/admin with support permissions.
    """
    # 1. Check Session Token (Guest/Anonymous flow)
    if session.session_token and x_session_token and session.session_token == x_session_token:
        return True
        
    # 2. Check Authenticated User (Owner flow)
    if current_user and current_user.user and session.user_id == current_user.user.id:
        return True
        
    # 3. Check Admin/Agent (Support flow)
    if current_user and current_user.has_any_permission(["admin:read", "support:read", "admin:write", "support:write"]):
        return True
        
    raise HTTPException(status_code=401, detail="Invalid session token or insufficient permissions")

# --- Endpoints ---

@router.post("/session", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def start_chat_session(
    request: Request,
    request_data: StartSessionRequest,
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """Start a new LiveChat session"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
    
    import secrets
    session_token = secrets.token_urlsafe(32)
    
    user_id = None
    is_auth_user = False
    
    # Priority 1: Use actual logged-in user if present
    if current_user and current_user.user:
        user_id = current_user.user.id
        is_auth_user = True
    # Priority 2: Contextual Guest Mode: if email provided, check if registered user
    elif request_data.email:
        try:
            from utils.auth_provider import get_auth_service
            auth_service = get_auth_service()
            # get_user_by_email lives on user_management_port, not auth_service directly
            user = auth_service.user_management_port.get_user_by_email(request_data.email)
            if user:
                user_id = user.id
                is_auth_user = False  # Contextual guest — not verified login
        except Exception:
            pass  # Silently fail — contextual guest lookup is best-effort

    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    
    initial_context = {
        "ip": client_ip,
        "user_agent": user_agent,
        "source_url": request_data.source_url,
        "custom": request_data.client_metadata
    }

    session = ticket_service.start_chat_session(
        user_id=user_id,
        session_token=session_token,
        is_authenticated_user=is_auth_user,
        initial_context=initial_context,
        initial_message=request_data.initial_message,
        is_proactive=request_data.is_proactive,
        ip_address=client_ip,
        user_agent=user_agent,
        current_url=request_data.source_url
    )
    
    return SessionResponse(
        id=session.id,
        session_token=session.session_token,
        status=session.status.value,
        created_at=session.created_at.isoformat()
    )

@router.get("/session/{session_id}", response_model=SessionMetadataResponse)
async def get_session_metadata(
    session_id: str,
    x_session_token: Optional[str] = Header(None),
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """Retrieve current session metadata (status, assigned agent, etc.)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    _verify_session_access(session, x_session_token, current_user)

    return SessionMetadataResponse(
        id=session.id,
        status=session.status.value,
        created_at=session.created_at.isoformat(),
        ended_at=session.ended_at.isoformat() if session.ended_at else None,
        agent_id=session.agent_id,
        ticket_id=session.ticket_id,
        is_authenticated_user=session.is_authenticated_user,
        user_id=session.user_id,
        initial_context=session.initial_context,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        current_url=session.current_url,
        is_proactive=session.is_proactive
    )

@router.post("/session/{session_id}/end")
async def guest_end_session(
    session_id: str,
    x_session_token: Optional[str] = Header(None),
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """(Guest) Explicitly end your own chat session"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    _verify_session_access(session, x_session_token, current_user)
        
    success = ticket_service.end_chat_session(session_id, ended_by_agent=False)
    return {"success": success}

@router.get("/session/{session_id}/messages", response_model=List[ChatMessageResponse])
async def get_chat_messages(
    session_id: str,
    x_session_token: Optional[str] = Header(None),
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """Get all messages for a LiveChat session (guest or agent)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    _verify_session_access(session, x_session_token, current_user)

    try:
        messages = ticket_service.get_chat_messages(session_id)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="Chat message persistence not yet implemented")
    
    return [
        ChatMessageResponse(
            id=m.id,
            sender_type=m.sender_type.value,
            message=m.message,
            created_at=m.created_at.isoformat(),
            sender_id=m.sender_id,
            attachments=[
                LiveChatAttachmentResponse(
                    id=a.id,
                    file_name=a.file_name,
                    file_url=a.file_url,
                    content_type=a.content_type,
                    file_size=a.file_size,
                    created_at=a.created_at.isoformat()
                ) for a in m.attachments
            ],
            context=m.context
        ) for m in messages
    ]

@router.post("/session/{session_id}/message", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def add_chat_message(
    session_id: str,
    request: ChatMessageRequest,
    x_session_token: Optional[str] = Header(None),
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """Add a message to the session (guest side)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    _verify_session_access(session, x_session_token, current_user)
    
    msg = ticket_service.add_chat_message(
        session_id=session_id,
        sender_type=LiveChatSenderType.USER,
        message=request.message,
        sender_id=session.user_id,
        context=request.context
    )
    
    return ChatMessageResponse(
        id=msg.id,
        sender_type=msg.sender_type.value,
        message=msg.message,
        created_at=msg.created_at.isoformat(),
        sender_id=msg.sender_id,
        attachments=[],
        context=msg.context
    )

@router.post("/session/{session_id}/convert", response_model=ConvertToTicketResponse)
async def convert_chat_to_ticket(
    session_id: str,
    request: ConvertToTicketRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """(Agents Only) Convert a LiveChat session into a support ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    try:
        ticket_id = ticket_service.convert_chat_to_ticket(
            session_id=session_id,
            subject=request.subject,
            category_id=request.category_id,
            agent_id=current_user.user.id
        )
        return ConvertToTicketResponse(ticket_id=ticket_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/session/{session_id}/attachments", response_model=LiveChatAttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    session_id: str,
    message_id: str,
    file: UploadFile = File(...),
    x_session_token: Optional[str] = Header(None),
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """Upload a file attachment for a specific LiveChat message"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    _verify_session_access(session, x_session_token, current_user)
        
    try:
        file_content = await file.read()
        attachment = ticket_service.upload_livechat_attachment(
            session_id=session_id,
            message_id=message_id,
            file_name=file.filename,
            file_content=file_content
        )
        return LiveChatAttachmentResponse(
            id=attachment.id,
            file_name=attachment.file_name,
            file_url=attachment.file_url,
            content_type=attachment.content_type,
            file_size=attachment.file_size,
            created_at=attachment.created_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/session/{session_id}/activity")
async def update_session_activity(
    session_id: str,
    request_data: ActivityUpdateRequest,
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    current_user: Optional[AuthContext] = Depends(rbac.optional())
):
    """Update user activity (current URL, typing status)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Security check
    _verify_session_access(session, x_session_token, current_user)
    
    sender_type = LiveChatSenderType.USER
    if current_user and current_user.user and current_user.user.id == session.agent_id:
        sender_type = LiveChatSenderType.AGENT
        
    success = ticket_service.update_chat_session_activity(
        session_id=session_id,
        current_url=request_data.current_url,
        is_typing=request_data.is_typing,
        sender_type=sender_type
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update activity")
        
    return {"status": "success"}

# --- Admin Operations ---

class AdminJoinSessionResponse(BaseModel):
    success: bool
    session_id: str

class PaginatedSessionResponse(BaseModel):
    items: List[SessionMetadataResponse]
    total: int
    page: int
    page_size: int

@router.get("/admin/sessions", response_model=PaginatedSessionResponse)
async def get_admin_sessions(
    chat_status: Optional[LiveChatStatus] = Query(None, alias="status", description="Filter by session status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: AuthContext = Depends(rbac.require_any(["admin:read", "support:read"]))
):
    """(Agents Only) Get LiveChat sessions with pagination and optional status filter"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")

    result = ticket_service.get_active_chat_sessions(status=chat_status, page=page, page_size=page_size)

    return PaginatedSessionResponse(
        items=[
            SessionMetadataResponse(
                id=s.id,
                status=s.status.value,
                created_at=s.created_at.isoformat(),
                ended_at=s.ended_at.isoformat() if s.ended_at else None,
                agent_id=s.agent_id,
                ticket_id=s.ticket_id,
                is_authenticated_user=s.is_authenticated_user,
                user_id=s.user_id,
                initial_context=s.initial_context,
                ip_address=s.ip_address,
                user_agent=s.user_agent,
                current_url=s.current_url,
                is_proactive=s.is_proactive
            ) for s in result["items"]
        ],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"]
    )

class LiveChatStatsResponse(BaseModel):
    waiting: int
    active: int
    ended: int
    total: int

@router.get("/admin/stats", response_model=LiveChatStatsResponse)
async def get_livechat_stats(
    current_user: AuthContext = Depends(rbac.require_any(["admin:read", "support:read"]))
):
    """(Agents Only) Get LiveChat session statistics (counts by status)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
    
    stats = ticket_service.get_livechat_session_stats()
    return LiveChatStatsResponse(**stats)

@router.post("/admin/session/{session_id}/join", response_model=AdminJoinSessionResponse)

async def admin_join_session(
    session_id: str,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """(Agents Only) Claim a WAITING session — changes its status to ACTIVE"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Hardening Round 2: Record which agent joined the session
    ticket_service.update_chat_session_status(
        session_id=session_id, 
        status=LiveChatStatus.ACTIVE, 
        agent_id=current_user.user.id
    )
    
    # BUG FIX: Resolve agent name from user object correctly
    user = current_user.user
    agent_name = (
        f"{user.first_name} {user.last_name}".strip()
        if (user.first_name or user.last_name)
        else user.email
    )
    
    ticket_service.add_chat_message(
        session_id=session_id,
        sender_type=LiveChatSenderType.SYSTEM,
        message=f"{agent_name} has joined the chat.",
        sender_id=user.id
    )
    
    return AdminJoinSessionResponse(success=True, session_id=session_id)

@router.post("/admin/session/{session_id}/message", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
async def agent_send_message(
    session_id: str,
    request: ChatMessageRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """(Agents Only) Send a message in a LiveChat session as the agent"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")

    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    msg = ticket_service.add_chat_message(
        session_id=session_id,
        sender_type=LiveChatSenderType.AGENT,
        message=request.message,
        sender_id=current_user.user.id,
        context=request.context
    )

    return ChatMessageResponse(
        id=msg.id,
        sender_type=msg.sender_type.value,
        message=msg.message,
        created_at=msg.created_at.isoformat(),
        sender_id=msg.sender_id,
        attachments=[],
        context=msg.context
    )

@router.get("/admin/session/{session_id}/messages", response_model=List[ChatMessageResponse])
async def admin_get_chat_messages(
    session_id: str,
    current_user: AuthContext = Depends(rbac.require_any(["admin:read", "support:read"]))
):
    """(Agents Only) Get all messages for a LiveChat session via Admin path"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    session = ticket_service.get_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    try:
        messages = ticket_service.get_chat_messages(session_id)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="Chat message persistence not yet implemented")
    
    return [
        ChatMessageResponse(
            id=m.id,
            sender_type=m.sender_type.value,
            message=m.message,
            created_at=m.created_at.isoformat(),
            sender_id=m.sender_id,
            attachments=[
                LiveChatAttachmentResponse(
                    id=a.id,
                    file_name=a.file_name,
                    file_url=a.file_url,
                    content_type=a.content_type,
                    file_size=a.file_size,
                    created_at=a.created_at.isoformat()
                ) for a in m.attachments
            ],
            context=m.context
        ) for m in messages
    ]

@router.post("/admin/session/{session_id}/end")
async def admin_end_session(
    session_id: str,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """(Agents Only) Formally end an active session"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    success = ticket_service.end_chat_session(
        session_id=session_id, 
        ended_by_agent=True, 
        agent_id=current_user.user.id
    )
    return {"success": success}
