import logging
import os
import sys
from utils.debug import colorize
from config import settings


class CLILogFormatter(logging.Formatter):
    """Custom logging formatter for CLI with colors and icons"""

    LEVEL_COLORS = {
        logging.DEBUG: 'cyan',
        logging.INFO: 'green',
        logging.WARNING: 'yellow',
        logging.ERROR: 'red',
        logging.CRITICAL: 'magenta'
    }

    LEVEL_ICONS = {
        logging.DEBUG: '🔍',
        logging.INFO: 'ℹ️',
        logging.WARNING: '⚠️',
        logging.ERROR: '❌',
        logging.CRITICAL: '🚨'
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, 'white')
        icon = self.LEVEL_ICONS.get(record.levelno, '•')
        timestamp = self.formatTime(record, "%H:%M:%S")

        message = record.getMessage()

        # Detect if it's a data row (contains our custom separator)
        if "∙" in message:
            return f"{colorize(timestamp, 'white')} {icon} {message}"

        # Standard minimalist format
        levelname = f"{record.levelname:5}"
        # Only show logger name if it's not the main 'run' or 'main'
        name = record.name.split('.')[-1]
        name_part = f" {colorize(name, 'magenta')} |" if name not in ['run', 'main', '__main__'] else ""

        if record.levelno >= logging.WARNING:
            message = colorize(message, color)

        return f"{colorize(timestamp, 'white')} {icon} {colorize(levelname, color)}{name_part} {message}"

def configure_logging():
    from utils.logging_config import get_console_formatter, SafeStreamHandler
    from utils.logging_context import ContextFilter

    cli_log_level_str = settings("CLI_LOG_LEVEL", "info").upper()
    cli_log_level = getattr(logging, cli_log_level_str, logging.INFO)

    # CLI defaults to "text" when PHOVEU_BACKEND_LOG_FORMAT is not set;
    # if the env var IS set, both API and CLI share the same format.
    log_format = os.getenv("PHOVEU_BACKEND_LOG_FORMAT", "text")

    console_handler = SafeStreamHandler(sys.stdout)
    console_handler.setFormatter(get_console_formatter(log_format))
    console_handler.addFilter(ContextFilter())

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    root_logger.setLevel(cli_log_level)
    root_logger.addHandler(console_handler)
