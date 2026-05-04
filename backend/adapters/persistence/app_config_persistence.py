"""SQLAlchemy adapter for generic app configuration persistence."""

import logging
from typing import List, Dict, Any, Optional

from ports.app_config import AppConfigPort

logger = logging.getLogger(__name__)


class AppConfigAdapter(AppConfigPort):
    """
    Implements AppConfigPort with SQLAlchemy.

    Uses its own session factory (thread-safe, isolated from request lifecycle),
    following the same pattern as EventConfigAdapter.
    """

    def __init__(self):
        self._session_factory = None

    def _get_session_factory(self):
        if self._session_factory is None:
            from database.core.connection import create_database_engine, get_session_maker
            engine = create_database_engine()
            self._session_factory = get_session_maker(engine)
        return self._session_factory

    def _model(self):
        from database.config.app_config_models import AppConfigModel
        return AppConfigModel

    def _session(self):
        """Create a session via the lazy factory. Use in a try/finally block."""
        return self._get_session_factory()()

    def get_by_namespace(self, namespace: str, scope: str = "global",
                         scope_id: Optional[str] = None) -> List[Dict[str, Any]]:
        Model = self._model()
        session = self._session()
        try:
            q = session.query(Model).filter(Model.namespace == namespace)
            if scope != "all":
                q = q.filter(Model.scope == scope)
                if scope_id is not None:
                    q = q.filter(Model.scope_id == scope_id)
            return [r.to_dict() for r in q.order_by(Model.key).all()]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_merged_config(self, namespace: str,
                          worker_id: Optional[int] = None) -> Dict[str, str]:
        Model = self._model()
        session = self._session()
        try:
            globals_ = (
                session.query(Model)
                .filter(Model.namespace == namespace, Model.scope == "global")
                .all()
            )
            merged = {r.key: r.value for r in globals_}

            if worker_id is not None:
                overrides = (
                    session.query(Model)
                    .filter(
                        Model.namespace == namespace,
                        Model.scope == "worker",
                        Model.scope_id == str(worker_id),
                    )
                    .all()
                )
                for r in overrides:
                    merged[r.key] = r.value

            return merged
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_value(self, namespace: str, key: str, value: str, value_type: str,
                  scope: str, scope_id: Optional[str],
                  updated_by: Optional[str]) -> Dict[str, Any]:
        Model = self._model()
        # Normalize scope_id: None → "" for UNIQUE constraint safety on PostgreSQL
        effective_scope_id = scope_id or ""
        session = self._session()
        try:
            row = (
                session.query(Model)
                .filter(
                    Model.namespace == namespace,
                    Model.key == key,
                    Model.scope == scope,
                    Model.scope_id == effective_scope_id,
                )
                .first()
            )
            if row:
                row.value = value
                row.value_type = value_type
                row.updated_by = updated_by
            else:
                row = Model(
                    namespace=namespace,
                    key=key,
                    value=value,
                    value_type=value_type,
                    scope=scope,
                    scope_id=effective_scope_id,
                    updated_by=updated_by,
                )
                session.add(row)
            session.commit()
            session.refresh(row)
            return row.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_value(self, namespace: str, key: str,
                     scope: str, scope_id: Optional[str]) -> bool:
        Model = self._model()
        effective_scope_id = scope_id or ""
        session = self._session()
        try:
            count = (
                session.query(Model)
                .filter(
                    Model.namespace == namespace,
                    Model.key == key,
                    Model.scope == scope,
                    Model.scope_id == effective_scope_id,
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return count > 0
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_all_namespaces(self) -> List[str]:
        Model = self._model()
        session = self._session()
        try:
            rows = session.query(Model.namespace).distinct().order_by(Model.namespace).all()
            return [r[0] for r in rows]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_all_configs(self) -> List[Dict[str, Any]]:
        Model = self._model()
        session = self._session()
        try:
            rows = session.query(Model).order_by(Model.namespace, Model.key).all()
            return [r.to_dict() for r in rows]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
