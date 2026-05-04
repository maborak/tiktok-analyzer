"""
Email Handler - Sends email notifications on hook events

Uses Jinja2 templates from templates/email/{template_set}/ for rendering.
"""

import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email import encoders
from email.charset import Charset, QP, BASE64
from email.utils import formataddr
from typing import List, Optional, Tuple, Dict, Any

from ports.hooks.base_handler import HookHandler, HookEvent, HookEventType
from ports.hooks.hook_manager import hook_manager
from utils.templates import EmailTemplateLoader
from utils.debug import colorize

logger = logging.getLogger(__name__)


def _get_charset(encoding: str = "quoted-printable") -> Charset:
    """
    Get a Charset object with the specified encoding.
    
    Args:
        encoding: "quoted-printable", "base64", or "7bit"
        
    Returns:
        Configured Charset object
    """
    charset = Charset('utf-8')
    encoding_lower = encoding.lower()
    if encoding_lower == "base64":
        charset.body_encoding = BASE64
    elif encoding_lower == "7bit":
        charset.body_encoding = None  # No encoding, raw 7-bit ASCII
    else:  # default to quoted-printable
        charset.body_encoding = QP
    return charset


class EmailHandler(HookHandler):
    """
    Handler that renders email notifications and enqueues them for async delivery.

    When a NotificationQueuePort is injected, emails are enqueued to Redis
    for delivery by the CLI consumer (python cli.py monitor queue-consume).
    Falls back to synchronous SMTP when Redis is unavailable or queue is not configured.

    Usage:
        from ports.hooks import hook_manager
        from adapters.hooks import EmailHandler

        handler = EmailHandler(
            sender="alerts@example.com",
            receiver="user@example.com",
            password="app_password",
            notification_queue=redis_queue_adapter,  # optional
        )
        hook_manager.register(handler)
    """

    def __init__(
        self,
        sender: str = "",
        sender_name: str = "",
        receiver: str = "",
        username: str = "",
        password: str = "",
        smtp_host: str = "localhost",
        smtp_port: int = 465,
        smtp_security: str = "ssl",
        smtp_verify_ssl: bool = True,
        content_encoding: str = "quoted-printable",
        template_set: str = "default",
        templates_dir: str = "",
        notify_on_verification_requested: bool = True,
        notify_on_password_reset_requested: bool = True,
        verification_base_url: str = "/account/verify",
        recipient_verification_base_url: str = "/account/verify-recipient",
        password_reset_base_url: str = "/account/reset-password",
        notify_on_admin_notification: bool = True,
        notify_on_ticket: bool = True,
        notify_users: bool = False,
        notification_queue=None,
    ):
        """
        Initialize email handler.
        
        Args:
            sender: Sender email address (e.g., "alerts@example.com")
            sender_name: Display name for sender (defaults to APP_NAME from config)
            receiver: Receiver email address (To header)
            username: SMTP login username (defaults to sender if empty)
            password: SMTP password/app password
            smtp_host: SMTP server host
            smtp_port: SMTP server port
            smtp_security: Connection security type:
                - "ssl": Direct SSL connection (typically port 465)
                - "starttls": Start plain, upgrade to TLS (typically port 587)
                - "plain": No encryption (typically port 25 or 2525)
            smtp_verify_ssl: Verify SSL certificates (set False for self-signed certs)
            content_encoding: Email body encoding:
                - "quoted-printable": More readable in raw form (default)
                - "base64": More compact, less readable
                - "7bit": No encoding, raw ASCII (only for pure ASCII content)
            template_set: Email template set to use (e.g., "default", "minimal", "corporate")
            templates_dir: Custom templates directory path (empty = use default templates/email/)
            notify_on_verification_requested: Send email when USER_VERIFICATION_REQUESTED
            notify_on_password_reset_requested: Send email when USER_PASSWORD_RESET_REQUESTED
            verification_base_url: Base URL for verification links (e.g., "https://yourdomain.com/verify-email")
            password_reset_base_url: Base URL for password reset links (e.g., "https://yourdomain.com/reset-password")
        
        Note: enabled status is controlled by HOOKS_USE_DB_CONFIG and
        either database or HOOKS_HANDLERS config.
        """
        super().__init__(name="EmailHandler")
        self._load_config(
            sender, sender_name, receiver, username, password, smtp_host, smtp_port,
            smtp_security, smtp_verify_ssl, content_encoding, template_set, templates_dir,
            notify_on_verification_requested, notify_on_password_reset_requested,
            verification_base_url, password_reset_base_url,
            recipient_verification_base_url=recipient_verification_base_url,
            notify_on_admin_notification=notify_on_admin_notification,
            notify_on_ticket=notify_on_ticket,
            notify_users=notify_users
        )

        # Notification queue for async delivery (None = sync fallback)
        self.notification_queue = notification_queue

        # Initialize template loader
        self._template_loader: Optional[EmailTemplateLoader] = None
    
    def _load_config(self, sender, sender_name, receiver, username, password, smtp_host, smtp_port,
                     smtp_security, smtp_verify_ssl, content_encoding, template_set, templates_dir,
                     notify_on_verification_requested, notify_on_password_reset_requested,
                     verification_base_url, password_reset_base_url, recipient_verification_base_url=None,
                     notify_on_admin_notification=True, notify_on_ticket=True, notify_users=False):
        """Load configuration from service or use provided values"""
        try:
            from database.hooks.services import hook_config_service
            config = hook_config_service.get_handler_config(self.name)
            if config:
                handler_config = config.get("config", {}) if isinstance(config.get("config"), dict) else config
                self.sender = handler_config.get("sender", sender) or sender
                self.sender_name = handler_config.get("sender_name", sender_name) or sender_name
                self.receiver = handler_config.get("receiver", receiver) or receiver
                self.username = handler_config.get("username", username) or username
                self.password = handler_config.get("password", password) or password
                self.smtp_host = handler_config.get("smtp_host", smtp_host) or smtp_host
                self.smtp_port = handler_config.get("smtp_port", smtp_port) or smtp_port
                self.smtp_security = handler_config.get("smtp_security", smtp_security) or smtp_security
                self.smtp_verify_ssl = handler_config.get("smtp_verify_ssl", smtp_verify_ssl)
                self.content_encoding = handler_config.get("content_encoding", content_encoding) or content_encoding
                self.template_set = handler_config.get("template_set", template_set) or template_set
                self.templates_dir = handler_config.get("templates_dir", templates_dir) or templates_dir
                self.notify_on_verification_requested = handler_config.get("notify_on_verification_requested", notify_on_verification_requested)
                self.notify_on_password_reset_requested = handler_config.get("notify_on_password_reset_requested", notify_on_password_reset_requested)
                self.verification_base_url = handler_config.get("verification_base_url", verification_base_url) or verification_base_url
                self.recipient_verification_base_url = handler_config.get("recipient_verification_base_url", recipient_verification_base_url) or recipient_verification_base_url or "/account/verify-recipient"
                self.password_reset_base_url = handler_config.get("password_reset_base_url", password_reset_base_url) or password_reset_base_url
                self.notify_on_admin_notification = handler_config.get("notify_on_admin_notification", notify_on_admin_notification)
                self.notify_on_ticket = handler_config.get("notify_on_ticket", notify_on_ticket)
                self.notify_users = handler_config.get("notify_users", notify_users)
                return
        except Exception:
            pass
        
        # Fallback to provided values
        self.sender = sender
        self.sender_name = sender_name
        self.receiver = receiver
        self.username = username
        self.password = password
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_security = smtp_security
        self.smtp_verify_ssl = smtp_verify_ssl
        self.content_encoding = content_encoding
        self.template_set = template_set
        self.templates_dir = templates_dir
        self.notify_on_verification_requested = notify_on_verification_requested
        self.notify_on_password_reset_requested = notify_on_password_reset_requested
        self.verification_base_url = verification_base_url
        self.recipient_verification_base_url = recipient_verification_base_url or "/account/verify-recipient"
        self.password_reset_base_url = password_reset_base_url
        self.notify_on_admin_notification = notify_on_admin_notification
        self.notify_on_ticket = notify_on_ticket
        self.notify_users = notify_users
    
    @property
    def subscribed_events(self) -> List[str]:
        return [
            HookEventType.USER_VERIFICATION_REQUESTED,
            HookEventType.USER_PASSWORD_RESET_REQUESTED,
            HookEventType.ADMIN_NOTIFICATION,
            HookEventType.TICKET_CREATED,
            HookEventType.TICKET_UPDATED,
        ]
    
    def handle(self, event: HookEvent) -> None:
        """
        Handle price events and user events based on event_type.
        """
        logger.info(f"EmailHandler: Handling event {event}")
        logger.debug("Event data = %s", event.data)
        logger.debug("Event recipient = %s", event.get('recipient'))
        logger.debug("Handler default receiver = %s", self.receiver)
        # Check for test mode
        is_test_mode = event.get("_test_mode", False)
        # Template override can come from _test_template (test mode) or template_set/template_override (general override)
        # Priority: _test_template > template_set > template_override > handler default
        test_template = event.get("_test_template") or event.get("template_set") or event.get("template_override")
        test_to = event.get("_test_to")  # Override recipient for testing
        
        # Log template selection for debugging
        if test_template:
            logger.info(f"EmailHandler: Using template override '{test_template}' from event data (handler default: '{self.template_set}')")
        else:
            logger.info(f"EmailHandler: Using handler default template_set '{self.template_set}'")
        
        # For user verification events, use the user's email as recipient
        recipient_override = test_to
        
        # Universal recipient resolution: check if any event carries subscriber data
        recipient_data = event.get("recipient")
        logger.info(f"EmailHandler: Recipient data {recipient_data}")
        logger.debug("recipient_data = %s, recipient_override = %s", recipient_data, recipient_override)
        if recipient_data and not recipient_override:
            if isinstance(recipient_data, dict):
                # Handle rich recipient dict from product tracks mapping
                email_val = recipient_data.get("value")
                name_val = recipient_data.get("name")
                if email_val:
                    if name_val:
                        from email.utils import formataddr
                        recipient_override = formataddr((name_val, email_val))
                    else:
                        recipient_override = email_val
            else:
                recipient_override = recipient_data
                logger.debug("Set recipient_override from recipient_data = %s", recipient_override)
        
        # For verification/password reset, fallback to 'email' field if no 'recipient' provided
        if not recipient_override and event.event_type in [HookEventType.USER_VERIFICATION_REQUESTED, HookEventType.USER_PASSWORD_RESET_REQUESTED]:
            recipient_override = event.get("email")
            logger.debug("Set recipient_override from email field = %s", recipient_override)

        logger.debug("Final recipient_override before send = %s", recipient_override)
        logger.debug("Handler receiver (fallback) = %s", self.receiver)

        # Decide whether to send email based on event_type
        if event.event_type == HookEventType.USER_VERIFICATION_REQUESTED and self.notify_on_verification_requested:
            subject, body = self._build_verification_email(event, test_template)
        elif event.event_type == HookEventType.USER_PASSWORD_RESET_REQUESTED and self.notify_on_password_reset_requested:
            subject, body = self._build_password_reset_email(event, test_template)
        elif event.event_type == HookEventType.ADMIN_NOTIFICATION and self.notify_on_admin_notification:
            subject, body = self._build_admin_notification_email(event, test_template)
        elif event.event_type in [HookEventType.TICKET_CREATED, HookEventType.TICKET_UPDATED] and self.notify_on_ticket:
            subject, body = self._build_ticket_email(event, test_template)
        else:
            logger.info(colorize(f"EmailHandler: Skipping event_type={event.event_type} (not configured)", "red"))
            return
        
        # Add template name at bottom for test mode
        if is_test_mode and subject and body:
            template_name = test_template or self.template_set
            body = self._append_test_footer(body, template_name)
        
        if subject and body:
            # Directed events (User alerts, resets, etc.) are always sent.
            # Global events (Price updates to Admin) are only sent if notify_users is False (logic reversed in config naming)

            is_directed = bool(recipient_override) or event.event_type in [
                HookEventType.USER_VERIFICATION_REQUESTED,
                HookEventType.USER_PASSWORD_RESET_REQUESTED,
                HookEventType.ADMIN_NOTIFICATION,
                HookEventType.TICKET_CREATED,
                HookEventType.TICKET_UPDATED
            ]

            logger.debug("is_directed = %s, notify_users = %s", is_directed, self.notify_users)
            logger.debug("Will send email = %s", is_directed or not self.notify_users)

            # If it's a directed alert OR if it's a global notification that isn't suppressed
            if is_directed or not self.notify_users:
                final_recipient = recipient_override or self.receiver

                # Try async queue first, fall back to synchronous SMTP
                if self._try_enqueue(subject, body, final_recipient, event):
                    return

                # Fallback: send synchronously (Redis down or queue not configured)
                logger.debug("Calling _send_email with recipient_override = %s", recipient_override)
                success = self._send_email(
                    subject,
                    body,
                    recipient_override=recipient_override,
                    sender_override=event.data.get("mail_from"),
                    sender_name_override=event.data.get("mail_from_name"),
                    username_override=event.data.get("smtp_user"),
                    password_override=event.data.get("smtp_pass"),
                    host_override=event.data.get("smtp_host"),
                    port_override=event.data.get("smtp_port")
                )
                # Emit outcome event for traceability
                self._emit_outcome_event(
                    success=success,
                    recipient=final_recipient,
                    subject=subject,
                    event_type_str=str(event.event_type),
                    trace_id=event.trace_id,
                )
            else:
                logger.debug(f"EmailHandler: Skipping global event {event.event_type} (notify_users is True, so only directed alerts are sent)")
    
    @property
    def template_loader(self) -> EmailTemplateLoader:
        """Get the default template loader (lazy initialization)."""
        if self._template_loader is None:
            from pathlib import Path
            templates_dir = Path(self.templates_dir) if self.templates_dir else None
            self._template_loader = EmailTemplateLoader(
                template_set=self.template_set,
                templates_dir=templates_dir
            )
        return self._template_loader
    
    def _get_template_loader(self, template_override: Optional[str] = None) -> EmailTemplateLoader:
        """
        Get a template loader, optionally with a different template set.
        
        Args:
            template_override: Template set name to use (overrides handler's default template_set)
            
        Returns:
            EmailTemplateLoader instance configured with the specified template set
        """
        if template_override is None:
            return self.template_loader
        
        # Create a new loader for the override template (event-level override takes precedence)
        from pathlib import Path
        templates_dir = Path(self.templates_dir) if self.templates_dir else None
        logger.debug(f"EmailHandler: Creating template loader with override '{template_override}' (handler default: '{self.template_set}')")
        return EmailTemplateLoader(
            template_set=template_override,
            templates_dir=templates_dir
        )
    
    def _append_test_footer(self, body: str, template_name: str) -> str:
        """Append template name footer for test mode emails."""
        footer_html = f'''
<!-- TEST MODE -->
<div style="margin-top: 20px; padding: 15px; background-color: #fff3cd; border: 2px dashed #ffc107; border-radius: 8px; text-align: center;">
    <span style="color: #856404; font-size: 12px; font-weight: bold;">
        🧪 TEST MODE - Template: <code style="background: #ffeaa7; padding: 2px 6px; border-radius: 4px;">{template_name}</code>
    </span>
</div>
'''
        footer_plain = f"\n\n---\n🧪 TEST MODE - Template: {template_name}\n"
        
        # Check if HTML or plain text
        if "</body>" in body.lower():
            # Insert before closing body tag
            return body.replace("</body>", f"{footer_html}</body>").replace("</BODY>", f"{footer_html}</BODY>")
        elif "</html>" in body.lower():
            # Insert before closing html tag
            return body.replace("</html>", f"{footer_html}</html>").replace("</HTML>", f"{footer_html}</HTML>")
        else:
            # Plain text - append at end
            return body + footer_plain
    
    @staticmethod
    def _get_domain_ui() -> str:
        """Get DOMAIN_UI with the configured scheme (DOMAIN_UI_SCHEME).

        Strips any existing scheme from DOMAIN_UI and prepends DOMAIN_UI_SCHEME
        so that email links are always clickable regardless of how DOMAIN_UI was set.
        """
        from config import CONFIG
        scheme = CONFIG.get("DOMAIN_UI_SCHEME", "https").rstrip(":/")
        raw = CONFIG.get("DOMAIN_UI", "http://localhost:3000").rstrip("/")
        # Strip existing scheme if present
        for prefix in ("https://", "http://"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return f"{scheme}://{raw}"

    def _build_verification_email(self, event: HookEvent, template_override: Optional[str] = None) -> Tuple[str, str]:
        """Build email for user email verification using Jinja2 template."""
        # Build verification-specific context
        token = event.get("verification_token", "")

        # Get domain with correct scheme
        domain_ui = self._get_domain_ui()
        
        # Select path based on event source
        if event.source == "recipients_route":
            verification_path = self.recipient_verification_base_url or "/account/verify-recipient"
        else:
            verification_path = self.verification_base_url or event.get("verification_base_url", "/account/verify")
        
        # Ensure path starts with /
        if not verification_path.startswith('/'):
            verification_path = '/' + verification_path
        
        # Token is already URL-safe (uses secrets.token_urlsafe)
        # Build verification URL: DOMAIN_UI + path + ?token=xxx
        verification_url = f"{domain_ui}{verification_path}?token={token}"
        
        context = {
            "email": event.get("email", ""),
            "username": event.get("username", ""),
            "first_name": event.get("first_name", ""),
            "last_name": event.get("last_name", ""),
            "verification_token": token,
            "verification_url": verification_url,
            "expires_in_days": event.get("expires_in_days", 7),
        }
        
        loader = self._get_template_loader(template_override)
        return loader.render("email_verification", context)
    
    def _build_password_reset_email(self, event: HookEvent, template_override: Optional[str] = None) -> Tuple[str, str]:
        """Build email for password reset using Jinja2 template."""
        # Build password reset-specific context
        token = event.get("reset_token", "")

        # Get domain with correct scheme
        domain_ui = self._get_domain_ui()
        reset_path = self.password_reset_base_url or event.get("password_reset_base_url", "/account/reset-password")
        
        # Ensure path starts with /
        if not reset_path.startswith('/'):
            reset_path = '/' + reset_path
        
        # Token is already URL-safe (uses secrets.token_urlsafe)
        # Build reset URL: DOMAIN_UI + path + ?token=xxx
        reset_url = f"{domain_ui}{reset_path}?token={token}"
        
        context = {
            "email": event.get("email", ""),
            "username": event.get("username", ""),
            "first_name": event.get("first_name", ""),
            "last_name": event.get("last_name", ""),
            "reset_token": token,
            "reset_url": reset_url,
            "expires_in_hours": event.get("expires_in_hours", 24),
        }
        
        loader = self._get_template_loader(template_override)
        return loader.render("password_reset", context)
    
    def _build_admin_notification_email(self, event: HookEvent, template_override: Optional[str] = None) -> Tuple[str, str]:
        """
        Build email for admin notifications.
        Uses event data 'subject' and 'body' directly if available,
        or renders a generic admin_notification template.
        """
        subject = event.get("subject", f"System Alert: {event.source}")
        message = event.get("message", "No details provided.")
        
        # If the event provides pre-formatted body, use it
        if event.get("body"):
             return subject, event.get("body")
             
        # Otherwise use a template
        context = {
            "title": subject,
            "message": message,
            "source": event.source,
            "timestamp": event.timestamp,
            "data": event.data
        }
        
        loader = self._get_template_loader(template_override)
        # We might need to create 'admin_notification.html' or reuse a generic one
        # For now, let's assume we can use a simple generic template or just wrap in HTML
        try:
             return loader.render("admin_notification", context)
        except Exception:
             # Fallback if template doesn't exist
             return subject, f"<html><body><h2>{subject}</h2><p>{message}</p><pre>{event.data}</pre></body></html>"
             
    def _build_ticket_email(self, event: HookEvent, template_override: Optional[str] = None) -> Tuple[str, str]:
        """Build email for support ticket notifications using Jinja2 template."""
        import re
        
        ticket_id = event.get("ticket_id")
        action = event.get("action", "updated")
        message = event.get("message")
        
        # If message not directly in event, check data
        if not message:
             message = event.data.get("message")
        
        # Determine status
        status = event.data.get("status", "OPEN")
        
        # Build subject with enterprise tracking token
        original_subject = event.data.get("subject") or f"Support Ticket {action}"
        # Ensure only one ticket token in the subject
        if not re.search(r"\[Ticket\s#([a-f0-9\-]{36})\]", original_subject, re.IGNORECASE):
            subject = f"{original_subject} [Ticket #{ticket_id}]"
        else:
            subject = original_subject
            
        # Build ticket URL
        domain_ui = self._get_domain_ui()
        guest_token = event.data.get("guest_access_token")
        
        if guest_token:
            ticket_url = f"{domain_ui}/support/view/{ticket_id}?token={guest_token}"
        else:
            ticket_url = f"{domain_ui}/account/tickets/{ticket_id}"
        
        context = {
            "title": subject,
            "ticket_id": ticket_id,
            "action": action,
            "message": message,
            "status": status,
            "ticket_url": ticket_url,
            "guest_access_token": guest_token
        }
        
        loader = self._get_template_loader(template_override)
        return loader.render("ticket_notification", context)
    
    def _create_mime_text(self, content: str, subtype: str = "plain") -> MIMEText:
        """
        Create a MIMEText part with the configured encoding.
        
        Args:
            content: The text content
            subtype: "plain" or "html"
            
        Returns:
            MIMEText object with the configured encoding (quoted-printable or base64)
        """
        # Create MIMEText with the charset configured for the desired encoding
        charset = _get_charset(self.content_encoding)
        part = MIMEText(content, subtype, _charset=charset)
        return part
    
    def _try_enqueue(self, subject: str, body: str, recipient: str, event: HookEvent) -> bool:
        """
        Try to enqueue the email to the notification queue for async delivery.

        Returns True if successfully enqueued, False if should fall back to sync.
        """
        if self.notification_queue is None:
            return False

        try:
            import asyncio
            import concurrent.futures
            from domain.entities.notification_models import NotificationMessage
            from config import CONFIG

            msg = NotificationMessage(
                channel="email",
                recipient_email=recipient,
                recipient_name=event.data.get("recipient_name") if event.data else None,
                subject=subject,
                body=body,
                max_attempts=CONFIG.get("NOTIFICATION_QUEUE_MAX_RETRIES", 5),
                trace_id=event.trace_id,
                event_type=str(event.event_type),
                user_id=event.data.get("user_id", 0) if event.data else 0,
                alert_id=event.data.get("alert_id") if event.data else None,
                track_id=event.data.get("track_id") if event.data else None,
                asin=event.data.get("asin", "") if event.data else "",
                country_code=event.data.get("country_code", "") if event.data else "",
                recipient_id=event.data.get("recipient", {}).get("id") if event.data else None,
            )

            # enqueue is async — we're in a ThreadPoolExecutor worker thread,
            # so submit the coroutine to the FastAPI main event loop.
            from utils.redis_client import get_main_loop
            main_loop = get_main_loop()
            if main_loop is None or not main_loop.is_running():
                logger.warning("EmailHandler: No running event loop available for enqueue, falling back")
                return False
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self.notification_queue.enqueue(msg), main_loop
            )
            enqueued = future.result(timeout=5)

            if enqueued:
                logger.info(
                    "EmailHandler: Enqueued email to %s (subject=%s, trace=%s)",
                    recipient, subject, event.trace_id
                )
                return True
            else:
                logger.warning("EmailHandler: Enqueue returned False, falling back to sync")
                return False

        except Exception as exc:
            logger.error("EmailHandler: Enqueue failed (%s), falling back to sync SMTP", exc, exc_info=True)
            return False

    def _emit_outcome_event(self, success: bool, recipient: str, subject: str,
                            event_type_str: str, trace_id: Optional[str] = None,
                            error: Optional[str] = None) -> None:
        """Emit EMAIL_SENT or EMAIL_FAILED event for traceability."""
        try:
            outcome_type = HookEventType.EMAIL_SENT if success else HookEventType.EMAIL_FAILED
            data = {
                "recipient": recipient,
                "subject": subject,
                "event_type": event_type_str,
            }
            if error:
                data["error"] = error
            hook_manager.fire(HookEvent(
                event_type=outcome_type,
                data=data,
                source=self.name,
                trace_id=trace_id,
            ))
        except Exception as e:
            logger.error(f"EmailHandler: Failed to emit outcome event: {e}")

    def _send_email(self, subject: str, body: str, recipient_override: Optional[str] = None,
                    sender_override: Optional[str] = None, sender_name_override: Optional[str] = None,
                    username_override: Optional[str] = None, password_override: Optional[str] = None,
                    host_override: Optional[str] = None, port_override: Optional[int] = None) -> bool:
        """
        Send the email (supports both HTML and plain text).
        
        Supports three connection modes:
        - "ssl": Direct SSL connection (SMTP_SSL, typically port 465)
        - "starttls": Plain connection upgraded to TLS (typically port 587)
        - "plain": No encryption (typically port 25 or 2525)
        
        Uses quoted-printable encoding instead of base64 for better readability.
        
        Args:
            subject: Email subject
            body: Email body (HTML or plain text)
            recipient_override: Optional email to send to instead of configured receiver
            sender_override: Optional from-email address
            sender_name_override: Optional from-name
            username_override: Optional SMTP login username
            password_override: Optional SMTP login password
            host_override: Optional SMTP host override
            port_override: Optional SMTP port override
        """
        recipient = recipient_override or self.receiver
        sender_email = sender_override or self.sender
        sender_name = sender_name_override or self.sender_name
        smtp_password = password_override or self.password
        smtp_host = host_override or self.smtp_host
        smtp_port = port_override or self.smtp_port
        
        logger.debug("_send_email - recipient_override = %s", recipient_override)
        logger.debug("_send_email - self.receiver = %s", self.receiver)
        logger.debug("_send_email - final recipient = %s", recipient)
        
        logger.info(f"Sending email to {recipient} from {sender_email} (via {smtp_host}:{smtp_port}) with subject {subject}")
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            # Format From header with display name
            if sender_name:
                msg["From"] = formataddr((sender_name, sender_email))
            else:
                msg["From"] = sender_email
            msg["To"] = recipient
            
            # Detect if body is HTML
            is_html = body.strip().startswith("<!DOCTYPE") or body.strip().startswith("<html")
            
            if is_html:
                # For HTML emails, attach both plain text and HTML versions
                plain_text = f"Notice: {subject}\n\nPlease view this email in an HTML-capable email client."
                msg.attach(self._create_mime_text(plain_text, "plain"))
                msg.attach(self._create_mime_text(body, "html"))
            else:
                msg.attach(self._create_mime_text(body, "plain"))
            
            # Use username for login, fallback to envelope sender if not set
            login_username = username_override or self.username or sender_email
            
            # Create SSL context based on verify_ssl setting
            ssl_context = ssl.create_default_context()
            if not self.smtp_verify_ssl:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            
            # Connect based on security mode
            security_mode = self.smtp_security.lower() if self.smtp_security else "ssl"
            
            if security_mode == "ssl":
                # Direct SSL connection (typically port 465)
                with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl_context, timeout=30) as server:
                    if smtp_password:
                        server.login(login_username, smtp_password)
                    server.sendmail(sender_email, recipient, msg.as_string())
                    
            elif security_mode == "starttls":
                # Plain connection upgraded to TLS (typically port 587)
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    if server.has_extn('STARTTLS'):
                        server.starttls(context=ssl_context)
                        server.ehlo()
                    if smtp_password:
                        server.login(login_username, smtp_password)
                    server.sendmail(sender_email, recipient, msg.as_string())
                    
            else:  # "plain" - no encryption
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    if smtp_password:
                        server.login(login_username, smtp_password)
                    server.sendmail(sender_email, recipient, msg.as_string())
            
            logger.info(f"📧 Email sent: {subject} (via {security_mode}) from {sender_email}")
            return True
            
        except Exception as e:
            logger.error(f"📧 Failed to send email: {e}")
            return False
