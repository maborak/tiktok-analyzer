"""SQLAlchemy adapter for event configuration persistence."""

import logging
from typing import List, Dict, Any

from ports.event_config import EventConfigPort

logger = logging.getLogger(__name__)


class EventConfigAdapter(EventConfigPort):
    """
    Implements EventConfigPort with SQLAlchemy.

    Uses its own session factory (thread-safe, isolated from request lifecycle),
    following the same pattern as EventPersistenceHandler.
    """

    def __init__(self):
        self._session_factory = None

    def _get_session_factory(self):
        if self._session_factory is None:
            from database.core.connection import create_database_engine, get_session_maker
            engine = create_database_engine()
            self._session_factory = get_session_maker(engine)
        return self._session_factory

    def get_all_event_configs(self) -> List[Dict[str, Any]]:
        from database.hooks.event_config_models import EventConfigModel
        session = self._get_session_factory()()
        try:
            rows = session.query(EventConfigModel).all()
            return [
                {
                    "event_type": r.event_type,
                    "handler_name": r.handler_name,
                    "enabled": r.enabled,
                }
                for r in rows
            ]
        finally:
            session.close()

    def upsert_event_config(self, event_type: str, handler_name: str, enabled: bool) -> Dict[str, Any]:
        from database.hooks.event_config_models import EventConfigModel
        session = self._get_session_factory()()
        try:
            row = (
                session.query(EventConfigModel)
                .filter_by(event_type=event_type, handler_name=handler_name)
                .first()
            )
            if row:
                row.enabled = enabled
            else:
                row = EventConfigModel(
                    event_type=event_type,
                    handler_name=handler_name,
                    enabled=enabled,
                )
                session.add(row)
            session.commit()
            return {
                "event_type": row.event_type,
                "handler_name": row.handler_name,
                "enabled": row.enabled,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def bulk_upsert_event_configs(self, updates: List[Dict[str, Any]]) -> int:
        from database.hooks.event_config_models import EventConfigModel
        session = self._get_session_factory()()
        count = 0
        try:
            for update in updates:
                et = update["event_type"]
                hn = update["handler_name"]
                en = update["enabled"]
                row = (
                    session.query(EventConfigModel)
                    .filter_by(event_type=et, handler_name=hn)
                    .first()
                )
                if row:
                    row.enabled = en
                else:
                    session.add(EventConfigModel(event_type=et, handler_name=hn, enabled=en))
                count += 1
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
