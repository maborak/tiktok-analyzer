from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from typing import List, Optional
from pydantic import BaseModel, Field

from domain.entities.auth_models import AuthContext
from domain.entities.ticket_models import TicketPriority, TicketStatus
from utils.security.rbac import rbac

router = APIRouter(tags=["Admin Tickets"])

# Dependency placeholder
ticket_service = None

# --- Helper to load user data from auth service ---
def _get_auth_service():
    from utils.auth_provider import get_auth_service as _provider
    try:
        return _provider()
    except Exception:
        return None

# --- Request & Response Models ---

class CustomerProfile(BaseModel):
    """Embedded customer identity shown on every admin ticket view"""
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_verified: bool
    is_active: bool
    max_products: int
    created_at: Optional[str] = None

class AdminTicketResponse(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    category_id: str
    created_at: str
    updated_at: str
    user_id: Optional[int]
    assigned_agent_id: Optional[int]
    customer: Optional[CustomerProfile] = None

class PaginatedAdminTicketResponse(BaseModel):
    items: List[AdminTicketResponse]
    total: int
    page: int
    page_size: int

class AgentSummary(BaseModel):
    """Used to populate Assignment dropdowns in the UI"""
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str

class TicketAttachmentResponse(BaseModel):
    id: str
    file_name: str
    file_url: str
    content_type: str
    file_size: int
    created_at: str

class AdminTicketMessageResponse(BaseModel):
    id: str
    message: str
    created_at: str
    sender_id: Optional[int]
    is_internal_note: bool
    is_agent: bool = False
    attachments: List[TicketAttachmentResponse] = []

class AgentMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    is_internal_note: bool = False

class TicketStatusUpdateRequest(BaseModel):
    status: TicketStatus

class TicketPriorityUpdateRequest(BaseModel):
    priority: TicketPriority

class TicketAssignRequest(BaseModel):
    assigned_to: Optional[int]

class TagRequest(BaseModel):
    tag_id: str

class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = Field(None, max_length=200)
    is_active: bool = True

class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    description: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None

class CategoryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    is_active: bool

# --- Endpoints ---

def _build_customer_profile(user_id: Optional[int]) -> Optional[CustomerProfile]:
    """Load slim user profile to embed inside ticket responses"""
    if not user_id:
        return None
    try:
        auth_svc = _get_auth_service()
        if not auth_svc:
            return None
        user = auth_svc.user_management_port.get_user_by_id(user_id)
        if not user:
            return None
        return CustomerProfile(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_verified=user.is_verified,
            is_active=user.is_active,
            max_products=user.max_products,
            created_at=user.created_at.isoformat() if user.created_at else None
        )
    except Exception:
        return None

@router.get("/tickets", response_model=PaginatedAdminTicketResponse)
async def get_all_tickets(
    status: Optional[TicketStatus] = None,
    agent_id: Optional[int] = None,
    unassigned: bool = False,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: AuthContext = Depends(rbac.require_any_read_only(["admin:write", "support:read"]))
):
    """Get all tickets with optional filtering and pagination"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")

    result = ticket_service.get_all_tickets(status=status, agent_id=agent_id, unassigned=unassigned, page=page, page_size=page_size)
    return PaginatedAdminTicketResponse(
        items=[
            AdminTicketResponse(
                id=t.id,
                subject=t.subject,
                status=t.status.value,
                priority=t.priority.value,
                category_id=t.category_id,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat(),
                user_id=t.user_id,
                assigned_agent_id=t.assigned_agent_id,
                customer=_build_customer_profile(t.user_id)
            ) for t in result["items"]
        ],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"]
    )

@router.get("/tickets/{ticket_id}", response_model=AdminTicketResponse)
async def get_ticket(
    ticket_id: str,
    current_user: AuthContext = Depends(rbac.require_any_read_only(["admin:write", "support:read"]))
):
    """Get details of a specific ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    ticket = ticket_service.get_ticket_for_agent(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
        
    return AdminTicketResponse(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status.value,
        priority=ticket.priority.value,
        category_id=ticket.category_id,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat(),
        user_id=ticket.user_id,
        assigned_agent_id=ticket.assigned_agent_id,
        customer=_build_customer_profile(ticket.user_id)
    )

@router.get("/agents", response_model=List[AgentSummary])
async def get_assignable_agents(
    current_user: AuthContext = Depends(rbac.require_any_read_only(["admin:write", "support:read"]))
):
    """List all admin/support staff that can be assigned to tickets (for assignment dropdowns)"""
    try:
        auth_svc = _get_auth_service()
        if not auth_svc:
            raise HTTPException(status_code=503, detail="Auth service unavailable")
        # Filter to non-regular-user roles; page_size=100 is sufficient for staff lists
        result = auth_svc.user_management_port.list_users(
            page=1, page_size=100, is_active=True
        )
        agents = [
            AgentSummary(
                id=u.id,
                email=u.email,
                first_name=u.first_name,
                last_name=u.last_name,
                role=u.role.value if hasattr(u.role, 'value') else str(u.role)
            )
            for u in result.get("users", [])
            if str(getattr(u.role, 'value', u.role)).lower() not in ("user",)
        ]
        return agents
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tickets/{ticket_id}/messages", response_model=List[AdminTicketMessageResponse])
async def get_ticket_messages(
    ticket_id: str,
    current_user: AuthContext = Depends(rbac.require_any_read_only(["admin:write", "support:read"]))
):
    """Get all messages for a specific ticket (including internal notes)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    ticket = ticket_service.get_ticket_for_agent(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
        
    messages = ticket_service.get_ticket_messages_for_agent(ticket_id)
    ticket_user_id = ticket.user_id
    
    return [
        AdminTicketMessageResponse(
            id=m.id,
            message=m.message,
            created_at=m.created_at.isoformat(),
            sender_id=m.sender_id,
            is_internal_note=m.is_internal_note,
            is_agent=m.is_internal_note or (m.sender_id != ticket_user_id),
            attachments=[
                TicketAttachmentResponse(
                    id=a.id,
                    file_name=a.file_name,
                    file_url=a.file_url,
                    content_type=a.content_type,
                    file_size=a.file_size,
                    created_at=a.created_at.isoformat()
                ) for a in (m.attachments or [])
            ]
        ) for m in messages
    ]

@router.post("/tickets/{ticket_id}/messages", response_model=AdminTicketMessageResponse, status_code=status.HTTP_201_CREATED)
async def add_ticket_message(
    ticket_id: str,
    request: AgentMessageRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Add a reply or internal note to a ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    try:
        msg = ticket_service.add_message_from_agent(
            agent_id=current_user.user.id,
            ticket_id=ticket_id,
            message=request.message,
            is_internal_note=request.is_internal_note
        )
        return AdminTicketMessageResponse(
            id=msg.id,
            message=msg.message,
            created_at=msg.created_at.isoformat(),
            sender_id=msg.sender_id,
            is_internal_note=msg.is_internal_note
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/tickets/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: str,
    request: TicketStatusUpdateRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Update ticket status"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    success = ticket_service.update_ticket_status(agent_id=current_user.user.id, ticket_id=ticket_id, status=request.status)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update status")
    return {"success": True}

@router.patch("/tickets/{ticket_id}/priority")
async def update_ticket_priority(
    ticket_id: str,
    request: TicketPriorityUpdateRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Update ticket priority"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    success = ticket_service.update_ticket_priority(agent_id=current_user.user.id, ticket_id=ticket_id, priority=request.priority)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update priority")
    return {"success": True}

@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: str,
    request: TicketAssignRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Assign ticket to an agent (or unassign if assigned_to is 0 or None)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
    
    # Convert 0 to None for unassignment (NULL in database)
    assigned_to = request.assigned_to if request.assigned_to and request.assigned_to > 0 else None
        
    success = ticket_service.assign_ticket(agent_id=current_user.user.id, ticket_id=ticket_id, assigned_to=assigned_to)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to assign ticket")
    return {"success": True}

@router.post("/tickets/{ticket_id}/tags")
async def add_ticket_tag(
    ticket_id: str,
    request: TagRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Add a tag to a ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")

    try:
        success = ticket_service.add_ticket_tag(ticket_id=ticket_id, tag_id=request.tag_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to add tag")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid tag or ticket: {str(e)}")

@router.delete("/tickets/{ticket_id}/tags/{tag_id}")
async def remove_ticket_tag(
    ticket_id: str,
    tag_id: str,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Remove a tag from a ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    success = ticket_service.remove_ticket_tag(ticket_id=ticket_id, tag_id=tag_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to remove tag")
    return {"success": True}

@router.get("/categories", response_model=List[CategoryResponse])
async def get_categories(
    active_only: bool = False,
    current_user: AuthContext = Depends(rbac.require_any_read_only(["admin:write", "support:read"]))
):
    """Get all categories"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    categories = ticket_service.get_categories(active_only=active_only)
    return [
        CategoryResponse(
            id=c.id,
            name=c.name,
            description=c.description,
            is_active=c.is_active
        ) for c in categories
    ]

@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    request: CategoryCreateRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write"]))
):
    """Create a new ticket category"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    category_id = ticket_service.create_category(
        name=request.name,
        description=request.description,
        is_active=request.is_active
    )
    
    return CategoryResponse(
        id=category_id,
        name=request.name,
        description=request.description,
        is_active=request.is_active
    )

@router.patch("/categories/{category_id}")
async def update_category(
    category_id: str,
    request: CategoryUpdateRequest,
    current_user: AuthContext = Depends(rbac.require_any(["admin:write"]))
):
    """Update a ticket category"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    success = ticket_service.update_category(
        category_id=category_id,
        name=request.name,
        description=request.description,
        is_active=request.is_active
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update category")
    return {"success": True}


@router.post("/tickets/{ticket_id}/attachments", response_model=TicketAttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_admin_attachment(
    ticket_id: str,
    message_id: str,
    file: UploadFile = File(...),
    current_user: AuthContext = Depends(rbac.require_any(["admin:write", "support:write"]))
):
    """Upload a file attachment to a ticket on behalf of an agent"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")

    try:
        file_content = await file.read()
        attachment = ticket_service.upload_ticket_attachment(
            ticket_id=ticket_id,
            message_id=message_id,
            uploader_id=current_user.user.id,
            file_name=file.filename,
            file_content=file_content,
            is_admin=True
        )
        return TicketAttachmentResponse(
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
