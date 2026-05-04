"""
Notification Consumer — async worker that dequeues and delivers notifications.

Runs as a standalone process via `python cli.py monitor queue-consume`.
Uses asyncio for concurrent delivery with configurable concurrency, retry,
rate limiting, and dead-letter queue support.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Set

from config import CONFIG
from domain.entities.notification_models import NotificationMessage
from ports.notification_queue import NotificationQueuePort
from ports.notification_delivery import (
    NotificationDeliveryPort,
    TransientDeliveryError,
    PermanentDeliveryError,
)

logger = logging.getLogger(__name__)


class NotificationConsumer:
    """Async consumer that dequeues notifications and delivers them via channel adapters."""

    def __init__(
        self,
        queue: NotificationQueuePort,
        delivery_registry: Dict[str, NotificationDeliveryPort],
        concurrency: int = 10,
        rate_max: int = 100,
        rate_window: int = 60,
        retry_base_seconds: int = 30,
        retry_max_seconds: int = 3600,
        retry_poll_interval: int = 5,
        shutdown_timeout: int = 30,
        dry_run: bool = False,
        hook_manager=None,
    ):
        self.queue = queue
        self.delivery_registry = delivery_registry
        self.hook_manager = hook_manager
        self.channels = list(delivery_registry.keys())
        self.concurrency = concurrency
        self.rate_max = rate_max
        self.rate_window = rate_window
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.retry_poll_interval = retry_poll_interval
        self.shutdown_timeout = shutdown_timeout
        self.dry_run = dry_run

        self._semaphore = asyncio.Semaphore(concurrency)
        self._running = True
        self._tasks: Set[asyncio.Task] = set()
        self._delivered = 0
        self._failed = 0

    async def run(self) -> None:
        """Main consumer loop. Call via asyncio.run() from the CLI command."""
        logger.info(
            "NotificationConsumer started: channels=%s, concurrency=%d, rate=%d/%ds, dry_run=%s",
            self.channels, self.concurrency, self.rate_max, self.rate_window, self.dry_run,
        )

        # Start retry promoter as background sub-task
        promoter_task = asyncio.create_task(self._retry_promoter())

        try:
            while self._running:
                msg = await self.queue.dequeue(self.channels, timeout=1)
                if msg is None:
                    continue

                adapter = self.delivery_registry.get(msg.channel)
                if not adapter:
                    logger.warning("No adapter for channel=%s, moving to DLQ (msg.id=%s)", msg.channel, msg.id)
                    await self.queue.move_to_dlq(msg)
                    continue

                # Rate limit check
                if not await self._check_rate_limit(msg.channel):
                    # Over rate limit — re-enqueue with short delay
                    await self.queue.enqueue_retry(msg, delay_seconds=self.rate_window / self.rate_max)
                    continue

                # Acquire semaphore slot and deliver concurrently
                await self._semaphore.acquire()
                task = asyncio.create_task(self._deliver_with_semaphore(msg, adapter))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        except asyncio.CancelledError:
            logger.info("NotificationConsumer: cancelled, draining in-flight tasks...")
        finally:
            promoter_task.cancel()
            try:
                await promoter_task
            except asyncio.CancelledError:
                pass

            if self._tasks:
                logger.info("NotificationConsumer: waiting for %d in-flight tasks...", len(self._tasks))
                await asyncio.wait(self._tasks, timeout=self.shutdown_timeout)

            logger.info(
                "NotificationConsumer stopped: delivered=%d, failed=%d",
                self._delivered, self._failed,
            )

    async def shutdown(self) -> None:
        """Signal the consumer to stop after draining in-flight deliveries."""
        logger.info("NotificationConsumer: shutdown requested")
        self._running = False

    async def _deliver_with_semaphore(self, msg: NotificationMessage, adapter: NotificationDeliveryPort) -> None:
        """Wrapper that releases the semaphore after delivery."""
        try:
            await self._deliver(msg, adapter)
        finally:
            self._semaphore.release()

    async def _deliver(self, msg: NotificationMessage, adapter: NotificationDeliveryPort) -> None:
        """Deliver a single notification with retry/DLQ error handling."""
        start = time.monotonic()
        try:
            if self.dry_run:
                logger.info(
                    "[DRY RUN] Would deliver %s to %s: %s (attempt %d/%d)",
                    msg.channel, msg.recipient_email, msg.subject, msg.attempt, msg.max_attempts,
                )
                await self.queue.increment_metric(msg.channel, "delivered")
                self._delivered += 1
                return

            await adapter.deliver(msg)

            elapsed_ms = int((time.monotonic() - start) * 1000)
            meta = {
                "id": msg.id,
                "channel": msg.channel,
                "recipient": msg.recipient_email,
                "subject": msg.subject,
                "event_type": msg.event_type,
                "asin": msg.asin,
                "country_code": msg.country_code,
                "user_id": msg.user_id,
                "alert_id": msg.alert_id,
                "track_id": msg.track_id,
                "recipient_id": msg.recipient_id,
                "trace_id": msg.trace_id,
                "attempt": f"{msg.attempt}/{msg.max_attempts}",
                "elapsed_ms": elapsed_ms,
                "body_preview": msg.body[:80].replace("\n", " ") + "..." if len(msg.body) > 80 else msg.body,
            }
            logger.info("Delivered | %s", meta)
            await self.queue.increment_metric(msg.channel, "delivered")
            self._delivered += 1
            self._fire_event("EMAIL_SENT", msg)

        except TransientDeliveryError as exc:
            await self._handle_transient_failure(msg, exc)

        except PermanentDeliveryError as exc:
            logger.error(
                "Permanent failure for %s to %s: %s (moving to DLQ)",
                msg.channel, msg.recipient_email, exc,
            )
            await self.queue.move_to_dlq(msg)
            await self.queue.increment_metric(msg.channel, "failed")
            self._failed += 1
            self._fire_event("EMAIL_FAILED", msg, error=str(exc))

        except Exception as exc:
            logger.error(
                "Unexpected error delivering %s to %s: %s",
                msg.channel, msg.recipient_email, exc, exc_info=True,
            )
            await self._handle_transient_failure(msg, exc)

    async def _handle_transient_failure(self, msg: NotificationMessage, exc: Exception) -> None:
        """Handle a transient failure: retry or move to DLQ."""
        if msg.attempt >= msg.max_attempts:
            logger.error(
                "Max retries (%d) exhausted for %s to %s: %s (moving to DLQ)",
                msg.max_attempts, msg.channel, msg.recipient_email, exc,
            )
            await self.queue.move_to_dlq(msg)
            await self.queue.increment_metric(msg.channel, "failed")
            self._failed += 1
            return

        msg.attempt += 1
        delay = min(
            self.retry_base_seconds * (2 ** (msg.attempt - 2)),
            self.retry_max_seconds,
        )
        logger.warning(
            "Transient failure for %s to %s (attempt %d/%d): %s — retry in %ds",
            msg.channel, msg.recipient_email, msg.attempt, msg.max_attempts, exc, delay,
        )
        await self.queue.enqueue_retry(msg, delay_seconds=delay)

    async def _retry_promoter(self) -> None:
        """Periodically move due items from the retry ZSET back to pending queues."""
        while self._running:
            try:
                promoted = await self.queue.promote_due_retries()
                if promoted:
                    logger.debug("Retry promoter: moved %d items back to pending", promoted)
            except Exception as exc:
                logger.warning("Retry promoter error: %s", exc)
            await asyncio.sleep(self.retry_poll_interval)

    def _fire_event(self, event_type_name: str, msg: NotificationMessage, error: Optional[str] = None) -> None:
        """Fire EMAIL_SENT / EMAIL_FAILED hook event so EventPersistenceHandler records it."""
        if self.hook_manager is None:
            return
        try:
            from ports.hooks.base_handler import HookEvent, HookEventType
            event_type = getattr(HookEventType, event_type_name, None)
            if event_type is None:
                return
            data = {
                "recipient": msg.recipient_email,
                "subject": msg.subject,
                "event_type": msg.event_type,
                "channel": msg.channel,
                "attempt": msg.attempt,
            }
            if error:
                data["error"] = error
            self.hook_manager.fire(HookEvent(
                event_type=event_type,
                source="NotificationConsumer",
                trace_id=msg.trace_id,
                data=data,
            ), async_mode=False)
        except Exception as exc:
            logger.debug("_fire_event failed (non-critical): %s", exc)

    async def _check_rate_limit(self, channel: str) -> bool:
        """
        Sliding-window rate limit check using Redis sorted set.
        Returns True if under the limit.
        """
        from utils.redis_client import get_redis
        r = get_redis()
        if r is None:
            return True  # No Redis = no rate limiting

        key = f"nq:rate:{channel}"
        now = time.time()
        window_start = now - self.rate_window

        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, "-inf", str(window_start))
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{id(self)}": now})
            pipe.expire(key, self.rate_window + 10)
            results = await pipe.execute()

            current_count = results[1]
            if current_count >= self.rate_max:
                # Over limit — remove the entry we just added
                await r.zrem(key, f"{now}:{id(self)}")
                return False
            return True
        except Exception:
            return True  # Fail open on rate limit errors
