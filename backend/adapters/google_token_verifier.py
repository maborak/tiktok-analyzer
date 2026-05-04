"""
Google Token Verifier Adapter

Verifies Google tokens: ID tokens via google-auth library,
access tokens via Google's userinfo API endpoint.
"""

import logging
from typing import Dict, Any

import requests as http_requests
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

logger = logging.getLogger(__name__)

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class GoogleTokenVerifier:
    """Verifies Google OAuth2 tokens (ID tokens and access tokens)."""

    def __init__(self, client_id: str):
        self.client_id = client_id

    def verify(self, token: str) -> Dict[str, Any]:
        """
        Verify a Google token and return user claims.

        Attempts access_token verification first (userinfo API), then falls back
        to ID token verification. This supports both the useGoogleLogin implicit
        flow (access_token) and the GoogleLogin credential flow (ID token).

        Returns dict with keys: sub, email, email_verified, name, picture, etc.
        """
        # Try as access_token first (shorter tokens, no dots)
        if "." not in token or len(token) < 500:
            try:
                return self._verify_access_token(token)
            except Exception as e:
                logger.debug("Access token verification failed, trying ID token: %s", e)

        # Fall back to ID token verification
        return self._verify_id_token(token)

    def _verify_id_token(self, token: str) -> Dict[str, Any]:
        """Verify a Google ID token (JWT) and return its claims."""
        idinfo = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), self.client_id,
            clock_skew_in_seconds=10
        )

        if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError(f"Invalid issuer: {idinfo.get('iss')}")

        return idinfo

    def _verify_access_token(self, token: str) -> Dict[str, Any]:
        """Verify a Google access token by calling the userinfo endpoint."""
        response = http_requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

        if response.status_code != 200:
            raise ValueError(f"Google userinfo request failed: {response.status_code}")

        userinfo = response.json()

        if not userinfo.get("sub"):
            raise ValueError("No 'sub' field in Google userinfo response")

        if not userinfo.get("email_verified", False):
            raise ValueError("Google email not verified")

        return userinfo
