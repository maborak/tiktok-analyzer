from ..core.base import Base
from sqlalchemy import Column, String, Integer, Text, DateTime, Index, func
from config import get_table_name


class ConfigSnapshotModel(Base):
    """Point-in-time capture of DB-stored config for rollback and audit.

    Only the rows present in ``app_config`` at snapshot time are stored.
    Env values and registry defaults re-resolve on restore so the payload
    stays compact and the replayed state still respects the resolution
    chain.
    """
    __tablename__ = get_table_name("config_snapshots")

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000), nullable=True)
    # manual | pre_import | pre_seed | pre_rollback
    trigger = Column(String(32), nullable=False, server_default="manual")
    # JSON array of {namespace, key, value, value_type} replayable via bulk_set.
    # TEXT because SQLite has no JSON column type.
    payload = Column(Text, nullable=False)
    key_count = Column(Integer, nullable=False, server_default="0")
    # Links the pre_rollback snapshot created by a restore back to the
    # snapshot that was restored — makes rollbacks reversible.
    parent_snapshot_id = Column(Integer, nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)

    __table_args__ = (
        Index("idx_config_snapshots_created_at", "created_at"),
        Index("idx_config_snapshots_trigger", "trigger"),
    )

    def to_dict(self, include_payload: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "key_count": self.key_count,
            "parent_snapshot_id": self.parent_snapshot_id,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_payload:
            data["payload"] = self.payload
        return data
