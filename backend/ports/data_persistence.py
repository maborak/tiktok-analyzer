"""
Data Persistence Port (stub)

Minimal stub for backward compatibility. Services that previously depended on the
full DataPersistencePort now use this as a type hint only. The actual implementation
is provided by DatabaseDataPersistenceAdapter which composes domain-specific sub-adapters.
"""

from abc import ABC


class DataPersistencePort(ABC):
    """Abstract base for data persistence operations.

    This is a minimal stub retained so that existing service constructors
    (CreditService, PaymentService, TicketService, etc.) can still use it
    as a type annotation without import errors.
    """
    pass
