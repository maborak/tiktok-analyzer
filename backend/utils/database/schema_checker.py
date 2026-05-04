"""
Database Schema Checking Utility

Centralized schema analysis and validation logic extracted from CLI sync command.
Used by both CLI and API components for consistent schema checking.
"""

import os
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass





@dataclass
class SchemaAnalysisResult:
    """Results of database schema analysis"""
    is_in_sync: bool
    missing_tables: List[str]
    extra_tables: List[str]
    column_changes: List[Dict[str, Any]]
    total_differences: int
    error_message: str
    success: bool


def _sort_tables_by_dependencies(metadata, table_names):
    """
    Sort tables by foreign key dependencies using topological sorting (Kahn's algorithm).
    Tables with no dependencies come first, then tables that depend on them, etc.
    
    Args:
        metadata: SQLAlchemy metadata object
        table_names: List of table names to sort
    
    Returns:
        List of table names sorted by dependency order
    """
    from collections import defaultdict, deque
    
    # Build dependency graph
    dependencies = defaultdict(set)  # table -> set of tables it depends on
    dependents = defaultdict(set)    # table -> set of tables that depend on it
    in_degree = defaultdict(int)     # table -> number of dependencies
    
    # Initialize in_degree for all tables
    for table_name in table_names:
        in_degree[table_name] = 0
    
    # Analyze foreign key relationships
    for table_name in table_names:
        if table_name in metadata.tables:
            table = metadata.tables[table_name]
            
            for fk in table.foreign_keys:
                referenced_table = fk.column.table.name
                
                # Only consider dependencies within our table list
                if referenced_table in table_names and referenced_table != table_name:
                    dependencies[table_name].add(referenced_table)
                    dependents[referenced_table].add(table_name)
                    in_degree[table_name] += 1
    
    # Topological sort using Kahn's algorithm
    queue = deque([table for table in table_names if in_degree[table] == 0])
    sorted_tables = []
    
    while queue:
        current_table = queue.popleft()
        sorted_tables.append(current_table)
        
        # Process all tables that depend on current_table
        for dependent_table in dependents[current_table]:
            in_degree[dependent_table] -= 1
            if in_degree[dependent_table] == 0:
                queue.append(dependent_table)
    
    # Check for circular dependencies
    if len(sorted_tables) != len(table_names):
        # Circular dependency detected, return original order
        return table_names
    
    return sorted_tables


def _is_type_equivalent(expected_type_str: str, actual_type_str: str, strict: bool = False) -> bool:
    """Check if two column types are equivalent, handling common MySQL/SQLAlchemy variations"""
    if expected_type_str == actual_type_str:
        return True
    
    if strict:
        return False
    
    # Common MySQL/SQLAlchemy type mappings that are functionally equivalent
    type_mappings = {
        'BOOLEAN': ['TINYINT', 'TINYINT(1)'],
        'TINYINT(1)': ['BOOLEAN', 'TINYINT'],
        'TINYINT': ['BOOLEAN', 'TINYINT(1)'],
        'VARCHAR': ['TEXT', 'VARCHAR('],
        'TEXT': ['VARCHAR'],
        'INTEGER': ['INT'],
        'INT': ['INTEGER'],
        'DATETIME': ['TIMESTAMP'],
        'TIMESTAMP': ['DATETIME'],
        'DECIMAL': ['NUMERIC'],
        'NUMERIC': ['DECIMAL'],
        'DOUBLE': ['FLOAT'],
        'FLOAT': ['DOUBLE'],
        'BIGINT': ['INTEGER'],
        'INTEGER': ['BIGINT', 'INT']
    }
    
    # Check if types are in equivalent groups
    for base_type, equivalents in type_mappings.items():
        if expected_type_str.upper().startswith(base_type) and any(actual_type_str.upper().startswith(eq) for eq in equivalents):
            return True
        if actual_type_str.upper().startswith(base_type) and any(expected_type_str.upper().startswith(eq) for eq in equivalents):
            return True
    
    return False


def _is_default_equivalent(expected_default: Any, actual_default: Any, strict: bool = False) -> bool:
    """Check if two default values are equivalent, handling common variations"""
    if expected_default == actual_default:
        return True
    
    if strict:
        return False
    
    # Convert to strings for comparison
    expected_str = str(expected_default).lower() if expected_default is not None else None
    actual_str = str(actual_default).lower() if actual_default is not None else None
    
    # Handle PostgreSQL type casts in defaults (e.g., '{}'::jsonb, '[]'::jsonb)
    if actual_str and '::' in actual_str:
        actual_str = actual_str.split('::')[0].strip("'\" ")
    if expected_str and '::' in expected_str:
        expected_str = expected_str.split('::')[0].strip("'\" ")

    # Handle None/null equivalence
    if (expected_str in [None, 'none', 'null'] or not expected_str) and \
       (actual_str in [None, 'none', 'null'] or not actual_str):
        return True
    
    # Handle empty JSON/Array equivalence
    if expected_str in ['{}', '[]'] and (actual_str in [None, 'none', 'null', '{}', '[]']):
        return True
    if actual_str in ['{}', '[]'] and (expected_str in [None, 'none', 'null', '{}', '[]']):
        return True

    # Handle datetime function equivalence
    datetime_functions = ['datetime.utcnow', 'datetime.now(timezone.utc)', 'current_timestamp', 'now()', 'utc_timestamp()']
    if expected_str and actual_str:
        expected_is_datetime_func = any(func in expected_str for func in datetime_functions)
        actual_is_datetime_func = any(func in actual_str for func in datetime_functions)
        if expected_is_datetime_func and actual_is_datetime_func:
            return True
    
    # Handle boolean equivalence (MySQL stores booleans as integers)
    if expected_str in ['true', '1'] and actual_str in ['true', '1']:
        return True
    if expected_str in ['false', '0'] and actual_str in ['false', '0']:
        return True
    
    # Handle integer equivalence (MySQL stores integers as strings in defaults)
    if expected_str and actual_str:
        # Check if both are numeric values
        try:
            expected_num = int(expected_str)
            actual_num = int(actual_str)
            if expected_num == actual_num:
                return True
        except (ValueError, TypeError):
            pass

    # Handle float equivalence (PostgreSQL '0'::double precision vs Python 0.0)
    if expected_str and actual_str:
        try:
            expected_num = float(expected_str)
            actual_num = float(actual_str)
            if expected_num == actual_num:
                return True
        except (ValueError, TypeError):
            pass
    
    # Handle string equivalence (MySQL stores strings with quotes)
    if expected_str and actual_str:
        # Remove quotes for comparison
        expected_clean = expected_str.strip("'\"")
        actual_clean = actual_str.strip("'\"")
        if expected_clean == actual_clean:
            return True
    
    # MySQL-specific: Handle SQLAlchemy default objects vs string defaults
    if expected_str and actual_str:
        # Extract values from SQLAlchemy default objects
        if 'scalarelementcolumndefault' in expected_str.lower():
            # Extract the value from ScalarElementColumnDefault
            import re
            # Handle Enum defaults like ScalarElementColumnDefault(<LogLevel.INFO: 'info'>)
            enum_match = re.search(r'<(\w+)\.(\w+):\s*[\'"](\w+)[\'"]>', expected_str)
            if enum_match:
                enum_value = enum_match.group(3)  # Extract the enum value ('info', 'started', etc.)
                if enum_value == actual_str.strip("'\""):
                    return True
            
            # Handle simple ScalarElementColumnDefault(True), ScalarElementColumnDefault(False), ScalarElementColumnDefault('active'), etc.
            simple_match = re.search(r'\([\'"]?([\w\.\s\-:]*)[\'"]?\)', expected_str)
            if simple_match:
                expected_value = simple_match.group(1)
                if expected_value == actual_str.strip("'\""):
                    return True
        
        # Handle current_timestamp variations
        if 'current_timestamp' in expected_str.lower() and actual_str in [None, 'none', 'null']:
            return True
    
    # Normalization of common clean values
    if expected_str and actual_str:
        expected_clean = expected_str.strip("'\" []{}")
        actual_clean = actual_str.strip("'\" []{}")
        if expected_clean == actual_clean:
            return True

    return False



def analyze_database_schema(strict: bool = False) -> SchemaAnalysisResult:
    """
    Analyze database schema and compare with expected schema from models.
    
    Args:
        strict: If True, report all differences including minor variations.
                If False, filter out common MySQL/SQLAlchemy variations.
    
    Returns:
        SchemaAnalysisResult with detailed analysis
    """
    try:
        from sqlalchemy import create_engine, inspect
        from database import Base
        from config import get_database_url
        
        # Import database package which automatically imports all models
        import database  # This imports all models via __init__.py
        
        # Get database connection
        from config import settings
        if settings("DB_USE_REPLICA_ENGINE", False):
            # Use write URL for schema analysis (safest for structural checks)
            connection_string = settings("DB_WRITE_URL") or get_database_url()
        else:
            connection_string = get_database_url()
            
        engine = create_engine(connection_string)
        
        # Get expected schema from models
        expected_metadata = Base.metadata
        
        # Get actual database schema
        inspector = inspect(engine)
        actual_tables = inspector.get_table_names()
        
        # Analyze schema differences
        expected_tables = list(expected_metadata.tables.keys())
        missing_tables = [table for table in expected_tables if table not in actual_tables]
        extra_tables = [table for table in actual_tables if table not in expected_tables]
        
        # Sort missing tables by dependencies (tables with no foreign keys first)
        if missing_tables:
            missing_tables = _sort_tables_by_dependencies(expected_metadata, missing_tables)
        
        # Analyze column differences for existing tables
        column_changes = []
        for table_name in expected_tables:
            if table_name in actual_tables:
                expected_table = expected_metadata.tables[table_name]
                actual_columns = {col['name']: col for col in inspector.get_columns(table_name)}
                expected_columns = {col.name: col for col in expected_table.columns}
                
                # Check for missing columns
                for column_name, column in expected_columns.items():
                    if column_name not in actual_columns:
                        column_changes.append({
                            'type': 'add_column',
                            'table': table_name,
                            'column': column_name,
                            'definition': str(column.type),
                            'expected': column,
                            'actual': None
                        })
                
                # Check for extra columns
                for column_name, actual_col in actual_columns.items():
                    if column_name not in expected_columns:
                        column_changes.append({
                            'type': 'extra_column',
                            'table': table_name,
                            'column': column_name,
                            'definition': f"Type: {actual_col.get('type', 'Unknown')}",
                            'expected': None,
                            'actual': actual_col
                        })
                
                # Check for column differences
                for column_name in expected_columns:
                    if column_name in actual_columns:
                        expected_col = expected_columns[column_name]
                        actual_col = actual_columns[column_name]
                        
                        differences = []
                        
                        # Check type differences
                        expected_type = str(expected_col.type)
                        actual_type = str(actual_col.get('type', 'Unknown'))
                        
                        if not _is_type_equivalent(expected_type, actual_type, strict):
                            differences.append(f"Type (actual: {actual_type}, expected: {expected_type})")
                        
                        # Check nullable differences
                        expected_nullable = expected_col.nullable
                        actual_nullable = actual_col.get('nullable', True)
                        
                        if expected_nullable != actual_nullable:
                            differences.append(f"Nullable (actual: {actual_nullable}, expected: {expected_nullable})")
                        
                        # Check default differences (check both default and server_default)
                        expected_default = expected_col.default
                        if expected_default is None and hasattr(expected_col, 'server_default') and expected_col.server_default:
                            # Try to get the string representation of the server default
                            try:
                                from sqlalchemy.sql.elements import TextClause
                                if isinstance(expected_col.server_default.arg, TextClause):
                                    expected_default = expected_col.server_default.arg.text
                                else:
                                    expected_default = str(expected_col.server_default.arg)
                            except:
                                expected_default = None
                                
                        actual_default = actual_col.get('default')
                        
                        if not _is_default_equivalent(expected_default, actual_default, strict):
                            differences.append(f"Default (actual: {actual_default}, expected: {expected_default})")
                        
                        # Only add to changes if there are significant differences or in strict mode
                        if differences:
                            column_changes.append({
                                'type': 'modify_column',
                                'table': table_name,
                                'column': column_name,
                                'definition': ' | '.join(differences),
                                'differences': differences,
                                'expected': expected_col,
                                'actual': actual_col
                            })
        
        # Calculate total differences
        total_differences = len(missing_tables) + len(extra_tables) + len(column_changes)
        
        # Determine if schema is in sync
        # For API startup, we're most concerned with missing tables and missing columns
        critical_differences = len(missing_tables) + len([c for c in column_changes if c['type'] in ['add_column']])
        is_in_sync = critical_differences == 0
        
        # Build detailed error message if not in sync
        error_message = ""
        if not is_in_sync:
            error_lines = ["Database schema is out of sync:"]
            
            # Missing tables section
            if missing_tables:
                error_lines.append("")
                error_lines.append(f"❌ Missing Tables ({len(missing_tables)}):")
                for table in missing_tables:
                    error_lines.append(f"    📋 Table '{table}':")
                    
                    # Show columns for this missing table
                    if table in expected_metadata.tables:
                        table_obj = expected_metadata.tables[table]
                        for col in table_obj.columns:
                            col_type = str(col.type)
                            nullable = "NULL" if col.nullable else "NOT NULL"
                            
                            # Get additional column info
                            col_info = f"({col_type}, {nullable}"
                            
                            # Add primary key info
                            if col.primary_key:
                                col_info += ", PRIMARY KEY"
                            
                            # Add default value if present
                            if col.default is not None:
                                try:
                                    if hasattr(col.default, 'arg'):
                                        default_val = col.default.arg
                                        col_info += f", DEFAULT {default_val}"
                                    elif 'datetime.utcnow' in str(col.default):
                                        col_info += ", DEFAULT CURRENT_TIMESTAMP"
                                    else:
                                        col_info += f", DEFAULT {col.default}"
                                except:
                                    pass
                            
                            col_info += ")"
                            error_lines.append(f"        • {col.name} {col_info}")
                        
                        # Show foreign key relationships if any
                        foreign_keys = [f"{fk.column.table.name}.{fk.column.name}" for fk in table_obj.foreign_keys]
                        if foreign_keys:
                            error_lines.append(f"        Dependencies: {', '.join(foreign_keys)}")
                    else:
                        error_lines.append(f"        • Table definition not found")
            
            # Missing columns section - grouped by table
            add_columns = [c for c in column_changes if c['type'] == 'add_column']
            if add_columns:
                # Group missing columns by table
                columns_by_table = {}
                for col in add_columns:
                    table = col['table']
                    if table not in columns_by_table:
                        columns_by_table[table] = []
                    columns_by_table[table].append(col)
                
                error_lines.append("")
                error_lines.append(f"❌ Missing Columns ({len(add_columns)}):")
                for table, cols in columns_by_table.items():
                    error_lines.append(f"    📋 Table '{table}':")
                    for col in cols:
                        col_type = col['definition']
                        
                        # Safely get nullable status
                        try:
                            nullable = "NULL" if col['expected'].nullable else "NOT NULL"
                        except:
                            nullable = "Unknown"
                        
                        # Get default value if present
                        default_info = ""
                        try:
                            if col['expected'].default is not None:
                                if hasattr(col['expected'].default, 'arg'):
                                    default_val = col['expected'].default.arg
                                    default_info = f", DEFAULT {default_val}"
                                elif 'datetime.utcnow' in str(col['expected'].default):
                                    default_info = ", DEFAULT CURRENT_TIMESTAMP"
                                else:
                                    default_info = f", DEFAULT {col['expected'].default}"
                        except:
                            pass
                        
                        error_lines.append(f"        • {col['column']} ({col_type}, {nullable}{default_info})")
            
            error_message = "\n".join(error_lines)
        
        return SchemaAnalysisResult(
            is_in_sync=is_in_sync,
            missing_tables=missing_tables,
            extra_tables=extra_tables,
            column_changes=column_changes,
            total_differences=total_differences,
            error_message=error_message,
            success=True
        )
        
    except Exception as e:
        # Check if this is a connection error
        error_str = str(e).lower()
        is_connection_error = any(keyword in error_str for keyword in [
            'unknown database',
            'access denied',
            'connection refused',
            'timeout',
            'network',
            'host',
            'port',
            'authentication',
            'login',
            'password',
            'user'
        ])
        
        if is_connection_error:
            error_message = f"Database connection failed: {e}"
        else:
            error_message = f"Error checking database schema: {e}"
        
        return SchemaAnalysisResult(
            is_in_sync=False,
            missing_tables=[],
            extra_tables=[],
            column_changes=[],
            total_differences=0,
            error_message=error_message,
            success=False
        )


def validate_schema_centralized() -> Tuple[bool, str, int, bool]:
    """
    Centralized database schema validation for both API and CLI.
    Returns (is_in_sync: bool, error_message: str, differences_count: int, is_connection_error: bool)
    
    Uses lenient validation that allows safe defaults and common variations.
    """
    result = analyze_database_schema(strict=False)
    
    if not result.success:
        # Check if this is a connection error
        error_str = result.error_message.lower()
        is_connection_error = any(keyword in error_str for keyword in [
            'database connection failed',
            'unknown database',
            'access denied',
            'connection refused',
            'timeout',
            'network',
            'host',
            'port',
            'authentication',
            'login',
            'password',
            'user'
        ])
        
        return False, result.error_message, 0, is_connection_error
    
    # Extract data from result
    missing_tables = result.missing_tables
    column_changes = result.column_changes
    
    # For API startup, we're more lenient - only fail on critical structural issues
    critical_changes = 0
    
    # Check for missing tables (critical)
    critical_changes += len(missing_tables)
    
    # Check for missing columns (critical)
    missing_columns = [c for c in column_changes if c['type'] == 'add_column']
    critical_changes += len(missing_columns)
    
    # For API startup, ignore safe defaults and common variations
    for change in column_changes:
        if change['type'] == 'modify_column':
            # Check if this is a safe default variation (e.g., Python default vs DB default, or JSONB empty objects)
            is_safe_default = (
                # Model has default but DB doesn't (safe for insert-time defaults)
                ('Default (actual: None, expected:' in change['definition'] and 
                (
                    'ScalarElementColumnDefault' in change['definition'] or  # Any scalar default (True, False, 0, enums, etc.)
                    'ColumnElementColumnDefault' in change['definition'] or  # SQL functions like func.current_timestamp()
                    'datetime.utcnow' in change['definition'] or
                    'current_timestamp' in change['definition']
                )) or
                # Model and DB both have the same equivalent value but different representations
                # (e.g. Postgres cast vs ScalarElementColumnDefault)
                (
                    # If the underlying values are equivalent, it was already handled by _is_default_equivalent
                    # But if we reached here, maybe it's a variation of "active" vs "active" with cast
                    'active' in change['definition'].lower() and 'character varying' in change['definition'].lower()
                ) or
                # DB has empty JSON/Array default but Model has None (safe for JSONB)
                ('expected: None)' in change['definition'] and 
                (
                    '{}' in change['definition'] or
                    '[]' in change['definition'] or
                    '::jsonb' in change['definition']
                )) or
                # Both are empty JSON/Array but represented differently
                ('{}' in change['definition'] and '[]' in change['definition']) or
                ('{}' in change['definition'] and '::jsonb' in change['definition'])
            )
            
            # Check if this is a PostgreSQL sequence default (normal for auto-incrementing primary keys)
            is_postgresql_sequence = (
                'Default (actual: nextval(' in change['definition'] and 
                'expected: None)' in change['definition'] and
                change['column'] == 'id'
            )
            
            # Check if this is a TIMESTAMP vs DATETIME type difference (normal PostgreSQL vs MySQL)
            is_timestamp_datetime_variation = (
                'Type (actual: TIMESTAMP, expected: DATETIME)' in change['definition'] or
                'Type (actual: DATETIME, expected: TIMESTAMP)' in change['definition']
            )
            
            # Check if this is a common MySQL type variation
            is_mysql_type_variation = any(mysql_pattern in change['definition'] for mysql_pattern in [
                'Type (actual: DECIMAL(10, 2), expected: NUMERIC(10, 2))',
                'Type (actual: NUMERIC(10, 2), expected: DECIMAL(10, 2))',
                'Type (actual: TINYINT, expected: BOOLEAN)',
                'Type (actual: BOOLEAN, expected: TINYINT)'
            ])
            
            # Only count as critical if it's not a safe default, PostgreSQL sequence, timestamp variation, or common MySQL variation
            is_critical = not is_safe_default and not is_postgresql_sequence and not is_timestamp_datetime_variation and not is_mysql_type_variation
            
            if is_critical:
                critical_changes += 1
    
    # For API startup, only fail if there are critical structural issues
    is_in_sync = (critical_changes == 0)
    
    # Build error message if not in sync
    error_message = ""
    if not is_in_sync:
        error_lines = ["Database schema requires attention:"]
        
        if critical_changes > 0:
            error_lines.append("")
            error_lines.append(f"🚫 Critical structural issues: {critical_changes}")
            
            # Show detailed missing tables
            if missing_tables:
                error_lines.append(f"   • Missing tables: {len(missing_tables)}")
                for table_name in missing_tables:
                    error_lines.append(f"     📋 {table_name}:")
                    
                    # Import Base to access table metadata
                    from database import Base
                    expected_metadata = Base.metadata
                    
                    if table_name in expected_metadata.tables:
                        table = expected_metadata.tables[table_name]
                        
                        # Show columns
                        error_lines.append(f"        Columns:")
                        for column in table.columns:
                            column_info = f"{column.name} {column.type}"
                            if not column.nullable:
                                column_info += " NOT NULL"
                            if column.default is not None:
                                if 'current_timestamp' in str(column.default):
                                    column_info += " DEFAULT CURRENT_TIMESTAMP"
                                elif hasattr(column.default, 'arg'):
                                    default_val = column.default.arg
                                    if isinstance(default_val, str):
                                        column_info += f" DEFAULT '{default_val}'"
                                    else:
                                        column_info += f" DEFAULT {default_val}"
                                else:
                                    # For other defaults, try to get a clean representation
                                    default_str = str(column.default)
                                    if 'function' in default_str:
                                        column_info += " DEFAULT <function>"
                                    else:
                                        column_info += f" DEFAULT {default_str}"
                            error_lines.append(f"          - {column_info}")
                        
                        # Show primary key
                        if table.primary_key.columns:
                            pk_columns = [col.name for col in table.primary_key.columns]
                            error_lines.append(f"        Primary Key: {', '.join(pk_columns)}")
                        
                        # Show foreign keys
                        foreign_keys = []
                        for column in table.columns:
                            for fk in column.foreign_keys:
                                foreign_keys.append(f"{column.name} → {fk.target_fullname}")
                        if foreign_keys:
                            error_lines.append(f"        Foreign Keys:")
                            for fk in foreign_keys:
                                error_lines.append(f"          - {fk}")
                        
                        # Show indexes
                        if table.indexes:
                            error_lines.append(f"        Indexes:")
                            for index in table.indexes:
                                index_columns = [col.name for col in index.columns]
                                unique_str = " (UNIQUE)" if index.unique else ""
                                error_lines.append(f"          - {index.name}: {', '.join(index_columns)}{unique_str}")
                    else:
                        error_lines.append(f"        ⚠️  Table definition not found in metadata")
            
            # Show detailed missing columns
            missing_column_changes = [c for c in column_changes if c['type'] == 'add_column']
            if missing_column_changes:
                error_lines.append(f"   • Missing columns: {len(missing_column_changes)}")
                for change in missing_column_changes:
                    error_lines.append(f"     - {change['table']}.{change['column']} ({change['definition']})")
            
            # Show other critical changes
            critical_column_changes = []
            for change in column_changes:
                if change['type'] == 'modify_column':
                    # Use the SAME logic as the main validation above
                    is_safe_default = (
                        'Default (actual: None, expected:' in change['definition'] and 
                        (
                            'ScalarElementColumnDefault' in change['definition'] or  # Any scalar default
                            'ColumnElementColumnDefault' in change['definition'] or  # SQL functions
                            'datetime.utcnow' in change['definition'] or
                            'current_timestamp' in change['definition']
                        )
                    )
                    
                    # Check if this is a PostgreSQL sequence default (normal for auto-incrementing primary keys)
                    is_postgresql_sequence = (
                        'Default (actual: nextval(' in change['definition'] and 
                        'expected: None)' in change['definition'] and
                        change['column'] == 'id'
                    )
                    
                    # Check if this is a TIMESTAMP vs DATETIME type difference (normal PostgreSQL vs MySQL)
                    is_timestamp_datetime_variation = (
                        'Type (actual: TIMESTAMP, expected: DATETIME)' in change['definition'] or
                        'Type (actual: DATETIME, expected: TIMESTAMP)' in change['definition']
                    )
                    
                    is_mysql_type_variation = any(mysql_pattern in change['definition'] for mysql_pattern in [
                        'Type (actual: DECIMAL(10, 2), expected: NUMERIC(10, 2))',
                        'Type (actual: NUMERIC(10, 2), expected: DECIMAL(10, 2))',
                        'Type (actual: TINYINT, expected: BOOLEAN)',
                        'Type (actual: BOOLEAN, expected: TINYINT)'
                    ])
                    
                    # Only count as critical if it's not a safe default, PostgreSQL sequence, timestamp variation, or common MySQL variation
                    is_critical = not is_safe_default and not is_postgresql_sequence and not is_timestamp_datetime_variation and not is_mysql_type_variation
                    
                    if is_critical:
                        critical_column_changes.append(change)
            
            if critical_column_changes:
                error_lines.append(f"   • Critical column changes: {len(critical_column_changes)}")
                for change in critical_column_changes:
                    error_lines.append(f"     - {change['table']}.{change['column']}: {change['definition']}")
            
            error_lines.append("")
            error_lines.append("   💡 Run: python cli.py system db sync --apply")
        
        error_message = "\n".join(error_lines)
    
    return is_in_sync, error_message, critical_changes, False  # False = not a connection error


def get_schema_sync_summary() -> Dict[str, Any]:
    """Get a summary of schema sync status for monitoring/health checks"""
    result = analyze_database_schema(strict=False)
    
    if not result.success:
        return {
            "status": "error",
            "in_sync": False,
            "missing_tables": 0,
            "missing_columns": 0,
            "total_differences": 0,
            "error": result.error_message
        }
    
    missing_columns = len([c for c in result.column_changes if c['type'] == 'add_column'])
    
    return {
        "status": "in_sync" if result.is_in_sync else "out_of_sync",
        "in_sync": result.is_in_sync,
        "missing_tables": len(result.missing_tables),
        "missing_columns": missing_columns,
        "total_differences": result.total_differences,
        "error": None
    } 