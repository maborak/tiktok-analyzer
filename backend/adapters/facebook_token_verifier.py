"""
Facebook Token Verifier Adapter

Exchanges a Facebook authorization code for an access token,
then fetches the user profile via the Graph API.
Implements OAuthTokenVerifierProtocol.
"""

import logging
from typing import Dict, Any

import requests as http_requests

logger = logging.getLogger(__name__)

FB_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
FB_ME_URL = "https://graph.facebook.com/v21.0/me"


class FacebookTokenVerifier:
    """Verifies Facebook OAuth2 authorization codes and returns user claims."""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret

    def verify(self, code: str, redirect_uri: str = "") -> Dict[str, Any]:
        """
        Exchange an authorization code for an access token, then fetch user profile.

        Args:
            code: Facebook authorization code
            redirect_uri: The exact redirect_uri used in the authorization request (passed per-call, not stored on instance)

        Returns dict with keys: sub, email, email_verified, name, picture
        """
        # 1. Exchange code for access token
        token_response = http_requests.get(
            FB_TOKEN_URL,
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=10,
        )

        if token_response.status_code != 200:
            error_body = token_response.text[:500]
            logger.error("Facebook token exchange failed: status=%d, body=%s, redirect_uri=%s",
                         token_response.status_code, error_body, redirect_uri)
            raise ValueError(f"Facebook token exchange failed: {token_response.status_code} — {error_body}")

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            error = token_data.get("error", {}).get("message", "unknown")
            raise ValueError(f"Facebook token exchange error: {error}")

        # 2. Fetch user profile with email
        me_response = http_requests.get(
            FB_ME_URL,
            params={
                "fields": "id,name,email,picture.type(large)",
                "access_token": access_token,
            },
            timeout=10,
        )

        if me_response.status_code != 200:
            raise ValueError(f"Facebook Graph API failed: {me_response.status_code}")

        user_data = me_response.json()

        fb_id = user_data.get("id")
        if not fb_id:
            raise ValueError("No 'id' field in Facebook user response")

        email = user_data.get("email")
        if not email:
            raise ValueError(
                "Facebook account has no email. "
                "Ensure the 'email' permission is granted and the account has a confirmed email."
            )

        # Facebook only returns email if it's confirmed
        email_verified = True

        name = user_data.get("name", "")
        picture = ""
        picture_data = user_data.get("picture", {}).get("data", {})
        if picture_data and not picture_data.get("is_silhouette"):
            picture = picture_data.get("url", "")

        return {
            "sub": str(fb_id),
            "email": email,
            "email_verified": email_verified,
            "name": name,
            "picture": picture,
        }
