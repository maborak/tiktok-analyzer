from ..core.base import Base
from sqlalchemy import Column, String, Integer, DateTime, Text, Index, func
from config import get_table_name


class HookEventModel(Base):
    __tablename__ = get_table_name("hook_events")

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False, index=True)
    source = Column(String(100), nullable=True, index=True)
    trace_id = Column(String(36), nullable=True, index=True)
    data_json = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_hook_events_type_created", "event_type", "created_at"),
    )

    def __repr__(self):
        return f"<HookEvent(id={self.id}, type='{self.event_type}', source='{self.source}')>"
