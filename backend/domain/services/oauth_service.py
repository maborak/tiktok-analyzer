"""
OAuth Service

Business logic for OAuth authentication (Google, future providers).
Follows hexagonal architecture: depends only on ports, never on adapters or database.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Protocol

import jwt as pyjwt

from domain.entities.auth_models import (
    User, UserSession, LoginRequest, LoginResponse, AuthStatus, UserRole, TokenPayload
)
from domain.entities.oauth_models import OAuthAccount
from ports.auth import AuthPort, UserManagementPort, SessionManagementPort
from ports.oauth import OAuthPort

logger = logging.getLogger(__name__)

# Sentinel value for OAuth-only users — verify_password() will never match this
OAUTH_PASSWORD_SENTINEL = "!OAUTH_ONLY"


class OAuthTokenVerifierProtocol(Protocol):
    """Protocol for OAuth token verification (Google, Apple, GitHub, etc.)."""
    def verify(self, token: str) -> Dict[str, Any]: ...


class OAuthService:
    """Multi-provider OAuth authentication service."""

    def __init__(
        self,
        oauth_port: OAuthPort,
        auth_port: AuthPort,
        user_management_port: UserManagementPort,
        session_management_port: SessionManagementPort,
        google_verifier: OAuthTokenVerifierProtocol,
        jwt_secret: str,
        jwt_algorithm: str = "HS256",
        access_token_expiry: int = 900,
        refresh_token_expiry: int = 2592000,
        credit_service=None,
    ):
        self.oauth_port = oauth_port
        self.auth_port = auth_port
        self.user_management_port = user_management_port
        self.session_management_port = session_management_port
        self._verifiers: Dict[str, OAuthTokenVerifierProtocol] = {}
        if google_verifier:
            self._verifiers["google"] = google_verifier
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.access_token_expiry = access_token_expiry
        self.refresh_token_expiry = refresh_token_expiry
        self.credit_service = credit_service

    # Keep backward-compatible convenience wrapper
    @property
    def google_verifier(self):
        return self._verifiers.get("google")

    def authenticate_with_google(
        self, id_token: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None
    ) -> LoginResponse:
        """Authenticate via Google. Delegates to the provider-agnostic core."""
        return self.authenticate_with_oauth("google", id_token, ip_address, user_agent)

    def authenticate_with_oauth(
        self, provider: str, token: str,
        ip_address: Optional[str] = None, user_agent: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> LoginResponse:
        """
        Provider-agnostic OAuth authentication.

        Flow:
        1. Verify token with the provider's verifier
        2. Look up existing OAuth link → login
        3. Email matches existing VERIFIED user → return LINK_REQUIRED (password confirmation needed)
        4. Email matches existing UNVERIFIED user → supersede unverified account, create new
        5. No email match → create new user + link + login
        """
        verifier = self._verifiers.get(provider)
        if not verifier:
            return LoginResponse(status=AuthStatus.FAILED, message=f"OAuth provider '{provider}' not configured")

        # 1. Verify the token (pass redirect_uri for Facebook code exchange)
        try:
            verify_kwargs = {"redirect_uri": redirect_uri} if redirect_uri else {}
            claims = verifier.verify(token, **verify_kwargs)
        except Exception as e:
            logger.warning("%s token verification failed: %s", provider, e)
            return LoginResponse(status=AuthStatus.FAILED, message=f"Invalid {provider} token")

        provider_user_id = claims.get("sub")
        email = claims.get("email")
        email_verified = claims.get("email_verified", False)
        name = claims.get("name", "")
        picture = claims.get("picture", "")

        if not provider_user_id or not email:
            return LoginResponse(status=AuthStatus.FAILED, message=f"Invalid {provider} token claims")

        if not email_verified:
            return LoginResponse(status=AuthStatus.FAILED, message=f"{provider.title()} email not verified")

        # 2. Look up existing OAuth account link
        oauth_account = self.oauth_port.get_oauth_account(provider, provider_user_id)

        if oauth_account:
            # Already linked → log in directly
            user = self.user_management_port.get_user_by_id(oauth_account.user_id)
            if not user:
                return LoginResponse(status=AuthStatus.FAILED, message="Linked user account not found")
            self._sync_profile(user, name)
            return self._create_session_response(user, provider, is_new_user=False, ip_address=ip_address, user_agent=user_agent)

        # 3. No existing link — check if email matches an existing user
        existing_user = self.user_management_port.get_user_by_email(email)

        if existing_user:
            if existing_user.is_verified:
                # VERIFIED user → require password confirmation before linking
                logger.info(
                    "OAuth link requires password confirmation: provider=%s, email=%s, user_id=%d",
                    provider, email, existing_user.id,
                )
                # Sign the link_data so the client cannot tamper with it
                link_token = pyjwt.encode(
                    {
                        "user_id": existing_user.id,
                        "email": email,
                        "provider": provider,
                        "provider_user_id": provider_user_id,
                        "name": name,
                        "picture": picture,
                        "purpose": "oauth_link",
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                    },
                    self.jwt_secret,
                    algorithm=self.jwt_algorithm,
                )
                return LoginResponse(
                    status=AuthStatus.LINK_REQUIRED,
                    message="An account with this email already exists. Please confirm your password to link.",
                    link_data={
                        "link_token": link_token,
                        "email": email,
                        "provider": provider,
                    },
                )
            else:
                # UNVERIFIED user → take over the account: verify it, sync profile, link OAuth
                logger.info(
                    "Taking over unverified account id=%d for OAuth user %s (%s)",
                    existing_user.id, email, provider,
                )
                first_name, last_name = self._split_name(name)
                updates: dict = {"is_verified": True, "is_active": True}
                if first_name and not existing_user.first_name:
                    updates["first_name"] = first_name
                if last_name and not existing_user.last_name:
                    updates["last_name"] = last_name
                self.user_management_port.update_user(existing_user.id, updates)
                existing_user.is_verified = True

                # Create the OAuth account link
                self.oauth_port.create_oauth_account(OAuthAccount(
                    id=0,
                    user_id=existing_user.id,
                    provider=provider,
                    provider_user_id=provider_user_id,
                    email=email,
                    name=name,
                    avatar_url=picture,
                ))

                return self._create_session_response(
                    existing_user, provider, is_new_user=False,
                    ip_address=ip_address, user_agent=user_agent,
                )

        # 4. No email match → create new user
        return self._create_new_oauth_user(
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            picture=picture,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    def confirm_link_with_password(
        self,
        link_token: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> LoginResponse:
        """
        Complete the OAuth account linking after the user confirms with their password.
        The link_token is a signed JWT containing the verified OAuth claims from the
        initial LINK_REQUIRED response — the client cannot tamper with it.
        """
        # Verify and decode the signed link token
        try:
            claims = pyjwt.decode(link_token, self.jwt_secret, algorithms=[self.jwt_algorithm])
        except pyjwt.ExpiredSignatureError:
            return LoginResponse(status=AuthStatus.FAILED, message="Link request expired. Please try again.")
        except pyjwt.InvalidTokenError:
            return LoginResponse(status=AuthStatus.FAILED, message="Invalid link request")

        if claims.get("purpose") != "oauth_link":
            return LoginResponse(status=AuthStatus.FAILED, message="Invalid link request")

        user_id = claims["user_id"]
        provider = claims["provider"]
        provider_user_id = claims["provider_user_id"]
        email = claims.get("email", "")
        name = claims.get("name", "")
        picture = claims.get("picture", "")

        # Verify the user exists
        user = self.user_management_port.get_user_by_id(user_id)
        if not user:
            return LoginResponse(status=AuthStatus.FAILED, message="User not found")

        if not user.is_active:
            return LoginResponse(status=AuthStatus.FAILED, message="Account is disabled")

        # Verify password via the auth port's standard login flow
        login_response = self.auth_port.authenticate_user(LoginRequest(
            email=user.email,
            password=password,
            ip_address=ip_address or "oauth-link",
            user_agent=user_agent or "oauth-link",
        ))

        if login_response.status != AuthStatus.SUCCESS:
            return LoginResponse(
                status=AuthStatus.FAILED,
                message="Incorrect password",
                failed_login_attempts=login_response.failed_login_attempts,
            )

        # Password confirmed — create the OAuth link
        self.oauth_port.create_oauth_account(OAuthAccount(
            id=0,
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            avatar_url=picture,
        ))

        # Sync profile from OAuth provider
        self._sync_profile(user, name)

        logger.info(
            "OAuth account linked via password confirmation: user_id=%d, provider=%s",
            user.id, provider,
        )

        return self._create_session_response(user, provider, is_new_user=False, ip_address=ip_address, user_agent=user_agent)

    def get_oauth_accounts_for_user(self, user_id: int):
        """Get all OAuth accounts linked to a user."""
        return self.oauth_port.get_oauth_accounts_by_user(user_id)

    def link_provider(
        self,
        user_id: int,
        provider: str,
        token: str,
        redirect_uri: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Link an OAuth provider to an already-authenticated user.
        Called from the My Account page (user has a valid JWT session).

        Args:
            user_id: From the JWT (never from client body)
            provider: "google", "github", "facebook"
            token: OAuth access_token or authorization code
            redirect_uri: Required for Facebook code exchange
            dry_run: If True, verify and return claims without creating the link

        Returns dict with: success, provider_email, email_mismatch, error
        """
        verifier = self._verifiers.get(provider)
        if not verifier:
            return {"success": False, "error": f"Provider '{provider}' not configured"}

        # 1. Verify the token (pass redirect_uri for Facebook code exchange)
        try:
            verify_kwargs = {"redirect_uri": redirect_uri} if redirect_uri else {}
            claims = verifier.verify(token, **verify_kwargs)
        except Exception as e:
            logger.warning("link_provider: %s token verification failed: %s", provider, e)
            return {"success": False, "error": f"Invalid {provider} token"}

        provider_user_id = claims.get("sub")
        email = claims.get("email", "")
        name = claims.get("name", "")
        picture = claims.get("picture", "")

        if not provider_user_id:
            return {"success": False, "error": "Invalid provider response"}

        # 2. Check conflict — already linked to a different user
        existing = self.oauth_port.get_oauth_account(provider, provider_user_id)
        if existing and existing.user_id != user_id:
            return {"success": False, "error": "This account is already linked to another user"}
        if existing and existing.user_id == user_id:
            return {"success": True, "provider_email": email, "email_mismatch": False, "already_linked": True}

        # 3. Check email mismatch
        user = self.user_management_port.get_user_by_id(user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        email_mismatch = bool(email and user.email and email.lower() != user.email.lower())

        if dry_run:
            return {"success": True, "provider_email": email, "email_mismatch": email_mismatch, "name": name, "picture": picture}

        # 4. Create the link
        self.oauth_port.create_oauth_account(OAuthAccount(
            id=0,
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            avatar_url=picture,
        ))

        # 5. Fire hook event
        self._fire_link_event(user_id, provider, email)

        logger.info("OAuth provider linked: user_id=%d, provider=%s, email=%s, mismatch=%s",
                     user_id, provider, email, email_mismatch)

        return {"success": True, "provider_email": email, "email_mismatch": email_mismatch}

    @staticmethod
    def _fire_link_event(user_id: int, provider: str, provider_email: str):
        try:
            from ports.hooks import hook_manager
            from ports.hooks.base_handler import HookEvent, HookEventType
            hook_manager.fire(HookEvent(
                event_type=HookEventType.OAUTH_ACCOUNT_LINKED,
                data={"user_id": user_id, "provider": provider, "provider_email": provider_email},
                source="oauth_service",
            ))
        except Exception as e:
            logger.warning("Failed to fire OAUTH_ACCOUNT_LINKED event: %s", e)

    def unlink_oauth_account(self, user_id: int, provider: str) -> bool:
        """
        Unlink an OAuth provider from a user account.
        Guard: must retain at least one auth method (password or another OAuth link).
        """
        user = self.user_management_port.get_user_by_id(user_id)
        if not user:
            return False

        oauth_accounts = self.oauth_port.get_oauth_accounts_by_user(user_id)
        has_password = getattr(user, "has_password", True)
        other_providers = [a for a in oauth_accounts if a.provider != provider]

        if not has_password and not other_providers:
            # Would lock user out — reject
            return False

        # Find the specific account to delete
        target = next((a for a in oauth_accounts if a.provider == provider), None)
        if not target:
            return False

        return self.oauth_port.delete_oauth_account(provider, target.provider_user_id)

    # --- Private helpers ---

    def _create_new_oauth_user(
        self, provider: str, provider_user_id: str,
        email: str, name: str, picture: str,
        ip_address: Optional[str], user_agent: Optional[str],
    ) -> LoginResponse:
        """Create a new user from OAuth, link the provider, grant credits."""
        first_name, last_name = self._split_name(name)
        new_user = User(
            id=0,
            username="",
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
            has_password=False,
        )
        user = self.user_management_port.create_user(new_user, OAUTH_PASSWORD_SENTINEL)
        if not user:
            return LoginResponse(status=AuthStatus.FAILED, message="Failed to create user account")

        # Grant registration credits
        if self.credit_service:
            try:
                self.credit_service.grant_registration_credits(user.id)
            except Exception as e:
                logger.warning("Failed to grant registration credits: %s", e)

        # Fire USER_REGISTERED hook
        self._fire_user_registered_hook(user, provider)

        # Create the OAuth account link
        self.oauth_port.create_oauth_account(OAuthAccount(
            id=0,
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            name=name,
            avatar_url=picture,
        ))

        return self._create_session_response(user, provider, is_new_user=True, ip_address=ip_address, user_agent=user_agent)

    def _create_session_response(
        self, user: User, provider: str, is_new_user: bool,
        ip_address: Optional[str], user_agent: Optional[str],
    ) -> LoginResponse:
        """Create session + JWT tokens and return a successful LoginResponse."""
        if not user.is_active:
            return LoginResponse(status=AuthStatus.FAILED, message="Account is disabled")

        session = self.session_management_port.create_session(
            user.id, ip_address, user_agent, remember_me=False
        )
        if not session:
            return LoginResponse(status=AuthStatus.FAILED, message="Failed to create session")

        access_token = self._generate_access_token(user, session)
        refresh_token = self._generate_refresh_token(user, session)

        self.session_management_port.update_session_refresh_token(
            session.id, self._hash_token(refresh_token)
        )

        self.user_management_port.update_user(user.id, {
            "last_login": datetime.now(timezone.utc),
            "failed_login_attempts": 0,
            "locked_until": None,
        })

        # Fire login event
        try:
            from ports.hooks import hook_manager
            from ports.hooks.base_handler import HookEvent, HookEventType
            hook_manager.fire(HookEvent(
                event_type=HookEventType.USER_LOGIN,
                data={
                    "user_id": user.id,
                    "email": user.email,
                    "auth_method": provider,
                    "is_new_user": is_new_user,
                },
                source="oauth_service",
            ))
        except Exception:
            pass

        return LoginResponse(
            status=AuthStatus.SUCCESS,
            user=user,
            session=session,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.access_token_expiry,
        )

    def _generate_access_token(self, user: User, session: UserSession) -> str:
        payload = TokenPayload(
            user_id=user.id,
            email=user.email,
            role=user.role.value,
            exp=datetime.now(timezone.utc) + timedelta(seconds=self.access_token_expiry),
            iat=datetime.now(timezone.utc),
            session_id=session.id,
        )
        return pyjwt.encode(
            {
                "user_id": payload.user_id,
                "email": payload.email,
                "role": payload.role,
                "exp": payload.exp,
                "iat": payload.iat,
                "session_id": payload.session_id,
                "type": "access",
            },
            self.jwt_secret,
            algorithm=self.jwt_algorithm,
        )

    def _generate_refresh_token(self, user: User, session: UserSession) -> str:
        payload = TokenPayload(
            user_id=user.id,
            email=user.email,
            role=user.role.value,
            exp=datetime.now(timezone.utc) + timedelta(seconds=self.refresh_token_expiry),
            iat=datetime.now(timezone.utc),
            session_id=session.id,
        )
        return pyjwt.encode(
            {
                "user_id": payload.user_id,
                "email": payload.email,
                "role": payload.role,
                "exp": payload.exp,
                "iat": payload.iat,
                "session_id": payload.session_id,
                "type": "refresh",
            },
            self.jwt_secret,
            algorithm=self.jwt_algorithm,
        )

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _sync_profile(self, user: User, name: str):
        """Sync first/last name from OAuth profile if missing on user."""
        if user.first_name and user.last_name:
            return
        first_name, last_name = self._split_name(name)
        updates: dict = {}
        if not user.first_name and first_name:
            updates["first_name"] = first_name
            user.first_name = first_name
        if not user.last_name and last_name:
            updates["last_name"] = last_name
            user.last_name = last_name
        if updates:
            self.user_management_port.update_user(user.id, updates)

    @staticmethod
    def _split_name(name: str):
        parts = name.strip().split(maxsplit=1)
        first_name = parts[0] if parts else None
        last_name = parts[1] if len(parts) > 1 else None
        return first_name, last_name

    @staticmethod
    def _fire_user_registered_hook(user: User, provider: str = "oauth"):
        try:
            from ports.hooks import hook_manager
            from ports.hooks.base_handler import HookEvent, HookEventType
            hook_manager.fire(HookEvent(
                event_type=HookEventType.USER_REGISTERED,
                data={
                    "user_id": user.id,
                    "email": user.email,
                    "username": user.username or "",
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "role": user.role.value if user.role else "user",
                    "auth_method": provider,
                },
                source="oauth_service",
            ))
        except Exception as e:
            logger.warning("Failed to fire USER_REGISTERED hook: %s", e)
