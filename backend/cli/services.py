from typing import Optional
from pathlib import Path
import sys

# Add project root to path if needed (though typically handled by entry point)
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from config import settings, set_database_url, clear_database_url_override
from adapters.database_persistence import DatabaseDataPersistenceAdapter
from domain.services.auth_service import AuthService
from domain.services.ticket_service import TicketService
from adapters.auth_persistence import AuthPersistenceAdapter
from ports.hooks import HookManager

class CLIServices:
    """Container for injected services following hexagonal architecture"""

    def __init__(self, database_url: Optional[str] = None, initialize_db: bool = False):
        """Initialize all services with dependency injection"""
        # Use provided database URL or default
        if database_url:
            self.data_persistence_adapter = DatabaseDataPersistenceAdapter(
                db_path=database_url,
                auto_init=initialize_db,
            )
        else:
            self.data_persistence_adapter = DatabaseDataPersistenceAdapter(
                auto_init=initialize_db,
            )

        # Initialize authentication services
        jwt_secret = settings("JWT_SECRET", "your-super-secret-jwt-key-here-change-this-in-production")
        self.auth_adapter = AuthPersistenceAdapter(jwt_secret)
        from adapters.password_hasher import PBKDF2PasswordHasher
        self.auth_service = AuthService(
            auth_port=self.auth_adapter,
            user_management_port=self.auth_adapter,
            session_management_port=self.auth_adapter,
            api_key_management_port=self.auth_adapter,
            authorization_port=self.auth_adapter,
            password_hasher=PBKDF2PasswordHasher(),
            jwt_secret=jwt_secret
        )

        # Initialize Support Ticket dependencies
        self.hook_manager = HookManager()
        self.hook_manager.configure(data_persistence=self.data_persistence_adapter)
        self.ticket_service = TicketService(
            data_port=self.data_persistence_adapter,
            hook_manager=self.hook_manager
        )


# Global services instance
services = None


def get_services(database_url: Optional[str] = None, initialize_db: bool = False, force_refresh: bool = False) -> CLIServices:
    """Get or create services instance (singleton pattern)"""
    global services
    if services is None or force_refresh:
        if force_refresh and not database_url:
            from config import clear_database_url_override
            clear_database_url_override()

        services = CLIServices(database_url, initialize_db)
    return services
