from ..core.base import Base
from sqlalchemy import Column, String, Integer, DateTime, Boolean, UniqueConstraint, func
from config import get_table_name


class EventConfigModel(Base):
    """Per (event_type, handler) enable/disable configuration."""
    __tablename__ = get_table_name("event_configs")

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False, index=True)
    handler_name = Column(String(100), nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(),
                       onupdate=func.current_timestamp(), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_type", "handler_name", name="uq_event_config"),
    )

    def __repr__(self):
        return f"<EventConfig(event_type='{self.event_type}', handler='{self.handler_name}', enabled={self.enabled})>"
