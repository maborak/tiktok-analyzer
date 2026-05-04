"""
Database session management utilities

Centralized database session management to eliminate duplicated try/finally patterns
and provide consistent error handling across the application.

Supports automatic read/write routing for database read replicas.
"""

import logging
import time
from typing import TypeVar
from contextlib import contextmanager
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import Select, Insert, Update, Delete
from database.core.connection import create_database_engine
# Alias for compatibility with existing code that uses this name
create_engine_from_url = create_database_engine
from contextvars import ContextVar
from config import settings
from utils.database.force_write import get_db_consistency_mode

logger = logging.getLogger(__name__)

# Global session counter for auditing
_session_counter = 0

# Context variable to hold the current session for the request
# This allows implicit session passing without drilling arguments
_session_context: ContextVar[Session] = ContextVar('db_session', default=None)

T = TypeVar('T')

# Global engines and session makers for connection pooling
_read_engine = None
_write_engine = None
_routing_session_maker = None
_legacy_engine = None
_legacy_session_maker = None

class RoutingSession(Session):
    """
    SQLAlchemy Session that automatically routes queries to read/write databases.
    
    - SELECT queries → Read replica (if configured)
    - INSERT/UPDATE/DELETE → Write master
    - Transactions → Write master (for consistency)
    """
    
    def __init__(self, read_engine=None, write_engine=None, **kwargs):
        """
        Initialize routing session.
        
        Args:
            read_engine: Read replica engine (for SELECT queries)
            write_engine: Write master engine (for INSERT/UPDATE/DELETE)
            **kwargs: Other session parameters (bind is ignored - we route dynamically)
        """
        # Remove bind from kwargs if present (we don't use it - we route dynamically)
        kwargs.pop('bind', None)
        # Don't bind to a specific engine - we'll route dynamically via get_bind()
        super().__init__(bind=None, **kwargs)
        # Store engines for routing
        self.read_engine = read_engine
        self.write_engine = write_engine
        self._force_write = False  # Flag to force write connection
    
    def get_bind(self, mapper=None, clause=None):
        """
        Route queries to appropriate database based on decorator preferences.
        
        This is called by SQLAlchemy for every query to determine which
        engine to use.
        
        Routing logic (in order of priority):
        1. Decorator preference (@require_write_db or @require_read_db) - highest priority
        2. Force write mode flag (for transactions or explicit write operations)
        3. Transaction check (use write for consistency)
        4. Default: Write engine (all operations default to write)
        
        Note: By default, ALL operations route to write. Only decorators can
        override this to use read connection.
        """
        from config import settings
        from utils.database.force_write import get_db_consistency_mode
        
        # Determine clause type and mapper name for logging
        clause_type = "unknown"
        if clause is not None:
            clause_type = type(clause).__name__
        
        mapper_name = "N/A"
        if mapper and hasattr(mapper, 'class_'):
            try:
                mapper_name = mapper.class_.__name__
            except (AttributeError, TypeError):
                pass
        
        # Check decorator preference first (highest priority)
        consistency_mode = get_db_consistency_mode()
        if consistency_mode == "write":
            # Decorator explicitly requested write connection
            logger.debug(
                "🟠 Using WRITE engine (decorator: @require_write_db) | "
                "Clause: %s | Mapper: %s",
                clause_type,
                mapper_name
            )
            return self.write_engine
        elif consistency_mode == "read":
            # Decorator explicitly requested read connection
            # If replica engine not enabled, get_read_engine() returns write_engine
            # So this will work correctly (using same connection, but respecting decorator intent)
            logger.debug(
                "🔵 Using READ engine (decorator: @require_read_db) | "
                "Clause: %s | Mapper: %s",
                clause_type,
                mapper_name
            )
            return self.read_engine
        
        # Force write mode (for transactions or explicit write operations)
        if self._force_write:
            logger.debug(
                "🟠 Using WRITE engine (force_write mode) | "
                "Clause: %s | Mapper: %s",
                clause_type,
                mapper_name
            )
            return self.write_engine
        
        # If we're in a transaction, use write engine for consistency
        # This ensures all operations in a transaction use the same connection
        if self.in_transaction():
            logger.debug(
                "🟠 Using WRITE engine (in transaction) | "
                "Clause: %s | Mapper: %s",
                clause_type,
                mapper_name
            )
            return self.write_engine
        
        # DEFAULT: All operations route to write engine
        # Only decorators can override this to use read connection
        logger.debug(
            "🟠 Using WRITE engine (default) | "
            "Clause: %s | Mapper: %s",
            clause_type,
            mapper_name
        )
        return self.write_engine
    
    def force_write_mode(self):
        """Force this session to use write connection for all operations"""
        self._force_write = True
    
    def reset_mode(self):
        """Reset to automatic routing"""
        self._force_write = False


def get_read_engine():
    """
    Get or create read engine (read replica).
    
    If DB_USE_REPLICA_ENGINE=true, loads the read replica URL.
    If false, returns the write engine (same connection).
    """
    global _read_engine
    if _read_engine is None:
        if settings("DB_USE_REPLICA_ENGINE", False):
            read_url = settings("DB_READ_URL") or get_database_url()
            _read_engine = create_engine_from_url(read_url, read_only=True)
            logger.info("Read engine initialized (replica engine mode): %s", read_url[:50] + "..." if len(read_url) > 50 else read_url)
        else:
            # If replica engine not enabled, use same as write
            _read_engine = get_write_engine()
            logger.info("Read engine initialized (using write engine — replica engine disabled)")
    return _read_engine


def get_write_engine():
    """
    Get or create write engine (master).
    
    If DB_USE_REPLICA_ENGINE=true, loads the write master URL.
    If false, uses the standard database URL.
    """
    global _write_engine
    if _write_engine is None:
        if settings("DB_USE_REPLICA_ENGINE", False):
            write_url = settings("DB_WRITE_URL") or get_database_url()
            _write_engine = create_engine_from_url(write_url, read_only=False)
            logger.info("Write engine initialized (replica engine mode): %s", write_url[:50] + "..." if len(write_url) > 50 else write_url)
        else:
            # Default behavior - use standard database URL
            _write_engine = create_database_engine()
            logger.info("Write engine initialized (standard mode — replica engine disabled)")
    return _write_engine


def get_routing_session_maker():
    """Get or create routing session maker"""
    global _routing_session_maker
    if _routing_session_maker is None:
        # Initialize both engines (this will trigger the log messages)
        read_engine = get_read_engine()
        write_engine = get_write_engine()
        logger.info("Routing session maker initialized (read/write routing enabled)")
        
        # Create a custom sessionmaker that properly instantiates RoutingSession
        # We need to override __call__ to pass read_engine and write_engine
        class RoutingSessionMaker:
            def __init__(self, read_engine, write_engine):
                self.read_engine = read_engine
                self.write_engine = write_engine
                self.autocommit = False
                self.autoflush = False
                self.expire_on_commit = False
            
            def __call__(self, **kwargs):
                # Remove bind if present (we don't use it)
                kwargs.pop('bind', None)
                # Create RoutingSession with engines
                return RoutingSession(
                    read_engine=self.read_engine,
                    write_engine=self.write_engine,
                    autocommit=self.autocommit,
                    autoflush=self.autoflush,
                    expire_on_commit=self.expire_on_commit,
                    **kwargs
                )
        
        _routing_session_maker = RoutingSessionMaker(read_engine, write_engine)
        logger.info("Routing session maker initialized")
    return _routing_session_maker


def get_engine():
    """Get or create the database engine with connection pooling (legacy - for backward compatibility)"""
    global _legacy_engine
    if _legacy_engine is None:
        _legacy_engine = create_database_engine()
    return _legacy_engine

def get_session_maker_optimized():
    """Get or create the session maker with connection pooling (legacy - for backward compatibility)"""
    global _legacy_session_maker
    if _legacy_session_maker is None:
        engine = get_engine()
        _legacy_session_maker = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False  # Keep objects in memory for better performance
        )
    return _legacy_session_maker

@contextmanager
def get_db_session():
    """
    Context manager for database sessions with automatic read/write routing.
    
    Automatically routes queries based on:
    - Decorator preferences (@require_write_db or @require_read_db)
    - Operation type (SELECT → read, INSERT/UPDATE/DELETE → write)
    - Transaction state (transactions → write)
    - DB_USE_REPLICA_ENGINE setting
    
    Decorator behavior:
    - @require_write_db: Forces write connection (overrides default routing)
    - @require_read_db: Forces read connection (overrides default routing, falls back to write if replicas disabled)
    
    No changes needed in calling code - routing happens automatically!
    
    Usage:
        with get_db_session() as session:
            # SELECT automatically goes to read replica (if configured)
            products = session.query(Product).all()
            
            # INSERT automatically goes to write master
            session.add(new_product)
            session.commit()
    """
    
    # Check if we already have an active session in this context
    # If so, return it instead of creating a new one (Implicit Context)
    existing_session = _session_context.get()
    if existing_session is not None:
        logger.debug("Reusing existing session from context")
        yield existing_session
        # Do not close or commit here - the outer context manager will handle it
        return

    global _session_counter
    _session_counter += 1
    logger.debug("Opening new DB session #%d", _session_counter)

    # Check decorator preference
    consistency_mode = get_db_consistency_mode()
    
    # Use routing session if:
    # 1. Replica engine is enabled (loads both read and write engines), OR
    # 2. Decorator explicitly requests read (even if replica engine disabled - will use same engine)
    # 3. Decorator explicitly requests write (to ensure routing works properly)
    use_routing = (
        settings("DB_USE_REPLICA_ENGINE", False) or 
        consistency_mode == "read" or 
        consistency_mode == "write"
    )
    
    if use_routing:
        session_maker = get_routing_session_maker()
        session = session_maker()
        # Force write mode if decorator explicitly requests write
        if consistency_mode == "write":
            session.force_write_mode()
    else:
        session_maker = get_session_maker_optimized()
        session = session_maker()
    
    # Set the session in the context var for children to use
    token = _session_context.set(session)
    
    start_time = time.time()
    try:
        yield session
        session.commit()
        execution_time = time.time() - start_time
        if execution_time > 1.0:  # Log slow queries
            logger.warning(f"Slow database operation: {execution_time:.2f}s")
    except Exception as e:
        session.rollback()
        execution_time = time.time() - start_time
        logger.error(f"Database operation failed after {execution_time:.2f}s: {e}")
        raise
    finally:
        # Reset context var
        try:
            _session_context.reset(token)
        except ValueError:
            # Token was created in a different context, which can happen with FastAPI thread switching
            pass
        session.close()



def get_connection_pool_stats():
    """Get connection pool statistics for monitoring"""
    from config import settings
    
    stats = {}
    
    if settings("DB_USE_REPLICA_ENGINE", False):
        # Get stats from both read and write pools
        read_engine = get_read_engine()
        write_engine = get_write_engine()
        
        read_pool = read_engine.pool
        write_pool = write_engine.pool
        
        stats = {
            "read_pool": {
                "pool_size": read_pool.size(),
                "checked_in": read_pool.checkedin(),
                "checked_out": read_pool.checkedout(),
                "overflow": read_pool.overflow(),
                "total_connections": read_pool.size() + read_pool.overflow()
            },
            "write_pool": {
                "pool_size": write_pool.size(),
                "checked_in": write_pool.checkedin(),
                "checked_out": write_pool.checkedout(),
                "overflow": write_pool.overflow(),
                "total_connections": write_pool.size() + write_pool.overflow()
            }
        }
    else:
        # Legacy single pool stats
        engine = get_engine()
        pool = engine.pool
        
        stats = {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow()
        }
    
    return stats

def log_pool_stats():
    """Log current connection pool statistics"""
    stats = get_connection_pool_stats()
    logger.info(f"Connection pool stats: {stats}")

def reset_database_connection():
    """Reset cached database engines and session makers
    
    Call this when the database URL changes to ensure new connections
    use the updated URL instead of the cached engines.
    """
    global _read_engine, _write_engine, _routing_session_maker, _legacy_engine, _legacy_session_maker
    
    # Dispose read engine
    if _read_engine is not None:
        try:
            _read_engine.dispose()  # Close all connections
        except Exception as e:
            logger.warning(f"Error disposing read engine: {e}")
    _read_engine = None
    
    # Dispose write engine
    if _write_engine is not None:
        try:
            _write_engine.dispose()  # Close all connections
        except Exception as e:
            logger.warning(f"Error disposing write engine: {e}")
    _write_engine = None
    
    # Dispose legacy engine
    if _legacy_engine is not None:
        try:
            _legacy_engine.dispose()  # Close all connections
        except Exception as e:
            logger.warning(f"Error disposing legacy engine: {e}")
    _legacy_engine = None
    
    # Reset session makers
    _routing_session_maker = None
    _legacy_session_maker = None
    
    logger.info("Database connection cache reset")


def get_db():
    """
    FastAPI dependency for database session.
    
    Wraps get_db_session context manager to provide a session generator
    that automatically handles commit/rollback and closing.
    """
    with get_db_session() as session:
        yield session


def get_current_session() -> Session:
    """
    Get the current active session correctly from context var.
    Returns None if no session is active.
    """
    return _session_context.get()

 