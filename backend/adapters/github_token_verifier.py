"""
GitHub Token Verifier Adapter

Exchanges a GitHub authorization code for an access token,
then fetches the user profile and primary email.
Implements OAuthTokenVerifierProtocol.
"""

import logging
from typing import Dict, Any

import requests as http_requests

logger = logging.getLogger(__name__)

GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


class GitHubTokenVerifier:
    """Verifies GitHub OAuth2 authorization codes and returns user claims."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def verify(self, code: str) -> Dict[str, Any]:
        """
        Exchange an authorization code for an access token, then fetch user profile.

        Returns dict with keys: sub, email, email_verified, name, picture
        (matching the same shape as GoogleTokenVerifier for provider-agnostic handling).
        """
        # 1. Exchange code for access token
        token_response = http_requests.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
            },
            timeout=10,
        )

        if token_response.status_code != 200:
            raise ValueError(f"GitHub token exchange failed: {token_response.status_code}")

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            error = token_data.get("error_description", token_data.get("error", "unknown"))
            raise ValueError(f"GitHub token exchange error: {error}")

        # 2. Fetch user profile
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

        user_response = http_requests.get(GITHUB_USER_URL, headers=headers, timeout=10)
        if user_response.status_code != 200:
            raise ValueError(f"GitHub user API failed: {user_response.status_code}")

        user_data = user_response.json()

        github_id = user_data.get("id")
        if not github_id:
            raise ValueError("No 'id' field in GitHub user response")

        # 3. Resolve email — GitHub users can hide their email
        email = user_data.get("email")
        email_verified = bool(email)  # If public email is set, GitHub has verified it

        if not email:
            # Fetch primary verified email from the emails endpoint
            email, email_verified = self._fetch_primary_email(headers)

        if not email:
            raise ValueError("GitHub account has no verified email address")

        if not email_verified:
            raise ValueError("GitHub email not verified")

        # 4. Return normalized claims
        name = user_data.get("name") or user_data.get("login", "")
        picture = user_data.get("avatar_url", "")

        return {
            "sub": str(github_id),
            "email": email,
            "email_verified": email_verified,
            "name": name,
            "picture": picture,
            "login": user_data.get("login", ""),
        }

    @staticmethod
    def _fetch_primary_email(headers: Dict[str, str]) -> tuple:
        """Fetch the primary verified email from GitHub's /user/emails endpoint."""
        try:
            response = http_requests.get(GITHUB_EMAILS_URL, headers=headers, timeout=10)
            if response.status_code != 200:
                return None, False

            emails = response.json()
            if not isinstance(emails, list):
                return None, False

            # Find primary + verified email
            for entry in emails:
                if entry.get("primary") and entry.get("verified"):
                    return entry["email"], True

            # Fallback: any verified email
            for entry in emails:
                if entry.get("verified"):
                    return entry["email"], True

            return None, False
        except Exception as e:
            logger.warning("Failed to fetch GitHub emails: %s", e)
            return None, False
