"""
Main router configuration and route setup

This module handles the main router creation and dependency injection setup.
"""

from fastapi import APIRouter

# Import debug utilities globally


from . import general, auth, user, media, webhooks, billing
from . import admin
from . import public_tiktok



def setup_routes(
    data_persistence_adapter,
    auth_service=None,
    ticket_service=None,
    payment_service=None,
    credit_service=None,
    rbac_port=None,
    event_config_service=None,
    notification_queue=None,
    app_config_adapter=None,
    oauth_service=None,
    config_service=None,
    tiktok_service=None,
):
    """Setup routes with dependency injection"""
    # Set authentication dependencies
    auth.data_persistence_adapter = data_persistence_adapter
    if auth_service:
        from utils.auth_provider import set_auth_service
        set_auth_service(auth_service)
        auth.auth_service = auth_service
        admin.auth_service = auth_service

    if ticket_service:
        from .admin import tickets as admin_tickets
        admin_tickets.ticket_service = ticket_service

        try:
            from . import livechat, contact, media
            livechat.ticket_service = ticket_service
            contact.ticket_service = ticket_service
            auth.ticket_service = ticket_service
            media.ticket_service = ticket_service
        except (ImportError, AttributeError) as e:
            pass

    if oauth_service:
        from utils.oauth_provider import set_oauth_service
        set_oauth_service(oauth_service)
        auth.oauth_service = oauth_service
        # Inject into user account OAuth management routes
        from routes.user.account import oauth as user_oauth
        user_oauth.oauth_service = oauth_service
        if auth_service:
            user_oauth.auth_service = auth_service

    if credit_service:
        auth.credit_service = credit_service

    # Set user dependencies. `tiktok_service` + `credit_service` thread
    # through for the /tiktok/* user-facing monitoring product (added
    # 2026-05-18 — users pay 1 credit per monitor, refundable within
    # 24h).
    user.set_dependencies(
        data_persistence_adapter,
        auth_service=auth_service,
        ticket_service=ticket_service,
        payment_service=payment_service,
        tiktok_service=tiktok_service,
        credit_service=credit_service,
    )

    # Set webhooks dependencies
    admin.set_dependencies(
        payment_service_instance=payment_service if payment_service else None,
        data_persistence_adapter_instance=data_persistence_adapter,
        event_config_service_instance=event_config_service,
        notification_queue_adapter_instance=notification_queue,
        app_config_adapter_instance=app_config_adapter,
        config_service_instance=config_service,
        tiktok_service_instance=tiktok_service,
    )
    # Public TikTok routes — same TikTokService instance, but exposed
    # via a no-auth router. Without this assignment the unauthenticated
    # endpoint 503s.
    if tiktok_service is not None:
        public_tiktok.tiktok_service = tiktok_service
    # `/public/tiktok/runtime-config` reads a 3-key slice of typed
    # config (poll interval + WS modes) and serves it to both admin
    # and public frontends so they can adapt their polling cadence
    # and stream/poll choice without a rebuild.
    if config_service is not None:
        public_tiktok.config_service = config_service
    if payment_service:
        webhooks.payment_service = payment_service
        billing.payment_service = payment_service

    # Inject RBAC port into admin route modules
    if rbac_port:
        from .admin import rbac as admin_rbac, users as admin_users
        admin_rbac.rbac_port = rbac_port
        admin_users.rbac_port = rbac_port

    # Make debug functions available globally
    # These functions can now be imported in any endpoint file
    # from utils.debug import debug_return, debug_log, debug_breakpoint

def create_main_router():
    """Create and configure the main router with all sub-routers"""
    main_router = APIRouter()

    # Include all sub-routers
    main_router.include_router(general.router, tags=["General"])
    main_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
    main_router.include_router(user.router, prefix="/user")
    main_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
    main_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
    main_router.include_router(billing.router, prefix="/billing", tags=["Billing"])

    from . import livechat, contact
    main_router.include_router(livechat.router, prefix="/livechat", tags=["LiveChat"])
    main_router.include_router(media.router, prefix="/media", tags=["Media"])
    main_router.include_router(contact.router, prefix="/contact", tags=["Contact"])

    # Public (unauthenticated) routes. Mounted at /public/* so admin
    # tooling can blanket-allow that prefix on the rate limiter and
    # firewall. NO auth dependency — endpoints inside must be safe to
    # serve to anonymous users.
    main_router.include_router(public_tiktok.router, prefix="/public", tags=["Public"])

    # User-facing /tiktok/* monitoring routes. Mounted at the ROOT
    # (not under /user/*) on purpose — the URL the operator told us
    # to use is `/tiktok/lives`, `/tiktok/credits`, etc. Internally
    # the router lives at `routes/user/tiktok.py` because it shares
    # the same auth dep (`get_current_user_swagger_compatible`) as
    # every other authenticated user endpoint; the FILE path follows
    # framework convention, the URL path does not.
    from routes.user import tiktok as user_tiktok
    main_router.include_router(user_tiktok.router, tags=["User TikTok"])

    return main_router
