import imaplib
import email
from email.message import Message
import logging
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
import re

from config import CONFIG
from domain.services.ticket_service import TicketService

logger = logging.getLogger(__name__)

class ImapPoller:
    """
    Connects to the configured support inbox via IMAP, fetches unread emails,
    parses their MIME content (extracting text, HTML, and safe attachments),
    filters out auto-responders to prevent email loops, and passes valid
    messages to the TicketService.
    """
    
    def __init__(self, ticket_service: TicketService):
        self.server = CONFIG.get("SUPPORT_INBOUND_SERVER")
        self.port = CONFIG.get("SUPPORT_INBOUND_PORT", 993)
        self.username = CONFIG.get("SUPPORT_INBOUND_USERNAME")
        self.password = CONFIG.get("SUPPORT_INBOUND_PASSWORD")
        self.use_ssl = CONFIG.get("SUPPORT_INBOUND_USE_SSL", True)
        self.ticket_service = ticket_service
        self.imap: Optional[imaplib.IMAP4] = None

        if not self.server or not self.username or not self.password:
            logger.warning("IMAP polling is not properly configured. Check PHOVEU_SUPPORT_INBOUND_* vars.")

    def connect(self) -> bool:
        """Establish connection to the IMAP server."""
        if not self.server or not self.username or not self.password:
            return False

        try:
            if self.use_ssl:
                self.imap = imaplib.IMAP4_SSL(self.server, self.port)
            else:
                self.imap = imaplib.IMAP4(self.server, self.port)
                
            self.imap.login(self.username, self.password)
            logger.info(f"Successfully connected to IMAP server {self.server} as {self.username}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            self.imap = None
            return False

    def disconnect(self):
        """Safely close the IMAP connection."""
        if self.imap:
            try:
                self.imap.close()
                self.imap.logout()
            except Exception as e:
                logger.debug(f"Error disconnecting IMAP: {e}")
            finally:
                self.imap = None

    def test_connection(self) -> Optional[Dict[str, int]]:
        """
        Tests connection and returns mailbox stats without processing.
        Returns: Dict containing 'total_messages' and 'unread_messages', or None on failure.
        """
        if not self.imap:
            if not self.connect():
                return None
                
        try:
            status, messages = self.imap.select("INBOX", readonly=True)
            if status != "OK":
                logger.error("Failed to select INBOX during test")
                return None
                
            stats = {"total_messages": 0, "unread_messages": 0}
            
            # Count total
            if messages and messages[0]:
                stats["total_messages"] = int(messages[0])
                
            # Count unread
            status, unread_response = self.imap.search(None, "UNSEEN")
            if status == "OK" and unread_response[0]:
                stats["unread_messages"] = len(unread_response[0].split())
                
            return stats
        except Exception as e:
            logger.error(f"Error testing connection: {e}")
            return None

    def poll_inbox(self) -> int:
        """
        Polls the INBOX for UNSEEN messages.
        Returns the number of messages processed.
        """
        if not self.imap:
            if not self.connect():
                return 0

        processed_count = 0
        try:
            status, messages = self.imap.select("INBOX")
            if status != "OK":
                logger.error("Failed to select INBOX")
                return 0

            # Search for unread messages
            status, response = self.imap.search(None, "UNSEEN")
            if status != "OK" or not response[0]:
                logger.debug("No unread messages found.")
                return 0

            message_ids = response[0].split()
            logger.info(f"Found {len(message_ids)} unread messages.")

            for msg_id in message_ids:
                if self._process_message(msg_id):
                    processed_count += 1
                
            return processed_count

        except Exception as e:
            logger.error(f"Error polling inbox: {e}")
            return processed_count

    def _process_message(self, msg_id: bytes) -> bool:
        """
        Fetches, parses, and processes a single message.
        Marks it as SEEN if successfully processed or if it's an auto-reply.
        """
        try:
            logger.debug("Processing message %s", msg_id)
            status, msg_data = self.imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data:
                logger.error(f"Failed to fetch message {msg_id}")
                return False

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            if self._is_auto_reply(msg):
                logger.info(f"Skipping auto-reply message {msg_id}")
                self._mark_as_seen(msg_id)
                return True

            sender = self._clean_email(msg.get("From", ""))
            subject = self._clean_header(msg.get("Subject", "No Subject"))
            to_header = msg.get("To", "")
            
            logger.debug("Raw From header: %s", msg.get('From', ''))
            logger.debug("Cleaned sender: %s", sender)
            logger.debug("To header: %s", to_header)
            
            if not sender:
                logger.warning(f"Skipping message {msg_id}: No sender found.")
                self._mark_as_seen(msg_id)
                return True

            body_text, _ = self._extract_body(msg)
            attachments = self._extract_attachments(msg)
            
            # Simple reply stripping (remove anything after "On <date>, <name> wrote:")
            clean_body = self._strip_replies(body_text)

            logger.info(f"Processing message from {sender}: {subject} with {len(attachments)} attachments")

            logger.debug("Calling ticket_service.process_inbound_email with sender=%s", sender)
            self.ticket_service.process_inbound_email(
                sender_email=sender,
                subject=subject,
                body=clean_body,
                raw_data={
                    "msg_id": msg.get("Message-ID", ""),
                    "to": to_header,
                    "attachments": attachments
                }
            )

            self._mark_as_seen(msg_id)
            return True

        except Exception as e:
            logger.error(f"Error processing message {msg_id}: {e}")
            return False

    def _mark_as_seen(self, msg_id: bytes):
        """Flags the message as read on the IMAP server."""
        try:
            self.imap.store(msg_id, '+FLAGS', '\\Seen')
        except Exception as e:
            logger.error(f"Failed to mark message {msg_id} as seen: {e}")

    def _is_auto_reply(self, msg: Message) -> bool:
        """Detects automated responses and out-of-office replies."""
        auto_submitted = str(msg.get("Auto-Submitted", "")).lower()
        if auto_submitted and auto_submitted != "no":
            return True
            
        x_autoreply = str(msg.get("X-Autoreply", "")).lower()
        if x_autoreply == "yes":
            return True
            
        precedence = str(msg.get("Precedence", "")).lower()
        if precedence in ["bulk", "auto_reply", "list"]:
            return True

        return False

    def _extract_body(self, msg: Message) -> Tuple[str, str]:
        """Iterates through the MIME structure to extract plain text and HTML bodies."""
        plain_text = ""
        html_text = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                        
                    charset = part.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")

                    if content_type == "text/plain":
                        plain_text += decoded
                    elif content_type == "text/html":
                        html_text += decoded
                except Exception as e:
                    logger.debug(f"Failed to decode MIME part {content_type}: {e}")
        else:
            try:
                charset = msg.get_content_charset() or "utf-8"
                payload = msg.get_payload(decode=True)
                if payload:
                    plain_text = payload.decode(charset, errors="replace")
            except Exception as e:
                logger.debug(f"Failed to decode single MIME msg: {e}")

        # If no plain text, heavily strip HTML
        if not plain_text and html_text:
            plain_text = re.sub(r'<[^>]+>', ' ', html_text)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()

        return plain_text, html_text

    def _extract_attachments(self, msg: Message) -> List[Dict[str, Any]]:
        """
        Extracts safe attachments from the MIME structure.
        Enforces a 5MB size limit and screens file extensions.
        """
        attachments = []
        MAX_SIZE_BYTES = 5 * 1024 * 1024
        ALLOWED_EXTENSIONS = {
            ".jpg", ".jpeg", ".png", ".gif", ".webp",
            ".pdf", ".txt", ".csv",
            ".doc", ".docx", ".xls", ".xlsx"
        }

        if not msg.is_multipart():
            return attachments

        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition"))
            if "attachment" not in content_disposition:
                continue

            filename = part.get_filename()
            if not filename:
                continue

            # Decode RFC2047 encoded filenames (e.g., =?utf-8?q?file_name.pdf?=)
            filename = self._clean_header(filename)

            # Security: check extension
            ext = ""
            if "." in filename:
                ext = filename[filename.rfind("."):].lower()
            
            if ext not in ALLOWED_EXTENSIONS:
                logger.warning(f"Skipping attachment {filename}: Extension {ext} not allowed.")
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue
                
            if len(payload) > MAX_SIZE_BYTES:
                logger.warning(f"Skipping attachment {filename}: Exceeds 5MB limit.")
                continue

            attachments.append({
                "filename": filename,
                "content_type": part.get_content_type(),
                "content": payload
            })

        return attachments

    def _strip_replies(self, text: str) -> str:
        """Attempts to remove historical email quotes from replies."""
        # Split on common reply patterns
        patterns = [
            r"(?m)^On\s+.*wrote:$",        # English Gmail
            r"(?m)^El\s+.*escribió:$",     # Spanish Gmail
            r"(?m)^From:.*$",              # Outlook / Exchange standard
            r"(?m)^>.*$",                  # Blockquotes
            r"(?m)-+\s*Original Message\s*-+"
        ]
        
        lines = text.split('\n')
        clean_lines = []
        
        for line in lines:
            is_quote = False
            for p in patterns:
                if re.search(p, line):
                    is_quote = True
                    break
            
            if is_quote:
                break # Stop reading as soon as we hit the quote boundary
                
            clean_lines.append(line)
            
        return '\n'.join(clean_lines).strip()

    def _clean_email(self, parse_string: str) -> str:
        """Extracts just the email address from 'Name <email@domain.com>'"""
        match = re.search(r'[\w\.-]+@[\w\.-]+', parse_string)
        return match.group(0).lower() if match else parse_string.strip()

    def _clean_header(self, raw_header: str) -> str:
        """Decodes MIME encoded headers if necessary."""
        from email.header import decode_header
        decoded_parts = decode_header(raw_header)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                result.append(part)
        return ''.join(result)
