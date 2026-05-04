"""
CLI Session Management

Handles authentication session persistence for CLI commands.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

class CLISessionManager:
    """Manages CLI authentication sessions"""
    
    def __init__(self, session_file: str = ".cli_session.json"):
        self.session_file = Path(session_file)
        self.session_data = {}
        self._load_session()
    
    def _load_session(self):
        """Load session data from file"""
        try:
            if self.session_file.exists():
                with open(self.session_file, 'r') as f:
                    self.session_data = json.load(f)
                    
                    # Check if session is expired
                    if self._is_session_expired():
                        self.clear_session()
        except Exception:
            self.session_data = {}
    
    def _save_session(self):
        """Save session data to file"""
        try:
            with open(self.session_file, 'w') as f:
                json.dump(self.session_data, f, indent=2)
        except Exception:
            pass
    
    def _is_session_expired(self) -> bool:
        """Check if current session is expired"""
        if not self.session_data:
            return True
        
        expires_at = self.session_data.get('expires_at')
        if not expires_at:
            return True
        
        try:
            expires_dt = datetime.fromisoformat(expires_at)
            
            # Use timezone-aware datetime and convert to naive only if needed
            now_utc = datetime.now(timezone.utc)
            if expires_dt.tzinfo is None:
                now_utc = now_utc.replace(tzinfo=None)
                
            return now_utc > expires_dt
        except Exception:
            return True
    
    def set_auth_context(self, user_id: int, username: str, role: str, session_id: int):
        """Set authentication context"""
        self.session_data = {
            'user_id': user_id,
            'username': username,
            'role': role,
            'session_id': session_id,
            'authenticated_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        }
        self._save_session()
    
    def get_auth_context(self) -> Optional[Dict[str, Any]]:
        """Get current authentication context"""
        if self._is_session_expired():
            self.clear_session()
            return None
        
        return self.session_data
    
    def clear_session(self):
        """Clear authentication session"""
        self.session_data = {}
        if self.session_file.exists():
            try:
                self.session_file.unlink()
            except Exception:
                pass
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated"""
        return self.get_auth_context() is not None
    
    def is_admin(self) -> bool:
        """Check if authenticated user is admin"""
        context = self.get_auth_context()
        return context and context.get('role') == 'admin'


# Global session manager instance
session_manager = CLISessionManager() 