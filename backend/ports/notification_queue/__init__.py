"""
Notification Queue Port — abstract interface for enqueue/dequeue/retry/DLQ operations.

Implementations: RedisNotificationQueueAdapter (adapters/notification_queue/redis_queue.py)
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

from domain.entities.notification_models import NotificationMessage


class NotificationQueuePort(ABC):
    """Port for notification queue operations (Redis-backed or in-memory)."""

    @abstractmethod
    async def enqueue(self, msg: NotificationMessage) -> bool:
        """Push a notification to the pending queue for its channel. Returns True on success."""
        pass

    @abstractmethod
    async def dequeue(self, channels: List[str], timeout: int = 1) -> Optional[NotificationMessage]:
        """
        Blocking pop from one of the pending queues (round-robin via BLPOP).
        Returns None on timeout or unavailability.
        """
        pass

    @abstractmethod
    async def enqueue_retry(self, msg: NotificationMessage, delay_seconds: float) -> bool:
        """Push a message to the retry ZSET with score = now + delay_seconds."""
        pass

    @abstractmethod
    async def move_to_dlq(self, msg: NotificationMessage) -> bool:
        """Move a permanently failed message to the dead-letter queue."""
        pass

    @abstractmethod
    async def promote_due_retries(self) -> int:
        """
        Move messages whose retry time has passed from the retry ZSET
        back to their channel's pending queue. Returns count promoted.
        """
        pass

    @abstractmethod
    async def get_metrics(self, channel: str) -> Dict[str, Any]:
        """
        Return queue metrics for a channel:
        - queue_depth: items in pending queue
        - retry_depth: items in retry ZSET
        - dlq_depth: items in DLQ
        - counters: enqueued, delivered, failed, dead_lettered
        """
        pass

    @abstractmethod
    async def get_dlq_items(self, channel: str, page: int = 1, page_size: int = 20) -> List[NotificationMessage]:
        """Return paginated items from the dead-letter queue."""
        pass

    @abstractmethod
    async def retry_dlq_items(self, channel: str, message_ids: Optional[List[str]] = None) -> int:
        """
        Re-enqueue DLQ items back to the pending queue.
        If message_ids is None, re-enqueue all. Returns count re-enqueued.
        """
        pass

    @abstractmethod
    async def increment_metric(self, channel: str, metric: str, amount: int = 1) -> None:
        """Increment a counter metric (enqueued, delivered, failed, dead_lettered)."""
        pass
