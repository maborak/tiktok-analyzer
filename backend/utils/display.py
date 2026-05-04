"""
Display utilities for beautiful data output

Provides jq-like beautiful formatting for Python data structures
with colors and proper indentation.
"""

import json
import sys
import re
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, date
from decimal import Decimal

try:
    from rich.console import Console
    from rich.json import JSON
    from rich.pretty import Pretty
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False





def convert_to_serializable(obj: Any, max_depth: int = 10, current_depth: int = 0, add_type_info: bool = True, ignore_keys: Optional[List[str]] = None) -> Any:
    """
    Convert complex Python objects to JSON-serializable format
    
    Args:
        obj: The object to convert
        max_depth: Maximum recursion depth to prevent infinite loops
        current_depth: Current recursion depth
        
    Returns:
        JSON-serializable representation of the object
    """
    if current_depth > max_depth:
        return f"<Max depth reached: {type(obj).__name__}>"
    
    # Handle None
    if obj is None:
        return None
    

    
    # Handle basic JSON-serializable types
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    # Handle datetime objects
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    
    # Handle Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    
    # Handle lists and tuples
    if isinstance(obj, (list, tuple)):
        return [convert_to_serializable(item, max_depth, current_depth + 1, add_type_info) for item in obj]
    
    # Handle dictionaries
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            str_key = str(key)
            # Check if this key should be ignored
            if ignore_keys and str_key in ignore_keys:
                result[str_key] = "<ignored>"
            else:
                result[str_key] = convert_to_serializable(value, max_depth, current_depth + 1, add_type_info, ignore_keys)
        return result
    
    # Handle sets
    if isinstance(obj, set):
        return list(convert_to_serializable(item, max_depth, current_depth + 1, add_type_info) for item in obj)
    
    # Handle SQLAlchemy models and other objects with __dict__
    if hasattr(obj, '__dict__'):
        result = {}
        # Add type information if requested and this is the top level
        if add_type_info and current_depth == 0:
            result['__type__'] = type(obj).__name__
        for key, value in obj.__dict__.items():
            # Skip private attributes and SQLAlchemy internals
            if not key.startswith('_'):
                str_key = str(key)
                # Check if this key should be ignored
                if ignore_keys and str_key in ignore_keys:
                    result[str_key] = "<ignored>"
                else:
                    try:
                        result[str_key] = convert_to_serializable(value, max_depth, current_depth + 1, add_type_info, ignore_keys)
                    except Exception:
                        result[str_key] = f"<Error converting {key}>"
        return result
    
    # Handle objects with __slots__
    if hasattr(obj, '__slots__'):
        result = {}
        # Add type information if requested and this is the top level
        if add_type_info and current_depth == 0:
            result['__type__'] = type(obj).__name__
        for slot in obj.__slots__:
            if hasattr(obj, slot):
                try:
                    value = getattr(obj, slot)
                    result[slot] = convert_to_serializable(value, max_depth, current_depth + 1, add_type_info)
                except Exception:
                    result[slot] = f"<Error converting {slot}>"
        return result
    
    # Handle dataclasses
    if hasattr(obj, '__dataclass_fields__'):
        result = {}
        # Add type information if requested and this is the top level
        if add_type_info and current_depth == 0:
            result['__type__'] = type(obj).__name__
        for field_name in obj.__dataclass_fields__:
            try:
                value = getattr(obj, field_name)
                result[field_name] = convert_to_serializable(value, max_depth, current_depth + 1, add_type_info)
            except Exception:
                result[field_name] = f"<Error converting {field_name}>"
        return result
    
    # Handle named tuples
    if hasattr(obj, '_fields'):
        result = {}
        # Add type information if requested and this is the top level
        if add_type_info and current_depth == 0:
            result['__type__'] = type(obj).__name__
        for field_name in obj._fields:
            try:
                value = getattr(obj, field_name)
                result[field_name] = convert_to_serializable(value, max_depth, current_depth + 1, add_type_info)
            except Exception:
                result[field_name] = f"<Error converting {field_name}>"
        return result
    
    # Fallback for other types
    try:
        # Try to convert to string
        return str(obj)
    except Exception:
        return f"<{type(obj).__name__} object>"


class BeautifulPrinter:
    """Beautiful printer for data structures"""
    
    def __init__(self, use_colors: bool = True, indent: int = 2):
        self.use_colors = use_colors and (RICH_AVAILABLE or COLORAMA_AVAILABLE)
        self.indent = indent
        self.console = Console() if RICH_AVAILABLE else None
    
    def print(self, data: Any, title: Optional[str] = None) -> None:
        """
        Print data beautifully with colors and formatting
        
        Args:
            data: The data to print (dict, list, str, int, float, bool, None)
            title: Optional title to display above the data
        """
        if title:
            self._print_title(title)
        
        # Check if data has type info - if so, use colorama for better formatting
        has_type_info = isinstance(data, dict) and '__type__' in data
        
        if RICH_AVAILABLE and not has_type_info:
            self._print_with_rich(data)
        elif self.use_colors and COLORAMA_AVAILABLE:
            self._print_with_colorama(data)
        else:
            self._print_plain(data)
    
    def _print_title(self, title: str) -> None:
        """Print a formatted title"""
        if RICH_AVAILABLE:
            self.console.print(f"\n[bold blue]📋 {title}[/bold blue]")
            self.console.print("[blue]" + "=" * (len(title) + 3) + "[/blue]")
        elif self.use_colors and COLORAMA_AVAILABLE:
            print(f"\n{Fore.BLUE}{Style.BRIGHT}📋 {title}")
            print(f"{Fore.BLUE}{'=' * (len(title) + 3)}{Style.RESET_ALL}")
        else:
            print(f"\n📋 {title}")
            print("=" * (len(title) + 3))
    
    def _print_with_rich(self, data: Any) -> None:
        """Print using rich library for best formatting"""
        if isinstance(data, (dict, list)):
            # Use Rich's JSON formatter for structured data
            try:
                json_str = json.dumps(data, indent=self.indent, ensure_ascii=False, default=str)
                # Print as raw text with Rich instead of using JSON formatter
                self.console.print(json_str)
            except (TypeError, ValueError):
                # Fallback to Pretty for non-JSON serializable objects
                self.console.print(Pretty(data, indent_size=self.indent))
        else:
            # Use Pretty for other types
            self.console.print(Pretty(data))
    
    def _print_with_colorama(self, data: Any, depth: int = 0) -> None:
        """Print using colorama for basic colors"""
        # For objects with type info at root level, use special formatting
        if isinstance(data, dict) and '__type__' in data and depth == 0:
            type_name = data['__type__']
            data_without_type = {k: v for k, v in data.items() if k != '__type__'}
            json_str = json.dumps(data_without_type, indent=self.indent, ensure_ascii=False, default=str)
            # Add type name with angle brackets
            json_str = json_str.replace('{', f'{Fore.MAGENTA}<{type_name}>{Fore.YELLOW}{{', 1)
            # Add basic coloring to the JSON string
            json_str = self._colorize_json_string(json_str)
            print(json_str)
        else:
            # For regular data, use standard JSON with basic coloring
            json_str = json.dumps(data, indent=self.indent, ensure_ascii=False, default=str)
            json_str = self._colorize_json_string(json_str)
            print(json_str)
    
    def _colorize_json_string(self, json_str: str) -> str:
        """Add basic coloring to a JSON string"""
        import re
        # Color strings (green)
        json_str = re.sub(r'"([^"]*)":', f'{Fore.CYAN}"\\1"{Style.RESET_ALL}:', json_str)
        json_str = re.sub(r': "([^"]*)"', f': {Fore.GREEN}"\\1"{Style.RESET_ALL}', json_str)
        # Color numbers (blue)
        json_str = re.sub(r': (\d+\.?\d*)', f': {Fore.BLUE}\\1{Style.RESET_ALL}', json_str)
        # Color booleans
        json_str = re.sub(r': true', f': {Fore.GREEN}true{Style.RESET_ALL}', json_str)
        json_str = re.sub(r': false', f': {Fore.RED}false{Style.RESET_ALL}', json_str)
        # Color null
        json_str = re.sub(r': null', f': {Fore.MAGENTA}null{Style.RESET_ALL}', json_str)
        # Color braces and brackets
        json_str = re.sub(r'([{}\\[\\]])', f'{Fore.YELLOW}\\1{Style.RESET_ALL}', json_str)
        return json_str
        


    
    def _print_plain(self, data: Any) -> None:
        """Print without colors as fallback"""
        if isinstance(data, (dict, list)):
            try:
                # Check if this is an object with type info
                if isinstance(data, dict) and '__type__' in data:
                    type_name = data['__type__']
                    data_without_type = {k: v for k, v in data.items() if k != '__type__'}
                    json_str = json.dumps(data_without_type, indent=self.indent, ensure_ascii=False, default=str)
                    # Add type name with angle brackets before the opening brace
                    json_str = json_str.replace('{', f'<{type_name}>{{', 1)
                    print(json_str)
                else:
                    json_str = json.dumps(data, indent=self.indent, ensure_ascii=False, default=str)
                    print(json_str)
            except (TypeError, ValueError):
                # Fallback to pprint for non-JSON serializable objects
                import pprint
                pprint.pprint(data, indent=self.indent)
        else:
            print(data)


# Global instance for easy usage
_printer = BeautifulPrinter()


def jq(data: Any, title: Optional[str] = None, colors: bool = True, indent: int = 2, mode: str = "auto", convert_objects: bool = True, ignore: Optional[List[str]] = None) -> None:
    """
    Print data beautifully like jq command line tool with multiple display modes
    
    Args:
        data: The data to print (any Python object)
        title: Optional title to display above the data
        colors: Whether to use colors (default: True)
        indent: Number of spaces for indentation (default: 2)
        mode: Display mode - "auto", "json", "table", "pretty", "plain" (default: "auto")
        convert_objects: Whether to convert complex objects to dictionaries (default: True)
        ignore: List of keys to ignore and display as "<ignored>" (default: None)
    
    Display modes:
        - "auto": Automatically choose the best format based on data type
        - "json": Force JSON syntax highlighting
        - "table": Force table display (works best with list of dicts)
        - "pretty": Standard pretty printing with colors
        - "plain": Plain text without colors
    
    Examples:
        >>> from utils.display import jq
        >>> data = {"name": "John", "age": 30, "items": [1, 2, 3]}
        >>> jq(data, "User Data")  # auto mode
        
        >>> jq(data, "User Data", mode="json")  # force JSON highlighting
        
        >>> users = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        >>> jq(users, "Users", mode="table")  # force table display
        
        >>> jq(complex_object, "Database Result")  # auto-converts objects
        
        >>> jq(data, "User Data", mode="plain")  # no colors
        
        >>> # Ignore specific keys
        >>> data = {"name": "John", "soup": beautifulsoup_object, "raw_html": "large_html"}
        >>> jq(data, "User Data", ignore=["soup", "raw_html"])  # soup and raw_html will show as <ignored>
    """
    # Convert complex objects to serializable format if needed
    if convert_objects:
        try:
            # Try to serialize WITHOUT default to detect if conversion is needed
            json.dumps(data)
            # Even if JSON serializable, we need to apply ignore keys
            if ignore:
                processed_data = convert_to_serializable(data, add_type_info=False, ignore_keys=ignore)
            else:
                processed_data = data
        except (TypeError, ValueError):
            # Complex object detected, convert it
            # Don't add type info for JSON mode (clean JSON output)
            add_type_info = mode != "json"
            processed_data = convert_to_serializable(data, add_type_info=add_type_info, ignore_keys=ignore)
    else:
        processed_data = data
    
    # Handle different display modes
    if mode == "json":
        json_print(processed_data, title)
    elif mode == "table":
        # Check if the processed data is suitable for table display
        if isinstance(processed_data, list) and processed_data and all(isinstance(item, dict) for item in processed_data):
            table_print(processed_data, title)
        else:
            print(f"Warning: Table mode works best with list of dictionaries. Falling back to pretty mode.")
            printer = BeautifulPrinter(use_colors=colors, indent=indent)
            printer.print(processed_data, title)
    elif mode == "plain":
        printer = BeautifulPrinter(use_colors=False, indent=indent)
        printer.print(processed_data, title)
    elif mode == "auto":
        # Auto-detect best format based on processed data
        if isinstance(processed_data, list) and processed_data and all(isinstance(item, dict) for item in processed_data):
            # List of dictionaries - use table
            table_print(processed_data, title)
        else:
            # Everything else - use pretty printing
            printer = BeautifulPrinter(use_colors=colors, indent=indent)
            printer.print(processed_data, title)
    elif mode == "pretty":
        # Standard pretty printing
        printer = BeautifulPrinter(use_colors=colors, indent=indent)
        printer.print(processed_data, title)
    else:
        raise ValueError(f"Unknown display mode: {mode}. Valid modes are: auto, json, table, pretty, plain")





def json_print(data: Any, title: Optional[str] = None) -> None:
    """
    Print data as JSON with syntax highlighting
    
    Args:
        data: The data to print as JSON
        title: Optional title to display above the data
    """
    if title:
        _printer._print_title(title)
    
    try:
        # Try to convert complex objects first
        try:
            json.dumps(data)
            processed_data = data
        except (TypeError, ValueError):
            # For json_print, always use clean JSON without type info
            processed_data = convert_to_serializable(data, add_type_info=False, ignore_keys=None)
        
        json_str = json.dumps(processed_data, indent=2, ensure_ascii=False, default=str)
        
        if RICH_AVAILABLE:
            # Use raw text instead of Syntax highlighting to avoid formatting issues
            _printer.console.print(json_str)
        else:
            print(json_str)
    except (TypeError, ValueError) as e:
        print(f"Error converting to JSON: {e}")
        # Fallback to basic jq without object conversion to avoid infinite loop
        jq(data, title, convert_objects=False)


def table_print(data: List[Dict[str, Any]], title: Optional[str] = None) -> None:
    """
    Print list of dictionaries as a table
    
    Args:
        data: List of dictionaries to display as table
        title: Optional title for the table
    """
    if not data or not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        print("Error: data must be a list of dictionaries")
        return
    
    if RICH_AVAILABLE:
        from rich.table import Table
        
        # Create table
        table = Table(title=title)
        
        # Add columns based on first row
        if data:
            for key in data[0].keys():
                table.add_column(str(key), style="cyan")
            
            # Add rows
            for row in data:
                table.add_row(*[str(row.get(key, "")) for key in data[0].keys()])
        
        _printer.console.print(table)
    else:
        # Fallback to simple table
        if title:
            print(f"\n📋 {title}")
            print("=" * (len(title) + 3))
        
        if not data:
            print("No data to display")
            return
        
        # Get all keys
        all_keys = set()
        for row in data:
            all_keys.update(row.keys())
        
        keys = list(all_keys)
        
        # Calculate column widths
        widths = {}
        for key in keys:
            widths[key] = max(len(str(key)), max(len(str(row.get(key, ""))) for row in data))
        
        # Print header
        header = " | ".join(str(key).ljust(widths[key]) for key in keys)
        print(header)
        print("-" * len(header))
        
        # Print rows
        for row in data:
            row_str = " | ".join(str(row.get(key, "")).ljust(widths[key]) for key in keys)
            print(row_str) 


def jq_http(data: Any, ignore: Optional[List[str]] = None, convert_objects: bool = True) -> Any:
    """
    HTTP version of jq - returns data as HTTP response with optional key filtering
    Similar to jq but for HTTP responses instead of terminal output
    
    Args:
        data: The data to process (any Python object)
        ignore: List of keys to ignore and display as "<ignored>" (default: None)
        convert_objects: Whether to convert complex objects to dictionaries (default: True)
    
    Returns:
        Processed data ready for HTTP response (JSON-serializable)
    
    Examples:
        >>> from utils.display import jq_http
        >>> data = {"name": "John", "soup": beautifulsoup_object, "raw_html": "large_html"}
        >>> result = jq_http(data, ignore=["soup", "raw_html"])
        >>> # result is now JSON-serializable with soup and raw_html as "<ignored>"
    """
    # Convert complex objects to serializable format if needed
    if convert_objects:
        try:
            # Try to serialize WITHOUT default to detect if conversion is needed
            json.dumps(data)
            # Even if JSON serializable, we need to apply ignore keys
            if ignore:
                processed_data = convert_to_serializable(data, add_type_info=False, ignore_keys=ignore)
            else:
                processed_data = data
        except (TypeError, ValueError):
            # Complex object detected, convert it
            # Don't add type info for HTTP responses (clean JSON output)
            processed_data = convert_to_serializable(data, add_type_info=False, ignore_keys=ignore)
    else:
        processed_data = data
    
    # Always raise HTTPException to return response from FastAPI routes
    try:
        from fastapi import HTTPException
        # Use 299 for debug responses - indicates debug data return
        raise HTTPException(status_code=299, detail=processed_data)
    except ImportError:
        return processed_data