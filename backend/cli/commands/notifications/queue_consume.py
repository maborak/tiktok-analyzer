"""
CLI command: monitor queue-consume

Runs the async notification consumer as a standalone long-lived process.
Dequeues notifications from Redis and delivers them via channel-specific adapters.

Usage:
    python cli.py monitor queue-consume                    # all channels
    python cli.py monitor queue-consume --channel=email    # email only
    python cli.py monitor queue-consume -c 20              # 20 concurrent deliveries
    python cli.py monitor queue-consume --dry-run          # log without sending
"""

import asyncio
import logging
import signal

import click

logger = logging.getLogger(__name__)


@click.command(name="queue-consume")
@click.option(
    "--channel",
    type=click.Choice(["all", "email", "telegram", "slack", "webhook"], case_sensitive=False),
    default="all",
    help="Which channel(s) to consume (default: all)",
)
@click.option("--concurrency", "-c", type=int, default=None, help="Max concurrent deliveries (default: from config)")
@click.option("--rate-max", type=int, default=None, help="Max deliveries per rate window (default: from config)")
@click.option("--rate-window", type=int, default=None, help="Rate window in seconds (default: from config)")
@click.option("--dry-run", is_flag=True, help="Log what would be sent without actually delivering")
@click.pass_context
def queue_consume(ctx, channel, concurrency, rate_max, rate_window, dry_run):
    """Consume notification queue and deliver messages.

    Runs as a long-lived process. Connects to the same Redis instance
    as the API server. Scale by running multiple instances — each BLPOP
    is atomic, so no duplicate delivery.

    \b
    Examples:
      python cli.py monitor queue-consume
      python cli.py monitor queue-consume --channel=email -c 10
      python cli.py monitor queue-consume --dry-run
    """
    from config import CONFIG

    # Resolve config with CLI overrides
    concurrency = concurrency or CONFIG.get("NOTIFICATION_QUEUE_EMAIL_CONCURRENCY", 10)
    rate_max = rate_max or CONFIG.get("NOTIFICATION_QUEUE_EMAIL_RATE_MAX", 100)
    rate_window = rate_window or CONFIG.get("NOTIFICATION_QUEUE_EMAIL_RATE_WINDOW", 60)
    retry_base = CONFIG.get("NOTIFICATION_QUEUE_RETRY_BASE_SECONDS", 30)
    retry_max = CONFIG.get("NOTIFICATION_QUEUE_RETRY_MAX_SECONDS", 3600)
    retry_poll = CONFIG.get("NOTIFICATION_QUEUE_RETRY_POLL_INTERVAL", 5)
    shutdown_timeout = CONFIG.get("NOTIFICATION_QUEUE_CONSUMER_SHUTDOWN_TIMEOUT", 30)

    from utils.logging_context import set_trace_id
    trace_id = set_trace_id()

    logger.info(
        "Notification consumer starting",
        extra={
            "channel": channel,
            "concurrency": concurrency,
            "rate_max": rate_max,
            "rate_window": rate_window,
            "dry_run": dry_run,
        },
    )

    try:
        asyncio.run(_run_consumer(
            channel=channel,
            concurrency=concurrency,
            rate_max=rate_max,
            rate_window=rate_window,
            retry_base=retry_base,
            retry_max=retry_max,
            retry_poll=retry_poll,
            shutdown_timeout=shutdown_timeout,
            dry_run=dry_run,
        ))
    except KeyboardInterrupt:
        logger.info("Shutdown complete")


async def _run_consumer(
    channel: str,
    concurrency: int,
    rate_max: int,
    rate_window: int,
    retry_base: int,
    retry_max: int,
    retry_poll: int,
    shutdown_timeout: int,
    dry_run: bool,
) -> None:
    """Async entry point — initializes Redis, builds adapters, runs consumer."""
    # Initialize Redis
    from utils.redis_client import init_redis, close_redis, is_redis_available
    await init_redis()

    if not is_redis_available():
        logger.error("Redis is not available — configure PHOVEU_REDIS_SERVER and ensure Redis is running")
        return

    # Build delivery registry
    from adapters.notification_delivery.email import EmailDeliveryAdapter
    all_adapters = {
        "email": EmailDeliveryAdapter(),
        # Future: "telegram": TelegramDeliveryAdapter(), "slack": SlackDeliveryAdapter(), etc.
    }

    if channel == "all":
        delivery_registry = all_adapters
    elif channel in all_adapters:
        delivery_registry = {channel: all_adapters[channel]}
    else:
        logger.warning("No adapter available for channel '%s' — available: %s", channel, list(all_adapters.keys()))
        await close_redis()
        return

    # Build queue adapter
    from adapters.notification_queue.redis_queue import RedisNotificationQueueAdapter
    queue = RedisNotificationQueueAdapter()

    # Initialize data persistence + hook_manager so EMAIL_SENT/FAILED events are recorded
    hook_manager = None
    try:
        from adapters.database_persistence import DatabaseDataPersistenceAdapter
        from ports.hooks import hook_manager as _hm
        data_persistence = DatabaseDataPersistenceAdapter(auto_init=False)
        _hm.configure(data_persistence=data_persistence)
        hook_manager = _hm
        logger.info("Hook manager configured for event persistence")
    except Exception as exc:
        logger.warning("Could not initialize hook_manager (events won't be persisted): %s", exc)

    # Build consumer
    from ports.notification_queue.consumer import NotificationConsumer
    consumer = NotificationConsumer(
        queue=queue,
        delivery_registry=delivery_registry,
        concurrency=concurrency,
        rate_max=rate_max,
        rate_window=rate_window,
        retry_base_seconds=retry_base,
        retry_max_seconds=retry_max,
        retry_poll_interval=retry_poll,
        shutdown_timeout=shutdown_timeout,
        dry_run=dry_run,
        hook_manager=hook_manager,
    )

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(consumer.shutdown()))

    try:
        await consumer.run()
    finally:
        await close_redis()
