from fastapi import APIRouter
from . import account
# `tiktok` (user-facing /tiktok/* monitoring) is imported here so
# set_dependencies can inject services, but the ROUTER itself is
# mounted by `routes/main.py:create_main_router` at the API root
# (not under /user/*). The URL space the operator picked is
# /tiktok/lives, /tiktok/credits, etc. — bare root, no prefix.
from . import tiktok as user_tiktok

router = APIRouter()

# Include sub-routers
router.include_router(account.router)

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
    # add/remove flow. None at boot → endpoints return 503. The
    # router itself is mounted in routes/main.py.
    if tiktok_service is not None:
        user_tiktok.tiktok_service = tiktok_service
    if credit_service is not None:
        user_tiktok.credit_service = credit_service
