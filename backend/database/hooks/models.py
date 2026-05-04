"""
Hook Configuration Database Models

Stores hook handler configuration and enabled/disabled status.
"""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from database.core.base import Base
from config import get_table_name


class HookConfig(Base):
    """
    SQLAlchemy model for hook handler configuration.
    
    Stores enabled status and configuration for each hook handler.
    Allows dynamic enable/disable of hooks at runtime.
    """
    __tablename__ = get_table_name("hook_configs")
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Handler identification
    name = Column(String(100), nullable=False, unique=True, index=True)  # Handler name (e.g., "EmailHandler")
    handler_type = Column(String(50), nullable=False, index=True)  # Type: "email", "log", "webhook", "push"
    description = Column(Text, nullable=True)  # Optional description
    
    # Status
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    
    # Configuration (JSON)
    config = Column(JSONB, nullable=True, server_default='{}')  # Handler-specific config
    # Example for email: {"sender": "...", "receiver": "...", "smtp_host": "..."}
    # Example for webhook: {"url": "...", "headers": {...}}
    
    # Event filtering
    subscribed_events = Column(JSONB, nullable=True, server_default='[]')  # List of event types to subscribe to
    # Example: ["price_saved", "price_changed"] or ["*"] for all
    
    # Metadata
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    
    def __repr__(self):
        return f"<HookConfig(name='{self.name}', type='{self.handler_type}', enabled={self.enabled})>"
    
    def __str__(self):
        status = "✓" if self.enabled else "✗"
        return f"[{status}] {self.name} ({self.handler_type})"
