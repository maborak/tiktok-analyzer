from ..core.base import Base
from sqlalchemy import Column, String, Integer, DateTime, UniqueConstraint, Index, func
from config import get_table_name


class AppConfigModel(Base):
    """Generic namespace/key/value configuration with per-worker override support."""
    __tablename__ = get_table_name("app_config")

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String(100), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(String(500), nullable=False)
    value_type = Column(String(20), nullable=False, server_default="string")  # int, string, boolean
    scope = Column(String(20), nullable=False, server_default="global")       # global, worker
    scope_id = Column(String(50), nullable=False, server_default="")          # worker ID when scope=worker, "" for global
    updated_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, server_default=func.current_timestamp(),
                       onupdate=func.current_timestamp(), nullable=False)

    __table_args__ = (
        UniqueConstraint("namespace", "key", "scope", "scope_id",
                         name="uq_app_config_ns_key_scope"),
        Index("idx_app_config_namespace", "namespace"),
        Index("idx_app_config_scope", "scope", "scope_id"),
    )

    def __repr__(self):
        scope_str = f"{self.scope}:{self.scope_id}" if self.scope_id else self.scope
        return f"<AppConfig({self.namespace}.{self.key}={self.value} [{scope_str}])>"

    def to_dict(self):
        return {
            "id": self.id,
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "value_type": self.value_type,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
