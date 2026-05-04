"""SQLAlchemy adapter for :class:`ConfigSnapshotPort`.

Persists snapshots to the ``config_snapshots`` table. Same
session-factory-per-adapter pattern as :class:`ConfigAdapter`.
"""

import logging
from typing import Dict, List, Optional

from ports.config_snapshot_port import ConfigSnapshotPort

logger = logging.getLogger(__name__)


class ConfigSnapshotAdapter(ConfigSnapshotPort):
    def __init__(self):
        self._session_factory = None

    def _get_session_factory(self):
        if self._session_factory is None:
            from database.core.connection import create_database_engine, get_session_maker
            engine = create_database_engine()
            self._session_factory = get_session_maker(engine)
        return self._session_factory

    def _model(self):
        from database.config.config_snapshot_models import ConfigSnapshotModel
        return ConfigSnapshotModel

    def _session(self):
        return self._get_session_factory()()

    def create(
        self,
        name: str,
        description: Optional[str],
        trigger: str,
        payload: str,
        key_count: int,
        created_by: Optional[str],
        parent_snapshot_id: Optional[int] = None,
    ) -> int:
        Model = self._model()
        session = self._session()
        try:
            row = Model(
                name=name,
                description=description,
                trigger=trigger,
                payload=payload,
                key_count=key_count,
                created_by=created_by,
                parent_snapshot_id=parent_snapshot_id,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list(self, limit: int = 50, offset: int = 0,
             trigger: Optional[str] = None) -> List[Dict]:
        Model = self._model()
        session = self._session()
        try:
            q = session.query(Model)
            if trigger:
                q = q.filter(Model.trigger == trigger)
            rows = (
                q.order_by(Model.created_at.desc(), Model.id.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            return [r.to_dict(include_payload=False) for r in rows]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def count(self, trigger: Optional[str] = None) -> int:
        Model = self._model()
        session = self._session()
        try:
            q = session.query(Model)
            if trigger:
                q = q.filter(Model.trigger == trigger)
            return q.count()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get(self, snapshot_id: int, include_payload: bool = False) -> Optional[Dict]:
        Model = self._model()
        session = self._session()
        try:
            row = session.query(Model).filter(Model.id == snapshot_id).first()
            if row is None:
                return None
            return row.to_dict(include_payload=include_payload)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete(self, snapshot_id: int) -> bool:
        Model = self._model()
        session = self._session()
        try:
            row = session.query(Model).filter(Model.id == snapshot_id).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def prune_oldest_non_manual(self, keep: int) -> int:
        Model = self._model()
        session = self._session()
        try:
            keep_rows = (
                session.query(Model)
                .filter(Model.trigger != "manual")
                .order_by(Model.created_at.desc(), Model.id.desc())
                .limit(keep)
                .all()
            )
            keep_ids = {r.id for r in keep_rows}
            victims = (
                session.query(Model)
                .filter(Model.trigger != "manual")
                .filter(~Model.id.in_(keep_ids) if keep_ids else Model.id.isnot(None))
                .all()
            )
            deleted = 0
            for v in victims:
                session.delete(v)
                deleted += 1
            session.commit()
            return deleted
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
