"""
Notification Delivery Port — channel-agnostic interface for sending notifications.

Each delivery channel (email, Telegram, Slack, webhook) implements this port.
The NotificationConsumer routes messages to the correct adapter based on msg.channel.
"""

from abc import ABC, abstractmethod

from domain.entities.notification_models import NotificationMessage


class NotificationDeliveryPort(ABC):
    """Port for delivering a single notification via a specific channel."""

    @abstractmethod
    async def deliver(self, msg: NotificationMessage) -> bool:
        """
        Deliver a notification message. Returns True on success, False on failure.

        Implementations should raise:
        - TransientDeliveryError for retryable failures (timeouts, 4xx, connection errors)
        - PermanentDeliveryError for non-retryable failures (5xx, invalid recipient)
        """
        pass


class TransientDeliveryError(Exception):
    """Retryable delivery failure (connection timeout, SMTP 4xx, temporary unavailability)."""
    pass


class PermanentDeliveryError(Exception):
    """Non-retryable delivery failure (SMTP 5xx, invalid recipient, malformed message)."""
    pass
