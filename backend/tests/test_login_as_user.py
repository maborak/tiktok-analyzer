
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

from domain.entities.auth_models import (
    User, UserSession, UserRole, AuthStatus, LoginResponse, 
    AuthContext, LoginRequest
)
from domain.services.auth_service import AuthService
from routes.admin.users import login_as_user_endpoint, login_as_user_by_email_endpoint

# --- Fixtures ---

@pytest.fixture
def mock_user_management_port():
    return MagicMock()

@pytest.fixture
def mock_session_management_port():
    return MagicMock()

@pytest.fixture
def mock_auth_service(mock_user_management_port, mock_session_management_port):
    return AuthService(
        auth_port=MagicMock(),
        user_management_port=mock_user_management_port,
        session_management_port=mock_session_management_port,
        api_key_management_port=MagicMock(),
        authorization_port=MagicMock(),
        password_hasher=MagicMock(),
        jwt_secret="test_secret",
        jwt_algorithm="HS256"
    )

@pytest.fixture
def admin_user():
    return User(
        id=1,
        username="admin",
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        role_id=1,
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
        max_products=100,
        api_rate_limit=1000,
        created_at=datetime.now(timezone.utc)
    )

@pytest.fixture
def target_user():
    return User(
        id=2,
        username="target",
        email="target@example.com",
        first_name="Target",
        last_name="User",
        role_id=2,
        role=UserRole.USER,
        is_active=True,
        is_verified=True,
        max_products=100,
        api_rate_limit=1000,
        created_at=datetime.now(timezone.utc)
    )

@pytest.fixture
def mock_session():
    return UserSession(
        id="session-uuid",
        user_id=2,
        session_token="token",
        refresh_token="refresh",
        ip_address="127.0.0.1",
        user_agent="Test",
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        created_at=datetime.now(timezone.utc)
    )

# --- Tests ---

class TestLoginAsUserSelection:
    
    def test_login_as_user_success(self, mock_auth_service, mock_session_management_port, mock_user_management_port, target_user, mock_session):
        """Test successful impersonation logic in service"""
        # Setup mocks
        mock_user_management_port.get_user_by_id.return_value = target_user
        mock_session_management_port.create_session.return_value = mock_session
        
        # Call method
        response = mock_auth_service.login_as_user(target_user.id)
        
        # Assertions
        assert response.status == AuthStatus.SUCCESS
        assert response.user == target_user
        assert response.session == mock_session
        assert response.access_token is not None
        assert response.refresh_token is not None
        
        # Verify calls
        mock_user_management_port.get_user_by_id.assert_called_with(target_user.id)
        mock_session_management_port.create_session.assert_called_with(target_user.id)

    def test_login_as_user_not_found(self, mock_auth_service, mock_user_management_port):
        """Test impersonation valid logic for non-existent user"""
        mock_user_management_port.get_user_by_id.return_value = None
        
        response = mock_auth_service.login_as_user(999)
        
        assert response.status == AuthStatus.FAILED
        assert response.message == "Target user not found"

    def test_login_as_user_session_fail(self, mock_auth_service, mock_user_management_port, mock_session_management_port, target_user):
        """Test impersonation fail on session creation"""
        mock_user_management_port.get_user_by_id.return_value = target_user
        mock_session_management_port.create_session.return_value = None
        
        response = mock_auth_service.login_as_user(target_user.id)
        
        assert response.status == AuthStatus.FAILED
        assert response.message == "Failed to create session"

    
    def test_login_as_user_by_email_success(self, mock_auth_service, mock_session_management_port, mock_user_management_port, target_user, mock_session):
        """Test successful impersonation by email logic"""
        mock_user_management_port.get_user_by_email.return_value = target_user
        mock_user_management_port.get_user_by_id.return_value = target_user # needed by inner call
        mock_session_management_port.create_session.return_value = mock_session
        
        response = mock_auth_service.login_as_user_by_email(target_user.email)
        
        assert response.status == AuthStatus.SUCCESS
        assert response.user == target_user
        mock_user_management_port.get_user_by_email.assert_called_with(target_user.email)

    def test_login_as_user_by_email_not_found(self, mock_auth_service, mock_user_management_port):
        """Test impersonation fail when email not found"""
        mock_user_management_port.get_user_by_email.return_value = None
        
        response = mock_auth_service.login_as_user_by_email("unknown@example.com")
        
        assert response.status == AuthStatus.FAILED
        assert response.message == "Target user not found"


# --- Integration / Route Tests (Mocked Dependencies) ---

@pytest.mark.asyncio
async def test_endpoint_login_as_user_success(admin_user, target_user):
    """Test the ID-based login endpoint"""
    mock_context = AuthContext(
        user=admin_user,
        permissions=["admin:write"],
        session=None
    )
    
    mock_service = MagicMock(spec=AuthService)
    mock_service.login_as_user.return_value = LoginResponse(
        status=AuthStatus.SUCCESS,
        user=target_user,
        session=MagicMock(),
        access_token="fake_access_token",
        refresh_token="fake_refresh_token",
        expires_in=3600
    )
    
    response = await login_as_user_endpoint(
        user_id=target_user.id,
        current_user=mock_context,
        auth_service=mock_service
    )
    
    assert response["access_token"] == "fake_access_token"
    mock_service.login_as_user.assert_called_with(target_user.id)

@pytest.mark.asyncio
async def test_endpoint_login_as_user_by_email_success(admin_user, target_user):
    """Test the email-based login endpoint"""
    mock_context = AuthContext(
        user=admin_user,
        permissions=["admin:write"],
        session=None
    )
    
    mock_service = MagicMock(spec=AuthService)
    mock_service.login_as_user_by_email.return_value = LoginResponse(
        status=AuthStatus.SUCCESS,
        user=target_user,
        session=MagicMock(),
        access_token="fake_access_token",
        refresh_token="fake_refresh_token",
        expires_in=3600
    )
    
    from routes.admin.users import LoginAsRequest
    request = LoginAsRequest(email=target_user.email)
    
    response = await login_as_user_by_email_endpoint(
        request=request,
        current_user=mock_context,
        auth_service=mock_service
    )
    
    assert response["access_token"] == "fake_access_token"
    mock_service.login_as_user_by_email.assert_called_with(target_user.email)

@pytest.mark.asyncio
async def test_endpoint_prevent_self_impersonation(admin_user):
    """Test prevention of self-impersonation"""
    mock_context = AuthContext(
        user=admin_user, # ID 1
        permissions=["admin:write"],
        session=None
    )
    
    mock_service = MagicMock(spec=AuthService)
    
    # Expect 400 Bad Request
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        await login_as_user_endpoint(
            user_id=admin_user.id, # Same as current user
            current_user=mock_context,
            auth_service=mock_service
        )
    
    assert excinfo.value.status_code == 400
    assert "not need to impersonate yourself" in excinfo.value.detail
