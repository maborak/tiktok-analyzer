"""
Notification Commands - Queue consumer and delivery management
"""

import click

from .queue_consume import queue_consume


@click.group()
def notifications():
    """Notification queue commands"""
    pass


notifications.add_command(queue_consume)
