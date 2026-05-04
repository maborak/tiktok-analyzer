import click
import logging
import sys

from utils.email.imap_poller import ImapPoller

logger = logging.getLogger(__name__)

@click.group()
def support():
    """Support & Ticketing System Management"""
    pass

@support.command("check-inbound")
@click.option('--test', is_flag=True, help="Test IMAP connectivity and show mailbox stats without processing emails.")
@click.option('--debug', is_flag=True, help="Enable debug logging for troubleshooting.")
@click.pass_context
def check_inbound(ctx, test, debug):
    """
    Poll the IMAP inbox for unread support emails and convert them into tickets.
    """
    if debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        click.echo("🔍 Debug mode enabled")

    click.echo("🔄 Checking inbound support mailbox...")
    logger.debug("check_inbound command started")

    services = ctx.obj.get('services')
    if not services:
        click.echo("❌ Services not initialized.", err=True)
        sys.exit(1)

    ticket_service = services.ticket_service
    logger.debug("ticket_service = %s", ticket_service)
    poller = ImapPoller(ticket_service)
    logger.debug("ImapPoller created")

    if not poller.connect():
        click.echo("❌ Failed to connect to IMAP. Check PHOVEU_SUPPORT_INBOUND_* configuration.", err=True)
        sys.exit(1)

    logger.debug("IMAP connected successfully")

    try:
        if test:
            stats = poller.test_connection()
            click.echo(f"✅ Connection successful!")
            if stats:
                click.echo(f"📊 Mailbox Stats: {stats['total_messages']} total, {stats['unread_messages']} unread.")
        else:
            logger.debug("Starting poll_inbox...")
            processed = poller.poll_inbox()
            logger.debug("poll_inbox returned %d processed messages", processed)
            if processed > 0:
                click.echo(f"✅ Successfully processed {processed} inbound emails into the Ticket System.")
            else:
                click.echo("✅ Mailbox checked. No new unread support emails found.")
    except Exception as e:
        logger.error(f"Error during check-inbound execution: {e}")
        click.echo(f"❌ Error processing inbox: {e}", err=True)
        sys.exit(1)
    finally:
        poller.disconnect()
        logger.debug("IMAP disconnected")
