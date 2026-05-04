"""
Composite database persistence adapter.

This module provides the backward-compatible `DatabaseDataPersistenceAdapter` class
that composes all domain-specific sub-adapters via multiple inheritance.

The actual implementations live in the `adapters.persistence` package:
  - _base.py                              -> BasePersistenceAdapter (shared infrastructure)
  - ticket_persistence.py                 -> DatabaseTicketPersistenceAdapter
  - billing_persistence.py                -> DatabaseBillingPersistenceAdapter
  - recipient_persistence.py              -> DatabaseRecipientPersistenceAdapter
  - database_management_persistence.py    -> DatabaseManagementPersistenceAdapter
  - event_persistence.py                  -> DatabaseEventPersistenceAdapter
"""

from adapters.persistence._base import BasePersistenceAdapter, RetrySession, RetryQuery
from adapters.persistence.ticket_persistence import DatabaseTicketPersistenceAdapter
from adapters.persistence.billing_persistence import DatabaseBillingPersistenceAdapter
from adapters.persistence.recipient_persistence import DatabaseRecipientPersistenceAdapter
from adapters.persistence.database_management_persistence import DatabaseManagementPersistenceAdapter
from adapters.persistence.event_persistence import DatabaseEventPersistenceAdapter


class DatabaseDataPersistenceAdapter(
    DatabaseTicketPersistenceAdapter,
    DatabaseBillingPersistenceAdapter,
    DatabaseRecipientPersistenceAdapter,
    DatabaseManagementPersistenceAdapter,
    DatabaseEventPersistenceAdapter,
):
    """
    Backward-compatible composite adapter.

    All method implementations are inherited from domain-specific sub-adapters
    via Python's MRO. The shared database infrastructure (session management,
    retry logic) comes from BasePersistenceAdapter, the common ancestor.

    New code should depend on domain-specific ports (e.g. TicketPersistencePort)
    rather than this composite class.
    """
    pass
