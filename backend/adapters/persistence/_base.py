"""
Shared database infrastructure for persistence adapters.

Contains retry-capable session/query wrappers and a base adapter class
with engine management, session lifecycle, and connection recovery logic.
No domain ports are imported here — this is pure infrastructure.
"""

from typing import Optional, Any, Callable
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
import time
import logging

from database import create_database_engine, get_session_maker
from utils.database.database_session import get_current_session

logger = logging.getLogger(__name__)

# Module-level tracking for screenshot threads
_screenshot_threads = set()  # Set of active screenshot threads
_screenshot_atexit_registered = False


class RetrySession:
    """
    Session wrapper that automatically retries database operations on connection errors.

    This wraps a SQLAlchemy Session and intercepts all method calls to automatically
    retry on connection errors with exponential backoff and engine recreation.
    """

    def __init__(self, session: Session, adapter_instance, should_close: bool = True):
        """
        Initialize retry session wrapper

        Args:
            session: The SQLAlchemy session to wrap
            adapter_instance: The adapter instance (for engine recreation)
            should_close: Whether to close the session when close() is called.
                         Set to False when reusing a shared session (ContextVars).
        """
        self._session = session
        self._adapter = adapter_instance
        self._should_close = should_close
        self._max_retries = 3
        self._initial_delay = 0.5

    def __getattr__(self, name):
        """Delegate all attribute access to the wrapped session"""
        attr = getattr(self._session, name)

        # If it's a callable method, wrap it with retry logic
        if callable(attr) and not name.startswith('_'):
            def wrapper(*args, **kwargs):
                return self._execute_with_retry(lambda: attr(*args, **kwargs))
            return wrapper

        return attr

    def _execute_with_retry(self, operation: Callable):
        """Execute operation with automatic retry on connection errors"""
        last_exception = None
        reconnected = False

        for attempt in range(self._max_retries):
            try:
                result = operation()
                # If we reconnected and operation succeeded, log success
                if reconnected:
                    logger.info(f"Database reconnection successful - operation completed after {attempt} retry attempts")
                return result
            except Exception as e:
                last_exception = e

                # Only retry on connection errors
                if not self._adapter._is_connection_error(e):
                    # Non-connection error, raise immediately
                    raise

                # If this is the last attempt, don't retry
                if attempt == self._max_retries - 1:
                    logger.error(f"Database connection error after {self._max_retries} attempts: {e}")
                    raise

                # Recreate engine on connection error
                self._adapter._recreate_engine()
                reconnected = True

                # Recreate session with new engine
                self._session.close()
                self._session = self._adapter.SessionLocal()

                # Exponential backoff: 0.5s, 1s, 2s
                delay = self._initial_delay * (2 ** attempt)
                logger.warning(f"Database connection error (attempt {attempt + 1}/{self._max_retries}), "
                             f"retrying in {delay:.1f}s: {e}")
                time.sleep(delay)

        # Should never reach here, but just in case
        if last_exception:
            raise last_exception

    def close(self):
        """Close the wrapped session"""
        if self._should_close:
            self._session.close()
        else:
            # Shared session - do not close
            pass

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure close is called"""
        self.close()

    def commit(self):
        """Commit with retry logic"""
        return self._execute_with_retry(lambda: self._session.commit())

    def rollback(self):
        """Rollback with retry logic"""
        return self._execute_with_retry(lambda: self._session.rollback())

    def query(self, *entities, **kwargs):
        """Query with retry logic - returns a wrapped query that retries on execution"""
        query = self._session.query(*entities, **kwargs)
        return RetryQuery(query, self)

    def add(self, instance):
        """Add instance with retry logic"""
        return self._execute_with_retry(lambda: self._session.add(instance))

    def delete(self, instance):
        """Delete instance with retry logic"""
        return self._execute_with_retry(lambda: self._session.delete(instance))

    def flush(self, objects=None):
        """Flush with retry logic"""
        return self._execute_with_retry(lambda: self._session.flush(objects))

    def refresh(self, instance, attribute_names=None, with_for_update=None):
        """Refresh with retry logic"""
        return self._execute_with_retry(lambda: self._session.refresh(instance, attribute_names, with_for_update))

    def merge(self, instance, load=True):
        """Merge with retry logic"""
        return self._execute_with_retry(lambda: self._session.merge(instance, load))

    def expunge(self, instance):
        """Expunge with retry logic"""
        return self._execute_with_retry(lambda: self._session.expunge(instance))

    def expunge_all(self):
        """Expunge all with retry logic"""
        return self._execute_with_retry(lambda: self._session.expunge_all())

    def execute(self, statement, params=None, execution_options=None, bind_arguments=None):
        """Execute with retry logic"""
        # SQLAlchemy Session.execute() only accepts statement, params, and execution_options
        # bind_arguments is not supported in older versions, so we only pass what's needed
        if execution_options is not None:
            return self._execute_with_retry(lambda: self._session.execute(statement, params, execution_options))
        elif params is not None:
            return self._execute_with_retry(lambda: self._session.execute(statement, params))
        else:
            return self._execute_with_retry(lambda: self._session.execute(statement))

    def scalar(self, statement, params=None, execution_options=None, bind_arguments=None):
        """Scalar with retry logic"""
        return self._execute_with_retry(lambda: self._session.scalar(statement, params, execution_options, bind_arguments))

    def scalars(self, statement, params=None, execution_options=None, bind_arguments=None):
        """Scalars with retry logic"""
        return self._execute_with_retry(lambda: self._session.scalars(statement, params, execution_options, bind_arguments))


class RetryQuery:
    """
    Query wrapper that automatically retries query execution on connection errors.
    """

    def __init__(self, query, retry_session):
        """
        Initialize retry query wrapper

        Args:
            query: The SQLAlchemy Query object to wrap
            retry_session: The RetrySession instance (for retry logic)
        """
        self._query = query
        self._retry_session = retry_session
        # Store query metadata for recreation if needed
        self._entities = query.column_descriptions if hasattr(query, 'column_descriptions') else None

    def __getattr__(self, name):
        """Delegate all attribute access to the wrapped query"""
        attr = getattr(self._query, name)

        # Execution methods that actually hit the database - these need retry
        execution_methods = ['all', 'first', 'one', 'one_or_none', 'scalar', 'count', 'get', 'delete', 'update']

        if callable(attr) and name in execution_methods:
            def wrapper(*args, **kwargs):
                return self._retry_session._execute_with_retry(lambda: attr(*args, **kwargs))
            return wrapper

        # Query building methods - these return new queries, wrap them
        if callable(attr) and name in ['filter', 'filter_by', 'order_by', 'group_by', 'having',
                                       'join', 'outerjoin', 'limit', 'offset', 'distinct', 'subquery']:
            def wrapper(*args, **kwargs):
                result = attr(*args, **kwargs)
                # If result is a query-like object, wrap it
                if hasattr(result, 'all') or hasattr(result, 'first') or hasattr(result, 'count'):
                    return RetryQuery(result, self._retry_session)
                return result
            return wrapper

        return attr


class BasePersistenceAdapter:
    """
    Base class for persistence adapters providing shared database infrastructure:
    - Engine and session management
    - Connection error detection and recovery
    - Retry logic with exponential backoff

    Subclasses should implement domain-specific data access methods.
    This class does NOT import any port ABCs — it is pure infrastructure.
    """

    def __init__(self, db_path: Optional[str] = None, auto_init: bool = True,
                 screenshot_port: Optional[Any] = None, background_tasks: Optional[Any] = None):
        """
        Initialize database adapter with SQLAlchemy

        Args:
            db_path: Optional custom database path (ignored for now, uses SQLAlchemy config)
            auto_init: Whether to automatically initialize the database (default: True)
            screenshot_port: Optional screenshot service port for taking screenshots
            background_tasks: Optional FastAPI BackgroundTasks for async screenshot processing
        """
        from config import settings
        from utils.database.database_session import get_routing_session_maker

        # Use routing session maker if read replicas enabled, otherwise use legacy
        if settings("DB_USE_REPLICA_ENGINE", False):
            self.SessionLocal = get_routing_session_maker()
            # For table creation, use write engine
            from utils.database.database_session import get_write_engine
            self.engine = get_write_engine()
        else:
            # Legacy mode - single engine
            # Always create a fresh engine to ensure we use the current database URL
            # This is important when database URL is changed via set_database_url()
            self.engine = create_database_engine()
            self.SessionLocal = get_session_maker(self.engine)

        self.screenshot_port = screenshot_port
        self.background_tasks = background_tasks
        if auto_init:
            self._ensure_database_exists()

    def _ensure_database_exists(self):
        """Ensure database exists and is initialized"""
        try:
            from database import create_tables
            create_tables(self.engine)
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def _get_session(self, session: Optional[Session] = None) -> RetrySession:
        """
        Get database session with automatic retry logic.

        Uses implicit context (ContextVars) to reuse sessions across calls
        within the same request/command lifecycle.

        Args:
            session: Optional explicit session. If provided, it will be used.
        """
        # 0. Use explicit session if provided
        if session:
            return RetrySession(session, self, should_close=False)

        # 1. Try to get implicit session from context (ContextVars)
        implicit_session = get_current_session()

        if implicit_session:
            # REUSE: Return wrapper that WON'T close the session
            return RetrySession(implicit_session, self, should_close=False)
        else:
            # FALLBACK: Create new session and return wrapper that WILL close it
            session = self.SessionLocal()
            return RetrySession(session, self, should_close=True)

    def _is_connection_error(self, error: Exception) -> bool:
        """
        Check if error is a connection-related error.

        SQLAlchemy wraps database driver errors in its own exceptions, so we check:
        1. SQLAlchemy's OperationalError and DisconnectionError
        2. Error message for connection-related keywords (database-agnostic)
        """
        # SQLAlchemy wraps database driver errors (psycopg2, pymysql, etc.)
        if isinstance(error, (OperationalError, DisconnectionError)):
            return True

        # Check error message for connection-related keywords (works for all databases)
        error_str = str(error).lower()
        connection_keywords = [
            'server closed the connection',
            'connection unexpectedly',
            'connection lost',
            'connection reset',
            'connection timed out',
            'connection refused',
            'broken pipe',
            'connection pool',
            'connection is closed',
            'connection was closed',
            'lost connection',
            'connection error',
            "'nonetype' object has no attribute 'connect'" # Handle uninitialized engine
        ]

        return any(keyword in error_str for keyword in connection_keywords)

    def _recreate_engine(self):
        """Recreate database engine and session maker after connection error"""
        logger.warning("Recreating database engine due to connection error")
        try:
            # Close existing engine connections
            if hasattr(self, 'engine'):
                self.engine.dispose(close=True)
        except Exception as e:
            logger.warning(f"Error disposing old engine: {e}")

        # Reset cached connections and recreate
        from config import settings
        from utils.database.database_session import get_routing_session_maker, reset_database_connection

        # Reset cached connections
        reset_database_connection()

        # Recreate based on read replica setting
        if settings("DB_USE_REPLICA_ENGINE", False):
            from utils.database.database_session import get_write_engine
            self.SessionLocal = get_routing_session_maker()
            self.engine = get_write_engine()
        else:
            self.engine = create_database_engine()
            self.SessionLocal = get_session_maker(self.engine)

        logger.info("Database engine recreated successfully")

    def _execute_with_retry(self, operation: Callable, max_retries: int = 3,
                            initial_delay: float = 0.5) -> Any:
        """
        Execute a database operation with automatic retry on connection errors.
        This is a generic wrapper that can be used for any database operation.

        The operation function should take a Session as its only parameter and return a result.
        The session is automatically managed (created, committed/rolled back, and closed).

        Args:
            operation: Callable that takes a Session and returns a result
            max_retries: Maximum number of retry attempts (default: 3)
            initial_delay: Initial delay in seconds before retry (default: 0.5)

        Returns:
            Result of the operation

        Raises:
            Exception: If all retries fail or non-connection error occurs
        """
        last_exception = None
        reconnected = False

        for attempt in range(max_retries):
            session = None
            try:
                session = self._get_session()
                result = operation(session)
                # If operation succeeds, commit and return
                session.commit()
                # If we reconnected and operation succeeded, log success
                if reconnected:
                    logger.info(f"Database reconnection successful - operation completed after {attempt} retry attempts")
                return result
            except Exception as e:
                last_exception = e

                # Rollback on error
                if session:
                    try:
                        session.rollback()
                    except Exception:
                        pass

                # Only retry on connection errors
                if not self._is_connection_error(e):
                    logger.error(f"Non-connection database error: {e}")
                    raise

                # If this is the last attempt, don't retry
                if attempt == max_retries - 1:
                    logger.error(f"Database connection error after {max_retries} attempts: {e}")
                    raise

                # Recreate engine on connection error
                self._recreate_engine()
                reconnected = True

                # Exponential backoff: 0.5s, 1s, 2s
                delay = initial_delay * (2 ** attempt)
                logger.warning(f"Database connection error (attempt {attempt + 1}/{max_retries}), "
                             f"retrying in {delay:.1f}s: {e}")
                time.sleep(delay)
            finally:
                if session:
                    session.close()

        # Should never reach here, but just in case
        if last_exception:
            raise last_exception
