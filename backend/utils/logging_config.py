"""
Centralised JSON logging configuration for the API.

Usage (composition root only):
    from utils.logging_config import configure_logging
    configure_logging(log_level="info", log_output="both", log_format="json")

LOG_FORMAT controls console output shape (file handlers always use compact JSON):
    "json"   — compact single-line JSON (default, for Filebeat / log aggregation)
    "pretty" — indented JSON with ANSI color syntax highlighting (for dev terminals)
    "text"   — colored icon-based human-readable lines (CLI default)
"""

import json as _json
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

from pythonjsonlogger import jsonlogger


_LOG_FIELDS = (
    "%(asctime)s %(name)s %(levelname)s %(message)s "
    "%(trace_id)s %(request_id)s %(user_id)s %(http_method)s %(http_path)s"
)


class AppJsonFormatter(jsonlogger.JsonFormatter):
    """Adds static 'service' field and renames asctime -> timestamp for Filebeat."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["service"] = "maborak-framework-api"
        if "asctime" in log_record:
            log_record["timestamp"] = log_record.pop("asctime")
        log_record.pop("color_message", None)  # strip uvicorn color escape codes


class SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that never crashes on encoding errors."""

    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Pretty JSON formatter (development use)
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    """Check if stdout supports ANSI colors, respecting NO_COLOR/FORCE_COLOR."""
    if os.environ.get("FORCE_COLOR", "0") == "1":
        return True
    if "NO_COLOR" in os.environ:
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _apply_json_colors(text: str) -> str:
    """Apply ANSI color syntax highlighting to a formatted JSON string."""
    C = "\033[96m"   # cyan   — keys
    G = "\033[92m"   # green  — strings, true
    B = "\033[94m"   # blue   — numbers
    M = "\033[95m"   # magenta — null
    R = "\033[91m"   # red    — false
    X = "\033[0m"    # reset
    text = re.sub(r'"([^"]+)":', f'{C}"\\1"{X}:', text)
    text = re.sub(r': "([^"]*)"', f': {G}"\\1"{X}', text)
    text = re.sub(r': (-?\d+\.?\d*)', f': {B}\\1{X}', text)
    text = re.sub(r': (true)', f': {G}\\1{X}', text)
    text = re.sub(r': (false)', f': {R}\\1{X}', text)
    text = re.sub(r': (null)', f': {M}\\1{X}', text)
    return text


class PrettyJsonFormatter(AppJsonFormatter):
    """Indented JSON with optional ANSI color highlighting for terminal use."""

    def __init__(self, *args, **kwargs):
        self._colorize = _supports_color()
        super().__init__(*args, **kwargs)

    def format(self, record):
        json_str = super().format(record)
        try:
            obj = _json.loads(json_str)
            formatted = _json.dumps(obj, indent=2, ensure_ascii=False)
            if self._colorize:
                formatted = _apply_json_colors(formatted)
            return formatted
        except Exception:
            return json_str


# ---------------------------------------------------------------------------
# Formatter factory — single entry point for both API and CLI
# ---------------------------------------------------------------------------

def get_console_formatter(log_format: str) -> logging.Formatter:
    """Return the appropriate console formatter based on log_format setting."""
    fmt = log_format.lower().strip()
    if fmt == "pretty":
        return PrettyJsonFormatter(_LOG_FIELDS)
    elif fmt == "text":
        from cli.logging_config import CLILogFormatter
        return CLILogFormatter()
    else:
        return AppJsonFormatter(_LOG_FIELDS)


def get_file_formatter() -> logging.Formatter:
    """Return the file formatter. Always compact JSON regardless of LOG_FORMAT."""
    return AppJsonFormatter(_LOG_FIELDS)


# ---------------------------------------------------------------------------
# Main configuration entry point
# ---------------------------------------------------------------------------

def configure_logging(log_level: str = "INFO", log_output: str = "both", log_format: str = "json") -> None:
    """
    Configure application-wide structured logging.

    Args:
        log_level:  Python logging level name (debug / info / warning / error).
        log_output: Where to write logs — "stdout", "file", or "both".
        log_format: Console output format — "json", "pretty", or "text".
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = []

    if log_output in ("stdout", "both"):
        console_handler = SafeStreamHandler(sys.stdout)
        console_handler.setFormatter(get_console_formatter(log_format))
        handlers.append(console_handler)

    if log_output in ("file", "both"):
        os.makedirs("logs", exist_ok=True)
        file_formatter = get_file_formatter()

        file_handler = RotatingFileHandler(
            "logs/api.log", maxBytes=50_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

        error_handler = RotatingFileHandler(
            "logs/errors.log", maxBytes=10_000_000, backupCount=3, encoding="utf-8"
        )
        error_handler.setLevel(logging.WARNING)
        error_handler.setFormatter(file_formatter)
        # Add directly to root so it captures all loggers without duplicating to handlers list
        logging.getLogger().addHandler(error_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Suppress noisy third-party loggers
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
