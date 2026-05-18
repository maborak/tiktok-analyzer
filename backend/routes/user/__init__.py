from fastapi import APIRouter
from . import account
from . import tiktok as user_tiktok

router = APIRouter()

# Include sub-routers
router.include_router(account.router)
# /tiktok/* — user-facing monitoring product (credits-gated). NOT
# under /user/* prefix on purpose: the URL space the user is
# supposed to memorise is `/tiktok/lives`, `/tiktok/credits`, etc.
router.include_router(user_tiktok.router)

# Dependency injection helper
def set_dependencies(
    adapter,
    auth_service=None,
    ticket_service=None,
    payment_service=None,
    tiktok_service=None,
    credit_service=None,
):
    account.set_dependencies(
        adapter,
        auth_service=auth_service,
        ticket_service=ticket_service,
        payment_service_dep=payment_service,
    )
    # User TikTok routes need both services for the credit-gated
    # add/remove flow. None at boot → endpoints return 503.
    if tiktok_service is not None:
        user_tiktok.tiktok_service = tiktok_service
    if credit_service is not None:
        user_tiktok.credit_service = credit_service
