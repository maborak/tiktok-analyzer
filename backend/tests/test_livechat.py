import pytest
from unittest.mock import Mock
from datetime import datetime, timezone
import uuid

from domain.services.ticket_service import TicketService
from domain.entities.ticket_models import (
    LiveChatSession, LiveChatStatus, LiveChatSenderType
)
from ports.hooks import HookEvent, HookEventType

@pytest.fixture
def mock_data_port():
    m = Mock()
    m.get_ticket_categories.return_value = []
    return m

@pytest.fixture
def mock_hook_manager():
    return Mock()

@pytest.fixture
def ticket_service(mock_data_port, mock_hook_manager):
    return TicketService(mock_data_port, mock_hook_manager)


def test_start_livechat_session_anonymous(ticket_service, mock_data_port):
    session_token = "secure-token"
    
    session = ticket_service.start_chat_session(
        user_id=None,
        session_token=session_token,
        is_authenticated_user=False
    )
    
    assert session.user_id is None
    assert session.session_token == session_token
    assert session.status == LiveChatStatus.WAITING
    assert not session.is_authenticated_user
    mock_data_port.create_chat_session.assert_called_once()

def test_start_livechat_session_contextual_guest(ticket_service, mock_data_port):
    session_token = "secure-token"
    user_id = 42
    
    session = ticket_service.start_chat_session(
        user_id=user_id,
        session_token=session_token,
        is_authenticated_user=False  # Crucial: matched email but NOT technically authenticated
    )
    
    assert session.user_id == user_id
    assert session.session_token == session_token
    assert session.status == LiveChatStatus.WAITING
    assert not session.is_authenticated_user
    mock_data_port.create_chat_session.assert_called_once()

def test_upload_livechat_attachment_success(ticket_service, mock_data_port):
    session_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    
    mock_session = LiveChatSession(
        id=session_id,
        user_id=None,
        session_token="token",
        status=LiveChatStatus.WAITING,
        created_at=datetime.now(timezone.utc)
    )
    mock_data_port.get_chat_session.return_value = mock_session
    
    # Simulate a valid PDF file with correct magic numbers
    pdf_magic = b'%PDF-'
    valid_pdf_content = pdf_magic + b'fake_pdf_data_here'
    
    attachment = ticket_service.upload_livechat_attachment(
        session_id=session_id,
        message_id=message_id,
        file_name="invoice.pdf",
        file_content=valid_pdf_content
    )
    
    assert attachment.file_name == "invoice.pdf"
    assert attachment.content_type == "application/pdf"
    assert "/media/livechat/" in attachment.file_url
    assert attachment.file_size == len(valid_pdf_content)
    
    mock_data_port.add_livechat_attachment.assert_called_once()


def test_admin_join_session_associates_agent(ticket_service, mock_data_port):
    session_id = str(uuid.uuid4())
    mock_session = LiveChatSession(
        id=session_id,
        user_id=123,
        session_token="token",
        status=LiveChatStatus.WAITING,
        created_at=datetime.now(timezone.utc)
    )
    mock_data_port.get_chat_session.return_value = mock_session
    
    # We test the service method directly for hardening
    ticket_service.update_chat_session_status(
        session_id=session_id,
        status=LiveChatStatus.ACTIVE,
        agent_id=999
    )
    
    mock_data_port.update_chat_session_status.assert_called_once_with(
        session_id, LiveChatStatus.ACTIVE, None, 999
    )


def test_get_session_metadata(ticket_service, mock_data_port):
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    mock_session = LiveChatSession(
        id=session_id,
        user_id=123,
        session_token="token",
        status=LiveChatStatus.ACTIVE,
        created_at=now,
        agent_id=999
    )
    mock_data_port.get_chat_session.return_value = mock_session
    
    session = ticket_service.get_chat_session(session_id)
    
    assert session.id == session_id
    assert session.status == LiveChatStatus.ACTIVE
    assert session.agent_id == 999


def test_end_chat_session(ticket_service, mock_data_port):
    session_id = str(uuid.uuid4())
    mock_session = LiveChatSession(
        id=session_id,
        user_id=123,
        session_token="token",
        status=LiveChatStatus.ACTIVE,
        created_at=datetime.now(timezone.utc)
    )
    mock_data_port.get_chat_session.return_value = mock_session
    mock_data_port.update_chat_session_status.return_value = True
    
    success = ticket_service.end_chat_session(session_id, ended_by_agent=True, agent_id=999)
    
    assert success is True
    # Verify status update call
    mock_data_port.update_chat_session_status.assert_called_with(session_id, LiveChatStatus.ENDED)
    # Verify system message call
    mock_data_port.add_chat_message.assert_called()
    last_call_args = mock_data_port.add_chat_message.call_args[0][0]
    assert "ended by the Agent" in last_call_args.message
    assert last_call_args.sender_type == LiveChatSenderType.SYSTEM
