from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import logging
import re

from domain.entities.ticket_models import (
    Ticket, TicketMessage, TicketCategoryDef, TicketInboundConfig,
    TicketStatus, TicketPriority, TicketOrigin, TicketTag, TicketAttachment,
    LiveChatSession, LiveChatMessage, LiveChatStatus, LiveChatSenderType,
    LiveChatAttachment
)
from ports.data_persistence import DataPersistencePort
from ports.hooks import HookManager, HookEvent, HookEventType
from utils.path import resolve_storage_path
from config import CONFIG, settings
import os
import shutil

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a user-supplied filename to prevent path traversal and special char attacks.
    Strips directory components, removes dangerous characters, and enforces extension allowlist.
    """
    # Strip any directory components (handles both / and \ separators)
    filename = os.path.basename(filename)
    # Remove null bytes
    filename = filename.replace('\x00', '')
    # Keep only alphanumeric, hyphens, underscores, dots, and spaces
    filename = re.sub(r'[^\w\-. ]', '', filename)
    # Replace spaces with underscores
    filename = filename.replace(' ', '_')
    # Collapse multiple dots/underscores
    filename = re.sub(r'\.{2,}', '.', filename)
    filename = re.sub(r'_{2,}', '_', filename)
    # Strip leading/trailing dots and spaces
    filename = filename.strip('. ')
    # Fallback if filename is empty after sanitization
    if not filename or '.' not in filename:
        raise ValueError("Invalid filename after sanitization.")
    return filename


def validate_file_content(file_bytes: bytes, filename: str) -> str:
    """
    Validates file content using magic numbers to prevent extension spoofing.
    Allows only JPEG, PNG, and PDF files.
    Returns the detected content type.
    """
    if len(file_bytes) < 4:
        raise ValueError("File is too small or empty.")

    # Magic numbers
    JPEG_MAGIC = b'\xff\xd8\xff'
    PNG_MAGIC = b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a'
    PDF_MAGIC = b'%PDF-'

    ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''

    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Extension '.{ext}' is not allowed. Only JPEG, PNG, and PDF are accepted.")

    if file_bytes.startswith(JPEG_MAGIC):
        if ext not in ['jpg', 'jpeg']:
            raise ValueError(f"Content is JPEG but extension is .{ext}")
        return "image/jpeg"
    elif file_bytes.startswith(PNG_MAGIC):
        if ext != 'png':
            raise ValueError(f"Content is PNG but extension is .{ext}")
        return "image/png"
    elif file_bytes.startswith(PDF_MAGIC):
        if ext != 'pdf':
            raise ValueError(f"Content is PDF but extension is .{ext}")
        return "application/pdf"
    else:
        raise ValueError("Unsupported file type. Only JPEG, PNG, and PDF are allowed.")

class TicketService:
    def __init__(self, data_port: DataPersistencePort, hook_manager: HookManager):
        self.data_port = data_port
        self.hook_manager = hook_manager
        self._ensure_default_category()
        
    def _ensure_default_category(self):
        """Ensure the 'General' category exists upon initialization"""
        try:
            categories = self.data_port.get_ticket_categories(active_only=False)
            has_general = any(c.name.lower() == "general" for c in categories)
            
            if not has_general:
                default_category = TicketCategoryDef(
                    id=str(uuid.uuid4()),
                    name="General",
                    description="Default category for general inquiries",
                    is_active=True
                )
                self.data_port.create_ticket_category(default_category)
                logger.info("Created default 'General' ticket category.")
        except Exception as e:
            # Concurrency protection: if another worker created it, we can safely continue
            logger.debug(f"Default category initialization note: {e}")

    def _get_general_category(self) -> TicketCategoryDef:
        categories = self.data_port.get_ticket_categories(active_only=True)
        for c in categories:
            if c.name.lower() == "general":
                return c
        return categories[0] if categories else None

    # --- User Flow ---

    def create_ticket(self, user_id: int, subject: str, message: str, category_id: Optional[str] = None, priority: TicketPriority = TicketPriority.NORMAL, origin: TicketOrigin = TicketOrigin.WEB) -> Ticket:
        """Create a new ticket for an authenticated user"""
        
        if not category_id:
            general_cat = self._get_general_category()
            if not general_cat:
                raise ValueError("No active ticket categories available.")
            category_id = general_cat.id
        else:
            categories = self.get_categories(active_only=False)
            if not any(c.id == category_id for c in categories):
                raise ValueError("Invalid category ID provided.")

        ticket_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        ticket = Ticket(
            id=ticket_id,
            subject=subject,
            status=TicketStatus.OPEN,
            priority=priority,
            category_id=category_id,
            origin=origin,
            created_at=now,
            updated_at=now,
            user_id=user_id
        )

        initial_message = TicketMessage(
            id=message_id,
            ticket_id=ticket_id,
            message=message,
            created_at=now,
            sender_id=user_id,
            is_internal_note=False
        )

        self.data_port.create_ticket(ticket, initial_message)
        
        # Fire Domain Event
        self.hook_manager.fire(HookEvent(
            event_type=HookEventType.TICKET_CREATED,
            data={
                "ticket_id": ticket.id,
                "user_id": ticket.user_id,
                "subject": ticket.subject
            },
            source="ticket_service"
        ))
        
        return ticket

    def create_guest_ticket(self, name: str, sender_email: str, subject: str, message: str, category_id: Optional[str] = None) -> Ticket:
        """Create a ticket from a non-authenticated 'Contact Us' form submission."""
        if not category_id:
            general_cat = self._get_general_category()
            if not general_cat:
                raise ValueError("No active ticket categories available.")
            category_id = general_cat.id
        else:
            categories = self.get_categories(active_only=False)
            if not any(c.id == category_id for c in categories):
                raise ValueError("Invalid category ID provided.")

        now = datetime.now(timezone.utc)
        ticket_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        # Secure token for guest access (non-predictable)
        guest_token = str(uuid.uuid4()).replace("-", "")

        ticket = Ticket(
            id=ticket_id,
            subject=subject,
            status=TicketStatus.OPEN,
            priority=TicketPriority.NORMAL,
            category_id=category_id,
            origin=TicketOrigin.CONTACT_FORM,
            created_at=now,
            updated_at=now,
            sender_email=sender_email,
            guest_access_token=guest_token,
        )

        initial_message = TicketMessage(
            id=message_id,
            ticket_id=ticket_id,
            message=f"[Contact Form] From: {name} <{sender_email}>\n\n{message}",
            created_at=now,
            sender_email=sender_email,
            is_internal_note=False,
        )

        self.data_port.create_ticket(ticket, initial_message)

        self.hook_manager.fire(HookEvent(
            event_type=HookEventType.TICKET_CREATED,
            data={
                "ticket_id": ticket.id,
                "sender_email": sender_email,
                "recipient": sender_email,
                "subject": ticket.subject,
                "status": "OPEN",
                "message": message,
                "action": "created via contact form",
                "mail_from": CONFIG.get("SUPPORT_INBOUND_EMAIL"),
                "mail_from_name": CONFIG.get("SUPPORT_OUTBOUND_SENDER_NAME"),
                "guest_access_token": guest_token
            },
            source="ticket_service"
        ))

        return ticket

    def get_ticket_messages(self, ticket_id: str) -> List[TicketMessage]:
        return self.data_port.get_ticket_messages(ticket_id)

    def get_ticket_by_token(self, ticket_id: str, token: str) -> Optional[Ticket]:
        """Retrieve a ticket by ID and verify the guest access token."""
        ticket = self.get_ticket_for_agent(ticket_id)
        if not ticket or ticket.guest_access_token != token:
            logger.warning(f"Unauthorized guest access attempt for ticket {ticket_id}")
            return None
        return ticket

    def get_user_tickets(self, user_id: int, status=None, search: Optional[str] = None, page: int = 1, page_size: int = 20) -> dict:
        return self.data_port.get_user_tickets(str(user_id), status=status, search=search, page=page, page_size=page_size)

    def migrate_guest_tickets(self, email: str, user_id: int) -> int:
        """Migrate all guest tickets for an email to a registered user account."""
        count = self.data_port.migrate_guest_tickets(email, user_id)
        if count > 0:
            logger.info(f"Successfully migrated {count} tickets for {email} to user ID {user_id}")
        return count

    def get_ticket_for_user(self, user_id: int, ticket_id: str) -> Optional[Ticket]:
        ticket = self.data_port.get_ticket(ticket_id)
        if ticket and ticket.user_id == user_id:
            return ticket
        return None

    def add_message_from_user(self, user_id: int, ticket_id: str, message: str, attachments: List[TicketAttachment] = None) -> TicketMessage:
        ticket = self.get_ticket_for_user(user_id, ticket_id)
        if not ticket:
            raise ValueError("Ticket not found or unauthorized.")

        msg = TicketMessage(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            message=message,
            created_at=datetime.now(timezone.utc),
            sender_id=user_id,
            is_internal_note=False,
            attachments=attachments or []
        )
        
        self.data_port.add_ticket_message(msg)
        
        reopened = False
        if ticket.status == TicketStatus.PENDING_CUSTOMER:
            self.data_port.update_ticket_status(ticket_id, TicketStatus.OPEN)
        elif ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            # Auto-reopen on reply if under the reopen cap
            if ticket.reopen_count < 3:
                self.data_port.reopen_ticket(ticket_id)
                reopened = True

        # Fire event WITHOUT recipient - user initiated this action, no need to email them
        self.hook_manager.fire(HookEvent(
            event_type=HookEventType.TICKET_UPDATED,
            data={
                "ticket_id": ticket.id,
                "user_id": ticket.user_id,
                "action": "reply added by user (reopened)" if reopened else "reply added by user",
                "message": message,
                "status": ticket.status.value
                # No recipient - don't email the user who just sent the message
            },
            source="ticket_service"
        ))

        return msg

    def add_message_from_guest(self, ticket_id: str, sender_email: str, message: str, attachments: List[TicketAttachment] = None) -> TicketMessage:
        """Add a message to a ticket from a guest user (via token access)."""
        ticket = self.data_port.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket not found.")
        
        # Verify the sender email matches the ticket's guest email
        if ticket.sender_email != sender_email:
            raise ValueError("Sender email does not match ticket.")

        msg = TicketMessage(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            message=message,
            created_at=datetime.now(timezone.utc),
            sender_email=sender_email,
            is_internal_note=False,
            attachments=attachments or []
        )
        
        self.data_port.add_ticket_message(msg)
        
        # Update status if waiting for customer
        if ticket.status == TicketStatus.PENDING_CUSTOMER:
            self.data_port.update_ticket_status(ticket_id, TicketStatus.OPEN)
            
        # Fire event WITHOUT recipient - guest initiated this action, no need to email them
        self.hook_manager.fire(HookEvent(
            event_type=HookEventType.TICKET_UPDATED,
            data={
                "ticket_id": ticket.id,
                "sender_email": sender_email,
                "subject": ticket.subject,
                "status": ticket.status.value,
                "message": message,
                "action": "reply added by guest"
                # No recipient - don't email the guest who just sent the message
            },
            source="ticket_service"
        ))
        
        return msg

    def get_ticket_messages_for_user(self, user_id: int, ticket_id: str) -> List[TicketMessage]:
        ticket = self.get_ticket_for_user(user_id, ticket_id)
        if not ticket:
            raise ValueError("Ticket not found or unauthorized.")
        
        messages = self.data_port.get_ticket_messages(ticket_id)
        # Filter out internal notes for users
        return [m for m in messages if not m.is_internal_note]

    def upload_ticket_attachment(self, ticket_id: str, message_id: str, uploader_id: int, file_name: str, file_content: bytes, *, is_admin: bool = False) -> TicketAttachment:
        ticket = self.data_port.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket not found.")

        # Verify uploader owns the ticket (unless admin/agent)
        if not is_admin and ticket.user_id != uploader_id:
            raise ValueError("Ticket not found or unauthorized.")

        if len(file_content) > MAX_FILE_SIZE_BYTES:
            raise ValueError("File exceeds the 5MB size limit.")
            
        sanitized_name = sanitize_filename(file_name)
        content_type = validate_file_content(file_content, sanitized_name)

        storage_dir = resolve_storage_path(settings("TICKET_UPLOAD_STORAGE_PATH", "data/uploads/tickets"))
        storage_dir.mkdir(parents=True, exist_ok=True)

        attachment_id = str(uuid.uuid4())
        safe_name = f"{attachment_id}_{sanitized_name}"
        file_path = (storage_dir / safe_name).resolve()

        # Verify resolved path is inside storage directory
        if not str(file_path).startswith(str(storage_dir.resolve())):
            raise ValueError("Invalid file path — path traversal detected.")

        with open(file_path, "wb") as f:
            f.write(file_content)

        file_url = f"/media/tickets/{safe_name}"

        attachment = TicketAttachment(
            id=attachment_id,
            ticket_id=ticket_id,
            message_id=message_id,
            file_name=file_name,
            file_url=file_url,
            content_type=content_type,
            file_size=len(file_content),
            created_at=datetime.now(timezone.utc)
        )

        self.data_port.add_ticket_attachment(attachment)
        return attachment

    # --- Agent/Admin Flow ---

    def get_all_tickets(self, status: Optional[TicketStatus] = None, agent_id: Optional[int] = None, unassigned: bool = False, page: int = 1, page_size: int = 20) -> dict:
        return self.data_port.get_all_tickets(status=status, agent_id=agent_id, unassigned=unassigned, page=page, page_size=page_size)
        
    def get_ticket_for_agent(self, ticket_id: str) -> Optional[Ticket]:
        return self.data_port.get_ticket(ticket_id)

    def get_ticket_messages_for_agent(self, ticket_id: str) -> List[TicketMessage]:
        return self.data_port.get_ticket_messages(ticket_id)

    def add_message_from_agent(self, agent_id: int, ticket_id: str, message: str, is_internal_note: bool = False, attachments: List[TicketAttachment] = None) -> TicketMessage:
        ticket = self.data_port.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket not found.")
            
        msg = TicketMessage(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            message=message,
            created_at=datetime.now(timezone.utc),
            sender_id=agent_id,
            is_internal_note=is_internal_note,
            attachments=attachments or []
        )
        
        self.data_port.add_ticket_message(msg)
        
        if not is_internal_note and ticket.status in [TicketStatus.OPEN, TicketStatus.IN_PROGRESS]:
            self.data_port.update_ticket_status(ticket_id, TicketStatus.PENDING_CUSTOMER)
            
        self.hook_manager.fire(HookEvent(
            event_type=HookEventType.TICKET_UPDATED,
            data={
                "ticket_id": ticket.id,
                "agent_id": agent_id,
                "recipient": ticket.sender_email,
                "subject": ticket.subject,
                "status": ticket.status.value,
                "message": message,
                "is_internal_note": is_internal_note,
                "action": "reply added by agent",
                "mail_from": CONFIG.get("SUPPORT_INBOUND_EMAIL"),
                "mail_from_name": CONFIG.get("SUPPORT_OUTBOUND_SENDER_NAME")
            },
            source="ticket_service"
        ))
            
        return msg

    def update_ticket_status(self, agent_id: int, ticket_id: str, status: TicketStatus) -> bool:
        success = self.data_port.update_ticket_status(ticket_id, status)
        if success:
            ticket = self.data_port.get_ticket(ticket_id)
            self.hook_manager.fire(HookEvent(
                event_type=HookEventType.TICKET_UPDATED,
                data={
                    "ticket_id": ticket_id,
                    "agent_id": agent_id,
                    "recipient": ticket.sender_email if ticket else None,
                    "subject": ticket.subject if ticket else None,
                    "new_status": status.value,
                    "action": f"status changed to {status.value}",
                    "mail_from": CONFIG.get("SUPPORT_INBOUND_EMAIL"),
                    "mail_from_name": CONFIG.get("SUPPORT_OUTBOUND_SENDER_NAME")
                },
                source="ticket_service"
            ))
        return success

    def update_ticket_priority(self, agent_id: int, ticket_id: str, priority: TicketPriority) -> bool:
        success = self.data_port.update_ticket_priority(ticket_id, priority)
        if success:
            self.hook_manager.fire(HookEvent(
                event_type=HookEventType.TICKET_UPDATED,
                data={
                    "ticket_id": ticket_id,
                    "agent_id": agent_id,
                    "new_priority": priority.value,
                    "action": "priority changed"
                },
                source="ticket_service"
            ))
        return success

    def assign_ticket(self, agent_id: int, ticket_id: str, assigned_to: Optional[int]) -> bool:
        success = self.data_port.assign_ticket(ticket_id, assigned_to)
        if success:
            self.hook_manager.fire(HookEvent(
                event_type=HookEventType.TICKET_UPDATED,
                data={
                    "ticket_id": ticket_id,
                    "assigned_by": agent_id,
                    "assigned_to": assigned_to,
                    "action": "ticket assigned"
                },
                source="ticket_service"
            ))
        return success
        
    def add_ticket_tag(self, ticket_id: str, tag_id: str) -> bool:
        return self.data_port.add_ticket_tag(ticket_id, tag_id)
        
    def remove_ticket_tag(self, ticket_id: str, tag_id: str) -> bool:
        return self.data_port.remove_ticket_tag(ticket_id, tag_id)

    def get_ticket_message_summaries(self, ticket_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get message summaries (reply count, timestamps, agent reply flag) for a batch of tickets."""
        if not ticket_ids:
            return {}
        return self.data_port.get_ticket_message_summaries(ticket_ids)

    def close_ticket_by_user(self, user_id: int, ticket_id: str) -> bool:
        """Allow a client to close their own ticket."""
        ticket = self.get_ticket_for_user(user_id, ticket_id)
        if not ticket:
            raise ValueError("Ticket not found or unauthorized.")
        if ticket.status == TicketStatus.CLOSED:
            raise ValueError("Ticket is already closed.")

        success = self.data_port.update_ticket_status(ticket_id, TicketStatus.CLOSED)
        if success:
            self.hook_manager.fire(HookEvent(
                event_type=HookEventType.TICKET_UPDATED,
                data={
                    "ticket_id": ticket_id,
                    "user_id": user_id,
                    "action": "closed by user",
                    "new_status": TicketStatus.CLOSED.value,
                },
                source="ticket_service"
            ))
        return success

    def reopen_ticket_by_user(self, user_id: int, ticket_id: str, message: str) -> TicketMessage:
        """Allow a client to reopen a RESOLVED or CLOSED ticket with a mandatory comment."""
        ticket = self.get_ticket_for_user(user_id, ticket_id)
        if not ticket:
            raise ValueError("Ticket not found or unauthorized.")
        if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
            raise ValueError("Only resolved or closed tickets can be reopened.")
        if ticket.reopen_count >= 3:
            raise ValueError("This ticket has reached the maximum number of reopens (3). Please create a new ticket.")

        self.data_port.reopen_ticket(ticket_id)

        msg = TicketMessage(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            message=message,
            created_at=datetime.now(timezone.utc),
            sender_id=user_id,
            is_internal_note=False
        )
        self.data_port.add_ticket_message(msg)

        self.hook_manager.fire(HookEvent(
            event_type=HookEventType.TICKET_UPDATED,
            data={
                "ticket_id": ticket_id,
                "user_id": user_id,
                "action": "reopened by user",
                "new_status": TicketStatus.OPEN.value,
                "message": message,
            },
            source="ticket_service"
        ))

        return msg

    def get_categories(self, active_only: bool = True) -> List[TicketCategoryDef]:
        return self.data_port.get_ticket_categories(active_only)

    def create_category(self, name: str, description: str, is_active: bool = True, category_id: Optional[str] = None) -> str:
        cat = TicketCategoryDef(
            id=category_id or str(uuid.uuid4()),
            name=name,
            description=description,
            is_active=is_active
        )
        return self.data_port.create_ticket_category(cat)

    def update_category(self, category_id: str, name: Optional[str] = None, description: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
        return self.data_port.update_ticket_category(category_id, name, description, is_active)

    # --- System Flow (Email Webhooks) ---

    def process_inbound_email(self, sender_email: str, subject: str, body: str, raw_data: dict) -> TicketMessage:
        """Process an inbound email, either creating a new ticket or appending to an existing one."""
        logger.debug("process_inbound_email called with sender_email=%s, subject=%s", sender_email, subject)
        logger.debug("raw_data = %s", raw_data)
        
        # Check if email is a reply to an existing ticket (e.g. by parsing subject line or headers)
        import re
        ticket_id_match = re.search(r"\[Ticket\s#([a-f0-9\-]{36})\]", subject, re.IGNORECASE)
        
        ticket = None
        if ticket_id_match:
            ticket_id = ticket_id_match.group(1)
            ticket = self.data_port.get_ticket(ticket_id)
            logger.debug("Found existing ticket %s", ticket_id)
        else:
            logger.debug("No existing ticket found, will create new ticket")
            
        now = datetime.now(timezone.utc)
        if ticket:
            # It's a reply
            msg = TicketMessage(
                id=str(uuid.uuid4()),
                ticket_id=ticket.id,
                message=body,
                created_at=now,
                sender_email=sender_email,
                is_internal_note=False
            )
            self.data_port.add_ticket_message(msg)
            
            # Save Attachments
            attachments_data = raw_data.get("attachments", [])
            for att in attachments_data:
                self._save_email_attachment(ticket.id, msg.id, att)
            
            if ticket.status == TicketStatus.PENDING_CUSTOMER:
                self.data_port.update_ticket_status(ticket.id, TicketStatus.OPEN)
                
            logger.debug("Firing TICKET_UPDATED event for email reply (no recipient - sender already knows)")
            # Fire event WITHOUT recipient - sender just emailed us, no need to email them back
            self.hook_manager.fire(HookEvent(
                event_type=HookEventType.TICKET_UPDATED,
                data={
                    "ticket_id": ticket.id,
                    "sender_email": sender_email,
                    "subject": subject,
                    "status": ticket.status.value,
                    "message": body,
                    "action": "reply added via email",
                    "guest_access_token": ticket.guest_access_token
                    # No recipient - don't email the person who just sent us an email
                },
                source="ticket_service"
            ))
            return msg
        else:
            # It's a new ticket
            # Check inbound configs for default category based on target address
            target_email = raw_data.get("to")
            category_id = None
            if target_email:
                config = self.data_port.get_inbound_config(target_email)
                if config:
                    category_id = config.default_category_id
                    
            if not category_id:
                general_cat = self._get_general_category()
                if general_cat:
                    category_id = general_cat.id
            
            # Simple identity matching based on email is handled upstream or user_id remains None
            # For this service, if we only have email, user_id is None.
            # In actual implementation, we might lookup user by email.
            
            # Note: We do not pass user_id here as we only definitely know sender_email.
            # Identity mapping should be done in the adapter/route before calling this, 
            # modifying this to accept optional user_id if we want.
            
            ticket_id = str(uuid.uuid4())
            # Generate guest token for email-based tickets (non-authenticated users)
            guest_token = str(uuid.uuid4()).replace("-", "")
            new_ticket = Ticket(
                id=ticket_id,
                subject=subject,
                status=TicketStatus.OPEN,
                priority=TicketPriority.NORMAL,
                category_id=category_id,
                origin=TicketOrigin.EMAIL,
                created_at=now,
                updated_at=now,
                sender_email=sender_email,
                guest_access_token=guest_token
            )
            
            initial_message = TicketMessage(
                id=str(uuid.uuid4()),
                ticket_id=ticket_id,
                message=body,
                created_at=now,
                sender_email=sender_email,
                is_internal_note=False
            )
            
            self.data_port.create_ticket(new_ticket, initial_message)
            
            # Save Attachments
            attachments_data = raw_data.get("attachments", [])
            for att in attachments_data:
                self._save_email_attachment(ticket_id, initial_message.id, att)
            
            logger.debug("Firing TICKET_CREATED event with recipient=%s", sender_email)
            self.hook_manager.fire(HookEvent(
                event_type=HookEventType.TICKET_CREATED,
                data={
                    "ticket_id": new_ticket.id,
                    "sender_email": sender_email,
                    "recipient": sender_email,
                    "subject": new_ticket.subject,
                    "status": "OPEN",
                    "message": body,
                    "action": "created",
                    "mail_from": CONFIG.get("SUPPORT_INBOUND_EMAIL"),
                    "mail_from_name": CONFIG.get("SUPPORT_OUTBOUND_SENDER_NAME"),
                    "guest_access_token": guest_token
                },
                source="ticket_service"
            ))
            return initial_message

    def _save_email_attachment(self, ticket_id: str, message_id: str, att_data: dict):
        """Helper to save safely extracted IMAP attachments to disk and tie to a TicketMessage."""
        try:
            file_name = att_data["filename"]
            file_content = att_data["content"]
            content_type = att_data["content_type"]

            if len(file_content) > MAX_FILE_SIZE_BYTES:
                return

            try:
                sanitized_name = sanitize_filename(file_name)
            except ValueError:
                logger.warning(f"Skipping email attachment with invalid filename: {file_name!r}")
                return

            storage_dir = resolve_storage_path(settings("TICKET_UPLOAD_STORAGE_PATH", "data/uploads/tickets"))
            storage_dir.mkdir(parents=True, exist_ok=True)

            attachment_id = str(uuid.uuid4())
            safe_name = f"{attachment_id}_{sanitized_name}"
            file_path = (storage_dir / safe_name).resolve()

            if not str(file_path).startswith(str(storage_dir.resolve())):
                logger.warning(f"Path traversal detected in email attachment: {file_name!r}")
                return

            with open(file_path, "wb") as f:
                f.write(file_content)

            file_url = f"/media/tickets/{safe_name}"

            attachment = TicketAttachment(
                id=attachment_id,
                ticket_id=ticket_id,
                message_id=message_id,
                file_name=file_name,
                file_url=file_url,
                content_type=content_type,
                file_size=len(file_content),
                created_at=datetime.now(timezone.utc)
            )

            self.data_port.add_ticket_attachment(attachment)
            logger.info(f"Saved email attachment {file_name} for ticket {ticket_id}")
        except Exception as e:
            logger.error(f"Failed to save email attachment: {e}")

    # --- LiveChat Flow ---
    
    def start_chat_session(self, user_id: Optional[int], session_token: Optional[str], is_authenticated_user: bool = False, initial_context: Optional[dict] = None, initial_message: Optional[str] = None, is_proactive: bool = False, ip_address: Optional[str] = None, user_agent: Optional[str] = None, current_url: Optional[str] = None) -> LiveChatSession:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        session = LiveChatSession(
            id=session_id,
            user_id=user_id,
            session_token=session_token,
            status=LiveChatStatus.WAITING,
            created_at=now,
            is_authenticated_user=is_authenticated_user,
            ip_address=ip_address,
            user_agent=user_agent,
            current_url=current_url or (initial_context.get("source_url") if initial_context else None),
            initial_context=initial_context,
            initial_message=initial_message,
            is_proactive=is_proactive
        )
        self.data_port.create_chat_session(session)
        
        if initial_message:
            self.add_chat_message(
                session_id=session_id,
                sender_type=LiveChatSenderType.USER,
                message=initial_message,
                sender_id=user_id
            )
            
        return session
        
    def get_chat_session(self, session_id: str) -> Optional[LiveChatSession]:
        return self.data_port.get_chat_session(session_id)
    
    def get_active_chat_sessions(self, status=None, page: int = 1, page_size: int = 20) -> dict:
        return self.data_port.get_active_chat_sessions(status=status, page=page, page_size=page_size)

    def get_livechat_session_stats(self) -> Dict[str, int]:
        """Get LiveChat session statistics (counts by status)"""
        return self.data_port.get_livechat_session_stats()

    def get_chat_messages(self, session_id: str) -> List[LiveChatMessage]:
        return self.data_port.get_chat_messages(session_id)

    def update_chat_session_status(self, session_id: str, status: LiveChatStatus, ticket_id: Optional[str] = None, agent_id: Optional[int] = None) -> bool:
        return self.data_port.update_chat_session_status(session_id, status, ticket_id, agent_id)

    def update_chat_session_activity(self, session_id: str, current_url: Optional[str] = None, is_typing: Optional[bool] = None, sender_type: LiveChatSenderType = LiveChatSenderType.USER) -> bool:
        """Update real-time session activity (URL and typing state)"""
        typing_status = None
        if is_typing is not None:
            # We store typing status as a small JSON with timestamps
            typing_status = {
                "sender_type": sender_type.value,
                "is_typing": is_typing,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        return self.data_port.update_chat_session_activity(session_id, current_url, typing_status)

    def convert_chat_to_ticket(self, session_id: str, category_id: str, subject: Optional[str] = None, priority: TicketPriority = TicketPriority.NORMAL, agent_id: Optional[int] = None) -> str:
        """Transform a chat session into a permanent Ticket."""
        session = self.get_chat_session(session_id)
        if not session:
            raise ValueError("Chat session not found.")
        
        if session.ticket_id:
            return session.ticket_id # Already converted
            
        messages = self.get_chat_messages(session_id)
        
        # Build transcript
        transcript = f"--- LiveChat Transcript (Session: {session_id}) ---\n"
        transcript += f"Start Time: {session.created_at}\n"
        transcript += f"IP: {session.ip_address} | UA: {session.user_agent}\n"
        transcript += f"Initial URL: {session.current_url}\n\n"
        
        for m in messages:
            sender = "User" if m.sender_type == LiveChatSenderType.USER else "Agent"
            transcript += f"[{m.created_at}] {sender}: {m.message}\n"
            
        # Create ticket
        ticket_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Determine subject if not provided
        if not subject:
            subject = f"Chat Conversion: {session.initial_message[:50]}..." if session.initial_message else f"Chat Conversion {session_id[:8]}"
        
        ticket = Ticket(
            id=ticket_id,
            subject=subject,
            status=TicketStatus.OPEN,
            priority=priority,
            category_id=category_id,
            origin=TicketOrigin.LIVECHAT,
            created_at=now,
            updated_at=now,
            user_id=session.user_id,
            assigned_agent_id=agent_id or session.agent_id
        )
        
        # Prepare transcript message for the ticket
        initial_msg = TicketMessage(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            sender_id=session.user_id,
            message=transcript,
            created_at=now,
            is_internal_note=False
        )
        
        self.data_port.create_ticket(ticket, initial_msg)
        
        # Link session to ticket
        self.update_chat_session_status(session_id, session.status, ticket_id=ticket_id)
        
        return ticket_id

        
    def add_chat_message(self, session_id: str, sender_type: LiveChatSenderType, message: str, sender_id: Optional[int] = None, context: Optional[dict] = None) -> LiveChatMessage:
        """Add a message to a live chat session."""
        chat_msg = LiveChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            sender_type=sender_type,
            message=message,
            created_at=datetime.now(timezone.utc),
            sender_id=sender_id,
            context=context
        )
        self.data_port.add_chat_message(chat_msg)
        return chat_msg
        
    def upload_livechat_attachment(self, session_id: str, message_id: str, file_name: str, file_content: bytes) -> "LiveChatAttachment":
        session = self.get_chat_session(session_id)
        if not session:
            raise ValueError("Chat session not found.")
            
        if len(file_content) > MAX_FILE_SIZE_BYTES:
            raise ValueError("File exceeds the 5MB size limit.")

        sanitized_name = sanitize_filename(file_name)
        content_type = validate_file_content(file_content, sanitized_name)

        storage_dir = resolve_storage_path(settings("LIVECHAT_UPLOAD_STORAGE_PATH", "data/uploads/livechat"))
        storage_dir.mkdir(parents=True, exist_ok=True)

        attachment_id = str(uuid.uuid4())
        safe_name = f"{attachment_id}_{sanitized_name}"
        file_path = (storage_dir / safe_name).resolve()

        if not str(file_path).startswith(str(storage_dir.resolve())):
            raise ValueError("Invalid file path — path traversal detected.")

        with open(file_path, "wb") as f:
            f.write(file_content)

        file_url = f"/media/livechat/{safe_name}"
        
        attachment = LiveChatAttachment(
            id=attachment_id,
            session_id=session_id,
            message_id=message_id,
            file_name=file_name,
            file_url=file_url,
            content_type=content_type,
            file_size=len(file_content),
            created_at=datetime.now(timezone.utc)
        )
        
        self.data_port.add_livechat_attachment(attachment)
        return attachment

    def get_livechat_attachment_by_file_url(self, file_url: str):
        """Look up a livechat attachment by its file_url path"""
        return self.data_port.get_livechat_attachment_by_file_url(file_url)

    def end_chat_session(self, session_id: str, ended_by_agent: bool = False, agent_id: Optional[int] = None) -> bool:
        """Explicitly end a LiveChat session"""
        session = self.get_chat_session(session_id)
        if not session or session.status == LiveChatStatus.ENDED:
            return False
            
        success = self.data_port.update_chat_session_status(session_id, LiveChatStatus.ENDED)
        if success:
            label = "Agent" if ended_by_agent else "User"
            self.add_chat_message(
                session_id=session_id,
                sender_type=LiveChatSenderType.SYSTEM,
                message=f"Chat session has been ended by the {label}.",
                sender_id=agent_id
            )
            logger.info(f"LiveChat session {session_id} ended by {label}.")
            
        return success
