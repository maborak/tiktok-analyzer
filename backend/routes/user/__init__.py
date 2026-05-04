from fastapi import APIRouter
from . import account

router = APIRouter()

# Include sub-routers
router.include_router(account.router)

# Dependency injection helper
def set_dependencies(adapter, auth_service=None, ticket_service=None, payment_service=None):
    account.set_dependencies(adapter, auth_service=auth_service, ticket_service=ticket_service, payment_service_dep=payment_service)
