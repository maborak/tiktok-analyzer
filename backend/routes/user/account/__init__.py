from fastapi import APIRouter
from . import info, edit, delete, recipients, billing

router = APIRouter()

# Include sub-routers.
router.include_router(info.router)
router.include_router(edit.router)
router.include_router(delete.router)
router.include_router(recipients.router, prefix="/account")

from . import tickets
router.include_router(tickets.router, prefix="/account/tickets")
router.include_router(billing.router, prefix="/account/billing")

from . import oauth
router.include_router(oauth.router, prefix="/account")

def set_dependencies(adapter, auth_service=None, ticket_service=None, payment_service_dep=None):
    info.data_persistence_adapter = adapter
    edit.data_persistence_adapter = adapter
    delete.data_persistence_adapter = adapter
    recipients.data_persistence_adapter = adapter

    if auth_service:
        info.auth_service = auth_service
        edit.auth_service = auth_service
        delete.auth_service = auth_service

    if ticket_service:
        tickets.ticket_service = ticket_service

    if payment_service_dep:
        billing.payment_service = payment_service_dep
