"""
Database Package

Centralized import of all database models to ensure SQLAlchemy metadata registration.
This solves the schema validation issue by importing all model files automatically.
"""

# Core
from .core.base import Base
from .core.connection import create_database_engine, get_session_maker, create_tables

# Auth
from .auth.models import User, UserSession, ApiKey, PasswordReset, EmailVerification
from .auth.oauth_models import OAuthAccount
from .auth.rbac_models import Permission, role_permissions, user_permissions
from .auth.rbac_service import RBACService

# Hooks
from .hooks.models import HookConfig
from .hooks.event_config_models import EventConfigModel

# Config
from .config.app_config_models import AppConfigModel

# Shared
from .shared.enums import UserRole

# Tickets
from .tickets.models import (
    TicketCategoryModel, TicketModel, TicketMessageModel, TicketTagModel,
    TicketTagAssociationModel, TicketAttachmentModel, TicketInboundConfigModel,
    LiveChatSessionModel, LiveChatMessageModel, LiveChatAttachmentModel
)

# Billing
from .billing.models import (
    CreditPackageModel, PaymentTransactionModel, CreditLedgerModel, InvoiceModel
)

# Recipients
from .recipients.models import Recipient, RecipientVerification, RecipientType

__all__ = [
    # Core
    'Base', 'create_database_engine', 'get_session_maker', 'create_tables',

    # Auth
    'User', 'UserSession', 'ApiKey', 'PasswordReset', 'EmailVerification', 'OAuthAccount',
    'Permission', 'role_permissions', 'user_permissions', 'RBACService',

    # Hooks
    'HookConfig', 'EventConfigModel',

    # Config
    'AppConfigModel',

    # Shared
    'UserRole',

    # Tickets
    'TicketCategoryModel', 'TicketModel', 'TicketMessageModel', 'TicketTagModel',
    'TicketTagAssociationModel', 'TicketAttachmentModel', 'TicketInboundConfigModel',
    'LiveChatSessionModel', 'LiveChatMessageModel', 'LiveChatAttachmentModel',

    # Billing
    'CreditPackageModel', 'PaymentTransactionModel', 'CreditLedgerModel', 'InvoiceModel',

    # Recipients
    'Recipient', 'RecipientVerification', 'RecipientType',
]
