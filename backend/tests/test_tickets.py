import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
import uuid

from domain.services.ticket_service import TicketService
from domain.entities.ticket_models import (
    Ticket, TicketMessage, TicketCategoryDef, 
    TicketStatus, TicketPriority, TicketOrigin
)
from ports.hooks import HookEvent, HookEventType

@pytest.fixture
def mock_data_port():
    port = Mock()
    # Setup some default return values
    port.get_ticket_categories.return_value = [
        TicketCategoryDef(id="cat-1", name="General", description="General", is_active=True)
    ]
    return port

@pytest.fixture
def mock_hook_manager():
    return Mock()

@pytest.fixture
def ticket_service(mock_data_port, mock_hook_manager):
    return TicketService(mock_data_port, mock_hook_manager)

def test_ensure_default_category_created(mock_data_port, mock_hook_manager):
    # Setup to return empty categories
    mock_data_port.get_ticket_categories.return_value = []
    
    # Initialize service
    TicketService(mock_data_port, mock_hook_manager)
    
    # Verify create was called
    mock_data_port.create_ticket_category.assert_called_once()
    args = mock_data_port.create_ticket_category.call_args[0]
    assert args[0].name == "General"

def test_create_ticket_for_user(ticket_service, mock_data_port, mock_hook_manager):
    user_id = 1
    subject = "Test Subject"
    message = "Test Message"
    
    ticket = ticket_service.create_ticket(user_id=user_id, subject=subject, message=message)
    
    assert ticket.subject == subject
    assert ticket.user_id == user_id
    assert ticket.status == TicketStatus.OPEN
    assert ticket.priority == TicketPriority.NORMAL
    
    # Verify persistence call
    mock_data_port.create_ticket.assert_called_once()
    
    # Verify event dispatched
    mock_hook_manager.fire.assert_called_once()
    event = mock_hook_manager.fire.call_args[0][0]
    assert event.event_type == HookEventType.TICKET_CREATED
    assert event.data["ticket_id"] == ticket.id
    assert event.data["user_id"] == user_id

def test_add_message_from_user(ticket_service, mock_data_port, mock_hook_manager):
    ticket_id = str(uuid.uuid4())
    user_id = 1
    
    # Mock existing ticket
    mock_ticket = Ticket(
        id=ticket_id,
        subject="Subject",
        status=TicketStatus.PENDING_CUSTOMER,
        priority=TicketPriority.NORMAL,
        category_id="cat-1",
        origin=TicketOrigin.WEB,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        user_id=user_id
    )
    mock_data_port.get_ticket.return_value = mock_ticket
    
    # Add message
    msg = ticket_service.add_message_from_user(user_id=user_id, ticket_id=ticket_id, message="Reply")
    
    assert msg.message == "Reply"
    assert msg.sender_id == user_id
    assert not msg.is_internal_note
    
    mock_data_port.add_ticket_message.assert_called_once()
    # It was PENDING_CUSTOMER, so status should be updated to OPEN
    mock_data_port.update_ticket_status.assert_called_once_with(ticket_id, TicketStatus.OPEN)
    
    mock_hook_manager.fire.assert_called_once()
    event = mock_hook_manager.fire.call_args[0][0]
    assert event.event_type == HookEventType.TICKET_UPDATED

def test_add_message_from_agent(ticket_service, mock_data_port, mock_hook_manager):
    ticket_id = str(uuid.uuid4())
    agent_id = 99
    
    # Mock existing ticket
    mock_ticket = Ticket(
        id=ticket_id,
        subject="Subject",
        status=TicketStatus.OPEN,
        priority=TicketPriority.NORMAL,
        category_id="cat-1",
        origin=TicketOrigin.WEB,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        user_id=1
    )
    mock_data_port.get_ticket.return_value = mock_ticket
    
    # Add agent reply
    msg = ticket_service.add_message_from_agent(
        agent_id=agent_id, 
        ticket_id=ticket_id, 
        message="Agent reply", 
        is_internal_note=False
    )
    
    assert msg.message == "Agent reply"
    assert msg.sender_id == agent_id
    assert not msg.is_internal_note
    
    # It was OPEN, so status should be updated to PENDING_CUSTOMER
    mock_data_port.update_ticket_status.assert_called_once_with(ticket_id, TicketStatus.PENDING_CUSTOMER)
    
    mock_hook_manager.fire.assert_called_once()
    event = mock_hook_manager.fire.call_args[0][0]
    assert event.event_type == HookEventType.TICKET_UPDATED

def test_add_internal_note_from_agent(ticket_service, mock_data_port, mock_hook_manager):
    ticket_id = str(uuid.uuid4())
    agent_id = 99
    
    # Mock existing ticket
    mock_ticket = Ticket(
        id=ticket_id,
        subject="Subject",
        status=TicketStatus.OPEN,
        priority=TicketPriority.NORMAL,
        category_id="cat-1",
        origin=TicketOrigin.WEB,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        user_id=1
    )
    mock_data_port.get_ticket.return_value = mock_ticket
    
    # Add internal note
    msg = ticket_service.add_message_from_agent(
        agent_id=agent_id, 
        ticket_id=ticket_id, 
        message="Internal note", 
        is_internal_note=True
    )
    
    assert msg.is_internal_note
    mock_data_port.update_ticket_status.assert_not_called()  # Status shouldn't change for internal notes

def test_user_unauthorized_access(ticket_service, mock_data_port):
    ticket_id = str(uuid.uuid4())
    user_id = 1
    
    # Mock existing ticket belonging to DIFFERENT user (user_id=2)
    mock_ticket = Ticket(
        id=ticket_id,
        subject="Subject",
        status=TicketStatus.OPEN,
        priority=TicketPriority.NORMAL,
        category_id="cat-1",
        origin=TicketOrigin.WEB,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        user_id=2
    )
    mock_data_port.get_ticket.return_value = mock_ticket
    
    # Trying to get ticket for user 1 should return None
    t = ticket_service.get_ticket_for_user(user_id=1, ticket_id=ticket_id)
    assert t is None
    
    # Trying to reply to ticket for user 1 should raise ValueError
    with pytest.raises(ValueError):
        ticket_service.add_message_from_user(user_id=1, ticket_id=ticket_id, message="Reply")

def test_upload_ticket_attachment_success(ticket_service, mock_data_port):
    ticket_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    user_id = 1
    
    mock_ticket = Ticket(
        id=ticket_id,
        subject="Subject",
        status=TicketStatus.OPEN,
        priority=TicketPriority.NORMAL,
        category_id="cat-1",
        origin=TicketOrigin.WEB,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        user_id=user_id
    )
    mock_data_port.get_ticket.return_value = mock_ticket
    
    # Simulate a valid PNG file with correct magic numbers
    png_magic = b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a'
    valid_png_content = png_magic + b'fake_image_data_here'
    
    attachment = ticket_service.upload_ticket_attachment(
        ticket_id=ticket_id,
        message_id=message_id,
        uploader_id=user_id,
        file_name="test_image.png",
        file_content=valid_png_content
    )
    
    assert attachment.file_name == "test_image.png"
    assert attachment.content_type == "image/png"
    assert "/media/tickets/" in attachment.file_url
    mock_data_port.add_ticket_attachment.assert_called_once()

def test_upload_ticket_attachment_invalid_mime(ticket_service, mock_data_port):
    ticket_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    user_id = 1
    
    mock_ticket = Ticket(
        id=ticket_id,
        subject="Subject",
        status=TicketStatus.OPEN,
        priority=TicketPriority.NORMAL,
        category_id="cat-1",
        origin=TicketOrigin.WEB,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        user_id=user_id
    )
    mock_data_port.get_ticket.return_value = mock_ticket
    
    # Simulate a malicious .txt file renamed to .png (missing magic numbers)
    malicious_content = b'This is just a text file script!'
    
    with pytest.raises(ValueError) as exc:
        ticket_service.upload_ticket_attachment(
            ticket_id=ticket_id,
            message_id=message_id,
            uploader_id=user_id,
            file_name="fake_image.png",
            file_content=malicious_content
        )
    
    assert "Unsupported file type" in str(exc.value)


