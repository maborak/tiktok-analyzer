"""
Email Template Loader

Jinja2-based email template loading and rendering with support for
multiple template sets (themes).

Each template set contains:
- {event_type}.html - Body template (e.g., price_changed.html)
- {event_type}_subject.html - Subject template (e.g., price_changed_subject.html)
- base.html - Optional base template for inheritance
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from config import CONFIG

logger = logging.getLogger(__name__)


class EmailTemplateLoader:
    """
    Loads and renders email templates using Jinja2.
    
    Supports multiple template sets (e.g., 'default', 'minimal', 'corporate')
    with automatic fallback to 'default' if a template is not found.
    
    Each template set can have its own subject style (formal, emoji, minimal)
    defined in {event_type}_subject.html files.
    
    Usage:
        loader = EmailTemplateLoader(template_set="default")
        subject, body = loader.render("price_changed", context)
    """
    
    def __init__(self, template_set: str = "default", templates_dir: Optional[Path] = None):
        """
        Initialize the template loader.
        
        Args:
            template_set: Name of the template set to use (e.g., 'default', 'minimal')
            templates_dir: Custom templates directory (defaults to project's templates/email/)
        """
        self.template_set = template_set
        
        # Determine templates directory
        if templates_dir:
            self.templates_dir = Path(templates_dir)
        else:
            # Default to project root's templates/email/
            project_root = Path(__file__).parent.parent.parent
            self.templates_dir = project_root / "templates" / "email"
        
        # Initialize Jinja2 environment
        self._env: Optional[Environment] = None
        self._initialized = False
    
    def _ensure_initialized(self) -> None:
        """Lazily initialize the Jinja2 environment."""
        if self._initialized:
            return
        
        # Check if templates directory exists
        template_set_dir = self.templates_dir / self.template_set
        default_dir = self.templates_dir / "default"
        
        # Use template set directory if it exists, otherwise fall back to default
        if template_set_dir.exists():
            search_paths = [template_set_dir]
            # Add default as fallback if it's a different directory
            if self.template_set != "default" and default_dir.exists():
                search_paths.append(default_dir)
        elif default_dir.exists():
            logger.warning("Template set '%s' not found, using 'default'", self.template_set)
            search_paths = [default_dir]
            self.template_set = "default"
        else:
            logger.warning("No templates found at %s, using inline templates", self.templates_dir)
            self._initialized = True
            return
        
        # Create Jinja2 environment
        self._env = Environment(
            loader=FileSystemLoader(search_paths),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        
        # Add custom filters
        self._env.filters['fmt'] = self._fmt_filter
        self._env.filters['currency'] = self._currency_filter
        
        self._initialized = True
        logger.info("Email templates loaded from: %s", search_paths[0])
    
    def _fmt_filter(self, value: Any) -> str:
        """Format a price value with 2 decimal places."""
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.2f}"
        except (ValueError, TypeError):
            return "N/A"
    
    def _currency_filter(self, value: Any, symbol: str = "$") -> str:
        """Format a value as currency."""
        formatted = self._fmt_filter(value)
        if formatted == "N/A":
            return formatted
        return f"{symbol}{formatted}"
    
    def get_subject(self, event_type: str, context: Dict[str, Any]) -> str:
        """
        Get the subject line for an event type.
        
        Loads subject from {event_type}_subject.html template file.
        Falls back to default subjects if template not found.
        
        Args:
            event_type: Event type (e.g., 'price_changed', 'price_new')
            context: Template context variables
            
        Returns:
            Rendered subject line (stripped of whitespace)
        """
        self._ensure_initialized()
        
        subject_template_name = f"{event_type}_subject.html"
        
        if self._env:
            try:
                template = self._env.get_template(subject_template_name)
                # Render and strip whitespace (subject should be single line)
                subject = template.render(**context).strip()
                # Remove any newlines and collapse whitespace
                subject = ' '.join(subject.split())
                return subject
            except TemplateNotFound:
                logger.debug("Subject template '%s' not found, using default", subject_template_name)
            except (TypeError, ValueError) as e:
                logger.error("Failed to render subject template '%s': %s", subject_template_name, e)
        
        # Default subjects fallback
        defaults: dict[str, str] = {}
        template_str = defaults.get(event_type, f"{CONFIG['APP_NAME']} Alert: {event_type}")
        
        # Render default template string
        if self._env:
            try:
                template = self._env.from_string(template_str)
                return template.render(**context)
            except (TemplateNotFound, TypeError, ValueError) as e:
                logger.error("Failed to render default subject: %s", e)
        
        return f"{CONFIG['APP_NAME']} Alert: {context.get('asin', 'Unknown')}"
    
    def render(self, event_type: str, context: Dict[str, Any]) -> Tuple[str, str]:
        """
        Render an email template.
        
        Args:
            event_type: Event type (e.g., 'price_changed', 'price_new')
            context: Template context variables
            
        Returns:
            Tuple of (subject, body)
        """
        self._ensure_initialized()
        
        # Get subject
        subject = self.get_subject(event_type, context)
        
        # Render body template
        template_name = f"{event_type}.html"
        
        if self._env:
            try:
                template = self._env.get_template(template_name)
                body = template.render(**context)
                return subject, body
            except TemplateNotFound:
                logger.warning("Template '%s' not found, using fallback", template_name)
            except (TypeError, ValueError) as e:
                logger.error("Failed to render template '%s': %s", template_name, e)
        
        # Fallback to inline template
        body = self._get_fallback_template(event_type, context)
        return subject, body
    
    def _get_fallback_template(self, event_type: str, context: Dict[str, Any]) -> str:  # noqa: ARG002
        """Generate a simple fallback template when Jinja2 templates are not available.
        
        Args:
            event_type: Event type (reserved for future use)
            context: Template context variables
        """
        _ = event_type  # Reserved for future event-specific fallback templates
        asin = context.get('asin', 'Unknown')
        title = context.get('title', 'Unknown Product')
        url = context.get('url', '')
        total_price = self._fmt_filter(context.get('total_price'))
        country_code = context.get('country_code', '')
        
        return f"""
Product: {title}
ASIN: {asin}
Country: {country_code}
Price: ${total_price}

URL: {url}

---
{CONFIG["APP_NAME"]}
        """.strip()
    
    def has_template(self, event_type: str) -> bool:
        """Check if a template exists for the given event type."""
        self._ensure_initialized()
        
        if not self._env:
            return False
        
        template_name = f"{event_type}.html"
        try:
            self._env.get_template(template_name)
            return True
        except TemplateNotFound:
            return False
    
    @property
    def available_templates(self) -> list:
        """List all available body template files (excludes subject templates)."""
        self._ensure_initialized()
        
        templates = []
        template_dir = self.templates_dir / self.template_set
        
        if template_dir.exists():
            for f in template_dir.glob("*.html"):
                # Exclude subject templates and base template
                if not f.stem.endswith('_subject') and f.stem != 'base':
                    templates.append(f.stem)
        
        return sorted(templates)
    
    @property
    def available_subject_templates(self) -> list:
        """List all available subject template files."""
        self._ensure_initialized()
        
        templates = []
        template_dir = self.templates_dir / self.template_set
        
        if template_dir.exists():
            for f in template_dir.glob("*_subject.html"):
                # Extract event type from filename (e.g., 'price_changed' from 'price_changed_subject.html')
                templates.append(f.stem.replace('_subject', ''))
        
        return sorted(templates)


# Singleton instance for convenience
_default_loader: Optional[EmailTemplateLoader] = None


def get_email_template_loader(template_set: str = "default") -> EmailTemplateLoader:
    """Get or create an email template loader."""
    global _default_loader
    
    if _default_loader is None or _default_loader.template_set != template_set:
        _default_loader = EmailTemplateLoader(template_set=template_set)
    
    return _default_loader
