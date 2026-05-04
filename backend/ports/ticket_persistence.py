from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from domain.entities.ticket_models import (
    Ticket, TicketMessage, TicketCategoryDef, TicketInboundConfig,
    TicketStatus, TicketPriority, TicketTag, TicketAttachment,
    LiveChatSession, LiveChatMessage, LiveChatStatus
)


class TicketPersistencePort(ABC):
    """Port for ticket and livechat persistence operations"""

    # --- Tickets ---
    @abstractmethod
    def create_ticket(self, ticket: Ticket, initial_message: TicketMessage) -> str:
        """Create a new ticket and its initial message"""
        pass

    @abstractmethod
    def get_user_tickets(self, user_id: str, status: Optional[TicketStatus] = None, search: Optional[str] = None, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get paginated tickets for a specific user"""
        pass

    @abstractmethod
    def get_all_tickets(self, status: Optional[TicketStatus] = None, agent_id: Optional[str] = None, unassigned: bool = False, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get all tickets with pagination and optional filters"""
        pass

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """Get a specific ticket by ID"""
        pass

    @abstractmethod
    def add_ticket_message(self, message: TicketMessage) -> str:
        """Add a new message to an existing ticket"""
        pass

    @abstractmethod
    def get_ticket_messages(self, ticket_id: str) -> List[TicketMessage]:
        """Get all messages for a specific ticket"""
        pass

    @abstractmethod
    def update_ticket_status(self, ticket_id: str, status: TicketStatus) -> bool:
        """Update a ticket's status"""
        pass

    @abstractmethod
    def reopen_ticket(self, ticket_id: str) -> bool:
        """Reopen a ticket: set status to OPEN, clear resolved_at, increment reopen_count"""
        pass

    @abstractmethod
    def update_ticket_priority(self, ticket_id: str, priority: TicketPriority) -> bool:
        """Update a ticket's priority"""
        pass

    @abstractmethod
    def assign_ticket(self, ticket_id: str, agent_id: str) -> bool:
        """Assign a ticket to an agent"""
        pass

    @abstractmethod
    def create_ticket_category(self, category: TicketCategoryDef) -> str:
        """Create a new ticket category"""
        pass

    @abstractmethod
    def migrate_guest_tickets(self, email: str, user_id: int) -> int:
        """Link guest tickets with a specific email to a user ID"""
        pass

    @abstractmethod
    def update_ticket_category(self, category_id: str, name: Optional[str] = None, description: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
        """Update an existing ticket category"""
        pass

    @abstractmethod
    def get_ticket_categories(self, active_only: bool = True) -> List[TicketCategoryDef]:
        """Get all ticket categories"""
        pass

    @abstractmethod
    def get_inbound_config(self, email_address: str) -> Optional[TicketInboundConfig]:
        """Get the inbound configuration for a specific email address"""
        pass

    @abstractmethod
    def add_ticket_tag(self, ticket_id: str, tag_id: str) -> bool:
        """Add a tag to a ticket"""
        pass

    @abstractmethod
    def remove_ticket_tag(self, ticket_id: str, tag_id: str) -> bool:
        """Remove a tag from a ticket"""
        pass

    @abstractmethod
    def add_ticket_attachment(self, attachment: TicketAttachment) -> str:
        """Save ticket attachment metadata"""
        pass

    @abstractmethod
    def get_ticket_message_summaries(self, ticket_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get message count, last message timestamp, and last agent message timestamp for a batch of tickets.
        Returns: {ticket_id: {"reply_count": int, "last_message_at": datetime|None, "last_agent_message_at": datetime|None}}"""
        pass

    # --- LiveChat ---
    @abstractmethod
    def create_chat_session(self, session: LiveChatSession) -> str:
        """Create a new LiveChat session"""
        pass

    @abstractmethod
    def get_chat_session(self, session_id: str) -> Optional[LiveChatSession]:
        """Get a specific LiveChat session"""
        pass

    @abstractmethod
    def add_chat_message(self, message: LiveChatMessage) -> str:
        """Add a message to a LiveChat session"""
        pass

    @abstractmethod
    def get_chat_messages(self, session_id: str) -> List[LiveChatMessage]:
        """Get all messages for a LiveChat session"""
        pass

    @abstractmethod
    def get_active_chat_sessions(self, status: Optional[LiveChatStatus] = None, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """Get LiveChat sessions with pagination and optional status filter"""
        pass

    @abstractmethod
    def get_livechat_session_stats(self) -> Dict[str, int]:
        """Get LiveChat session statistics (counts by status)"""
        pass

    @abstractmethod
    def update_chat_session_activity(self, session_id: str, current_url: Optional[str] = None, typing_status: Optional[dict] = None) -> bool:
        """Update real-time session activity"""
        pass

    @abstractmethod
    def update_chat_session_status(self, session_id: str, status: LiveChatStatus, ticket_id: Optional[str] = None, agent_id: Optional[int] = None) -> bool:
        """Update a LiveChat session's status"""
        pass

    @abstractmethod
    def add_livechat_attachment(self, attachment: Any) -> str:
        """Save livechat attachment metadata"""
        pass

    @abstractmethod
    def get_livechat_attachment_by_file_url(self, file_url: str) -> Optional[Any]:
        """Look up a livechat attachment by its file_url path"""
        pass
