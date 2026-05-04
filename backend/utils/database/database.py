"""
Database Utility Module

Handles database connection string parsing and engine configuration
following hexagonal architecture principles.

Supports:
- SQLite: sqlite:///path/to/database.db
- PostgreSQL: postgresql://user:password@host:port/database
- MySQL: mysql+pymysql://user:password@host:port/database
- MariaDB: mariadb+pymysql://user:password@host:port/database
- Oracle: oracle+cx_oracle://user:password@host:port/database
- SQL Server: mssql+pyodbc://user:password@host:port/database
"""

from typing import Dict, Any, Tuple
from pathlib import Path
from urllib.parse import urlparse
import os
from config import settings


class DatabaseConnectionParser:
    """Utility class for parsing database connection strings and configuring engines"""
    
    @staticmethod
    def parse_connection_string(connection_string: str) -> Tuple[str, Dict[str, Any]]:
        """
        Parse database connection string and return engine type and configuration
        
        Args:
            connection_string: Database URL like mysql+pymysql://user:pass@host:port/db
            
        Returns:
            Tuple of (engine_type, parsed_info)
        """
        parsed = urlparse(connection_string)
        
        # Extract scheme (engine type)
        scheme = parsed.scheme.lower()
        engine_type = scheme.split('+')[0]  # Remove driver part like 'mysql' from 'mysql+pymysql'
        
        parsed_info = {
            'scheme': scheme,
            'engine': engine_type,
            'driver': scheme.split('+')[1] if '+' in scheme else None,
            'username': parsed.username,
            'password': parsed.password,
            'hostname': parsed.hostname,
            'port': parsed.port,
            'database': parsed.path.lstrip('/') if parsed.path else None,
            'query': dict(param.split('=') for param in parsed.query.split('&') if '=' in param) if parsed.query else {}
        }
        
        return engine_type, parsed_info
    
    @staticmethod
    def get_connect_args(connection_string: str) -> Dict[str, Any]:
        """
        Get database-specific connection arguments based on connection string
        
        Args:
            connection_string: Database URL
            
        Returns:
            Dictionary of connection arguments for SQLAlchemy
        """
        engine_type, parsed_info = DatabaseConnectionParser.parse_connection_string(connection_string)
        connect_args = {}
        
        if engine_type == "sqlite":
            connect_args["check_same_thread"] = False
            
            # Ensure SQLite directory exists
            if parsed_info['database']:
                db_path = Path(parsed_info['database'])
                db_dir = db_path.parent
                db_dir.mkdir(parents=True, exist_ok=True)
        
        elif engine_type in ["postgresql", "postgres"]:
            # PostgreSQL SSL settings can be in query parameters
            query_params = parsed_info.get('query', {})
            if 'sslmode' in query_params:
                connect_args['sslmode'] = query_params['sslmode']
            if 'sslcert' in query_params:
                connect_args['sslcert'] = query_params['sslcert']
            if 'sslkey' in query_params:
                connect_args['sslkey'] = query_params['sslkey']
            if 'sslrootcert' in query_params:
                connect_args['sslrootcert'] = query_params['sslrootcert']
        
        elif engine_type in ["mysql", "mariadb"]:
            # MySQL/MariaDB SSL settings
            query_params = parsed_info.get('query', {})
            ssl_dict = {}
            if 'ssl_ca' in query_params:
                ssl_dict['ca'] = query_params['ssl_ca']
            if 'ssl_cert' in query_params:
                ssl_dict['cert'] = query_params['ssl_cert']
            if 'ssl_key' in query_params:
                ssl_dict['key'] = query_params['ssl_key']
            if ssl_dict:
                connect_args['ssl'] = ssl_dict
        
        elif engine_type in ["mssql", "sqlserver"]:
            # SQL Server ODBC settings
            query_params = parsed_info.get('query', {})
            if 'driver' not in query_params:
                connect_args['driver'] = "ODBC Driver 17 for SQL Server"
            if query_params.get('encrypt', '').lower() == 'yes':
                connect_args['Encrypt'] = 'yes'
                connect_args['TrustServerCertificate'] = 'no'
        
        return connect_args
    
    @staticmethod
    def get_engine_kwargs(connection_string: str, echo: bool = False, echo_pool: bool = False) -> Dict[str, Any]:
        """
        Get database engine creation arguments based on connection string
        
        Args:
            connection_string: Database URL
            echo: Enable SQL query logging
            echo_pool: Enable connection pool logging
            
        Returns:
            Dictionary of engine creation arguments for SQLAlchemy
        """
        engine_type, parsed_info = DatabaseConnectionParser.parse_connection_string(connection_string)
        
        engine_kwargs = {
            "echo": echo,
            "echo_pool": echo_pool,
            "connect_args": DatabaseConnectionParser.get_connect_args(connection_string)
        }
        
        # Enhanced connection pooling configuration
        if engine_type != "sqlite":
            # Production-ready pool settings
            engine_kwargs.update({
                "pool_size": int(settings("DB_POOL_SIZE", "20").split('#')[0].strip()),  # Handle comments
                "max_overflow": int(settings("DB_MAX_OVERFLOW", "30").split('#')[0].strip()),  # Handle comments
                "pool_timeout": int(settings("DB_POOL_TIMEOUT", "30").split('#')[0].strip()),  # Handle comments
                "pool_recycle": int(settings("DB_POOL_RECYCLE", "3600").split('#')[0].strip()),  # Handle comments
                "pool_pre_ping": True,  # Verify connections before use
                "pool_reset_on_return": "commit"  # Reset connections properly
            })
        else:
            # SQLite-specific optimizations
            engine_kwargs.update({
                "pool_size": 1,  # SQLite doesn't support multiple connections well
                "max_overflow": 0,
                "pool_pre_ping": True,
                "pool_reset_on_return": "commit"
            })
        
        return engine_kwargs
    
    @staticmethod
    def get_optimized_pool_settings(engine_type: str) -> Dict[str, Any]:
        """
        Get optimized connection pool settings based on database type
        
        Args:
            engine_type: Type of database (sqlite, postgresql, mysql, etc.)
            
        Returns:
            Dictionary of optimized pool settings
        """
        if engine_type == "sqlite":
            return {
                "pool_size": 1,
                "max_overflow": 0,
                "pool_pre_ping": True,
                "pool_reset_on_return": "commit"
            }
        elif engine_type in ["postgresql", "postgres"]:
            return {
                "pool_size": 20,
                "max_overflow": 30,
                "pool_timeout": 30,
                "pool_recycle": 3600,
                "pool_pre_ping": True,
                "pool_reset_on_return": "commit"
            }
        elif engine_type in ["mysql", "mariadb"]:
            return {
                "pool_size": 15,
                "max_overflow": 25,
                "pool_timeout": 30,
                "pool_recycle": 3600,
                "pool_pre_ping": True,
                "pool_reset_on_return": "commit"
            }
        else:
            # Default settings for other databases
            return {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
                "pool_recycle": 3600,
                "pool_pre_ping": True,
                "pool_reset_on_return": "commit"
            }
    
    @staticmethod
    def validate_connection_string(connection_string: str) -> Tuple[bool, str]:
        """
        Validate database connection string format
        
        Args:
            connection_string: Database URL to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            engine_type, parsed_info = DatabaseConnectionParser.parse_connection_string(connection_string)
            
            # Basic scheme validation
            supported_engines = ["sqlite", "postgresql", "postgres", "mysql", "mariadb", "oracle", "mssql", "sqlserver"]
            if engine_type not in supported_engines:
                return False, f"Unsupported database engine: {engine_type}. Supported: {', '.join(supported_engines)}"
            
            # SQLite validation
            if engine_type == "sqlite":
                if not parsed_info.get('database'):
                    return False, "SQLite connection string must include database path"
                return True, ""
            
            # Other databases validation
            required_fields = ['hostname', 'database']
            for field in required_fields:
                if not parsed_info.get(field):
                    return False, f"Connection string missing required field: {field}"
            
            # Check if username/password are provided (usually required for remote databases)
            if not parsed_info.get('username'):
                return False, "Connection string missing username"
                
            return True, ""
            
        except Exception as e:
            return False, f"Invalid connection string format: {str(e)}"
    
    @staticmethod
    def get_database_info(connection_string: str) -> Dict[str, Any]:
        """
        Get database information from connection string
        
        Args:
            connection_string: Database URL
            
        Returns:
            Dictionary with database information
        """
        try:
            engine_type, parsed_info = DatabaseConnectionParser.parse_connection_string(connection_string)
            
            info = {
                "engine": engine_type,
                "driver": parsed_info.get('driver'),
                "host": parsed_info.get('hostname', 'N/A'),
                "port": parsed_info.get('port', 'default'),
                "database": parsed_info.get('database', 'N/A'),
                "username": parsed_info.get('username', 'N/A')
            }
            
            if engine_type == "sqlite":
                db_path = Path(parsed_info['database'])
                info.update({
                    "path": str(db_path),
                    "exists": db_path.exists(),
                    "size": f"{db_path.stat().st_size / (1024*1024):.2f} MB" if db_path.exists() else "N/A"
                })
            else:
                info.update({
                    "path": f"{info['host']}:{info['port']}/{info['database']}",
                    "exists": True,  # Assume true for remote databases
                    "size": "N/A"    # Size not easily available for remote databases
                })
            
            return info
            
        except Exception as e:
            return {
                "engine": "unknown",
                "error": str(e),
                "path": connection_string,
                "exists": False,
                "size": "unknown"
            }


def get_database_driver_requirements() -> Dict[str, str]:
    """
    Get installation requirements for different database engines
    
    Returns:
        Dictionary mapping engine names to their driver requirements
    """
    return {
        "sqlite": "No additional drivers required (built into Python)",
        "postgresql": "pip install psycopg2-binary",
        "mysql": "pip install PyMySQL",
        "mariadb": "pip install PyMySQL", 
        "oracle": "pip install cx_Oracle",
        "mssql": "pip install pyodbc (+ ODBC Driver 17 for SQL Server)",
    }


 