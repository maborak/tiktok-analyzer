from fastapi import APIRouter, Depends, HTTPException, status, Body, File, UploadFile, Query
from typing import List, Optional
from pydantic import BaseModel, Field

from domain.entities.ticket_models import (
    TicketPriority, TicketStatus, TicketOrigin
)

router = APIRouter(tags=["User Tickets"])

# Dependency placeholder
ticket_service = None

# We use the existing auth dependency
from routes.auth import get_current_user_swagger_compatible as get_current_user
from domain.entities.auth_models import AuthContext

# --- Request & Response Models ---

class TicketCreateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200, description="Ticket subject")
    message: str = Field(..., min_length=10, max_length=5000, description="Initial message/description")
    category_id: Optional[str] = Field(None, description="ID of the ticket category")
    priority: TicketPriority = Field(default=TicketPriority.NORMAL, description="Priority level")

class TicketMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Reply message content")
    # Attachments would typically be handled via multipart/form-data rather than JSON

class TicketAttachmentResponse(BaseModel):
    id: str
    file_name: str
    file_url: str
    content_type: str
    file_size: int
    created_at: str

class CategoryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]

class TicketReopenRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=5000, description="Reason for reopening the ticket")

class TicketResponse(BaseModel):
    id: str
    subject: str
    status: str
    priority: str
    category_id: str
    category_name: Optional[str] = None
    reply_count: int = 0
    last_message_at: Optional[str] = None
    has_agent_reply: bool = False
    reopen_count: int = 0
    created_at: str
    updated_at: str

class PaginatedTicketResponse(BaseModel):
    items: List[TicketResponse]
    total: int
    page: int
    page_size: int

class TicketMessageResponse(BaseModel):
    id: str
    message: str
    created_at: str
    sender_id: Optional[int]
    is_agent: bool
    attachments: List[TicketAttachmentResponse] = []

# --- Endpoints ---

@router.get("/categories", response_model=List[CategoryResponse])
async def get_ticket_categories():
    """Get list of active ticket categories"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
    categories = ticket_service.get_categories(active_only=True)
    return [
        CategoryResponse(id=c.id, name=c.name, description=c.description)
        for c in categories
    ]

@router.post("", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(request: TicketCreateRequest, current_user: AuthContext = Depends(get_current_user)):
    """Create a new support ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    try:
        ticket = ticket_service.create_ticket(
            user_id=current_user.user.id,
            subject=request.subject,
            message=request.message,
            category_id=request.category_id,
            priority=request.priority,
            origin=TicketOrigin.WEB
        )
        return TicketResponse(
            id=ticket.id,
            subject=ticket.subject,
            status=ticket.status.value,
            priority=ticket.priority.value,
            category_id=ticket.category_id,
            created_at=ticket.created_at.isoformat(),
            updated_at=ticket.updated_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ticket: {str(e)}")

@router.get("", response_model=PaginatedTicketResponse)
async def get_user_tickets(
    ticket_status: Optional[TicketStatus] = Query(None, alias="status", description="Filter by ticket status"),
    search: Optional[str] = Query(None, min_length=1, max_length=200, description="Search tickets by subject"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(5, ge=1, le=100, description="Items per page"),
    current_user: AuthContext = Depends(get_current_user)
):
    """Get paginated tickets for the authenticated user"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")

    result = ticket_service.get_user_tickets(user_id=current_user.user.id, status=ticket_status, search=search, page=page, page_size=page_size)
    tickets = result["items"]

    # Bulk-fetch message summaries and categories for enrichment
    ticket_ids = [t.id for t in tickets]
    summaries = ticket_service.get_ticket_message_summaries(ticket_ids) if ticket_ids else {}
    categories = {c.id: c.name for c in ticket_service.get_categories(active_only=False)}

    return PaginatedTicketResponse(
        items=[
            TicketResponse(
                id=t.id,
                subject=t.subject,
                status=t.status.value,
                priority=t.priority.value,
                category_id=t.category_id,
                category_name=categories.get(t.category_id),
                reply_count=summaries.get(t.id, {}).get("reply_count", 0),
                last_message_at=summaries.get(t.id, {}).get("last_message_at", t.updated_at).isoformat() if summaries.get(t.id, {}).get("last_message_at") else None,
                has_agent_reply=summaries.get(t.id, {}).get("last_agent_message_at") is not None,
                reopen_count=t.reopen_count,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat()
            ) for t in tickets
        ],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"]
    )

@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: str, current_user: AuthContext = Depends(get_current_user)):
    """Get details of a specific ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    ticket = ticket_service.get_ticket_for_user(user_id=current_user.user.id, ticket_id=ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
        
    return TicketResponse(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status.value,
        priority=ticket.priority.value,
        category_id=ticket.category_id,
        reopen_count=ticket.reopen_count,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat()
    )

@router.post("/{ticket_id}/close", response_model=TicketResponse)
async def close_ticket(ticket_id: str, current_user: AuthContext = Depends(get_current_user)):
    """Close a ticket (client action)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
    try:
        ticket_service.close_ticket_by_user(user_id=current_user.user.id, ticket_id=ticket_id)
        ticket = ticket_service.get_ticket_for_user(user_id=current_user.user.id, ticket_id=ticket_id)
        return TicketResponse(
            id=ticket.id,
            subject=ticket.subject,
            status=ticket.status.value,
            priority=ticket.priority.value,
            category_id=ticket.category_id,
            reopen_count=ticket.reopen_count,
            created_at=ticket.created_at.isoformat(),
            updated_at=ticket.updated_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{ticket_id}/reopen", response_model=TicketResponse)
async def reopen_ticket(ticket_id: str, request: TicketReopenRequest, current_user: AuthContext = Depends(get_current_user)):
    """Reopen a resolved or closed ticket (client action, max 3 reopens)"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
    try:
        ticket_service.reopen_ticket_by_user(
            user_id=current_user.user.id,
            ticket_id=ticket_id,
            message=request.message
        )
        ticket = ticket_service.get_ticket_for_user(user_id=current_user.user.id, ticket_id=ticket_id)
        return TicketResponse(
            id=ticket.id,
            subject=ticket.subject,
            status=ticket.status.value,
            priority=ticket.priority.value,
            category_id=ticket.category_id,
            reopen_count=ticket.reopen_count,
            created_at=ticket.created_at.isoformat(),
            updated_at=ticket.updated_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{ticket_id}/messages", response_model=List[TicketMessageResponse])
async def get_ticket_messages(ticket_id: str, current_user: AuthContext = Depends(get_current_user)):
    """Get all messages for a specific ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    try:
        messages = ticket_service.get_ticket_messages_for_user(user_id=current_user.user.id, ticket_id=ticket_id)
        
        # Determine if message is from agent (if sender_id is different from user_id, 
        # or if it has a sender_email but no user_id, or if sender is considered an agent)
        # For simplicity from user perspective, anything not matching their ID is agent/system
        
        return [
            TicketMessageResponse(
                id=m.id,
                message=m.message,
                created_at=m.created_at.isoformat(),
                sender_id=m.sender_id,
                is_agent=(m.sender_id != current_user.user.id),
                attachments=[
                    TicketAttachmentResponse(
                        id=a.id,
                        file_name=a.file_name,
                        file_url=a.file_url,
                        content_type=a.content_type,
                        file_size=a.file_size,
                        created_at=a.created_at.isoformat()
                    ) for a in m.attachments
                ]
            ) for m in messages
        ]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{ticket_id}/messages", response_model=TicketMessageResponse)
async def add_ticket_message(ticket_id: str, request: TicketMessageRequest, current_user: AuthContext = Depends(get_current_user)):
    """Add a reply to a ticket"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    try:
        msg = ticket_service.add_message_from_user(
            user_id=current_user.user.id,
            ticket_id=ticket_id,
            message=request.message
            # attachments handling would go here via standard multipart form
        )
        return TicketMessageResponse(
            id=msg.id,
            message=msg.message,
            created_at=msg.created_at.isoformat(),
            sender_id=msg.sender_id,
            is_agent=False
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{ticket_id}/attachments", response_model=TicketAttachmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    ticket_id: str,
    message_id: str, # Attachments must link to a specific message ID that is being composed
    file: UploadFile = File(...),
    current_user: AuthContext = Depends(get_current_user)
):
    """Upload a file attachment for a specific ticket message"""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Ticket Service unavailable")
        
    try:
        # Read the file content into memory. Since we cap at 5MB, this is safe.
        file_content = await file.read()
        
        attachment = ticket_service.upload_ticket_attachment(
            ticket_id=ticket_id,
            message_id=message_id,
            uploader_id=current_user.user.id,
            file_name=file.filename,
            file_content=file_content
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
