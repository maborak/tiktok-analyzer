"""
Email Delivery Adapter — SMTP implementation of NotificationDeliveryPort.

Extracted from EmailHandler._send_email(). Used by the NotificationConsumer
to deliver emails asynchronously via asyncio.to_thread().

Supports three connection modes: ssl, starttls, plain.
"""

import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from config import CONFIG
from domain.entities.notification_models import NotificationMessage
from ports.notification_delivery import (
    NotificationDeliveryPort,
    TransientDeliveryError,
    PermanentDeliveryError,
)

logger = logging.getLogger(__name__)


class EmailDeliveryAdapter(NotificationDeliveryPort):
    """Delivers email notifications via SMTP."""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_security: Optional[str] = None,
        smtp_verify_ssl: bool = True,
        sender_email: Optional[str] = None,
        sender_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        _email = CONFIG.get("HOOKS_HANDLERS", {}).get("EmailHandler", {})
        self.smtp_host = smtp_host or _email.get("smtp_host", "localhost")
        self.smtp_port = smtp_port or int(_email.get("smtp_port", 465))
        self.smtp_security = smtp_security or _email.get("smtp_security", "ssl")
        self.smtp_verify_ssl = smtp_verify_ssl if smtp_verify_ssl is not None else _email.get("smtp_verify_ssl", True)
        self.sender_email = sender_email or _email.get("sender", "")
        self.sender_name = sender_name or _email.get("sender_name", "")
        self.username = username or _email.get("username", "")
        self.password = password or _email.get("password", "")

    async def deliver(self, msg: NotificationMessage) -> bool:
        """Deliver an email via SMTP using asyncio.to_thread for non-blocking I/O."""
        try:
            success = await asyncio.to_thread(
                self._send_smtp,
                recipient=msg.recipient_email,
                subject=msg.subject,
                body=msg.body,
            )
            if success:
                return True
            raise TransientDeliveryError("SMTP send returned False")
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
            raise PermanentDeliveryError(f"SMTP rejected: {exc}") from exc
        except smtplib.SMTPResponseException as exc:
            if 500 <= exc.smtp_code < 600:
                raise PermanentDeliveryError(f"SMTP 5xx: {exc}") from exc
            raise TransientDeliveryError(f"SMTP {exc.smtp_code}: {exc}") from exc
        except (smtplib.SMTPException, ConnectionError, TimeoutError, OSError) as exc:
            raise TransientDeliveryError(f"SMTP connection error: {exc}") from exc

    def _send_smtp(self, recipient: str, subject: str, body: str) -> bool:
        """Synchronous SMTP send (runs in thread via asyncio.to_thread)."""
        mime_msg = MIMEMultipart("alternative")
        mime_msg["Subject"] = subject
        if self.sender_name:
            mime_msg["From"] = formataddr((self.sender_name, self.sender_email))
        else:
            mime_msg["From"] = self.sender_email
        mime_msg["To"] = recipient

        # Detect HTML vs plain text
        is_html = body.strip().startswith("<!DOCTYPE") or body.strip().startswith("<html")
        if is_html:
            plain_text = f"Notice: {subject}\n\nPlease view this email in an HTML-capable email client."
            mime_msg.attach(MIMEText(plain_text, "plain", "utf-8"))
            mime_msg.attach(MIMEText(body, "html", "utf-8"))
        else:
            mime_msg.attach(MIMEText(body, "plain", "utf-8"))

        login_username = self.username or self.sender_email

        ssl_context = ssl.create_default_context()
        if not self.smtp_verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        security_mode = (self.smtp_security or "ssl").lower()

        if security_mode == "ssl":
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ssl_context, timeout=30) as server:
                if self.password:
                    server.login(login_username, self.password)
                server.sendmail(self.sender_email, recipient, mime_msg.as_string())

        elif security_mode == "starttls":
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.ehlo()
                if server.has_extn("STARTTLS"):
                    server.starttls(context=ssl_context)
                    server.ehlo()
                if self.password:
                    server.login(login_username, self.password)
                server.sendmail(self.sender_email, recipient, mime_msg.as_string())

        else:  # plain
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.ehlo()
                if self.password:
                    server.login(login_username, self.password)
                server.sendmail(self.sender_email, recipient, mime_msg.as_string())

        logger.info("Email delivered to %s | subject=%r", recipient, subject)
        return True
