"""
Persistence infrastructure package.

Domain-specific database adapters and shared base class.
"""

from adapters.persistence._base import BasePersistenceAdapter, RetrySession, RetryQuery
from adapters.persistence.ticket_persistence import DatabaseTicketPersistenceAdapter
from adapters.persistence.billing_persistence import DatabaseBillingPersistenceAdapter

__all__ = [
    "BasePersistenceAdapter",
    "RetrySession",
    "RetryQuery",
    "DatabaseTicketPersistenceAdapter",
    "DatabaseBillingPersistenceAdapter",
]
