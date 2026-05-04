from ..core.base import Base
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from domain.entities.ticket_models import TicketStatus, TicketPriority, TicketOrigin, LiveChatStatus, LiveChatSenderType

class TicketCategoryModel(Base):
    __tablename__ = "ticket_categories"
    
    id = Column(String(36), primary_key=True) # UUID based
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)

    tickets = relationship("TicketModel", back_populates="category")

class TicketModel(Base):
    __tablename__ = "tickets"
    
    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    subject = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default=TicketStatus.OPEN.value, index=True)
    priority = Column(String(50), nullable=False, default=TicketPriority.NORMAL.value)
    category_id = Column(String(36), ForeignKey('ticket_categories.id'), nullable=False, index=True)
    origin = Column(String(50), nullable=False, default=TicketOrigin.WEB.value)
    sender_email = Column(String(255), nullable=True)
    assigned_agent_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    sla_due_date = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    reopen_count = Column(Integer, default=0, nullable=False, server_default='0')
    guest_access_token = Column(String(100), nullable=True, index=True)
    
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)

    category = relationship("TicketCategoryModel", back_populates="tickets")
    messages = relationship("TicketMessageModel", back_populates="ticket", cascade="all, delete-orphan")
    tags = relationship("TicketTagModel", secondary="ticket_tag_associations", back_populates="tickets")
    attachments = relationship("TicketAttachmentModel", back_populates="ticket", cascade="all, delete-orphan")
    user = relationship("User", foreign_keys=[user_id])
    agent = relationship("User", foreign_keys=[assigned_agent_id])

class TicketMessageModel(Base):
    __tablename__ = "ticket_messages"
    
    id = Column(String(36), primary_key=True)
    ticket_id = Column(String(36), ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    message = Column(Text, nullable=False)
    sender_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    sender_email = Column(String(255), nullable=True)
    is_internal_note = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    ticket = relationship("TicketModel", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    attachments = relationship("TicketAttachmentModel", back_populates="message", cascade="all, delete-orphan")

class TicketTagModel(Base):
    __tablename__ = "ticket_tags"
    
    id = Column(String(36), primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    color = Column(String(7), nullable=False, default="#CCCCCC")

    tickets = relationship("TicketModel", secondary="ticket_tag_associations", back_populates="tags")

class TicketTagAssociationModel(Base):
    __tablename__ = "ticket_tag_associations"
    
    ticket_id = Column(String(36), ForeignKey('tickets.id', ondelete='CASCADE'), primary_key=True)
    tag_id = Column(String(36), ForeignKey('ticket_tags.id', ondelete='CASCADE'), primary_key=True)

class TicketAttachmentModel(Base):
    __tablename__ = "ticket_attachments"
    
    id = Column(String(36), primary_key=True)
    ticket_id = Column(String(36), ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey('ticket_messages.id', ondelete='SET NULL'), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_url = Column(String(1024), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    ticket = relationship("TicketModel", back_populates="attachments")
    message = relationship("TicketMessageModel", back_populates="attachments")

class TicketInboundConfigModel(Base):
    __tablename__ = "ticket_inbound_configs"
    
    id = Column(String(36), primary_key=True)
    email_address = Column(String(255), nullable=False, unique=True)
    default_category_id = Column(String(36), ForeignKey('ticket_categories.id'), nullable=False)

    category = relationship("TicketCategoryModel")

class LiveChatSessionModel(Base):
    __tablename__ = "livechat_sessions"
    
    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    session_token = Column(String(255), nullable=True, unique=True, index=True)
    agent_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    status = Column(String(50), nullable=False, default=LiveChatStatus.WAITING.value, index=True)
    ticket_id = Column(String(36), ForeignKey('tickets.id', ondelete='SET NULL'), nullable=True)
    
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    ended_at = Column(DateTime, nullable=True)
    is_authenticated_user = Column(Boolean, default=False, nullable=False)
    
    # Client Metadata
    ip_address = Column(String(45), nullable=True)  # IPv6 support
    user_agent = Column(Text, nullable=True)
    current_url = Column(Text, nullable=True)

    # Enterprise Features
    initial_context = Column(JSONB, nullable=True)
    initial_message = Column(Text, nullable=True)
    typing_status = Column(JSONB, nullable=True)
    first_response_at = Column(DateTime, nullable=True)
    resolution_time_seconds = Column(Integer, nullable=True)
    csat_score = Column(Integer, nullable=True)
    csat_comment = Column(Text, nullable=True)
    is_proactive = Column(Boolean, default=False, nullable=False)

    messages = relationship("LiveChatMessageModel", back_populates="session", cascade="all, delete-orphan")
    attachments = relationship("LiveChatAttachmentModel", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", foreign_keys=[user_id])
    agent = relationship("User", foreign_keys=[agent_id])
    ticket = relationship("TicketModel")

class LiveChatMessageModel(Base):
    __tablename__ = "livechat_messages"
    
    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey('livechat_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    sender_type = Column(String(50), nullable=False, default=LiveChatSenderType.USER.value)
    sender_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    message = Column(Text, nullable=False)

    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    read_at = Column(DateTime, nullable=True)
    context = Column(JSONB, nullable=True)

    session = relationship("LiveChatSessionModel", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    attachments = relationship("LiveChatAttachmentModel", back_populates="message", cascade="all, delete-orphan")


class LiveChatAttachmentModel(Base):
    __tablename__ = "livechat_attachments"
    
    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey('livechat_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    message_id = Column(String(36), ForeignKey('livechat_messages.id', ondelete='SET NULL'), nullable=True, index=True)
    file_name = Column(String(255), nullable=False)
    file_url = Column(String(1024), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)

    session = relationship("LiveChatSessionModel", back_populates="attachments")
    message = relationship("LiveChatMessageModel", back_populates="attachments")

