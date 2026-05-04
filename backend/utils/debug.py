"""
Debug utilities for FastAPI endpoints

This module provides debugging functions that can be used across all endpoints,
as well as terminal debug context utilities with colored output.
"""

from fastapi import HTTPException, status
from datetime import datetime
from typing import Any, Dict, Union, Optional
import inspect
import sys
from functools import wraps

def debug_return(data: Any = "1", status_code: int = 200, additional_data: Optional[Dict[str, Any]] = None):
    """
    Simple debug function to quickly return any data and exit
    
    Usage:
        debug_return("test message")  # Returns 200 with string
        debug_return({"key": "value"})  # Returns 200 with dict
        debug_return([1, 2, 3])  # Returns 200 with list
        debug_return("error", 500)  # Returns 500 with error message
        debug_return({"user": "john"}, 200, {"extra": "info"})  # Returns with additional data
    """
    response_data = {
        "debug_data": data,
        "timestamp": datetime.now().isoformat(),
        "status": "debug_return"
    }
    
    # Add additional data if provided
    if additional_data:
        response_data.update(additional_data)
    
    raise HTTPException(
        status_code=status_code,
        detail=response_data
    )


# ANSI color codes for terminal output
class Colors:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def colorize(text: str, color: str = None) -> str:
    """Apply color to text if color is specified"""
    if not color:
        return text

    # Check if terminal supports colors
    import os
    force_color = os.environ.get('FORCE_COLOR', '0') == '1'
    no_color = 'NO_COLOR' in os.environ

    # Only disable colors if explicitly disabled
    if no_color and not force_color:
        return text

    color_map = {
        'red': Colors.RED,
        'green': Colors.GREEN,
        'yellow': Colors.YELLOW,
        'blue': Colors.BLUE,
        'magenta': Colors.MAGENTA,
        'cyan': Colors.CYAN,
        'white': Colors.WHITE,
        'bold': Colors.BOLD,
        'underline': Colors.UNDERLINE
    }

    color_code = color_map.get(color.lower())
    if color_code:
        return f"{color_code}{text}{Colors.RESET}"
    return text

class DebugContext:
    """Context manager for debug output with automatic indentation"""

    def __init__(self, debug: bool = False, class_name: str = None, method_name: str = None):
        self.debug = debug
        self.class_name = class_name
        self.method_name = method_name
        self.depth = 0
        self.buffer = []
        self.buffering = False

    def __enter__(self):
        if self.debug:
            self.depth += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.debug:
            self.depth -= 1

    def print(self, message: str, level: str = "INFO", line_number: Optional[int] = None):
        """Print debug message with structured formatting"""
        if not self.debug:
            return

        # Get caller info if line_number not provided
        if line_number is None:
            frame = inspect.currentframe().f_back
            line_number = frame.f_lineno if frame else "?"

        # Build prefix with indentation
        indent = "  " * self.depth
        prefix = f"{indent}🔍"

        # Add class and method info if available
        if self.class_name and self.method_name:
            prefix += f" [{self.class_name}.{self.method_name}:{line_number}]"
        elif self.class_name:
            prefix += f" [{self.class_name}:{line_number}]"
        else:
            prefix += f" [L{line_number}]"

        # Add level indicator
        level_icons = {
            "INFO": "ℹ️",
            "DEBUG": "🔍",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "SUCCESS": "✅",
            "REQUEST": "📤",
            "RESPONSE": "📥",
            "PROCESSING": "⚙️",
            "SAVING": "💾",
            "CLEANING": "🧹",
            "TIMING": "⏱️",
            "NETWORK": "🌐"
        }

        icon = level_icons.get(level, "🔍")
        prefix += f" {icon} "

        print(f"{prefix}{message}")

    def section(self, title: str, line_number: Optional[int] = None):
        """Start a debug section with title"""
        if not self.debug:
            return self

        self.print(f"=== {title} ===", "INFO", line_number)
        return self

    def subsection(self, title: str, line_number: Optional[int] = None):
        """Start a debug subsection"""
        if not self.debug:
            return self

        self.print(f"--- {title} ---", "INFO", line_number)
        return self

    def group(self, title: str, items: Dict[str, str], line_number: Optional[int] = None):
        """Print a group of related items with consistent formatting"""
        if not self.debug:
            return self

        self.subsection(title, line_number)
        for key, value in items.items():
            self.print(f"{key}: {value}")
        return self

    def headers(self, headers_dict: Dict[str, str], title: str = "Headers", line_number: Optional[int] = None):
        """Print headers in a grouped format"""
        if not self.debug:
            return self

        self.subsection(title, line_number)
        for header, value in headers_dict.items():
            self.print(f"    {header}: {value}")
        return self

    def start_buffer(self, buffer_id: str, title: str = None, line_number: Optional[int] = None,
                    color: str = None, title_color: str = None, body_color: str = None):
        """Start buffering debug messages with a specific ID"""
        if not self.debug:
            return self

        self.buffering = True
        self.buffer = []
        self.buffer_id = buffer_id
        self.buffer_title = title
        self.buffer_color = color
        self.buffer_title_color = title_color
        self.buffer_body_color = body_color

        # Print begin marker with color
        indent = "  " * self.depth
        begin_marker = f"{indent}🔍"
        if self.class_name and self.method_name:
            begin_marker += f" [{self.class_name}.{self.method_name}:{line_number or '?'}]"
        else:
            begin_marker += f" [L{line_number or '?'}]"

        # Add color if specified (prioritize title_color over color)
        marker_text = f" ℹ️ ---- {title or buffer_id} [begin] ----"
        if title_color:
            begin_marker += colorize(marker_text, title_color)
        elif color:
            begin_marker += colorize(marker_text, color)
        else:
            begin_marker += marker_text

        print(begin_marker)

        return self

    def buffer_add(self, message: str, level: str = "INFO", line_number: Optional[int] = None):
        """Add a message to the buffer"""
        if not self.debug or not self.buffering:
            return

        # Add message directly to buffer without any debug prefixes
        # Just add indentation for visual hierarchy
        indent = "  " * (self.depth + 1)

        # Apply body color if specified
        if self.buffer_body_color:
            self.buffer.append(f"{indent}{colorize(message, self.buffer_body_color)}")
        else:
            self.buffer.append(f"{indent}{message}")

    def buffer_flush(self, line_number: Optional[int] = None):
        """Flush the buffer and print all buffered messages"""
        if not self.debug or not self.buffering:
            return self

        # Print all buffered messages
        for message in self.buffer:
            print(message)

        # Print end marker with color
        indent = "  " * self.depth
        end_marker = f"{indent}🔍"
        if self.class_name and self.method_name:
            end_marker += f" [{self.class_name}.{self.method_name}:{line_number or '?'}]"
        else:
            end_marker += f" [L{line_number or '?'}]"

        # Add color if specified (prioritize title_color over color)
        marker_text = f" ℹ️ ---- {self.buffer_title or self.buffer_id} [end] ----"
        if self.buffer_title_color:
            end_marker += colorize(marker_text, self.buffer_title_color)
        elif self.buffer_color:
            end_marker += colorize(marker_text, self.buffer_color)
        else:
            end_marker += marker_text

        print(end_marker)

        # Reset buffer state
        self.buffering = False
        self.buffer = []
        self.buffer_id = None
        self.buffer_title = None
        self.buffer_color = None
        self.buffer_title_color = None
        self.buffer_body_color = None

        return self

    def buffered_headers(self, headers_dict: Dict[str, str], title: str = "Headers", line_number: Optional[int] = None,
                        color: str = None, title_color: str = None, body_color: str = None):
        """Print headers in a buffered grouped format"""
        if not self.debug:
            return self

        self.start_buffer(f"headers_{title.lower().replace(' ', '_')}", title, line_number, color, title_color, body_color)
        for header, value in headers_dict.items():
            self.buffer_add(f"    {header}: {value}")
        self.buffer_flush(line_number)
        return self

def get_debug_context(debug: bool = False, class_name: str = None, method_name: str = None) -> DebugContext:
    """Get a debug context for manual use"""
    return DebugContext(debug, class_name, method_name)
