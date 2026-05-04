"""
Authentication utility functions

Provides utility functions for password hashing, token generation,
and other authentication-related operations.
"""

import secrets
import hashlib
import hmac
import base64
from typing import Tuple


def generate_salt(length: int = 32) -> str:
    """
    Generate a random salt for password hashing
    
    Args:
        length: Length of the salt in bytes (default: 32)
        
    Returns:
        Base64 encoded salt string
    """
    salt_bytes = secrets.token_bytes(length)
    return base64.b64encode(salt_bytes).decode('utf-8')


def hash_password(password: str, salt: str) -> str:
    """
    Hash a password with a salt using PBKDF2
    
    Args:
        password: Plain text password
        salt: Base64 encoded salt
        
    Returns:
        Base64 encoded password hash
    """
    # Decode salt from base64
    salt_bytes = base64.b64decode(salt.encode('utf-8'))
    
    # Use PBKDF2 with SHA256 for password hashing
    hash_obj = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt_bytes,
        100000,  # 100k iterations
        32  # 32 bytes output
    )
    
    return base64.b64encode(hash_obj).decode('utf-8')


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    """
    Verify a password against a stored hash
    
    Args:
        password: Plain text password to verify
        salt: Base64 encoded salt used for the hash
        stored_hash: Base64 encoded stored password hash
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        # Generate hash for the provided password
        computed_hash = hash_password(password, salt)
        
        # Compare hashes using constant-time comparison
        return hmac.compare_digest(computed_hash, stored_hash)
    except Exception:
        # If any error occurs during verification, return False
        return False


def generate_session_token(length: int = 32) -> str:
    """
    Generate a secure session token
    
    Args:
        length: Length of the token in bytes (default: 32)
        
    Returns:
        Base64 encoded session token
    """
    token_bytes = secrets.token_bytes(length)
    return base64.b64encode(token_bytes).decode('utf-8')


def generate_api_key() -> Tuple[str, str]:
    """
    Generate an API key and its hash
    
    Returns:
        Tuple of (api_key, api_key_hash)
    """
    # Generate a 32-byte API key
    api_key_bytes = secrets.token_bytes(32)
    api_key = base64.b64encode(api_key_bytes).decode('utf-8')
    
    # Generate hash for storage
    salt = generate_salt()
    api_key_hash = hash_password(api_key, salt)
    
    return api_key, api_key_hash


def generate_reset_token(length: int = 32) -> str:
    """
    Generate a password reset token
    
    Args:
        length: Length of the token in bytes (default: 32)
        
    Returns:
        Base64 encoded reset token
    """
    token_bytes = secrets.token_bytes(length)
    return base64.b64encode(token_bytes).decode('utf-8')


def generate_urlsafe_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure URL-safe token.
    
    Uses secrets.token_urlsafe() which:
    - Is cryptographically secure (uses os.urandom internally)
    - Produces URL-safe characters only (A-Z, a-z, 0-9, '-', '_')
    - No padding characters (=) that cause URL issues
    - 256 bits of entropy with default length=32
    
    Args:
        length: Number of random bytes (default: 32 = 256 bits of entropy)
        
    Returns:
        URL-safe token string (approximately 4/3 * length characters)
    """
    return secrets.token_urlsafe(length) 