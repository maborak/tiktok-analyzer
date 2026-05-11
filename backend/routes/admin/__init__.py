"""
Admin API Routes

FastAPI routes for administrative functions.
Requires admin authentication.
"""

from fastapi import APIRouter
from typing import Optional

from domain.services.auth_service import AuthService

# Global variable for dependency injection
auth_service: Optional[AuthService] = None

# Create main admin router
router = APIRouter()

# Import sub-routers
from . import general, users, rbac

# Include sub-routers
router.include_router(general.router)
router.include_router(users.router)
router.include_router(rbac.router)

from . import tickets
router.include_router(tickets.router, prefix="/tickets")

from . import billing
router.include_router(billing.router, prefix="/billing")

from . import payment_gateways
router.include_router(payment_gateways.router, prefix="/payment-gateways")

from . import events as admin_events
router.include_router(admin_events.router)

from . import app_config as admin_app_config
router.include_router(admin_app_config.router)

from . import configuration as admin_configuration
router.include_router(admin_configuration.router)

from . import security as admin_security
router.include_router(admin_security.router)

from . import tiktok as admin_tiktok
router.include_router(admin_tiktok.router, prefix="/tiktok")

def set_dependencies(payment_service_instance=None, data_persistence_adapter_instance=None,
                     system_monitor_service_instance=None, event_config_service_instance=None,
                     notification_queue_adapter_instance=None,
                     app_config_adapter_instance=None, queue_config_service_instance=None,
                     config_service_instance=None,
                     tiktok_service_instance=None):
    if payment_service_instance:
        billing.payment_service = payment_service_instance
        payment_gateways.payment_service = payment_service_instance
    if data_persistence_adapter_instance:
        admin_events.data_persistence_adapter = data_persistence_adapter_instance
    if event_config_service_instance:
        admin_events.event_config_service = event_config_service_instance
    if app_config_adapter_instance:
        admin_app_config.app_config_adapter = app_config_adapter_instance
    if config_service_instance:
        admin_configuration.config_service = config_service_instance
        # The TikTok module's sign-engine page also needs read/write access.
        admin_tiktok.config_service = config_service_instance
    if tiktok_service_instance:
        admin_tiktok.tiktok_service = tiktok_service_instance
