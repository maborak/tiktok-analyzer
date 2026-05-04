"""
PBKDF2 Password Hasher Adapter

Implements PasswordHasherPort using PBKDF2-SHA256 with 100k iterations.
Wraps the utility functions from database/auth/utils.py behind a port interface.
"""

from ports.auth import PasswordHasherPort
from database.auth.utils import (
    generate_salt as _generate_salt,
    hash_password as _hash_password,
    verify_password as _verify_password,
)


class PBKDF2PasswordHasher(PasswordHasherPort):
    """Password hasher using PBKDF2-SHA256."""

    def generate_salt(self) -> str:
        return _generate_salt()

    def hash_password(self, password: str, salt: str) -> str:
        return _hash_password(password, salt)

    def verify_password(self, password: str, salt: str, stored_hash: str) -> bool:
        return _verify_password(password, salt, stored_hash)
