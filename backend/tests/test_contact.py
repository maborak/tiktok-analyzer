"""Unit tests for the guest Contact Us ticket flow."""
import pytest
from unittest.mock import Mock
from domain.services.ticket_service import TicketService
from domain.entities.ticket_models import TicketCategoryDef, TicketOrigin
from ports.hooks import HookManager


@pytest.fixture
def mock_data_port():
    m = Mock()
    general_cat = TicketCategoryDef(id="cat-general", name="General", description="Default", is_active=True)
    m.get_ticket_categories.return_value = [general_cat]
    m.create_ticket.return_value = None
    return m


@pytest.fixture
def mock_hook_manager():
    return Mock(spec=HookManager)


@pytest.fixture
def ticket_service(mock_data_port, mock_hook_manager):
    return TicketService(mock_data_port, mock_hook_manager)


def test_create_guest_ticket_has_contact_form_origin(ticket_service, mock_data_port):
    ticket = ticket_service.create_guest_ticket(
        name="Alice",
        sender_email="alice@example.com",
        subject="Need help with my account",
        message="I have been waiting for a reply for 5 days now.",
    )
    assert ticket.origin == TicketOrigin.CONTACT_FORM


def test_create_guest_ticket_has_no_user_id(ticket_service):
    ticket = ticket_service.create_guest_ticket(
        name="Bob",
        sender_email="bob@example.com",
        subject="Product question",
        message="Can you tell me more about your premium plan?",
    )
    assert ticket.user_id is None


def test_create_guest_ticket_stores_sender_email(ticket_service):
    ticket = ticket_service.create_guest_ticket(
        name="Carol",
        sender_email="carol@test.com",
        subject="Billing issue",
        message="I was charged twice this month, please help.",
    )
    assert ticket.sender_email == "carol@test.com"


def test_create_guest_ticket_message_includes_name(ticket_service, mock_data_port):
    ticket_service.create_guest_ticket(
        name="Dave",
        sender_email="dave@test.com",
        subject="Hello",
        message="Just checking in.",
    )
    # Inspect the TicketMessage that was passed to the persistence layer
    call_args = mock_data_port.create_ticket.call_args
    _, initial_message = call_args[0]
    assert "Dave" in initial_message.message
    assert "<dave@test.com>" in initial_message.message


def test_create_guest_ticket_invalid_category_raises(ticket_service, mock_data_port):
    mock_data_port.get_ticket_categories.return_value = [
        TicketCategoryDef(id="cat-general", name="General", description="Default", is_active=True)
    ]
    with pytest.raises(ValueError, match="Invalid category"):
        ticket_service.create_guest_ticket(
            name="Eve",
            sender_email="eve@test.com",
            subject="Bad category test",
            message="This should fail because the category does not exist.",
            category_id="non-existent-cat-id",
        )
