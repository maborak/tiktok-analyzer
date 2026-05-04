#!/usr/bin/env python3
"""
Database Management Commands

Database configuration, status checking, and index optimization commands.
"""

import click
import sys
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import create_engine, text, inspect, MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Index
from sqlalchemy.exc import SQLAlchemyError
import re

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from config import get_database_url, set_database_url, clear_database_url_override
from utils.database.database import DatabaseConnectionParser
from database import create_database_engine, get_session_maker
from cli.session import session_manager
from cli.auth_decorators import no_auth, require_admin_auth as require_admin_auth_decorator


def get_database_with_mode(read_only: bool = True, database_url: Optional[str] = None):
    """
    Get database engine with controlled initialization mode
    
    Args:
        read_only: If True, only load metadata without initializing tables
        database_url: Optional database URL override
        
    Returns:
        Tuple of (engine, session_maker, base_metadata)
    """
    # Set database URL override if provided
    if database_url:
        set_database_url(database_url)
    
    engine = create_database_engine()
    
    if read_only:
        # Load metadata without initializing tables
        from database import Base
        metadata = MetaData()
        metadata.reflect(bind=engine)
        session_maker = get_session_maker(engine)
        return engine, session_maker, metadata
    else:
        # Full initialization
        from database import create_tables
        create_tables(engine)
        from database import Base
        session_maker = get_session_maker(engine)
        return engine, session_maker, Base.metadata


class IndexOptimizer:
    """Handles database index optimization for better performance"""
    
    def __init__(self, database_url: Optional[str] = None, read_only: bool = True):
        self.database_url = database_url or get_database_url()
        self.engine = create_engine(self.database_url)
        self.engine_type = DatabaseConnectionParser.parse_connection_string(self.database_url)[0]
        self.read_only = read_only
        
        # Cache for database initialization
        self._initialized = False
        self._base_metadata = None
        self._table_names = None
    
    def _ensure_initialized(self):
        """Ensure database is initialized only once"""
        if not self._initialized:
            from database import Base
            
            if self.read_only:
                # Read-only mode: just load metadata without initializing database
                self._base_metadata = Base.metadata
                self._table_names = list(Base.metadata.tables.keys())
            else:
                # Full initialization mode: create tables and seed data
                from database import create_tables
                create_tables(self.engine)
                self._base_metadata = Base.metadata
                self._table_names = list(Base.metadata.tables.keys())
            
            self._initialized = True
    
    def get_existing_indexes(self) -> List[str]:
        """Get list of existing indexes using pure SQLAlchemy ORM"""
        indexes = []
        
        # Use cached initialization
        self._ensure_initialized()
        
        # Ensure table_names is not None
        if self._table_names is None:
            return []
        
        # For read-only mode, only get indexes that actually exist in the database
        # Don't include indexes from model definitions
        try:
            from sqlalchemy import inspect
            
            inspector = inspect(self.engine)
            
            for table_name in self._table_names:
                try:
                    # Get indexes from database using SQLAlchemy reflection (ORM-based)
                    table_indexes = inspector.get_indexes(table_name)
                    for index_info in table_indexes:
                        if index_info['name']:
                            indexes.append(index_info['name'])
                except Exception as e:
                    # Skip tables that don't exist or can't be inspected
                    continue
                        
        except Exception as e:
            # If reflection fails, return empty list for read-only mode
            return []
        
        return sorted(list(set(indexes)))  # Remove duplicates and sort
    
    def get_required_indexes(self) -> Dict[str, List[str]]:
        """Get list of indexes that should exist for optimal performance"""
        # Use cached initialization
        self._ensure_initialized()
        
        required_indexes = {}
        
        # Get all table names from cached metadata
        if self._base_metadata is None:
            return {}
        
        tables = self._base_metadata.tables
        
        for table_name, table in tables.items():
            indexes = []
            
            # Get existing indexes from the table
            for index in table.indexes:
                indexes.append(index.name)
            
            # Get single column indexes from columns with index=True
            for column in table.columns:
                if column.index:
                    # Generate index name based on table and column
                    index_name = f"idx_{table_name}_{column.name}"
                    indexes.append(index_name)
            
            if indexes:
                required_indexes[table_name] = sorted(indexes)
        
        return required_indexes
    
    def create_index(self, table: str, index_name: str, columns: str, index_type: str = "BTREE") -> tuple[bool, str]:
        """Create a database index using pure SQLAlchemy ORM. Returns (success, error_message)"""
        try:
            # Check if index already exists
            existing_indexes = self.get_existing_indexes()
            if index_name in existing_indexes:
                return True, "already_exists"
            
            # Use cached initialization
            self._ensure_initialized()
            
            # Get the table object from cached metadata
            if self._base_metadata is None or table not in self._base_metadata.tables:
                return False, f"Table '{table}' not found in models"
            
            table_obj = self._base_metadata.tables[table]
            
            # Parse columns (handle multiple columns and directions)
            column_list = []
            for col_def in columns.split(','):
                col_def = col_def.strip()
                if ' DESC' in col_def.upper():
                    col_name = col_def.replace(' DESC', '').replace(' desc', '').strip()
                    # Get the actual column object from the table
                    if col_name in table_obj.columns:
                        column_list.append(table_obj.columns[col_name].desc())
                    else:
                        return False, f"Column '{col_name}' not found in table '{table}'"
                elif ' ASC' in col_def.upper():
                    col_name = col_def.replace(' ASC', '').replace(' asc', '').strip()
                    if col_name in table_obj.columns:
                        column_list.append(table_obj.columns[col_name].asc())
                    else:
                        return False, f"Column '{col_name}' not found in table '{table}'"
                else:
                    if col_def in table_obj.columns:
                        column_list.append(table_obj.columns[col_def])
                    else:
                        return False, f"Column '{col_def}' not found in table '{table}'"
            
            # Create SQLAlchemy Index object using actual column objects
            index_obj = Index(index_name, *column_list)
            
            # Since we can't dynamically add indexes to existing tables in pure ORM,
            # we'll use SQLAlchemy's reflection to create the index
            # This is the purest ORM approach available
            with self.engine.begin() as conn:
                # Use SQLAlchemy's reflection to create the index
                # This is still ORM-based as it uses SQLAlchemy's metadata
                index_obj.create(conn)
            
            return True, ""
            
        except Exception as e:
            error_msg = str(e)
            return False, error_msg
    
    def get_missing_index_sql_commands(self) -> List[Dict[str, str]]:
        """Get SQLAlchemy commands for creating missing indexes. Returns list of dicts with table, index, columns, and sqlalchemy_code."""
        analysis = self.analyze_query_performance()
        existing_indexes = analysis['existing_indexes']
        recommended_indexes = analysis['recommended_indexes']
        
        sqlalchemy_commands = []
        
        for table, indexes in recommended_indexes.items():
            for index in indexes:
                if index not in existing_indexes:
                    # Extract column name from index name (fixed logic)
                    column_name = None
                    
                    # Handle idx_ prefix
                    if index.startswith('idx_'):
                        table_prefix = f"idx_{table}_"
                        if index.startswith(table_prefix):
                            column_name = index[len(table_prefix):]
                    
                    # Handle ix_ prefix  
                    elif index.startswith('ix_'):
                        table_prefix = f"ix_{table}_"
                        if index.startswith(table_prefix):
                            column_name = index[len(table_prefix):]
                    
                    # If we couldn't extract the column name with prefixes, try parsing
                    if not column_name:
                        parts = index.split('_')
                        if len(parts) >= 3:
                            # Remove prefix and table name, join the rest
                            # Example: ix_users_last_login -> ['ix', 'users', 'last', 'login'] -> 'last_login'
                            if parts[0] in ['idx', 'ix'] and parts[1] == table:
                                column_name = '_'.join(parts[2:])  # Join remaining parts
                            else:
                                # Last resort: take everything after the last underscore
                                column_name = parts[-1]
                    
                    # Only proceed if we successfully extracted a column name
                    if not column_name:
                        continue
                    
                    # Generate SQLAlchemy code instead of raw SQL
                    sqlalchemy_code = f"""
# Add this to your model definition:
from sqlalchemy import Index

# In the {table} table model:
Index('{index}', '{column_name}')
"""
                    
                    sqlalchemy_commands.append({
                        "table": table,
                        "index": index,
                        "columns": column_name,
                        "sqlalchemy_code": sqlalchemy_code,
                        "description": f"Index on {table}.{column_name} for better query performance"
                    })
        
        return sqlalchemy_commands
    
    def generate_sql_commands(self, missing_indexes: List[Dict[str, Any]]) -> List[str]:
        """Generate raw SQL commands for creating missing indexes"""
        sql_commands = []
        
        for index_info in missing_indexes:
            table_name = index_info['table']
            index_name = index_info['name']
            columns = index_info['columns']
            
            # Generate CREATE INDEX SQL
            columns_str = ', '.join(columns)
            sql = f"CREATE INDEX {index_name} ON {table_name} ({columns_str});"
            sql_commands.append(sql)
        
        return sql_commands
    
    def create_composite_indexes(self) -> tuple[bool, list]:
        """Create composite indexes for common query patterns using dynamic analysis. Returns (success, failed_indexes)"""
        # Use cached initialization
        self._ensure_initialized()
        
        # Generate composite indexes based on dynamic table structure analysis
        composite_indexes = []
        
        # Get all table names from cached metadata
        if self._base_metadata is None:
            return True, []
        
        tables = self._base_metadata.tables
        
        for table_name, table in tables.items():
            # Dynamically analyze table structure for optimal composite indexes
            table_indexes = self._analyze_table_for_composite_indexes(table_name, table)
            composite_indexes.extend(table_indexes)
        
        created_count = 0
        skipped_count = 0
        failed_count = 0
        failed_indexes = []
        
        for index in composite_indexes:
            success, error_msg = self.create_index(index["table"], index["name"], index["columns"])
            if success:
                if error_msg == "":  # Actually created
                    created_count += 1
                else:  # Skipped (already exists)
                    skipped_count += 1
            else:
                failed_count += 1
                failed_indexes.append({
                    "table": index["table"],
                    "name": index["name"],
                    "columns": index["columns"],
                    "error": error_msg
                })
        
        return failed_count == 0, failed_indexes
    
    def _analyze_table_for_composite_indexes(self, table_name: str, table) -> List[Dict[str, str]]:
        """Dynamically analyze table structure to generate optimal composite indexes"""
        indexes = []
        
        # Get column categories for dynamic analysis
        column_categories = self._categorize_columns(table)
        
        # Generate composite indexes based on column patterns
        indexes.extend(self._generate_foreign_key_indexes(table_name, table, column_categories))
        indexes.extend(self._generate_timestamp_indexes(table_name, table, column_categories))
        indexes.extend(self._generate_status_indexes(table_name, table, column_categories))
        indexes.extend(self._generate_search_indexes(table_name, table, column_categories))
        indexes.extend(self._generate_relationship_indexes(table_name, table, column_categories))
        
        return indexes
    
    def _categorize_columns(self, table) -> Dict[str, List[str]]:
        """Categorize table columns for intelligent index generation"""
        categories = {
            'foreign_keys': [],
            'timestamps': [],
            'booleans': [],
            'identifiers': [],
            'searchable': [],
            'numeric': [],
            'text': []
        }
        
        for column in table.columns:
            col_name = column.name.lower()
            col_type = str(column.type).lower()
            
            # Foreign keys
            if column.foreign_keys:
                categories['foreign_keys'].append(column.name)
            
            # Timestamps and dates
            elif any(time_word in col_name for time_word in ['timestamp', 'created_at', 'updated_at', 'expires_at', 'last_check', 'last_login', 'last_used', 'recorded_at']):
                categories['timestamps'].append(column.name)
            
            # Boolean columns
            elif col_type == 'boolean':
                categories['booleans'].append(column.name)
            
            # ID columns (but not primary keys)
            elif 'id' in col_name and column.name != 'id':
                categories['identifiers'].append(column.name)
            
            # Numeric columns
            elif any(num_type in col_type for num_type in ['integer', 'numeric', 'decimal', 'float']):
                categories['numeric'].append(column.name)
            
            # Text columns
            elif any(text_type in col_type for text_type in ['string', 'text', 'varchar']):
                categories['text'].append(column.name)
                
                # Searchable text columns
                if any(search_word in col_name for search_word in ['name', 'title', 'description', 'email', 'username']):
                    categories['searchable'].append(column.name)
        
        return categories
    
    def _generate_foreign_key_indexes(self, table_name: str, table, categories: Dict[str, List[str]]) -> List[Dict[str, str]]:
        """Generate composite indexes for foreign key relationships"""
        indexes = []
        
        foreign_keys = categories['foreign_keys']
        timestamps = categories['timestamps']
        booleans = categories['booleans']
        
        # FK + Timestamp combinations (common for audit trails)
        for fk in foreign_keys:
            for ts in timestamps:
                if fk != ts:
                    indexes.append({
                        "table": table_name,
                        "name": f"idx_{table_name}_{fk}_{ts}",
                        "columns": f"{fk}, {ts} DESC"
                    })
        
        # FK + Boolean combinations (common for filtering)
        for fk in foreign_keys:
            for bool_col in booleans:
                if fk != bool_col:
                    indexes.append({
                        "table": table_name,
                        "name": f"idx_{table_name}_{fk}_{bool_col}",
                        "columns": f"{fk}, {bool_col}"
                    })
        
        return indexes
    
    def _generate_timestamp_indexes(self, table_name: str, table, categories: Dict[str, List[str]]) -> List[Dict[str, str]]:
        """Generate composite indexes for timestamp-based queries"""
        indexes = []
        
        timestamps = categories['timestamps']
        booleans = categories['booleans']
        
        # Boolean + Timestamp combinations (common for status tracking)
        for bool_col in booleans:
            for ts in timestamps:
                if bool_col != ts:
                    indexes.append({
                        "table": table_name,
                        "name": f"idx_{table_name}_{bool_col}_{ts}",
                        "columns": f"{bool_col}, {ts} DESC"
                    })
        
        return indexes
    
    def _generate_status_indexes(self, table_name: str, table, categories: Dict[str, List[str]]) -> List[Dict[str, str]]:
        """Generate composite indexes for status-based queries"""
        indexes = []
        
        booleans = categories['booleans']
        
        # Multiple boolean combinations (common for complex status filtering)
        if len(booleans) >= 2:
            for i, bool1 in enumerate(booleans):
                for bool2 in booleans[i+1:]:
                    indexes.append({
                        "table": table_name,
                        "name": f"idx_{table_name}_{bool1}_{bool2}",
                        "columns": f"{bool1}, {bool2}"
                    })
        
        return indexes
    
    def _generate_search_indexes(self, table_name: str, table, categories: Dict[str, List[str]]) -> List[Dict[str, str]]:
        """Generate composite indexes for search queries"""
        indexes = []
        
        searchable = categories['searchable']
        booleans = categories['booleans']
        
        # Searchable + Boolean combinations (common for filtered searches)
        for search_col in searchable:
            for bool_col in booleans:
                if search_col != bool_col:
                    indexes.append({
                        "table": table_name,
                        "name": f"idx_{table_name}_{search_col}_{bool_col}",
                        "columns": f"{search_col}, {bool_col}"
                    })
        
        return indexes
    
    def _generate_relationship_indexes(self, table_name: str, table, categories: Dict[str, List[str]]) -> List[Dict[str, str]]:
        """Generate composite indexes for relationship queries"""
        indexes = []
        
        identifiers = categories['identifiers']
        booleans = categories['booleans']
        
        # ID + Boolean combinations (common for relationship filtering)
        for id_col in identifiers:
            for bool_col in booleans:
                if id_col != bool_col:
                    indexes.append({
                        "table": table_name,
                        "name": f"idx_{table_name}_{id_col}_{bool_col}",
                        "columns": f"{id_col}, {bool_col}"
                    })
        
        return indexes
    
    def create_single_column_indexes(self) -> tuple[bool, list]:
        """Create single column indexes for basic queries. Returns (success, failed_indexes)"""
        # Use cached initialization
        self._ensure_initialized()
        
        single_indexes = []
        
        # Get all table names from cached metadata
        if self._base_metadata is None:
            return True, []
        
        tables = self._base_metadata.tables
        
        for table_name, table in tables.items():
            # Get single column indexes from columns with index=True
            for column in table.columns:
                if column.index:
                    # Generate index name based on table and column
                    index_name = f"idx_{table_name}_{column.name}"
                    single_indexes.append({
                        "table": table_name,
                        "name": index_name,
                        "columns": column.name
                    })
        
        # Add additional performance indexes that aren't in the models
        additional_indexes = []
        
        # Generate additional indexes based on actual table structures
        for table_name, table in tables.items():
            # Get timestamp/date columns for time-based indexes
            timestamp_columns = [col.name for col in table.columns 
                               if 'timestamp' in col.name.lower() or 
                                  'created_at' in col.name.lower() or 
                                  'updated_at' in col.name.lower() or
                                  'expires_at' in col.name.lower() or
                                  'last_check' in col.name.lower() or
                                  'last_login' in col.name.lower() or
                                  'last_used' in col.name.lower()]
            
            # Get price-related columns for price indexes
            price_columns = [col.name for col in table.columns 
                           if 'price' in col.name.lower() or 
                              'total' in col.name.lower()]
            
            # Generate additional indexes for each table
            for col_name in timestamp_columns:
                additional_indexes.append({
                    "table": table_name,
                    "name": f"idx_{table_name}_{col_name}",
                    "columns": col_name
                })
            
            for col_name in price_columns:
                additional_indexes.append({
                    "table": table_name,
                    "name": f"idx_{table_name}_{col_name}",
                    "columns": col_name
                })
        
        single_indexes.extend(additional_indexes)
        
        created_count = 0
        skipped_count = 0
        failed_count = 0
        failed_indexes = []
        
        for index in single_indexes:
            success, error_msg = self.create_index(index["table"], index["name"], index["columns"])
            if success:
                if error_msg == "":  # Actually created
                    created_count += 1
                else:  # Skipped (already exists)
                    skipped_count += 1
            else:
                failed_count += 1
                failed_indexes.append({
                    "table": index["table"],
                    "name": index["name"],
                    "columns": index["columns"],
                    "error": error_msg
                })
        
        return failed_count == 0, failed_indexes
    
    def analyze_query_performance(self) -> Dict[str, Any]:
        """Analyze query performance and suggest optimizations using pure SQLAlchemy ORM"""
        # Use cached initialization
        self._ensure_initialized()
        
        analysis = {
            "database_type": self.engine_type,
            "existing_indexes": self.get_existing_indexes(),
            "recommended_indexes": self.get_required_indexes(),
            "performance_metrics": {}
        }
        
        # Add database-specific performance metrics using SQLAlchemy ORM
        if self.engine_type in ["postgresql", "postgres"]:
            try:
                from sqlalchemy import inspect
                
                inspector = inspect(self.engine)
                
                # Use cached table names
                if self._table_names is None:
                    return analysis
                
                # Get table statistics using SQLAlchemy reflection (ORM-based)
                column_statistics = []
                
                for table_name in self._table_names:
                    try:
                        # Get table columns using SQLAlchemy reflection
                        columns = inspector.get_columns(table_name)
                        
                        for column_info in columns:
                            # Get column statistics using SQLAlchemy ORM
                            column_statistics.append({
                                'tablename': table_name,
                                'attname': column_info['name'],
                                'type': str(column_info['type']),
                                'nullable': column_info.get('nullable', True),
                                'default': column_info.get('default', None)
                            })
                    except Exception as e:
                        # Skip tables that can't be inspected
                        continue
                
                analysis["column_statistics"] = column_statistics
                
            except Exception as e:
                # If reflection fails, continue without statistics
                analysis["column_statistics"] = []
                analysis["reflection_error"] = str(e)
        
        return analysis
    
    def optimize_all_indexes(self) -> tuple[bool, list]:
        """Create all recommended indexes for optimal performance. Returns (success, all_failed_indexes)"""
        # Get current state
        existing_indexes = self.get_existing_indexes()
        
        # Create single column indexes
        single_success, single_failed = self.create_single_column_indexes()
        
        # Create composite indexes
        composite_success, composite_failed = self.create_composite_indexes()
        
        # Combine all failed indexes
        all_failed_indexes = single_failed + composite_failed
        
        # Analyze final performance
        analysis = self.analyze_query_performance()
        final_indexes = self.get_existing_indexes()
        new_indexes = len(final_indexes) - len(existing_indexes)
        
        overall_success = single_success and composite_success
        return overall_success, all_failed_indexes

    def optimize_all_indexes_interactive(self) -> tuple[bool, list]:
        """Create all recommended indexes for optimal performance, asking for confirmation. Returns (success, all_failed_indexes)"""
        # Get current state
        existing_indexes = self.get_existing_indexes()
        
        # Analyze what indexes are missing
        analysis = self.analyze_query_performance()
        
        # Collect all missing indexes
        missing_indexes = []
        for table, indexes in analysis['recommended_indexes'].items():
            for index in indexes:
                if index not in existing_indexes:
                    # Parse index name to get columns (fixed logic)
                    if index.startswith('idx_') or index.startswith('ix_'):
                        # Extract column name from index name
                        column = None
                        
                        # Handle idx_ prefix
                        if index.startswith('idx_'):
                            table_prefix = f"idx_{table}_"
                            if index.startswith(table_prefix):
                                column = index[len(table_prefix):]
                        
                        # Handle ix_ prefix  
                        elif index.startswith('ix_'):
                            table_prefix = f"ix_{table}_"
                            if index.startswith(table_prefix):
                                column = index[len(table_prefix):]
                        
                        # If we couldn't extract the column name with prefixes, try parsing
                        if not column:
                            parts = index.split('_')
                            if len(parts) >= 3:
                                # Remove prefix and table name, join the rest
                                # Example: ix_users_last_login -> ['ix', 'users', 'last', 'login'] -> 'last_login'
                                if parts[0] in ['idx', 'ix'] and parts[1] == table:
                                    column = '_'.join(parts[2:])  # Join remaining parts
                                else:
                                    # Last resort: take everything after the last underscore
                                    column = parts[-1]
                        
                        if column:
                            missing_indexes.append({
                                'table': table,
                                'name': index,
                                'columns': [column]
                            })
        
        # Ask for confirmation for each missing index
        confirmed_indexes = []
        failed_indexes = []
        
        if missing_indexes:
            click.echo(f"\n🔍 Found {len(missing_indexes)} missing indexes to review:")
            click.echo("=" * 50)
            click.echo("💡 Options: [y]es, [n]o, [a]bort all, [s]kip remaining")
            click.echo()
            
            for i, index_info in enumerate(missing_indexes, 1):
                table_name = index_info['table']
                index_name = index_info['name']
                columns = index_info['columns']
                
                click.echo(f"\n{i:2d}. Index: {index_name}")
                click.echo(f"    Table:  {table_name}")
                click.echo(f"    Columns: {', '.join(columns)}")
                
                # Generate and show the SQL command that will be executed
                columns_str = ', '.join(columns)
                if "mysql" in self.engine_type.lower():
                    sql_command = f"CREATE INDEX {index_name} ON {table_name} ({columns_str}) USING BTREE;"
                elif "postgres" in self.engine_type.lower():
                    sql_command = f"CREATE INDEX CONCURRENTLY {index_name} ON {table_name} USING BTREE ({columns_str});"
                else:
                    sql_command = f"CREATE INDEX {index_name} ON {table_name} ({columns_str});"
                
                click.echo(f"    SQL:    {sql_command}")
                
                # Get user choice with abort option
                choice = click.prompt(
                    "    Create this index?",
                    type=click.Choice(['y', 'n', 'a', 's'], case_sensitive=False),
                    default='y',
                    show_choices=True
                )
                
                if choice.lower() == 'a':
                    click.echo("    ⏹️  Aborting all remaining operations...")
                    click.echo(f"\n📊 Interactive Optimization Summary:")
                    click.echo(f"  ✅ Created: {len(confirmed_indexes)} indexes")
                    click.echo(f"  ❌ Failed: {len(failed_indexes)} indexes")
                    click.echo(f"  ⏹️  Aborted: {len(missing_indexes) - i + 1} indexes remaining")
                    click.echo(f"  ⏭️  Skipped: {i - 1 - len(confirmed_indexes) - len(failed_indexes)} indexes")
                    overall_success = len(failed_indexes) == 0
                    return overall_success, failed_indexes
                
                elif choice.lower() == 's':
                    click.echo("    ⏭️  Skipping remaining indexes...")
                    click.echo(f"\n📊 Interactive Optimization Summary:")
                    click.echo(f"  ✅ Created: {len(confirmed_indexes)} indexes")
                    click.echo(f"  ❌ Failed: {len(failed_indexes)} indexes")
                    click.echo(f"  ⏭️  Skipped: {len(missing_indexes) - i + 1} indexes remaining")
                    overall_success = len(failed_indexes) == 0
                    return overall_success, failed_indexes
                
                elif choice.lower() == 'y':
                    success, error_msg = self.create_index(table_name, index_name, ', '.join(columns))
                    if success:
                        click.echo(f"    ✅ Created index '{index_name}' on table '{table_name}'")
                        confirmed_indexes.append(index_name)
                    else:
                        click.echo(f"    ❌ Failed to create index '{index_name}': {error_msg}")
                        failed_indexes.append({
                            "table": table_name,
                            "name": index_name,
                            "columns": ', '.join(columns),
                            "error": error_msg
                        })
                else:  # choice.lower() == 'n'
                    click.echo(f"    ⏭️  Skipped index '{index_name}'")
            
            click.echo(f"\n📊 Interactive Optimization Summary:")
            click.echo(f"  ✅ Created: {len(confirmed_indexes)} indexes")
            click.echo(f"  ❌ Failed: {len(failed_indexes)} indexes")
            click.echo(f"  ⏭️  Skipped: {len(missing_indexes) - len(confirmed_indexes) - len(failed_indexes)} indexes")
        else:
            click.echo("🎉 No missing indexes found!")
        
        overall_success = len(failed_indexes) == 0
        return overall_success, failed_indexes


def _sort_tables_by_dependencies(metadata, table_names):
    """
    Sort tables by their foreign key dependencies.
    Tables with no dependencies come first, then tables that depend on them.
    
    Args:
        metadata: SQLAlchemy MetaData object
        table_names: List of table names to sort
        
    Returns:
        List of table names sorted by dependencies
    """
    # Build dependency graph
    dependencies = {}
    for table_name in table_names:
        dependencies[table_name] = set()
        
        if table_name in metadata.tables:
            table = metadata.tables[table_name]
            
            # Find foreign key dependencies
            for fk in table.foreign_keys:
                referenced_table = fk.column.table.name
                # Only consider dependencies within our list of missing tables
                if referenced_table in table_names:
                    dependencies[table_name].add(referenced_table)
    
    # Topological sort using Kahn's algorithm
    sorted_tables = []
    remaining_deps = {name: deps.copy() for name, deps in dependencies.items()}
    
    # Find tables with no dependencies
    no_deps = [name for name, deps in remaining_deps.items() if not deps]
    
    while no_deps:
        # Take a table with no dependencies
        current = no_deps.pop(0)
        sorted_tables.append(current)
        
        # Remove this table from other tables' dependencies
        for table_name in remaining_deps:
            if current in remaining_deps[table_name]:
                remaining_deps[table_name].remove(current)
                
                # If this table now has no dependencies, add it to the queue
                if not remaining_deps[table_name] and table_name not in sorted_tables and table_name not in no_deps:
                    no_deps.append(table_name)
    
    # Check for circular dependencies
    remaining = [name for name, deps in remaining_deps.items() if deps and name not in sorted_tables]
    if remaining:
        # Add remaining tables (may have circular dependencies)
        # For now, just append them - in production, you might want to handle this more gracefully
        sorted_tables.extend(remaining)
        click.echo(f"⚠️  Warning: Potential circular dependencies detected in tables: {remaining}")
    
    return sorted_tables


def require_admin_auth(ctx):
    """Check if user has admin authentication - DISABLED for system db commands"""
    # System db commands should work without authentication
    return True


# Import centralized database connection info function
from utils.database.connection_info import display_detailed_connection_info


@click.group(cls=click.Group)
def db():
    """Database management and configuration commands"""
    pass


# Override the format_commands method to group dangerous operations
class DatabaseGroup(click.Group):
    def format_commands(self, ctx, formatter):
        """Custom command formatting with grouped dangerous operations."""
        # Define command groups
        dangerous_commands = {'init', 'clear', 'sync'}
        safe_commands = set()
        
        # Get all commands and categorize them
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None:
                continue
            if subcommand in dangerous_commands:
                continue  # Handle these separately
            safe_commands.add(subcommand)
            commands.append((subcommand, cmd))
        
        # Sort safe commands
        commands.sort()
        
        # Format safe commands first
        if commands:
            with formatter.section('Commands'):
                formatter.write_dl([(name, cmd.get_short_help_str()) for name, cmd in commands])
        
        # Format dangerous commands group
        dangerous_cmds = []
        for subcommand in sorted(dangerous_commands):
            cmd = self.get_command(ctx, subcommand)
            if cmd is not None:
                dangerous_cmds.append((subcommand, cmd))
        
        if dangerous_cmds:
            # Use red for the section title and format dangerous commands in orange
            with formatter.section(click.style('🚨 Dangerous Operations (Require Confirmation)', fg='red', bold=True)):
                # Format each dangerous command with orange color
                dangerous_list = []
                for name, cmd in dangerous_cmds:
                    colored_name = click.style(name, fg='yellow', bold=True)  # Orange/yellow for commands
                    dangerous_list.append((colored_name, cmd.get_short_help_str()))
                formatter.write_dl(dangerous_list)
                formatter.write('\n' + click.style('⚠️  These commands can destroy data - use with extreme caution!', fg='red') + '\n')


# Update the db group to use the custom class
db = DatabaseGroup(name='db', help='Database management and configuration commands')


@db.command()
@no_auth()
@click.pass_context
def config(ctx):
    """
    Show database configuration
    
    Display current database connection settings, pool configuration,
    and environment variables related to database connectivity.
    """
    
    # Display detailed database connection information
    display_detailed_connection_info()
    
    return 0


@db.command()
@no_auth()
@click.pass_context
def status(ctx):
    """
    Check database schema status
    
    Compare current database models with the actual database schema
    to check for synchronization issues with tables, columns, indexes, etc.
    """
    
    click.echo("🔍 Database Schema Status")
    click.echo("=" * 50)
    
    # Display current database connection
    display_detailed_connection_info()
    
    try:
        from sqlalchemy import create_engine, MetaData, inspect
        from database import Base
        from config import get_database_url
        
        # Get database connection
        connection_string = get_database_url()
        engine = create_engine(connection_string)
        inspector = inspect(engine)
        
        # Get expected tables from models
        expected_tables = set(Base.metadata.tables.keys())
        
        # Get actual tables from database
        actual_tables = set(inspector.get_table_names())
        
        click.echo("📋 Table Status:")
        click.echo(f"  Expected Tables:     {len(expected_tables)}")
        click.echo(f"  Actual Tables:       {len(actual_tables)}")
        
        # Check for missing tables
        missing_tables = expected_tables - actual_tables
        extra_tables = actual_tables - expected_tables
        
        if missing_tables:
            click.echo(f"  ❌ Missing Tables:   {len(missing_tables)}")
            for table in sorted(missing_tables):
                click.echo(f"    • {table}")
        else:
            click.echo("  ✅ All expected tables exist")
        
        if extra_tables:
            click.echo(f"  ⚠️  Extra Tables:     {len(extra_tables)}")
            for table in sorted(extra_tables):
                click.echo(f"    • {table}")
        
        # Check each table's structure
        click.echo(f"\n🔍 Table Structure Analysis:")
        
        for table_name in sorted(expected_tables):
            if table_name not in actual_tables:
                click.echo(f"  ❌ {table_name}: Table missing")
                continue
            
            click.echo(f"  📋 {table_name}:")
            
            # Get expected columns from model
            expected_table = Base.metadata.tables[table_name]
            expected_columns = {col.name: col for col in expected_table.columns}
            
            # Get actual columns from database
            actual_columns = {col['name']: col for col in inspector.get_columns(table_name)}
            
            # Check columns
            missing_columns = set(expected_columns.keys()) - set(actual_columns.keys())
            extra_columns = set(actual_columns.keys()) - set(expected_columns.keys())
            
            if missing_columns:
                click.echo(f"    ❌ Missing columns: {', '.join(sorted(missing_columns))}")
            if extra_columns:
                click.echo(f"    ⚠️  Extra columns: {', '.join(sorted(extra_columns))}")
            if not missing_columns and not extra_columns:
                click.echo(f"    ✅ Columns: {len(expected_columns)} columns match")
            
            # Check primary keys
            expected_pk = [col.name for col in expected_table.primary_key.columns]
            actual_pk = inspector.get_pk_constraint(table_name)['constrained_columns']
            
            if expected_pk != actual_pk:
                click.echo(f"    ❌ Primary key mismatch:")
                click.echo(f"      Expected: {expected_pk}")
                click.echo(f"      Actual:   {actual_pk}")
            else:
                click.echo(f"    ✅ Primary key: {actual_pk}")
            
            # Check indexes
            expected_indexes = {idx.name: idx for idx in expected_table.indexes}
            actual_indexes = {idx['name']: idx for idx in inspector.get_indexes(table_name)}
            
            missing_indexes = set(expected_indexes.keys()) - set(actual_indexes.keys())
            extra_indexes = set(actual_indexes.keys()) - set(expected_indexes.keys())
            
            if missing_indexes:
                click.echo(f"    ❌ Missing indexes: {', '.join(sorted(filter(None, missing_indexes)))}")
            if extra_indexes:
                click.echo(f"    ⚠️  Extra indexes: {', '.join(sorted(filter(None, extra_indexes)))}")
            if not missing_indexes and not extra_indexes:
                click.echo(f"    ✅ Indexes: {len(expected_indexes)} indexes match")
        
        # Overall status
        total_issues = len(missing_tables) + len(extra_tables)
        for table_name in expected_tables:
            if table_name in actual_tables:
                expected_table = Base.metadata.tables[table_name]
                expected_columns = set(expected_table.columns.keys())
                actual_columns = set(col['name'] for col in inspector.get_columns(table_name))
                total_issues += len(expected_columns - actual_columns) + len(actual_columns - expected_columns)
        
        click.echo(f"\n📊 Summary:")
        if total_issues == 0:
            click.echo("  ✅ Database schema is in sync with models")
        else:
            click.echo(f"  ❌ Found {total_issues} schema issues")
            click.echo("  💡 Consider running 'python api_main.py --init-db' to sync schema")
        
        return 0 if total_issues == 0 else 1
        
    except Exception as e:
        click.echo(f"❌ Error checking database status: {e}", err=True)
        return 1


@db.command()
@no_auth()
@click.option('--apply', is_flag=True, help='Apply schema changes (two-phase: tables bulk, columns interactive)')
@click.option('--interactive', is_flag=True, help='Step-by-step manual confirmation mode (only works with --apply)')
@click.option('--strict', is_flag=True, help='Use strict comparison (reports all differences including minor variations)')
@click.pass_context
def sync(ctx, apply, interactive, strict):
    """
    Synchronize database schema using SQLAlchemy ORM
    
    Analyze database tables, columns, and schema structure.
    Shows what schema changes would be applied and optionally applies them using ORM methods.
    
    APPLY MODES:
    • --apply: Two-phase sync - Phase 1: create_all() for tables, Phase 2: interactive for columns
    • --apply --interactive: Manual step-by-step confirmation for each change (tables + columns)
    
    The default --apply mode uses a two-phase approach for safety:
    1. Tables are created automatically using create_all() for speed
    2. Column additions are handled interactively for safety and review
    
    By default, only significant differences are reported. Use --strict to see all differences
    including minor MySQL/SQLAlchemy variations (TINYINT vs BOOLEAN, datetime.utcnow vs CURRENT_TIMESTAMP).
    
    Interactive mode gives granular control, standard apply mode balances speed and safety.
    """
    
    if apply:
        if interactive:
            click.echo("🔄 Database Schema Synchronization (INTERACTIVE MODE)")
            click.echo("=" * 50)
            click.echo("💡 Interactive mode: Manual step-by-step confirmation for each change")
        else:
            click.echo("🔄 Database Schema Synchronization (BULK APPLY MODE)")
            click.echo("=" * 50)
            click.echo("💡 Bulk mode: Using create_all() for fast automatic synchronization")
    else:
        click.echo("🔄 Database Schema Synchronization (DRY RUN)")
        click.echo("=" * 50)
        click.echo("💡 This is a dry run. Use --apply to actually apply schema changes.")
        if interactive:
            click.echo("⚠️  Interactive mode only works with --apply flag")
            click.echo("💡 Interactive mode provides step-by-step confirmation when applying changes")
            click.echo("💡 Use: python cli.py system db sync --apply --interactive")
        click.echo()
    
    if strict:
        click.echo("🔍 Strict comparison mode enabled - showing all differences including minor variations")
    else:
        click.echo("🔍 Standard comparison mode - filtering out common MySQL/SQLAlchemy variations")
        click.echo("    Use --strict to see all differences including minor type/default variations")
    click.echo()

    display_detailed_connection_info()
    
    try:
        from utils.database.schema_checker import analyze_database_schema
        from sqlalchemy import create_engine, MetaData, inspect, text
        from database import Base
        
        # Import database package which automatically imports all models
        import database  # This imports all models via __init__.py
        
        # Use centralized schema analysis
        schema_result = analyze_database_schema(strict=strict)
        
        if not schema_result.success:
            click.echo(f"❌ Error analyzing schema: {schema_result.error_message}", err=True)
            return 1
        
        missing_tables = schema_result.missing_tables
        extra_tables = schema_result.extra_tables
        column_changes = schema_result.column_changes
        

        
        # Show dependency ordering info if tables were reordered
        if missing_tables:
            click.echo(f"📋 Table creation order optimized for foreign key dependencies:")
            for i, table_name in enumerate(missing_tables, 1):
                click.echo(f"  {i}. {table_name}")
            click.echo()
        
        # Get database engine for SQL generation and execution
        connection_string = get_database_url()
        engine = create_engine(connection_string)
        expected_metadata = Base.metadata
        
        # Generate SQL commands
        sql_commands = []
        
        # Create missing tables
        for table_name in missing_tables:
            table = expected_metadata.tables[table_name]
            # Generate CREATE TABLE SQL
            create_table_sql = f"CREATE TABLE {table_name} ("
            columns = []
            for column in table.columns:
                col_def = f"{column.name} {column.type}"
                if not column.nullable:
                    col_def += " NOT NULL"
                if column.primary_key:
                    col_def += " PRIMARY KEY"
                    # Only add AUTOINCREMENT for INTEGER primary keys that have it
                    if hasattr(column, 'autoincrement') and column.autoincrement and str(column.type).startswith('INTEGER'):
                        col_def += " AUTOINCREMENT"
                columns.append(col_def)
            create_table_sql += ", ".join(columns) + ");"
            
            sql_commands.append({
                'type': 'create_table',
                'table': table_name,
                'sql': create_table_sql
            })
        
        # Add missing columns (only add_column type can be safely automated)
        for change in column_changes:
            if change['type'] == 'add_column':
                sql = f"ALTER TABLE {change['table']} ADD COLUMN {change['column']} {change['definition']};"
                sql_commands.append({
                    'type': 'add_column',
                    'table': change['table'],
                    'column': change['column'],
                    'sql': sql
                })
        
        # Note: modify_column and extra_column changes require manual intervention
        # These are complex operations that may require:
        # - ALTER COLUMN statements (not supported in SQLite)
        # - Table recreation with data migration
        # - DROP COLUMN statements (potentially destructive)
        
        # Display analysis results
        expected_tables = list(expected_metadata.tables.keys())
        actual_table_count = len(expected_tables) - len(missing_tables) + len(extra_tables)
        click.echo(f"📊 Schema Analysis:")
        click.echo(f"Expected Tables:     {len(expected_tables)}")
        click.echo(f"Actual Tables:       {actual_table_count}")
        click.echo(f"Missing Tables:      {len(missing_tables)}")
        click.echo(f"Extra Tables:        {len(extra_tables)}")
        click.echo(f"Column Changes:      {len(column_changes)}")
        click.echo()
        
        # Show missing tables
        if missing_tables:
            click.echo("📋 Missing Tables:")
            for table in missing_tables:
                click.echo(f"  ❌ {table}")
            click.echo()
        
        # Show extra tables
        if extra_tables:
            click.echo("📋 Extra Tables (not in models):")
            for table in extra_tables:
                click.echo(f"  ⚠️  {table}")
            click.echo()
        
        # Show column changes
        if column_changes:
            click.echo("📋 Column Changes:")
            add_count = len([c for c in column_changes if c['type'] == 'add_column'])
            modify_count = len([c for c in column_changes if c['type'] == 'modify_column'])
            extra_count = len([c for c in column_changes if c['type'] == 'extra_column'])
            
            if add_count > 0:
                click.echo(f"  ➕ Missing Columns ({add_count}):")
                click.echo(f"      💡 These can be safely added with --apply")
                for change in column_changes:
                    if change['type'] == 'add_column':
                        click.echo(f"    • {change['table']}.{change['column']} ({change['definition']})")
            
            if modify_count > 0:
                # Filter out safe defaults in non-strict mode
                significant_changes = []
                safe_default_changes_display = []
                for change in column_changes:
                    if change['type'] == 'modify_column':
                        # Check if this is a safe default (Python-side default that SQLAlchemy handles)
                        is_safe = (
                            'Default (actual: None, expected:' in change['definition'] and 
                            (
                                'ScalarElementColumnDefault' in change['definition'] or
                                'ColumnElementColumnDefault' in change['definition'] or
                                'datetime.utcnow' in change['definition'] or
                                'current_timestamp' in change['definition']
                            )
                        )
                        # Check if PostgreSQL sequence default on id column
                        is_pg_sequence = (
                            'Default (actual: nextval(' in change['definition'] and 
                            'expected: None)' in change['definition'] and
                            change['column'] == 'id'
                        )
                        
                        if is_safe or is_pg_sequence:
                            safe_default_changes_display.append(change)
                        else:
                            significant_changes.append(change)
                
                if strict:
                    # Show all changes in strict mode
                    click.echo(f"  🔄 Column Differences ({modify_count}):")
                    click.echo(f"      💡 Strict mode: showing ALL differences including safe defaults")
                    for change in column_changes:
                        if change['type'] == 'modify_column':
                            click.echo(f"    • {change['table']}.{change['column']}: {change['definition']}")
                else:
                    # Only show significant changes in non-strict mode
                    if significant_changes:
                        click.echo(f"  🔄 Significant Column Differences ({len(significant_changes)}):")
                        click.echo(f"      ⚠️  These require attention:")
                        for change in significant_changes:
                            click.echo(f"    • {change['table']}.{change['column']}: {change['definition']}")
                    
                    if safe_default_changes_display:
                        click.echo(f"  ✅ Safe Default Differences ({len(safe_default_changes_display)}) - hidden in standard mode")
                        click.echo(f"      💡 Use --strict to see all {len(safe_default_changes_display)} safe default differences")
            
            if extra_count > 0:
                click.echo(f"  ⚠️  Extra Columns in DB ({extra_count}):")
                for change in column_changes:
                    if change['type'] == 'extra_column':
                        click.echo(f"    • {change['table']}.{change['column']} ({change['definition']})")
                click.echo(f"       💡 These columns exist in database but not in models")
            
            click.echo()
        
        # Show SQL commands
        if sql_commands:
            click.echo("🔧 Raw SQL Commands that would be executed:")
            click.echo("=" * 50)
            for i, cmd in enumerate(sql_commands, 1):
                click.echo(f"{i:2d}. {cmd['sql']}")
            click.echo()
        
        if apply:
            # Two-phase approach: 1) create_all for tables, 2) interactive for columns
            click.echo("🔄 Applying schema changes in two phases...")
            click.echo("💡 Phase 1: Creating missing tables with create_all()")
            click.echo("💡 Phase 2: Adding missing columns interactively (if any)")
            click.echo()
            
            try:
                # Phase 1: Use create_all() to create missing tables
                if missing_tables:
                    click.echo(f"📋 Phase 1: Creating {len(missing_tables)} missing tables...")
                    expected_metadata.create_all(engine, checkfirst=True)
                    click.echo("✅ Phase 1 completed: All missing tables created")
                else:
                    click.echo("✅ Phase 1 completed: No missing tables to create")
                
                # Phase 2: Handle column additions and safe default value additions
                add_column_changes = [c for c in column_changes if c['type'] == 'add_column']
                safe_default_changes = []
                
                # Identify nullable changes (always include - these are structural)
                nullable_changes = []
                for change in column_changes:
                    if change['type'] == 'modify_column' and 'Nullable (actual:' in change['definition']:
                        nullable_changes.append(change)
                
                # Only identify safe default value additions when --strict is present
                if strict:
                    # Identify safe default value additions from modify_column changes
                    for change in column_changes:
                        if change['type'] == 'modify_column' and 'Default (actual: None, expected:' in change['definition']:
                            # This is a default value addition - check if it's safe to auto-apply
                            # Any Python-side default (ScalarElementColumnDefault, ColumnElementColumnDefault) is safe
                            if (
                                'ScalarElementColumnDefault' in change['definition'] or
                                'ColumnElementColumnDefault' in change['definition'] or
                                'datetime.utcnow' in change['definition'] or
                                'current_timestamp' in change['definition']
                            ):
                                safe_default_changes.append(change)
                
                total_column_changes = len(add_column_changes) + len(safe_default_changes) + len(nullable_changes)
                
                if total_column_changes > 0:
                    click.echo(f"\n📋 Phase 2: Processing {total_column_changes} column changes interactively...")
                    if add_column_changes:
                        click.echo(f"  ➕ {len(add_column_changes)} missing columns to add")
                    if nullable_changes:
                        click.echo(f"  🔒 {len(nullable_changes)} nullable constraint changes")
                    if safe_default_changes:
                        click.echo(f"  🔧 {len(safe_default_changes)} safe default values to add (--strict mode)")
                    click.echo("💡 Each change requires confirmation for safety")
                    click.echo("💡 Options: [y]es, [n]o, [a]bort all, [s]kip remaining")
                    click.echo()
                    
                    applied_changes = 0
                    failed_changes = 0
                    skipped_changes = 0
                    
                    # Combine all changes for processing
                    all_column_changes = []
                    
                    # Add missing columns
                    for change in add_column_changes:
                        all_column_changes.append({
                            'type': 'add_column',
                            'change': change,
                            'description': f"Add missing column '{change['column']}' to table '{change['table']}'"
                        })
                    
                    # Add nullable constraint changes (these are structural and important)
                    for change in nullable_changes:
                        # Parse the nullable change to determine direction
                        if 'actual: True, expected: False' in change['definition']:
                            all_column_changes.append({
                                'type': 'set_not_null',
                                'change': change,
                                'description': f"Set column '{change['column']}' in table '{change['table']}' to NOT NULL"
                            })
                        elif 'actual: False, expected: True' in change['definition']:
                            all_column_changes.append({
                                'type': 'drop_not_null',
                                'change': change,
                                'description': f"Allow NULL in column '{change['column']}' in table '{change['table']}'"
                            })
                    
                    # Add safe default value changes
                    for change in safe_default_changes:
                        all_column_changes.append({
                            'type': 'add_default',
                            'change': change,
                            'description': f"Add default value to column '{change['column']}' in table '{change['table']}'"
                        })
                    
                    for i, item in enumerate(all_column_changes, 1):
                        change = item['change']
                        table_name = change['table']
                        column_name = change['column']
                        
                        click.echo(f"\n{i:2d}. {item['description']}")
                        click.echo(f"    Table: {table_name}")
                        click.echo(f"    Column: {column_name}")
                        
                        if item['type'] == 'add_column':
                            # Handle missing column addition
                            expected_table = expected_metadata.tables[table_name]
                            expected_column = expected_table.columns[column_name]
                            
                            click.echo(f"    Type: {change['definition']}")
                            
                            # Build and show the SQL that will be executed
                            column_def = str(expected_column.type)
                            if not expected_column.nullable:
                                column_def += " NOT NULL"
                            
                            # Handle default values for display
                            if hasattr(expected_column, 'default') and expected_column.default is not None:
                                default_str = str(expected_column.default)
                                if 'datetime.utcnow' in default_str:
                                    column_def += " DEFAULT CURRENT_TIMESTAMP"
                                elif hasattr(expected_column.default, 'arg'):
                                    default_value = expected_column.default.arg
                                    if isinstance(default_value, str):
                                        column_def += f" DEFAULT '{default_value}'"
                                    else:
                                        column_def += f" DEFAULT {default_value}"
                                elif not hasattr(expected_column.default, '__call__'):
                                    if isinstance(expected_column.default, str):
                                        column_def += f" DEFAULT '{expected_column.default}'"
                                    else:
                                        column_def += f" DEFAULT {expected_column.default}"
                            
                            sql_command = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def};"
                            click.echo(f"    SQL: {sql_command}")
                            
                        elif item['type'] == 'add_default':
                            # Handle default value addition
                            click.echo(f"    Change: {change['definition']}")
                            
                            expected_table = expected_metadata.tables[table_name]
                            expected_column = expected_table.columns[column_name]
                            
                            # Build the MODIFY COLUMN statement for default value - for display only
                            column_type = str(expected_column.type)
                            nullable_clause = "" if expected_column.nullable else " NOT NULL"
                            
                            if 'datetime.utcnow' in str(expected_column.default):
                                # Function default (like datetime.utcnow) - check this first!
                                default_clause = " DEFAULT CURRENT_TIMESTAMP"
                            elif hasattr(expected_column.default, 'arg'):
                                # Scalar default value
                                default_val = expected_column.default.arg
                                if isinstance(default_val, str):
                                    default_clause = f" DEFAULT '{default_val}'"
                                else:
                                    default_clause = f" DEFAULT {default_val}"
                            elif not callable(expected_column.default):
                                # Direct value
                                if isinstance(expected_column.default, str):
                                    default_clause = f" DEFAULT '{expected_column.default}'"
                                else:
                                    default_clause = f" DEFAULT {expected_column.default}"
                            else:
                                default_clause = " DEFAULT NULL"  # Fallback for other callable objects
                            
                            sql_command = f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} {column_type}{nullable_clause}{default_clause};"
                            click.echo(f"    SQL: {sql_command}")
                        
                        elif item['type'] == 'set_not_null':
                            # Handle setting NOT NULL constraint
                            click.echo(f"    Change: {change['definition']}")
                            click.echo(f"    ⚠️  Warning: This will fail if NULL values exist in the column!")
                            sql_command = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL;"
                            click.echo(f"    SQL: {sql_command}")
                        
                        elif item['type'] == 'drop_not_null':
                            # Handle dropping NOT NULL constraint
                            click.echo(f"    Change: {change['definition']}")
                            sql_command = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP NOT NULL;"
                            click.echo(f"    SQL: {sql_command}")
                        
                        # Get user choice
                        choice = click.prompt(
                            "    Apply this change?",
                            type=click.Choice(['y', 'n', 'a', 's'], case_sensitive=False),
                            default='y',
                            show_choices=True
                        )
                        
                        if choice.lower() == 'a':
                            click.echo("    ⏹️  Aborting all remaining changes...")
                            skipped_changes += len(all_column_changes) - i + 1
                            break
                        elif choice.lower() == 's':
                            click.echo("    ⏭️  Skipping remaining changes...")
                            skipped_changes += len(all_column_changes) - i + 1
                            break
                        elif choice.lower() == 'y':
                            # Apply the change
                            try:
                                from sqlalchemy import text
                                
                                if item['type'] == 'add_column':
                                    # Add missing column
                                    expected_table = expected_metadata.tables[table_name]
                                    expected_column = expected_table.columns[column_name]
                                    
                                    # Generate DDL from the ORM column definition
                                    column_sql = str(expected_column.type)
                                    
                                    # Fix PostgreSQL compatibility - convert DATETIME to TIMESTAMP
                                    if 'postgresql' in connection_string.lower() and column_sql == 'DATETIME':
                                        column_sql = 'TIMESTAMP'
                                    
                                    # Add NOT NULL constraint if needed
                                    if not expected_column.nullable:
                                        column_sql += " NOT NULL"
                                    
                                    # Add default value if present
                                    if expected_column.default is not None:
                                        if hasattr(expected_column.default, 'arg'):
                                            # Scalar default value
                                            default_val = expected_column.default.arg
                                            if isinstance(default_val, str):
                                                column_sql += f" DEFAULT '{default_val}'"
                                            else:
                                                column_sql += f" DEFAULT {default_val}"
                                        elif 'datetime.utcnow' in str(expected_column.default):
                                            # Function default (like datetime.utcnow)
                                            column_sql += " DEFAULT CURRENT_TIMESTAMP"
                                        elif not callable(expected_column.default):
                                            # Direct value
                                            if isinstance(expected_column.default, str):
                                                column_sql += f" DEFAULT '{expected_column.default}'"
                                            else:
                                                column_sql += f" DEFAULT {expected_column.default}"
                                    
                                    # Execute using text() for better compatibility
                                    sql_statement = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
                                    
                                    with engine.begin() as conn:
                                        conn.execute(text(sql_statement))
                                    
                                    click.echo(f"    ✅ Added column '{column_name}' to table '{table_name}'")
                                    applied_changes += 1
                                    
                                elif item['type'] == 'add_default':
                                    # Add default value to existing column
                                    expected_table = expected_metadata.tables[table_name]
                                    expected_column = expected_table.columns[column_name]
                                    
                                    # Build the MODIFY COLUMN statement for default value
                                    column_type = str(expected_column.type)
                                    
                                    # Fix PostgreSQL compatibility - convert DATETIME to TIMESTAMP
                                    if 'postgresql' in connection_string.lower() and column_type == 'DATETIME':
                                        column_type = 'TIMESTAMP'
                                    
                                    nullable_clause = "" if expected_column.nullable else " NOT NULL"
                                    
                                    if 'datetime.utcnow' in str(expected_column.default):
                                        # Function default (like datetime.utcnow) - check this first!
                                        default_clause = " DEFAULT CURRENT_TIMESTAMP"
                                    elif hasattr(expected_column.default, 'arg'):
                                        # Scalar default value
                                        default_val = expected_column.default.arg
                                        if isinstance(default_val, str):
                                            default_clause = f" DEFAULT '{default_val}'"
                                        else:
                                            default_clause = f" DEFAULT {default_val}"
                                    elif not callable(expected_column.default):
                                        # Direct value
                                        if isinstance(expected_column.default, str):
                                            default_clause = f" DEFAULT '{expected_column.default}'"
                                        else:
                                            default_clause = f" DEFAULT {expected_column.default}"
                                    else:
                                        default_clause = " DEFAULT NULL"  # Fallback for other callable objects
                                    
                                    # Execute MODIFY COLUMN to add default
                                    sql_statement = f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} {column_type}{nullable_clause}{default_clause}"
                                    
                                    with engine.begin() as conn:
                                        conn.execute(text(sql_statement))
                                    
                                    click.echo(f"    ✅ Added default value to column '{column_name}' in table '{table_name}'")
                                    applied_changes += 1
                                
                                elif item['type'] == 'set_not_null':
                                    # Set NOT NULL constraint
                                    # First check for existing NULL values
                                    check_sql = f"SELECT COUNT(*) FROM {table_name} WHERE {column_name} IS NULL"
                                    with engine.connect() as conn:
                                        result = conn.execute(text(check_sql))
                                        null_count = result.scalar()
                                    
                                    if null_count > 0:
                                        click.echo(f"    ⚠️  Found {null_count} rows with NULL values!")
                                        fix_choice = click.prompt(
                                            f"    Delete these rows before setting NOT NULL?",
                                            type=click.Choice(['y', 'n'], case_sensitive=False),
                                            default='n'
                                        )
                                        if fix_choice.lower() == 'y':
                                            delete_sql = f"DELETE FROM {table_name} WHERE {column_name} IS NULL"
                                            with engine.begin() as conn:
                                                conn.execute(text(delete_sql))
                                            click.echo(f"    🗑️  Deleted {null_count} rows with NULL values")
                                        else:
                                            click.echo(f"    ⏭️  Skipping NOT NULL change (NULLs exist)")
                                            skipped_changes += 1
                                            continue
                                    
                                    # Apply the NOT NULL constraint
                                    sql_statement = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL"
                                    with engine.begin() as conn:
                                        conn.execute(text(sql_statement))
                                    
                                    click.echo(f"    ✅ Set NOT NULL on column '{column_name}' in table '{table_name}'")
                                    applied_changes += 1
                                
                                elif item['type'] == 'drop_not_null':
                                    # Drop NOT NULL constraint
                                    sql_statement = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP NOT NULL"
                                    with engine.begin() as conn:
                                        conn.execute(text(sql_statement))
                                    
                                    click.echo(f"    ✅ Dropped NOT NULL on column '{column_name}' in table '{table_name}'")
                                    applied_changes += 1
                                
                            except Exception as e:
                                click.echo(f"    ❌ Failed to apply change: {e}")
                                failed_changes += 1
                        else:  # choice.lower() == 'n'
                            click.echo(f"    ⏭️  Skipped change")
                            skipped_changes += 1
                    
                    # Show column summary
                    click.echo(f"\n📊 Phase 2 Summary:")
                    click.echo(f"  ✅ Applied: {applied_changes} changes")
                    click.echo(f"  ❌ Failed: {failed_changes} changes")
                    click.echo(f"  ⏭️  Skipped: {skipped_changes} changes")
                    
                    if failed_changes == 0:
                        click.echo("✅ Phase 2 completed successfully!")
                    else:
                        click.echo("⚠️  Phase 2 completed with some failures")
                else:
                    click.echo("✅ Phase 2 completed: No column changes to apply")
                
                # Show note about other column changes that require manual intervention
                # Exclude changes that were already processed (safe defaults and nullable changes)
                processed_changes = set(id(c) for c in safe_default_changes + nullable_changes)
                other_changes = [c for c in column_changes if c['type'] in ['modify_column', 'extra_column'] and id(c) not in processed_changes]
                if other_changes:
                    click.echo(f"\n⚠️  Note: {len(other_changes)} other column differences detected but not auto-applied:")
                    click.echo(f"    These require manual review and intervention:")
                    for change in other_changes[:5]:  # Show first 5 examples
                        if change['type'] == 'modify_column':
                            click.echo(f"    • {change['table']}.{change['column']}: {change['definition']}")
                        elif change['type'] == 'extra_column':
                            click.echo(f"    • {change['table']}.{change['column']}: Extra column in database")
                    if len(other_changes) > 5:
                        click.echo(f"    ... and {len(other_changes) - 5} more")
                    click.echo("    💡 Use --interactive mode for manual control over these changes")
                
                # Show note about safe default changes that require strict mode
                if not strict:
                    safe_default_count = 0
                    for change in column_changes:
                        if change['type'] == 'modify_column' and 'Default (actual: None, expected:' in change['definition']:
                            # Any Python-side default is safe
                            if (
                                'ScalarElementColumnDefault' in change['definition'] or
                                'ColumnElementColumnDefault' in change['definition'] or
                                'datetime.utcnow' in change['definition'] or
                                'current_timestamp' in change['definition']
                            ):
                                safe_default_count += 1
                    
                    if safe_default_count > 0:
                        click.echo(f"\n💡 Note: {safe_default_count} safe default value additions were detected")
                        click.echo("    Add --strict flag to include these in the interactive process:")
                        click.echo("    python cli.py system db sync --apply --strict")
                
                click.echo("\n🎉 Schema synchronization completed!")
                return 0
                
            except Exception as e:
                click.echo(f"❌ Error during schema synchronization: {e}")
                return 1
        else:
            # Dry run mode - show what would be applied
            auto_changes = len([c for c in column_changes if c['type'] == 'add_column']) + len(missing_tables)
            
            # Count manual changes, excluding safe default additions unless in strict mode
            manual_changes = 0
            for change in column_changes:
                if change['type'] == 'extra_column':
                    # Extra columns don't prevent sync in standard mode - they exist in DB but not in models
                    if strict:
                        manual_changes += 1
                elif change['type'] == 'modify_column':
                    # Check if this is a safe default addition (Python-side defaults that SQLAlchemy handles)
                    is_safe_default = (
                        'Default (actual: None, expected:' in change['definition'] and 
                        (
                            'ScalarElementColumnDefault' in change['definition'] or  # Any scalar default (True, False, 0, enums, etc.)
                            'ColumnElementColumnDefault' in change['definition'] or  # SQL functions like func.current_timestamp()
                            'datetime.utcnow' in change['definition'] or
                            'current_timestamp' in change['definition']
                        )
                    )
                    
                    # Check if this is a PostgreSQL sequence default (normal for auto-increment PKs)
                    is_postgresql_sequence = (
                        'Default (actual: nextval(' in change['definition'] and 
                        'expected: None)' in change['definition'] and
                        change['column'] == 'id'
                    )
                    
                    # Check if this is a common MySQL type variation
                    is_common_type_variation = (
                        'Type (actual: DECIMAL(' in change['definition'] and 'expected: NUMERIC(' in change['definition']
                    )
                    
                    # Only count as manual if it's not a safe pattern (unless strict)
                    if strict:
                        manual_changes += 1
                    elif not is_safe_default and not is_postgresql_sequence and not is_common_type_variation:
                        manual_changes += 1
            
            if auto_changes > 0:
                click.echo(f"💡 Run 'python cli.py system db sync --apply' to apply {auto_changes} changes using create_all() (fast)")
                click.echo(f"💡 Use 'python cli.py system db sync --apply --interactive' for step-by-step confirmation")
            
            if manual_changes > 0:
                if strict:
                    click.echo(f"⚠️  {manual_changes} column differences require manual intervention")
                    click.echo(f"💡 Use 'python cli.py system db sync --apply --interactive' for step-by-step review")
                else:
                    click.echo(f"⚠️  {manual_changes} column differences require manual intervention")
                    click.echo(f"💡 These are complex changes (type changes, extra columns) that need careful review")
                    click.echo(f"💡 Use 'python cli.py system db sync --apply --interactive' for step-by-step control")
            
            # Show note about safe default changes in non-strict mode
            safe_default_count = 0
            if not strict:
                for change in column_changes:
                    if change['type'] == 'modify_column' and 'Default (actual: None, expected:' in change['definition']:
                        # Any Python-side default is safe
                        if (
                            'ScalarElementColumnDefault' in change['definition'] or
                            'ColumnElementColumnDefault' in change['definition'] or
                            'datetime.utcnow' in change['definition'] or
                            'current_timestamp' in change['definition']
                        ):
                            safe_default_count += 1
                
                if safe_default_count > 0:
                    click.echo(f"📋 Additionally: {safe_default_count} safe default value improvements available")
                    click.echo(f"💡 These are optional and safe to apply automatically")
                    click.echo(f"💡 Add --strict to include them: python cli.py system db sync --apply --strict")
            
            # Determine sync status
            if auto_changes == 0 and manual_changes == 0:
                if safe_default_count == 0:
                    click.echo("\n" + "=" * 60)
                    click.echo(click.style("🎉 DATABASE SCHEMA IS IN SYNC!", fg='green', bold=True))
                    click.echo(click.style("✅ All tables and columns are properly synchronized", fg='green'))
                    click.echo("=" * 60)
                else:
                    click.echo("\n" + "=" * 60)
                    click.echo(click.style("🎉 DATABASE SCHEMA IS IN SYNC (CORE STRUCTURE)!", fg='green', bold=True))
                    click.echo(click.style("✅ All required tables and columns are properly synchronized", fg='green'))
                    click.echo(click.style(f"💡 {safe_default_count} optional default value improvements available with --strict", fg='yellow'))
                    click.echo("=" * 60)
            
            return 0
            
    except Exception as e:
        click.echo(f"❌ Error synchronizing schema: {e}", err=True)
        return 1


@db.command()
@no_auth()
@click.option('--apply', is_flag=True, help='Actually apply the optimizations (default is dry-run)')
@click.option('--interactive', is_flag=True, help='Ask for confirmation for each index (only works with --apply)')
@click.pass_context
def optimize(ctx, apply, interactive):
    """
    Optimize database indexes
    
    Analyze and optimize database indexes for better performance.
    By default, this runs in dry-run mode to show what would be done.
    Use --apply to actually create the missing indexes.
    Use --interactive with --apply to confirm each index individually.
    """
    
    if apply:
        click.echo("🔧 Database Index Optimization (APPLY MODE)")
        click.echo("=" * 50)
        if interactive:
            click.echo("💡 Interactive mode enabled - you will be asked to confirm each index")
    else:
        click.echo("🔧 Database Index Optimization (DRY RUN)")
        click.echo("=" * 50)
        click.echo("💡 This is a dry run. Use --apply to actually create indexes.")
        click.echo()
    
    # Display current database connection
    display_detailed_connection_info()
    
    try:
        # Use read-only mode for dry run, full mode for apply
        optimizer = IndexOptimizer(read_only=not apply)
        
        if apply:
            # Actually apply the optimizations
            if interactive:
                # Interactive mode - ask for each index
                success, failed_indexes = optimizer.optimize_all_indexes_interactive()
            else:
                # Non-interactive mode - apply all at once
                success, failed_indexes = optimizer.optimize_all_indexes()
            
            # Get final analysis to show what was actually done
            final_analysis = optimizer.analyze_query_performance()
            
            click.echo("\n📊 Optimization Results:")
            click.echo("=" * 30)
            
            # Count what was actually created vs what was skipped
            total_recommended = 0
            total_existing = 0
            total_missing = 0
            
            for table, indexes in final_analysis['recommended_indexes'].items():
                for index in indexes:
                    total_recommended += 1
                    if index in final_analysis['existing_indexes']:
                        total_existing += 1
                    else:
                        total_missing += 1
            
            click.echo(f"Total Recommended Indexes: {total_recommended}")
            click.echo(f"Existing Indexes: {total_existing}")
            click.echo(f"Missing Indexes: {total_missing}")
            
            # Show recommended indexes with status
            click.echo(f"\n📋 Index Status:")
            for table, indexes in final_analysis['recommended_indexes'].items():
                if indexes:
                    click.echo(f"  📋 {table}:")
                    for index in indexes:
                        status = "✅" if index in final_analysis['existing_indexes'] else "❌"
                        click.echo(f"    {status} {index}")
            
            # Show failed indexes with solutions
            if failed_indexes:
                click.echo(f"\n❌ Failed Indexes ({len(failed_indexes)}):")
                click.echo("=" * 30)
                
                for failed in failed_indexes:
                    click.echo(f"\n🔴 {failed['name']} on {failed['table']}")
                    click.echo(f"   Columns: {failed['columns']}")
                    click.echo(f"   Error: {failed['error']}")
                    
                    # Provide manual solution
                    if "mysql" in optimizer.engine_type.lower():
                        sql_command = f"CREATE INDEX {failed['name']} ON {failed['table']} ({failed['columns']}) USING BTREE;"
                    elif "postgres" in optimizer.engine_type.lower():
                        sql_command = f"CREATE INDEX CONCURRENTLY {failed['name']} ON {failed['table']} USING BTREE ({failed['columns']});"
                    else:
                        sql_command = f"CREATE INDEX {failed['name']} ON {failed['table']} ({failed['columns']});"
                    
                    click.echo(f"   💡 Manual fix: {sql_command}")
                    
                    # Common solutions based on error type
                    if "duplicate" in failed['error'].lower():
                        click.echo("   💡 Solution: Index already exists, no action needed")
                    elif "syntax" in failed['error'].lower():
                        click.echo("   💡 Solution: Check column names and syntax")
                    elif "permission" in failed['error'].lower():
                        click.echo("   💡 Solution: Run with database admin privileges")
                    elif "table" in failed['error'].lower() and "not exist" in failed['error'].lower():
                        click.echo("   💡 Solution: Ensure table exists and is accessible")
                    else:
                        click.echo("   💡 Solution: Check database logs for detailed error")
                
                click.echo(f"\n⚠️  Note: {len(failed_indexes)} indexes failed to create. See manual solutions above.")
            
            if success:
                click.echo("\n✅ Database indexes optimized successfully")
                return 0
            else:
                click.echo("\n❌ Failed to optimize database indexes")
                return 1
        else:
            # Dry run - just analyze and show what would be done
            analysis = optimizer.analyze_query_performance()
            
            click.echo(f"Database Type: {analysis['database_type']}")
            click.echo(f"Existing Indexes: {len(analysis['existing_indexes'])}")
            click.echo(f"Recommended Indexes: {sum(len(indexes) for indexes in analysis['recommended_indexes'].values())}")
            
            # Count missing indexes and collect details
            missing_count = 0
            missing_by_table = {}
            
            for table, indexes in analysis['recommended_indexes'].items():
                missing_in_table = []
                for index in indexes:
                    if index not in analysis['existing_indexes']:
                        missing_count += 1
                        missing_in_table.append(index)
                
                if missing_in_table:
                    missing_by_table[table] = missing_in_table
            
            click.echo(f"Missing Indexes: {missing_count}")
            
            if missing_count > 0:
                # Show what would be created
                if missing_by_table:
                    click.echo("📋 Indexes that would be created:")
                    for table_name, indexes in missing_by_table.items():
                        click.echo(f"  📋 {table_name}:")
                        for index in indexes:
                            click.echo(f"    • {index}")
                    click.echo()
                    
                    # Generate missing indexes list for SQL generation
                    missing_indexes = []
                    for table, indexes in analysis['recommended_indexes'].items():
                        for index in indexes:
                            if index not in analysis['existing_indexes']:
                                # Parse index name to get columns (fixed logic)
                                if index.startswith('idx_') or index.startswith('ix_'):
                                    # Extract column name from index name
                                    column = None
                                    
                                    # Handle idx_ prefix
                                    if index.startswith('idx_'):
                                        table_prefix = f"idx_{table}_"
                                        if index.startswith(table_prefix):
                                            column = index[len(table_prefix):]
                                    
                                    # Handle ix_ prefix  
                                    elif index.startswith('ix_'):
                                        table_prefix = f"ix_{table}_"
                                        if index.startswith(table_prefix):
                                            column = index[len(table_prefix):]
                                    
                                    # If we couldn't extract the column name with prefixes, try parsing
                                    if not column:
                                        parts = index.split('_')
                                        if len(parts) >= 3:
                                            # Remove prefix and table name, join the rest
                                            # Example: ix_users_last_login -> ['ix', 'users', 'last', 'login'] -> 'last_login'
                                            if parts[0] in ['idx', 'ix'] and parts[1] == table:
                                                column = '_'.join(parts[2:])  # Join remaining parts
                                            else:
                                                # Last resort: take everything after the last underscore
                                                column = parts[-1]
                                    
                                    if column:
                                        missing_indexes.append({
                                            'table': table,
                                            'name': index,
                                            'columns': [column]
                                        })
                    
                    # Generate and show raw SQL commands
                    sql_commands = optimizer.generate_sql_commands(missing_indexes)
                    click.echo("🔧 Raw SQL Commands that would be executed:")
                    click.echo("=" * 50)
                    for i, sql in enumerate(sql_commands, 1):
                        click.echo(f"{i:2d}. {sql}")
                    click.echo()
                    
                    click.echo("💡 Note: The --apply option will use SQLAlchemy ORM for safer index creation")
                    click.echo("💡 Use --interactive with --apply to confirm each index individually")
            else:
                click.echo(f"\n🎉 All recommended indexes are already in place!")
            
            return 0
            
    except Exception as e:
        click.echo(f"❌ Error analyzing indexes: {e}", err=True)
        return 1


@db.command()
@no_auth()
@click.pass_context
def analyze(ctx):
    """
    Analyze database index performance
    
    Analyze current database indexes and provide recommendations
    for performance optimization. This shows existing indexes,
    recommended indexes, and performance insights.
    """
    
    click.echo("📊 Database Index Analysis")
    click.echo("=" * 50)
    
    # Display current database connection
    display_detailed_connection_info()
    
    try:
        # Use read-only mode to avoid creating tables
        optimizer = IndexOptimizer(read_only=True)
        analysis = optimizer.analyze_query_performance()
        
        click.echo(f"Database Type: {analysis['database_type']}")
        click.echo(f"Existing Indexes: {len(analysis['existing_indexes'])}")
        click.echo(f"Recommended Indexes: {sum(len(indexes) for indexes in analysis['recommended_indexes'].values())}")
        
        # Count missing indexes
        missing_count = 0
        for table, indexes in analysis['recommended_indexes'].items():
            for index in indexes:
                if index not in analysis['existing_indexes']:
                    missing_count += 1
        
        click.echo(f"Missing Indexes: {missing_count}")
        
        # Show existing indexes
        if analysis['existing_indexes']:
            click.echo(f"\n📋 Existing Indexes:")
            for index in sorted(analysis['existing_indexes']):
                click.echo(f"  ✅ {index}")
        
        # Show recommended indexes by table with status
        if analysis['recommended_indexes']:
            click.echo(f"\n💡 Recommended Indexes by Table:")
            for table, indexes in analysis['recommended_indexes'].items():
                if indexes:
                    click.echo(f"  📋 {table}:")
                    missing_in_table = 0
                    for index in indexes:
                        status = "✅" if index in analysis['existing_indexes'] else "⏳"
                        click.echo(f"    {status} {index}")
                        if status == "⏳":
                            missing_in_table += 1
                    
                    if missing_in_table > 0:
                        click.echo(f"    📊 Missing: {missing_in_table}/{len(indexes)} indexes")
        
        # Show performance insights
        if 'performance_insights' in analysis:
            click.echo(f"\n🔍 Performance Insights:")
            for insight in analysis['performance_insights']:
                click.echo(f"  • {insight}")
        
        if missing_count > 0:
            click.echo(f"\n💡 Run 'python cli.py system db optimize' to create {missing_count} missing indexes")
        else:
            click.echo(f"\n🎉 All recommended indexes are already in place!")
        
        return 0
        
    except Exception as e:
        click.echo(f"❌ Error analyzing indexes: {e}", err=True)
        return 1 


@db.command('init')
@no_auth()
@click.pass_context
def init(ctx):
    """Initialize/reset the database with fresh tables and seed data
    
    ⚠️  WARNING: This is a DESTRUCTIVE operation that will:
    - Drop all existing tables and data
    - Recreate fresh schema
    - Add seed data (currencies, product states, countries)
    
    Use with extreme caution!
    
    The --database-url option can be provided at the top level:
    python cli.py --database-url <url> system db init
    """
    try:
        # Import here to avoid circular imports
        from utils.database import init_database
        
        # Database URL is already set at the top-level CLI if provided
        
        # Display connection info immediately when command is called
        display_detailed_connection_info()
        
        # Show red warning
        click.echo("")
        click.echo("=" * 60)
        click.echo(click.style("⚠️  DANGEROUS OPERATION - DATABASE INITIALIZATION", fg='red', bold=True))
        click.echo(click.style("   This will DESTROY ALL existing data and recreate the database!", fg='red'))
        click.echo("=" * 60)
        click.echo("")
        
        click.echo(click.style("📋 What will happen:", fg='yellow'))
        click.echo("   • Drop all existing tables and data")
        click.echo("   • Recreate fresh database schema")
        click.echo("   • Add seed data (currencies, product states, countries)")
        click.echo("   • Create all indexes and constraints")
        click.echo("")
        
        click.echo(click.style("💡 Note:", fg='cyan'))
        click.echo("   If you just want to add new tables/columns without destroying existing data,")
        click.echo(click.style("   use: python cli.py system db sync --apply", fg='cyan', bold=True))
        click.echo("   ↳ sync = Safe addition of missing schema (preserves existing data)")
        click.echo("   ↳ init = Complete reset (destroys everything)")
        click.echo("")
        
        # Interactive confirmation
        if not click.confirm(click.style("❓ Are you sure you want to INITIALIZE the database?", fg='red', bold=True)):
            click.echo(click.style("✅ Operation cancelled - database unchanged", fg='green'))
            return 0
        
        # Second confirmation for extra safety
        if not click.confirm(click.style("❓ Last chance - this will DESTROY ALL DATA. Continue?", fg='red', bold=True)):
            click.echo(click.style("✅ Operation cancelled - database unchanged", fg='green'))
            return 0
        
        # Execute the operation
        click.echo("")
        click.echo("🔧 Proceeding with database initialization...")
        
        success = init_database()
        
        if success:
            click.echo("")
            click.echo(click.style("✅ DATABASE INITIALIZATION COMPLETED", fg='green', bold=True))
            return 0
        else:
            click.echo("")
            click.echo(click.style("❌ DATABASE INITIALIZATION FAILED", fg='red', bold=True))
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error during database initialization: {e}", err=True)
        return 1


@db.command('clear')
@no_auth()
@click.option('--keep-currencies', is_flag=True, default=True, help='Keep currency seed data (default: True)')
@click.pass_context
def clear(ctx, keep_currencies):
    """Clear all data from database while keeping schema intact
    
    ⚠️  WARNING: This is a DESTRUCTIVE operation that will:
    - Delete all data from all tables
    - Preserve the database schema structure
    - Optionally keep currency seed data
    
    Use with extreme caution!
    """
    try:
        # Import here to avoid circular imports
        from utils.database import clear_database
        
        # Display connection info immediately when command is called
        display_detailed_connection_info()
        
        # Show red warning
        click.echo("")
        click.echo("=" * 60)
        click.echo(click.style("⚠️  DANGEROUS OPERATION - DATABASE CLEAR", fg='red', bold=True))
        click.echo(click.style("   This will DELETE ALL DATA from the database!", fg='red'))
        click.echo("=" * 60)
        click.echo("")
        
        click.echo(click.style("📋 What will happen:", fg='yellow'))
        click.echo("   • Delete ALL data from all tables")
        click.echo("   • Preserve database schema (tables, columns, indexes)")
        if keep_currencies:
            click.echo("   • Keep currency seed data")
        else:
            click.echo("   • Delete currency seed data")
        click.echo("")
        
        # Interactive confirmation
        if not click.confirm(click.style("❓ Are you sure you want to CLEAR all database data?", fg='red', bold=True)):
            click.echo(click.style("✅ Operation cancelled - database unchanged", fg='green'))
            return 0
        
        # Second confirmation for extra safety
        if not click.confirm(click.style("❓ This will DELETE ALL DATA. Are you absolutely sure?", fg='red', bold=True)):
            click.echo(click.style("✅ Operation cancelled - database unchanged", fg='green'))
            return 0
        
        # Execute the operation
        click.echo("")
        click.echo("🧹 Proceeding with database clear...")
        
        success = clear_database(keep_currencies=keep_currencies)
        
        if success:
            click.echo("")
            click.echo(click.style("✅ DATABASE CLEAR COMPLETED", fg='green', bold=True))
            return 0
        else:
            click.echo("")
            click.echo(click.style("❌ DATABASE CLEAR FAILED", fg='red', bold=True))
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error during database clear: {e}", err=True)
        return 1


@db.command('seed')
@no_auth()
@click.pass_context
def seed(ctx):
    """Seed the database with default data (currencies, product states, process states, countries, and RBAC)
    
    This command will populate the database with essential default data:
    - Default currencies (USD, EUR, GBP, CAD, AUD)
    - Default product states (available, unavailable, pending, processing, disabled)
    - Default process states (running, paused, killed, stopped, error, completed)
    - Default countries (BO, PE, CL, AR, BR, CA, US)
    - RBAC permissions and role-permission mappings
    
    Use this after clearing the database to restore essential data.
    """
    try:
        # Import here to avoid circular imports
        from utils.database import seed_database
        
        # Display connection info immediately when command is called
        display_detailed_connection_info()
        
        click.echo("")
        click.echo(click.style("🌱 DATABASE SEEDING", fg='green', bold=True))
        click.echo("=" * 50)
        click.echo("")
        
        click.echo(click.style("📋 What will be seeded:", fg='yellow'))
        click.echo("   • Default currencies (USD, EUR, GBP, CAD, AUD)")
        click.echo("   • Default product states (available, unavailable, pending, processing, disabled)")
        click.echo("   • Default process states (running, paused, killed, stopped, error, completed)")
        click.echo("   • Default countries (BO, PE, CL, AR, BR, CA, US)")
        click.echo("   • RBAC permissions and role-permission mappings")
        click.echo("")
        
        # Interactive confirmation
        if not click.confirm(click.style("❓ Do you want to seed the database with default data?", fg='green', bold=True)):
            click.echo(click.style("✅ Operation cancelled", fg='green'))
            return 0
        
        # Execute the operation
        click.echo("")
        click.echo("🌱 Proceeding with database seeding...")
        
        success = seed_database()
        
        if success:
            click.echo("")
            click.echo(click.style("✅ DATABASE SEEDING COMPLETED", fg='green', bold=True))
            return 0
        else:
            click.echo("")
            click.echo(click.style("❌ DATABASE SEEDING FAILED", fg='red', bold=True))
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error during database seeding: {e}", err=True)
        return 1