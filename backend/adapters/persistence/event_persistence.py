"""
Hook event persistence adapter.

Implements the four hook-event query methods consumed by
`backend/routes/admin/events.py`:

  - get_hook_events           — paginated list with filters
  - get_hook_events_summary   — aggregate counts over a time window
  - get_events_by_trace_id    — all events for a single trace, ordered
  - get_recent_traces         — recent traces grouped by trace_id with summary

Adapted from the reference implementation in
amazon-watcher-backend/backend/adapters/persistence/product_persistence.py
(lines 4839–5034). The only deltas vs. the reference:

  - Model path: database.monitoring.hook_event_model (ref, singular)
    →            database.hooks.hook_event_models (here, plural, post-rename)
  - The `asin` filter is dropped because the framework no longer has
    Amazon-specific domain data. `country_code` is kept as a passthrough
    substring match for callers that still inject it.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func

from adapters.persistence._base import BasePersistenceAdapter

logger = logging.getLogger(__name__)


class DatabaseEventPersistenceAdapter(BasePersistenceAdapter):
    """Hook event query adapter — used by the admin Event Monitor page."""

    def get_hook_events(
        self,
        page: int = 1,
        page_size: int = 50,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict:
        """Paginated list of hook events with optional filters."""
        from database.hooks.hook_event_models import HookEventModel

        def _get(session):
            query = session.query(HookEventModel)
            if event_type:
                query = query.filter(HookEventModel.event_type == event_type)
            if source:
                query = query.filter(HookEventModel.source == source)
            if date_from:
                query = query.filter(HookEventModel.created_at >= date_from)
            if date_to:
                query = query.filter(HookEventModel.created_at <= date_to)

            total = query.count()
            items = (
                query.order_by(HookEventModel.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [
                    {
                        "id": e.id,
                        "event_type": e.event_type,
                        "source": e.source,
                        "trace_id": getattr(e, "trace_id", None),
                        "data": json.loads(e.data_json) if e.data_json else {},
                        "metadata": json.loads(e.metadata_json) if e.metadata_json else {},
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in items
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            }

        return self._execute_with_retry(_get)

    def get_hook_events_summary(self, window_hours: int = 24) -> dict:
        """Aggregate hook event counts grouped by event_type and source."""
        from database.hooks.hook_event_models import HookEventModel

        def _get(session):
            cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
            base = session.query(HookEventModel).filter(HookEventModel.created_at >= cutoff)

            total = base.count()

            by_type_rows = (
                session.query(HookEventModel.event_type, func.count(HookEventModel.id))
                .filter(HookEventModel.created_at >= cutoff)
                .group_by(HookEventModel.event_type)
                .all()
            )
            by_source_rows = (
                session.query(HookEventModel.source, func.count(HookEventModel.id))
                .filter(HookEventModel.created_at >= cutoff)
                .group_by(HookEventModel.source)
                .all()
            )

            return {
                "total_events": total,
                "by_event_type": {row[0]: row[1] for row in by_type_rows},
                "by_source": {(row[0] or "unknown"): row[1] for row in by_source_rows},
                "window_hours": window_hours,
            }

        return self._execute_with_retry(_get)

    def get_events_by_trace_id(self, trace_id: str) -> dict:
        """Return all events for a given trace_id, ordered chronologically."""
        from database.hooks.hook_event_models import HookEventModel

        def _get(session):
            events = (
                session.query(HookEventModel)
                .filter(HookEventModel.trace_id == trace_id)
                .order_by(HookEventModel.created_at.asc())
                .all()
            )
            items = [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "source": e.source,
                    "trace_id": e.trace_id,
                    "data": json.loads(e.data_json) if e.data_json else {},
                    "metadata": json.loads(e.metadata_json) if e.metadata_json else {},
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ]
            duration_ms = None
            if len(events) >= 2 and events[0].created_at and events[-1].created_at:
                delta = events[-1].created_at - events[0].created_at
                duration_ms = int(delta.total_seconds() * 1000)

            return {
                "trace_id": trace_id,
                "events": items,
                "total": len(items),
                "duration_ms": duration_ms,
            }

        return self._execute_with_retry(_get)

    def get_recent_traces(
        self,
        country_code: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """Return recent traces grouped by trace_id with summary info."""
        from database.hooks.hook_event_models import HookEventModel

        def _get(session):
            base = session.query(HookEventModel).filter(HookEventModel.trace_id.isnot(None))

            if date_from:
                base = base.filter(HookEventModel.created_at >= date_from)
            if date_to:
                base = base.filter(HookEventModel.created_at <= date_to)
            if country_code:
                # Fragile but kept for parity with reference: substring match on data_json.
                base = base.filter(HookEventModel.data_json.like(f'%"{country_code}"%'))

            # Subquery: distinct trace_ids with aggregates.
            sub = (
                base.with_entities(
                    HookEventModel.trace_id,
                    func.count(HookEventModel.id).label("event_count"),
                    func.min(HookEventModel.created_at).label("started_at"),
                    func.max(HookEventModel.created_at).label("ended_at"),
                )
                .group_by(HookEventModel.trace_id)
                .order_by(func.max(HookEventModel.created_at).desc())
            )

            total = sub.count()
            rows = sub.offset((page - 1) * page_size).limit(page_size).all()

            traces = []
            for row in rows:
                tid = row[0]
                first_event = (
                    session.query(HookEventModel.event_type)
                    .filter(HookEventModel.trace_id == tid)
                    .order_by(HookEventModel.created_at.asc())
                    .first()
                )
                last_event = (
                    session.query(HookEventModel.event_type)
                    .filter(HookEventModel.trace_id == tid)
                    .order_by(HookEventModel.created_at.desc())
                    .first()
                )
                duration_ms = None
                if row[2] and row[3]:
                    delta = row[3] - row[2]
                    duration_ms = int(delta.total_seconds() * 1000)

                traces.append({
                    "trace_id": tid,
                    "first_event": first_event[0] if first_event else None,
                    "last_event": last_event[0] if last_event else None,
                    "event_count": row[1],
                    "started_at": row[2].isoformat() if row[2] else None,
                    "duration_ms": duration_ms,
                })

            return {
                "traces": traces,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            }

        return self._execute_with_retry(_get)
