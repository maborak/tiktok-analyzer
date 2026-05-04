"""
Hook Configuration Service

Provides database operations for hook configuration.
Supports both database-based and config-file-based configuration.
"""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from database.hooks.models import HookConfig

logger = logging.getLogger(__name__)


def _get_db_session():
    """Lazy import to avoid circular dependency"""
    from utils.database.database_session import get_db_session
    return get_db_session()


def _get_config():
    """Lazy import to avoid circular dependency"""
    from config import CONFIG
    return CONFIG


class HookConfigService:
    """
    Service for managing hook configurations.
    
    Supports two modes (controlled by HOOKS_USE_DB_CONFIG):
    - Database mode (true): Check database for config, disabled if not in DB
    - Config mode (false): Use HOOKS_HANDLERS from config.py
    """
    
    def _use_db_config(self) -> bool:
        """Check if database config should be used"""
        config = _get_config()
        return config.get("HOOKS_USE_DB_CONFIG", True)
    
    def _get_config_handler(self, name: str) -> Optional[Dict[str, Any]]:
        """Get handler config from CONFIG (for non-DB mode)"""
        config = _get_config()
        handlers = config.get("HOOKS_HANDLERS", {})
        return handlers.get(name)
    
    def get_all_configs(self) -> List[HookConfig]:
        """Get all hook configurations"""
        with _get_db_session() as session:
            return session.query(HookConfig).all()
    
    def get_enabled_configs(self) -> List[HookConfig]:
        """Get only enabled hook configurations"""
        with _get_db_session() as session:
            return session.query(HookConfig).filter(HookConfig.enabled == True).all()  # noqa: E712
    
    def get_config_by_name(self, name: str) -> Optional[HookConfig]:
        """Get hook configuration by handler name from database"""
        with _get_db_session() as session:
            return session.query(HookConfig).filter(HookConfig.name == name).first()
    
    def is_handler_enabled(self, name: str) -> bool:
        """
        Check if a handler is enabled.
        
        If HOOKS_USE_DB_CONFIG is true:
            - Check database for handler config
            - If NOT in database → DISABLED
            - If in database → return what DB says
        
        If HOOKS_USE_DB_CONFIG is false:
            - Check HOOKS_HANDLERS in config.py
            - If NOT in config → DISABLED
            - If in config → return what config says
        """
        if self._use_db_config():
            # Database mode
            config = self.get_config_by_name(name)
            if config is None:
                # Not in database = disabled
                logger.debug(f"Handler {name} not found in database, disabled")
                return False
            return config.enabled
        else:
            # Config file mode
            handler_config = self._get_config_handler(name)
            if handler_config is None:
                # Not in config = disabled
                logger.debug(f"Handler {name} not found in HOOKS_HANDLERS config, disabled")
                return False
            return handler_config.get("enabled", False)
    
    def get_handler_config(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get handler configuration (settings, not just enabled status).
        
        Returns dict with handler config or None if not found.
        """
        if self._use_db_config():
            # Database mode
            db_config = self.get_config_by_name(name)
            if db_config is None:
                return None
            return {
                "enabled": db_config.enabled,
                "config": db_config.config or {},
                "subscribed_events": db_config.subscribed_events or [],
            }
        else:
            # Config file mode
            return self._get_config_handler(name)
    
    def create_config(
        self,
        name: str,
        handler_type: str,
        enabled: bool = True,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        subscribed_events: Optional[List[str]] = None
    ) -> HookConfig:
        """Create a new hook configuration"""
        with _get_db_session() as session:
            hook_config = HookConfig(
                name=name,
                handler_type=handler_type,
                enabled=enabled,
                description=description,
                config=config or {},
                subscribed_events=subscribed_events or []
            )
            session.add(hook_config)
            session.commit()
            session.refresh(hook_config)
            logger.info(f"Created hook config: {name} (enabled={enabled})")
            return hook_config
    
    def update_config(
        self,
        name: str,
        enabled: Optional[bool] = None,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        subscribed_events: Optional[List[str]] = None
    ) -> Optional[HookConfig]:
        """Update an existing hook configuration"""
        with _get_db_session() as session:
            hook_config = session.query(HookConfig).filter(HookConfig.name == name).first()
            
            if not hook_config:
                return None
            
            if enabled is not None:
                hook_config.enabled = enabled
            if description is not None:
                hook_config.description = description
            if config is not None:
                hook_config.config = config
            if subscribed_events is not None:
                hook_config.subscribed_events = subscribed_events
            
            session.commit()
            session.refresh(hook_config)
            logger.info(f"Updated hook config: {name} (enabled={hook_config.enabled})")
            return hook_config
    
    def enable_handler(self, name: str) -> bool:
        """Enable a handler"""
        result = self.update_config(name, enabled=True)
        return result is not None
    
    def disable_handler(self, name: str) -> bool:
        """Disable a handler"""
        result = self.update_config(name, enabled=False)
        return result is not None
    
    def delete_config(self, name: str) -> bool:
        """Delete a hook configuration"""
        with _get_db_session() as session:
            hook_config = session.query(HookConfig).filter(HookConfig.name == name).first()
            
            if not hook_config:
                return False
            
            session.delete(hook_config)
            session.commit()
            logger.info(f"Deleted hook config: {name}")
            return True
    
    def get_or_create_config(
        self,
        name: str,
        handler_type: str,
        enabled: bool = True,
        **kwargs
    ) -> HookConfig:
        """Get existing config or create new one"""
        config = self.get_config_by_name(name)
        if config:
            return config
        return self.create_config(name=name, handler_type=handler_type, enabled=enabled, **kwargs)


# Singleton instance
hook_config_service = HookConfigService()
