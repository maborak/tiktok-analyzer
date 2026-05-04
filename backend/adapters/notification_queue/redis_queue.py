"""
Redis-backed Notification Queue Adapter

Uses Redis LIST (RPUSH/BLPOP) for pending queues, ZSET for retry scheduling,
and LIST for dead-letter queues. Falls back gracefully when Redis is unavailable.

Key schema:
  nq:pending:{channel}  — LIST  — main work queue
  nq:retry              — ZSET  — delayed retries (score = next_retry_timestamp)
  nq:dlq:{channel}      — LIST  — dead-letter queue
  nq:metrics            — HASH  — counters per channel
  nq:rate:{channel}     — ZSET  — sliding-window rate limiter
"""

import json
import logging
import time
from typing import Optional, List, Dict, Any

from domain.entities.notification_models import NotificationMessage
from ports.notification_queue import NotificationQueuePort
from utils.redis_client import get_redis, mark_redis_unavailable

logger = logging.getLogger(__name__)

# Key prefixes
_PENDING = "nq:pending:{channel}"
_RETRY = "nq:retry"
_DLQ = "nq:dlq:{channel}"
_METRICS = "nq:metrics"


def _pending_key(channel: str) -> str:
    return _PENDING.format(channel=channel)


def _dlq_key(channel: str) -> str:
    return _DLQ.format(channel=channel)


def _metric_field(channel: str, metric: str) -> str:
    return f"{metric}:{channel}"


class RedisNotificationQueueAdapter(NotificationQueuePort):
    """Redis LIST/ZSET implementation of the notification queue."""

    async def enqueue(self, msg: NotificationMessage) -> bool:
        r = get_redis()
        if r is None:
            return False
        try:
            await r.rpush(_pending_key(msg.channel), msg.to_json())
            await self.increment_metric(msg.channel, "enqueued")
            return True
        except Exception as exc:
            logger.warning("NotificationQueue: enqueue failed: %s", exc)
            mark_redis_unavailable()
            return False

    async def dequeue(self, channels: List[str], timeout: int = 1) -> Optional[NotificationMessage]:
        r = get_redis()
        if r is None:
            return None
        try:
            keys = [_pending_key(ch) for ch in channels]
            result = await r.blpop(keys, timeout=timeout)
            if result is None:
                return None
            _key, data = result
            return NotificationMessage.from_json(data)
        except Exception as exc:
            logger.warning("NotificationQueue: dequeue failed: %s", exc)
            mark_redis_unavailable()
            return None

    async def enqueue_retry(self, msg: NotificationMessage, delay_seconds: float) -> bool:
        r = get_redis()
        if r is None:
            return False
        try:
            score = time.time() + delay_seconds
            await r.zadd(_RETRY, {msg.to_json(): score})
            return True
        except Exception as exc:
            logger.warning("NotificationQueue: enqueue_retry failed: %s", exc)
            mark_redis_unavailable()
            return False

    async def move_to_dlq(self, msg: NotificationMessage) -> bool:
        r = get_redis()
        if r is None:
            return False
        try:
            await r.rpush(_dlq_key(msg.channel), msg.to_json())
            await self.increment_metric(msg.channel, "dead_lettered")
            return True
        except Exception as exc:
            logger.warning("NotificationQueue: move_to_dlq failed: %s", exc)
            mark_redis_unavailable()
            return False

    async def promote_due_retries(self) -> int:
        r = get_redis()
        if r is None:
            return 0
        try:
            now = time.time()
            # Get due items (score <= now)
            items = await r.zrangebyscore(_RETRY, "-inf", str(now), start=0, num=100)
            if not items:
                return 0

            promoted = 0
            for item_json in items:
                # Remove from retry ZSET
                removed = await r.zrem(_RETRY, item_json)
                if removed:
                    msg = NotificationMessage.from_json(item_json)
                    await r.rpush(_pending_key(msg.channel), item_json)
                    promoted += 1

            if promoted:
                logger.debug("NotificationQueue: promoted %d retries back to pending", promoted)
            return promoted
        except Exception as exc:
            logger.warning("NotificationQueue: promote_due_retries failed: %s", exc)
            mark_redis_unavailable()
            return 0

    async def get_metrics(self, channel: str) -> Dict[str, Any]:
        r = get_redis()
        if r is None:
            return {"queue_depth": 0, "retry_depth": 0, "dlq_depth": 0, "counters": {}}
        try:
            queue_depth = await r.llen(_pending_key(channel))
            retry_depth = await r.zcard(_RETRY)
            dlq_depth = await r.llen(_dlq_key(channel))

            counters = {}
            for metric in ("enqueued", "delivered", "failed", "dead_lettered"):
                val = await r.hget(_METRICS, _metric_field(channel, metric))
                counters[metric] = int(val) if val else 0

            return {
                "queue_depth": queue_depth,
                "retry_depth": retry_depth,
                "dlq_depth": dlq_depth,
                "counters": counters,
            }
        except Exception as exc:
            logger.warning("NotificationQueue: get_metrics failed: %s", exc)
            mark_redis_unavailable()
            return {"queue_depth": 0, "retry_depth": 0, "dlq_depth": 0, "counters": {}}

    async def get_dlq_items(self, channel: str, page: int = 1, page_size: int = 20) -> List[NotificationMessage]:
        r = get_redis()
        if r is None:
            return []
        try:
            start = (page - 1) * page_size
            end = start + page_size - 1
            items = await r.lrange(_dlq_key(channel), start, end)
            return [NotificationMessage.from_json(item) for item in items]
        except Exception as exc:
            logger.warning("NotificationQueue: get_dlq_items failed: %s", exc)
            mark_redis_unavailable()
            return []

    async def retry_dlq_items(self, channel: str, message_ids: Optional[List[str]] = None) -> int:
        r = get_redis()
        if r is None:
            return 0
        try:
            dlq = _dlq_key(channel)
            pending = _pending_key(channel)
            count = 0

            if message_ids is None:
                # Re-enqueue all DLQ items
                while True:
                    item = await r.lpop(dlq)
                    if item is None:
                        break
                    msg = NotificationMessage.from_json(item)
                    msg.attempt = 1  # Reset attempts
                    await r.rpush(pending, msg.to_json())
                    count += 1
            else:
                # Re-enqueue specific items by ID
                dlq_len = await r.llen(dlq)
                items = await r.lrange(dlq, 0, dlq_len - 1) if dlq_len > 0 else []
                for item_json in items:
                    msg = NotificationMessage.from_json(item_json)
                    if msg.id in message_ids:
                        await r.lrem(dlq, 1, item_json)
                        msg.attempt = 1
                        await r.rpush(pending, msg.to_json())
                        count += 1

            if count:
                logger.info("NotificationQueue: re-enqueued %d DLQ items for channel=%s", count, channel)
            return count
        except Exception as exc:
            logger.warning("NotificationQueue: retry_dlq_items failed: %s", exc)
            mark_redis_unavailable()
            return 0

    async def increment_metric(self, channel: str, metric: str, amount: int = 1) -> None:
        r = get_redis()
        if r is None:
            return
        try:
            await r.hincrby(_METRICS, _metric_field(channel, metric), amount)
        except Exception:
            pass  # Metrics are best-effort
