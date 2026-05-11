"""Redis pub/sub event bus for the TikTok module.

When the listener pool runs as a separate worker process, the API
process can't reach in-process listeners — so the worker publishes
every event to a Redis channel and the API subscribes to forward to
WebSocket clients.

Two roles in this module:
  - `EventPublisher`: a service-listener-shaped callable that the worker
    registers with `TikTokService.add_listener(...)`. Every match/comment/
    gift envelope flows through it to Redis.
  - `subscribe_events()`: an async generator the API's WS handler reads
    from. Each `yield` is one decoded envelope dict.

Falls back gracefully when Redis is unavailable: publishes silently
no-op, subscribers receive an empty stream and close cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from utils.redis_client import get_redis

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL = "tiktok:events"


class EventPublisher:
    """Service-listener callable that publishes envelopes to Redis."""

    def __init__(self, channel: str = DEFAULT_CHANNEL) -> None:
        self._channel = channel
        self._warned_unavailable = False

    async def __call__(self, envelope: dict[str, Any]) -> None:
        await self.publish(envelope)

    async def publish(self, envelope: dict[str, Any]) -> None:
        r = get_redis()
        if r is None:
            if not self._warned_unavailable:
                logger.warning(
                    "Redis unavailable; event fan-out disabled. "
                    "DB persistence still works."
                )
                self._warned_unavailable = True
            return
        try:
            await r.publish(self._channel, json.dumps(envelope))
            self._warned_unavailable = False
        except Exception:
            logger.exception("Redis publish failed for envelope type=%s", envelope.get("type"))


async def subscribe_events(
    *, channel: str = DEFAULT_CHANNEL, stop: asyncio.Event | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding event envelopes received on the channel.

    Caller is expected to drive this from a websocket handler. If `stop` is
    provided, the generator terminates when stop.set() is called.
    """
    r = get_redis()
    if r is None:
        logger.warning("Redis unavailable; tiktok events subscriber returning empty stream.")
        return
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(channel)
        while True:
            if stop is not None and stop.is_set():
                break
            # `get_message` with a short timeout lets us check `stop` regularly
            # without blocking forever on an idle channel.
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None:
                continue
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if not data:
                continue
            try:
                yield json.loads(data) if isinstance(data, str) else json.loads(data.decode())
            except (TypeError, ValueError):
                logger.warning("Discarded non-JSON message on %s", channel)
                continue
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            logger.exception("Error closing pubsub for %s", channel)
