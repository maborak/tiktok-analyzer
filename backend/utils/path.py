"""
Path utility functions for resolving storage paths.

Provides centralized path resolution logic that always resolves relative paths
from the project root (where api_main.py is located).
"""

from pathlib import Path
from config import get_project_root


def resolve_storage_path(storage_path: str) -> Path:
    """
    Resolve a storage path, handling both relative and absolute paths.
    
    If the path is relative, it will be resolved from the project root
    (where api_main.py is located). If absolute, it will be used as-is.
    
    Args:
        storage_path: Storage path from config (can be relative or absolute)
        
    Returns:
        Resolved Path object
        
    Examples:
        >>> resolve_storage_path("./var/screenshots")
        Path("/project/root/var/screenshots")
        
        >>> resolve_storage_path("/var/screenshots")
        Path("/var/screenshots")
    """
    storage_path_obj = Path(storage_path)
    
    if not storage_path_obj.is_absolute():
        # Relative path - resolve from project root (where api_main.py is located)
        project_root = get_project_root()
        return (project_root / storage_path).resolve()
    else:
        # Absolute path - use as-is
        return Path(storage_path)
