"""
Integration tests for Enterprise LiveChat Features: Context & Initial Message
"""

import pytest
import os
from unittest.mock import Mock
from fastapi.testclient import TestClient

# We need to test the real DB columns, not mocks.
os.environ["API_BASE_URL"] = "http://localhost:9001"
from api_main import app

client = TestClient(app)

def test_enterprise_context_flow():
    """
    Test starting a chat with initial context and an initial message,
    then sending a follow-up message with per-message context.
    """
    from utils.auth_provider import set_auth_service
    from routes import livechat
    from domain.services.ticket_service import TicketService
    mock_auth = Mock()
    mock_auth.user_management_port.get_user_by_email.return_value = None
    set_auth_service(mock_auth)
    
    mock_ticket_service = Mock(spec=TicketService)
    
    # Needs to return a mock session
    from domain.entities.ticket_models import LiveChatSession, LiveChatStatus, LiveChatMessage, LiveChatSenderType
    from datetime import datetime, timezone
    
    mock_session = LiveChatSession(
        id="test-session-123",
        user_id=None,
        session_token="test-token-abc",
        status=LiveChatStatus.WAITING,
        created_at=datetime.now(timezone.utc),
        is_authenticated_user=False,
        initial_context={
            "ip": "127.0.0.1",
            "user_agent": "Mozilla/5.0 Enterprise-Bot",
            "source_url": "https://example.com/enterprise-pricing",
            "custom": {
                "browser": "Chrome",
                "screen": "1920x1080"
            }
        },
        initial_message="Hello, I need enterprise support.",
        is_proactive=False
    )
    
    mock_msg = LiveChatMessage(
        id="test-msg-1",
        session_id="test-session-123",
        sender_type=LiveChatSenderType.USER,
        message="Hello, I need enterprise support.",
        created_at=datetime.now(timezone.utc),
    )
    
    mock_msg_2 = LiveChatMessage(
        id="test-msg-2",
        session_id="test-session-123",
        sender_type=LiveChatSenderType.USER,
        message="Actually, I changed my mind. I'm looking at standard now.",
        created_at=datetime.now(timezone.utc),
        context={"current_url": "https://example.com/standard-pricing"}
    )
    
    mock_ticket_service.start_chat_session.return_value = mock_session
    mock_ticket_service.get_chat_session.return_value = mock_session
    mock_ticket_service.get_chat_messages.return_value = [mock_msg]
    mock_ticket_service.add_chat_message.return_value = mock_msg_2
    
    livechat.ticket_service = mock_ticket_service
    
    # 1. Start a session with Proactive flag, Context, and Initial Message
    start_payload = {
        "name": "Enterprise Tester",
        "email": "enterprise@example.com",
        "initial_message": "Hello, I need enterprise support.",
        "is_proactive": False,
        "source_url": "https://example.com/enterprise-pricing",
        "client_metadata": {
            "browser": "Chrome",
            "screen": "1920x1080"
        }
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 Enterprise-Bot"
    }

    start_resp = client.post("/livechat/session", json=start_payload, headers=headers)
    assert start_resp.status_code == 201, f"Failed to start session: {start_resp.text}"
    
    start_data = start_resp.json()
    session_id = start_data["id"]
    token = start_data["session_token"]

    # 2. Verify Session Metadata (Context extraction)
    meta_resp = client.get(
        f"/livechat/session/{session_id}",
        headers={"x-session-token": token}
    )
    assert meta_resp.status_code == 200, f"Failed to get metadata: {meta_resp.text}"
    
    meta_data = meta_resp.json()
    context = meta_data.get("initial_context", {})
    
    assert context is not None, "Initial context is None!"
    assert context.get("user_agent") == "Mozilla/5.0 Enterprise-Bot", "User-Agent mismatch"
    assert context.get("source_url") == "https://example.com/enterprise-pricing", "Source URL mismatch"
    assert context.get("custom", {}).get("browser") == "Chrome", "Client metadata mismatch"
    assert meta_data.get("is_proactive") is False, "Proactive flag should be False"

    # 3. Verify Initial Message was automatically created
    msgs_resp = client.get(
        f"/livechat/session/{session_id}/messages",
        headers={"x-session-token": token}
    )
    assert msgs_resp.status_code == 200, f"Failed to get messages: {msgs_resp.text}"
    
    msgs_data = msgs_resp.json()
    assert len(msgs_data) == 1, f"Expected exactly 1 message, got {len(msgs_data)}"
    
    initial_msg = msgs_data[0]
    assert initial_msg["message"] == "Hello, I need enterprise support.", "Initial message text mismatch"
    assert initial_msg["sender_type"] == "USER", "Initial message sender should be USER"

    # 4. Send a follow-up message with Per-Message Context
    follow_up_payload = {
        "message": "Actually, I changed my mind. I'm looking at standard now.",
        "context": {
            "current_url": "https://example.com/standard-pricing"
        }
    }
    
    msg_resp = client.post(
        f"/livechat/session/{session_id}/messages",
        json=follow_up_payload,
        headers={"x-session-token": token}
    )
    assert msg_resp.status_code == 201, f"Failed to send follow-up: {msg_resp.text}"
    
    msg_data = msg_resp.json()
    assert msg_data["context"] is not None, "Follow-up context is missing"
    assert msg_data["context"].get("current_url") == "https://example.com/standard-pricing", "Per-message context URL mismatch"
