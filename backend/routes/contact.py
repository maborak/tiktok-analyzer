"""
Public "Contact Us" endpoint — no authentication required.
Allows guests (non-registered visitors) to submit a support request.

CAPTCHA support: reuses the same `validate_captcha` utility as the auth routes.
Controlled by PHOVEU_BACKEND_CAPTCHA_TYPE (none / recaptcha_v3 / turnstile).
"""

from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, Field, EmailStr
from typing import Optional

from utils.security.captcha import validate_captcha
from utils.request import get_request_metadata

router = APIRouter(tags=["Contact"])

# Dependency placeholder (set by main.py)
ticket_service = None


# --- Request / Response Models ---

class ContactFormRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Your name")
    email: EmailStr = Field(..., description="Your email address so we can reply")
    subject: str = Field(..., min_length=3, max_length=200, description="Brief subject")
    message: str = Field(..., min_length=10, max_length=5000, description="Your message")
    category_id: Optional[str] = Field(None, description="Optional category UUID (from GET /tickets/categories)")
    captcha_token: Optional[str] = Field(None, description="CAPTCHA token (required when CAPTCHA is enabled)")
    # Simple bot trap — a legit browser leaves this empty
    honeypot: Optional[str] = Field(None, alias="_hp", description="Leave this empty")

    model_config = {"populate_by_name": True}


class ContactFormResponse(BaseModel):
    ticket_id: str
    message: str


# --- Endpoint ---

@router.post("", response_model=ContactFormResponse, status_code=status.HTTP_201_CREATED)
async def submit_contact_form(
    request: Request,
    body: ContactFormRequest,
):
    """
    Submit a public 'Contact Us' form. No authentication required.
    Creates a support ticket visible to agents in the admin queue.

    CAPTCHA behaviour (controlled by `PHOVEU_BACKEND_CAPTCHA_TYPE`):
    - `none` (default): no CAPTCHA, suitable for local/dev
    - `recaptcha_v3`: Google reCAPTCHA v3 invisible (score-based)
    - `turnstile`: Cloudflare Turnstile
    """
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Support service unavailable")

    # Bot protection: reject if honeypot field is filled
    if body.honeypot:
        # Return a fake 201 to confuse bots — don't reveal the rejection
        return ContactFormResponse(
            ticket_id="00000000-0000-0000-0000-000000000000",
            message="Thank you! Your message has been received."
        )

    # CAPTCHA verification
    remote_ip, _ = get_request_metadata(request)
    captcha_token = body.captcha_token or ""
    captcha_valid, error_message = await validate_captcha(captcha_token, remote_ip)
    if not captcha_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message or "CAPTCHA validation failed. Please complete the CAPTCHA challenge."
        )

    try:
        ticket = ticket_service.create_guest_ticket(
            name=body.name,
            sender_email=body.email,
            subject=body.subject,
            message=body.message,
            category_id=body.category_id,
        )
        return ContactFormResponse(
            ticket_id=ticket.id,
            message="Thank you! Your message has been received. We'll get back to you at the email you provided."
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class TicketGuestResponse(BaseModel):
    id: str
    subject: str
    status: str
    created_at: str
    updated_at: str


class TicketAttachmentResponse(BaseModel):
    id: str
    file_name: str
    file_url: str
    content_type: str
    file_size: int
    created_at: str


class TicketMessageGuestResponse(BaseModel):
    id: str
    message: str
    created_at: str
    is_agent: bool
    attachments: list[TicketAttachmentResponse] = []


@router.get("/{ticket_id}", response_model=TicketGuestResponse)
async def get_guest_ticket(ticket_id: str, token: str):
    """View a guest ticket status using a secure token."""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Support service unavailable")

    ticket = ticket_service.get_ticket_by_token(ticket_id, token)
    if not ticket:
        raise HTTPException(status_code=403, detail="Invalid ticket ID or access token")

    return TicketGuestResponse(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status.value,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat()
    )


@router.get("/{ticket_id}/messages", response_model=list[TicketMessageGuestResponse])
async def get_guest_ticket_messages(ticket_id: str, token: str):
    """View conversation history for a guest ticket."""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Support service unavailable")

    ticket = ticket_service.get_ticket_by_token(ticket_id, token)
    if not ticket:
        raise HTTPException(status_code=403, detail="Invalid ticket ID or access token")

    messages = ticket_service.get_ticket_messages(ticket_id)
    return [
        TicketMessageGuestResponse(
            id=m.id,
            message=m.message,
            created_at=m.created_at.isoformat(),
            is_agent=(m.sender_email != ticket.sender_email),
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


class GuestReplyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Your reply message")


class GuestReplyResponse(BaseModel):
    id: str
    message: str
    created_at: str


@router.post("/{ticket_id}/messages", response_model=GuestReplyResponse, status_code=status.HTTP_201_CREATED)
async def add_guest_ticket_message(ticket_id: str, token: str, body: GuestReplyRequest):
    """Add a reply to a guest ticket using the secure access token."""
    if not ticket_service:
        raise HTTPException(status_code=503, detail="Support service unavailable")

    # Verify ticket and token
    ticket = ticket_service.get_ticket_by_token(ticket_id, token)
    if not ticket:
        raise HTTPException(status_code=403, detail="Invalid ticket ID or access token")

    try:
        # Add message as guest reply
        msg = ticket_service.add_message_from_guest(
            ticket_id=ticket_id,
            sender_email=ticket.sender_email,
            message=body.message
        )
        
        return GuestReplyResponse(
            id=msg.id,
            message=msg.message,
            created_at=msg.created_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add message: {str(e)}")
