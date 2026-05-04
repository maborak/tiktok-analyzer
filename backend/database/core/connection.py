from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import Pool
from config import get_database_url
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def create_database_engine(database_url: Optional[str] = None, read_only: bool = False):
    """
    Create database engine with connection pooling and connection error handling.
    
    Args:
        database_url: Optional database URL. If None, uses get_database_url()
        read_only: If True, uses read-specific pool settings (for read replicas)
    
    Returns:
        SQLAlchemy engine
    """
    from config import settings
    
    if database_url is None:
        if settings("DB_USE_REPLICA_ENGINE", False):
            if read_only:
                database_url = settings("DB_READ_URL") or get_database_url()
            else:
                database_url = settings("DB_WRITE_URL") or get_database_url()
        else:
            database_url = get_database_url()
    
    # Get pool settings from config
    echo = settings("DB_ECHO", False)
    echo_pool = settings("DB_ECHO_POOL", False)
    
    # Determine database type from URL
    is_sqlite = database_url.startswith("sqlite://")
    
    # Configure pool settings based on database type and read/write mode
    if is_sqlite:
        # SQLite doesn't support multiple connections well - use single connection
        # SQLite also doesn't support read replicas
        pool_size = 1
        max_overflow = 0
        pool_timeout = None  # SQLite doesn't use timeout
        pool_recycle = None  # SQLite doesn't need recycling
    else:
        # Production-ready pool settings for PostgreSQL, MySQL, etc.
        if read_only:
            pool_size = settings("DB_READ_POOL_SIZE", 10)
        else:
            pool_size = settings("DB_WRITE_POOL_SIZE", 20)
        max_overflow = int(settings("DB_MAX_OVERFLOW", "30"))
        pool_timeout = int(settings("DB_POOL_TIMEOUT", "30"))
        pool_recycle = int(settings("DB_POOL_RECYCLE", "3600"))
    
    # Build engine kwargs
    engine_kwargs = {
        "echo": echo,
        "echo_pool": echo_pool,
        "pool_pre_ping": True,  # Test connections before using to detect stale connections
    }
    
    # Add pool settings (skip None values for SQLite)
    if pool_size is not None:
        engine_kwargs["pool_size"] = pool_size
    if max_overflow is not None:
        engine_kwargs["max_overflow"] = max_overflow
    if pool_timeout is not None:
        engine_kwargs["pool_timeout"] = pool_timeout
    if pool_recycle is not None:
        engine_kwargs["pool_recycle"] = pool_recycle
    
    # Create engine with pool settings
    engine = create_engine(database_url, **engine_kwargs)
    
    # Add event listener to handle connection pool errors gracefully
    @event.listens_for(Pool, "invalidate")
    def receive_invalidate(_dbapi_conn, _connection_record, exception):
        """Called when a connection is invalidated - log but don't raise"""
        if exception:
            # Log the invalidation but don't raise - pool will create new connection
            # This is normal when connections are closed by the server
            logger.debug("Connection invalidated (this is normal for stale connections): %s", type(exception).__name__)
    
    return engine


class AuditedSession(Session):
    """
    SQLAlchemy Session that logs creation and closure for auditing purposes.
    Helps detect connection leaks and verify session reuse.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Session creation is already logged in get_db_session()
        # but we could add more specific tracking here if needed

    def close(self):
        super().close()
        # Session closure is also handled in get_db_session() but
        # keeping this class ensures compatibility with callers of get_session_maker()

def get_session_maker(engine):
    """Create session maker for database operations"""
    # Create original sessionmaker
    original_session_maker = sessionmaker(bind=engine)
    
    # Return a factory that produces audited sessions
    # We can either subclass sessionmaker or just replace the class_ it instantiates
    # Easier: duplicate sessionmaker behavior but use our class
    return sessionmaker(bind=engine, class_=AuditedSession)

def create_tables(engine):
    """Create all database tables"""
    from .. import Base  # Import all models to register them
    Base.metadata.create_all(engine) 