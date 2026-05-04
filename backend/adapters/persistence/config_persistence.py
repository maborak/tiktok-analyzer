"""SQLAlchemy adapter for :class:`ConfigPort`.

Reads and writes the ``app_config`` table, restricted to the global scope
(``scope='global'``, ``scope_id=''``). The wider per-worker scope is still
handled by :class:`AppConfigAdapter`.
"""

import logging
from typing import Dict, List, Optional

from ports.config_port import ConfigPort

logger = logging.getLogger(__name__)

_GLOBAL_SCOPE = "global"
_GLOBAL_SCOPE_ID = ""


class ConfigAdapter(ConfigPort):
    """Session-factory-based adapter, mirroring the AppConfigAdapter pattern."""

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
        return self._get_session_factory()()

    def get_all_values(self) -> Dict[str, str]:
        Model = self._model()
        session = self._session()
        try:
            rows = (
                session.query(Model)
                .filter(Model.scope == _GLOBAL_SCOPE, Model.scope_id == _GLOBAL_SCOPE_ID)
                .all()
            )
            return {r.key: r.value for r in rows}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_namespace_values(self, namespace: str) -> Dict[str, str]:
        Model = self._model()
        session = self._session()
        try:
            rows = (
                session.query(Model)
                .filter(
                    Model.namespace == namespace,
                    Model.scope == _GLOBAL_SCOPE,
                    Model.scope_id == _GLOBAL_SCOPE_ID,
                )
                .all()
            )
            return {r.key: r.value for r in rows}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_value(self, namespace: str, key: str, value: str,
                  value_type: str, updated_by: Optional[str] = None) -> None:
        Model = self._model()
        session = self._session()
        try:
            row = (
                session.query(Model)
                .filter(
                    Model.namespace == namespace,
                    Model.key == key,
                    Model.scope == _GLOBAL_SCOPE,
                    Model.scope_id == _GLOBAL_SCOPE_ID,
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
                    scope=_GLOBAL_SCOPE,
                    scope_id=_GLOBAL_SCOPE_ID,
                    updated_by=updated_by,
                )
                session.add(row)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def bulk_set(self, entries: List[Dict]) -> int:
        Model = self._model()
        session = self._session()
        count = 0
        try:
            for entry in entries:
                namespace = entry["namespace"]
                key = entry["key"]
                value = entry["value"]
                value_type = entry["value_type"]
                updated_by = entry.get("updated_by")

                row = (
                    session.query(Model)
                    .filter(
                        Model.namespace == namespace,
                        Model.key == key,
                        Model.scope == _GLOBAL_SCOPE,
                        Model.scope_id == _GLOBAL_SCOPE_ID,
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
                        scope=_GLOBAL_SCOPE,
                        scope_id=_GLOBAL_SCOPE_ID,
                        updated_by=updated_by,
                    )
                    session.add(row)
                count += 1
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def export_all(self) -> List[Dict]:
        Model = self._model()
        session = self._session()
        try:
            rows = (
                session.query(Model)
                .filter(Model.scope == _GLOBAL_SCOPE, Model.scope_id == _GLOBAL_SCOPE_ID)
                .order_by(Model.namespace, Model.key)
                .all()
            )
            return [
                {
                    "namespace": r.namespace,
                    "key": r.key,
                    "value": r.value,
                    "value_type": r.value_type,
                    "updated_by": r.updated_by,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_db_metadata(self) -> Dict[str, Dict]:
        Model = self._model()
        session = self._session()
        try:
            rows = (
                session.query(Model)
                .filter(Model.scope == _GLOBAL_SCOPE, Model.scope_id == _GLOBAL_SCOPE_ID)
                .all()
            )
            return {
                r.key: {
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "updated_by": r.updated_by,
                }
                for r in rows
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
