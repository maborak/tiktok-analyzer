"""
Database Connection Information Utility

Centralized functions for displaying database connection details, configuration,
and status information. Used by both CLI and API components.

Optimized with shared data generation logic and minimal code duplication.
"""

import os
from typing import Dict, Any, Optional, List, Callable


def _mask_password_in_url(url: str) -> str:
    """Safely mask password in connection URL"""
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.password:
            # Replace only the password portion in netloc
            masked_netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            masked_parsed = parsed._replace(netloc=masked_netloc)
            return urlunparse(masked_parsed)
        return url
    except:
        return url


def _get_connection_info_data() -> Dict[str, Any]:
    """
    Generate structured database connection information.
    Core data generation function used by all display methods.
    """
    try:
        from config import get_database_url, settings
        from utils.database import DatabaseConnectionParser
        
        if settings("DB_USE_REPLICA_ENGINE", False):
            # When replica engine is on, 'primary' used for info is the WRITE url
            connection_string = settings("DB_WRITE_URL") or get_database_url()
            replica_info = {
                "use_replica": True,
                "read_url_masked": _mask_password_in_url(settings("DB_READ_URL") or connection_string),
                "write_url_masked": _mask_password_in_url(settings("DB_WRITE_URL") or connection_string)
            }
        else:
            connection_string = get_database_url()
            replica_info = {"use_replica": False}
            
        engine_type, parsed_info = DatabaseConnectionParser.parse_connection_string(connection_string)
        
        # Determine override status
        env_database_url = os.getenv("PHOVEU_BACKEND_DATABASE_URL", "sqlite:///./database/product_cache.db")
        is_override = connection_string != env_database_url
        
        # Basic connection info
        connection_data = {
            "connection_string": connection_string,
            "connection_string_masked": _mask_password_in_url(connection_string),
            "engine": engine_type,
            "driver": parsed_info.get('driver'),
            "is_override": is_override,
            "override_status": "🔧 Override Active" if is_override else "📋 Environment Variable"
        }
        
        # Add engine-specific details
        if engine_type != "sqlite":
            connection_data.update({
                "host": parsed_info.get('hostname', 'N/A'),
                "port": parsed_info.get('port', 'default'),
                "database": parsed_info.get('database', 'N/A'),
                "username": parsed_info.get('username', 'N/A'),
                "password_status": '***' if parsed_info.get('password') else '(not set)'
            })
        else:
            connection_data["sqlite_path"] = parsed_info.get('database', 'N/A')
        
        # Pool settings
        pool_settings = {
            "pool_size": settings('DB_POOL_SIZE', '5'),
            "max_overflow": settings('DB_MAX_OVERFLOW', '10'),
            "pool_timeout": settings('DB_POOL_TIMEOUT', '30'),
            "pool_recycle": settings('DB_POOL_RECYCLE', '3600')
        }
        
        # Debug settings
        debug_settings = {
            "echo_sql": str(settings("DB_ECHO", False)).lower(),
            "echo_pool": str(settings("DB_ECHO_POOL", False)).lower()
        }
        
        # Environment variables with masking
        env_vars = {}
        env_var_names = ["DATABASE_URL", "DB_ECHO", "DB_ECHO_POOL", "DB_POOL_SIZE", "DB_MAX_OVERFLOW"]
        for var in env_var_names:
            value = os.getenv(var, "(not set)")
            if var == "DATABASE_URL" and value != "(not set)":
                value = _mask_password_in_url(value)
            env_vars[var] = value
        
        # Database status
        db_status = {}
        try:
            db_info = DatabaseConnectionParser.get_database_info(connection_string)
            db_status = {
                "path": db_info['path'],
                "exists": db_info['exists'],
                "size": db_info['size'],
                "error": None
            }
        except Exception as e:
            db_status = {
                "path": "Unknown",
                "exists": False,
                "size": "Unknown",
                "error": str(e)
            }
        
        return {
            "success": True,
            "connection": connection_data,
            "pool_settings": pool_settings,
            "debug_settings": debug_settings,
            "environment_variables": env_vars,
            "database_status": db_status,
            "replica_info": replica_info
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "connection": {},
            "pool_settings": {},
            "debug_settings": {},
            "environment_variables": {},
            "database_status": {}
        }


def _display_connection_info_with_output(output_func: Callable[[str], None], context: str = ""):
    """
    Display database connection information using provided output function.
    
    Args:
        output_func: Function to use for output (print, click.echo, etc.)
        context: Optional context string (e.g., "CLI", "API")
    """
    data = _get_connection_info_data()
    
    if not data["success"]:
        output_func(f"❌ Error getting connection info: {data['error']}")
        output_func("")
        return
    
    conn = data["connection"]
    pool = data["pool_settings"]
    debug = data["debug_settings"]
    env_vars = data["environment_variables"]
    db_status = data["database_status"]
    
    # Header
    output_func("🗃️  Database Connection:")
    output_func("=" * 50)
    
    # Basic connection info
    output_func(f"Connection String:    {conn['connection_string_masked']}")
    output_func(f"Engine:               {conn['engine']}")
    
    if conn.get('driver'):
        output_func(f"Driver:               {conn['driver']}")
    
    # Engine-specific details
    if 'sqlite_path' in conn:
        output_func(f"SQLite Path:          {conn['sqlite_path']}")
    else:
        output_func(f"Host:                 {conn['host']}")
        output_func(f"Port:                 {conn['port']}")
        output_func(f"Database:             {conn['database']}")
        output_func(f"Username:             {conn['username']}")
        output_func(f"Password:             {conn['password_status']}")
    
    # Replica status
    replica = data.get("replica_info", {})
    if replica.get("use_replica"):
        output_func(f"\nStatus:               {conn['override_status']} (Replica Engine: ✅ ENABLED)")
        output_func(f"Read Replica URL:     {replica['read_url_masked']}")
        output_func(f"Write Replica URL:    {replica['write_url_masked']}")
    else:
        output_func(f"\nStatus:               {conn['override_status']} (Replica Engine: ❌ DISABLED)")
    
    # Pool settings
    output_func(f"\nPool Settings:")
    output_func(f"Pool Size:            {pool['pool_size']}")
    output_func(f"Max Overflow:         {pool['max_overflow']}")
    output_func(f"Pool Timeout:         {pool['pool_timeout']}")
    output_func(f"Pool Recycle:         {pool['pool_recycle']}")
    
    # Debug settings
    output_func(f"\nDebug Settings:")
    output_func(f"Echo SQL:             {debug['echo_sql']}")
    output_func(f"Echo Pool:            {debug['echo_pool']}")
    
    # Environment variables
    output_func(f"\nEnvironment Variables:")
    for var, value in env_vars.items():
        output_func(f"  {var:<20} = {value}")
    
    # Database status
    output_func(f"\nDatabase Status:")
    if db_status.get('error'):
        output_func(f"Path:                 Error - {db_status['error']}")
    else:
        output_func(f"Path:                 {db_status['path']}")
        output_func(f"Exists:               {db_status['exists']}")
        output_func(f"Size:                 {db_status['size']}")
    
    output_func("")


def display_detailed_connection_info():
    """Display detailed database connection information (API/print version)"""
    _display_connection_info_with_output(print)





def get_database_info() -> Dict[str, Any]:
    """Get database information in a structured format for programmatic use"""
    data = _get_connection_info_data()
    
    if not data["success"]:
        return {
            "type": "Unknown",
            "path": "Unknown",
            "exists": False,
            "size": "Unknown",
            "status": f"Error: {data['error']}"
        }
    
    db_status = data["database_status"]
    conn = data["connection"]
    
    return {
        "type": conn["engine"].upper(),
        "path": db_status["path"],
        "exists": db_status["exists"],
        "size": db_status["size"],
        "status": "Ready" if db_status["exists"] and not db_status.get("error") else "Not initialized"
    }


 