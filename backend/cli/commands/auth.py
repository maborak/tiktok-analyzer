"""
Authentication Commands - CLI authentication and user management
"""

import click
from domain.entities.auth_models import LoginRequest, UserRole, AuthContext, AuthStatus
from cli.session import session_manager


@click.group()
def auth():
    """Authentication and user management commands"""
    pass


@auth.command()
@click.option('--username', '-u', prompt=True, help='Admin username')
@click.option('--password', '-p', prompt=True, hide_input=True, help='Admin password')
@click.pass_context
def login(ctx, username, password):
    """
    Authenticate as admin user
    
    Authenticate with admin credentials to enable superuser operations.
    """
    services = ctx.obj['services']
    verbose = ctx.obj.get('verbose', False)
    
    click.echo("🔐 Admin Authentication")
    click.echo("=" * 40)
    
    try:
        # Create login request
        request = LoginRequest(
            email=username,
            password=password,
            remember_me=True
        )
        
        # Authenticate user
        response = services.auth_service.authenticate_user(request)
        
        if verbose:
            click.echo(f"🔍 Debug: Response status: {response.status}")
            click.echo(f"🔍 Debug: Response message: {response.message}")
            click.echo(f"🔍 Debug: User: {response.user}")
            click.echo(f"🔍 Debug: Session: {response.session}")
        
        if response.status == AuthStatus.SUCCESS and response.user:
            # Check if user is admin
            if response.user.role == UserRole.ADMIN:
                # Store in session manager
                session_manager.set_auth_context(
                    user_id=response.user.id,
                    username=response.user.username,
                    role=response.user.role.value,
                    session_id=response.session.id if response.session else 0
                )
                
                click.echo(f"✅ Authenticated as admin: {response.user.username}")
                click.echo(f"👤 User ID: {response.user.id}")
                click.echo(f"📧 Email: {response.user.email}")
                click.echo(f"🔑 Role: {response.user.role.value}")
                
                if verbose:
                    click.echo(f"🆔 Session ID: {response.session.id if response.session else 'N/A'}")
                
                return 0
            else:
                click.echo(f"❌ User {username} is not an admin", err=True)
                return 1
        else:
            click.echo(f"❌ Authentication failed: {response.message}", err=True)
            return 1
            
    except Exception as e:
        click.echo(f"❌ Authentication error: {e}", err=True)
        if verbose:
            import traceback
            click.echo(f"🔍 Debug traceback: {traceback.format_exc()}")
        return 1


@auth.command()
@click.pass_context
def logout(ctx):
    """
    Logout current user
    
    Clear the current authentication session.
    """
    if session_manager.is_authenticated():
        username = session_manager.get_auth_context()['username']
        session_manager.clear_session()
        click.echo(f"👋 Logged out: {username}")
    else:
        click.echo("ℹ️  No active session")


@auth.command()
@click.pass_context
def status(ctx):
    """
    Show authentication status
    
    Display current authentication status and user information.
    """
    if session_manager.is_authenticated():
        context = session_manager.get_auth_context()
        click.echo("🔐 Authentication Status")
        click.echo("=" * 30)
        click.echo(f"✅ Authenticated: Yes")
        click.echo(f"👤 Username: {context['username']}")
        click.echo(f"🔑 Role: {context['role']}")
        click.echo(f"🆔 User ID: {context['user_id']}")
        click.echo(f"🆔 Session ID: {context['session_id']}")
        click.echo(f"⏰ Authenticated: {context['authenticated_at']}")
        click.echo(f"⏰ Expires: {context['expires_at']}")
    else:
        click.echo("❌ Not authenticated")
        click.echo("💡 Use 'auth login' to authenticate")


@auth.command('resend-email')
@click.option('--user', '-u', required=True, help='User email address')
@click.option('--force', '-f', is_flag=True, help='Force send even if already verified')
@click.option('--theme', '-t', help='Email template theme to use (e.g., default, tech-stripe, enterprise-dark)')
@click.pass_context
def resend_email(ctx, user, force, theme):
    """
    Resend verification email to a user
    
    Generates a new verification token and sends a verification email
    to the specified user's email address.
    
    Example:
        python cli.py auth resend-email --user=user@example.com
        python cli.py auth resend-email --user=user@example.com --force
        python cli.py auth resend-email --user=user@example.com --theme=tech-stripe
    """
    services = ctx.obj['services']
    verbose = ctx.obj.get('verbose', False)
    
    click.echo("📧 Resend Verification Email")
    click.echo("=" * 40)
    
    if theme:
        click.echo(f"🎨 Using template theme: {theme}")
    
    try:
        # Look up user by email
        user_obj = services.auth_adapter.get_user_by_email(user)
        
        if not user_obj:
            click.echo(f"❌ User not found: {user}", err=True)
            return 1
        
        if verbose:
            click.echo(f"🔍 Debug: User found - id={user_obj.id}, email={user_obj.email}")
            click.echo(f"🔍 Debug: is_verified={user_obj.is_verified}")
            if theme:
                click.echo(f"🔍 Debug: Template theme override: {theme}")
        
        # Check if already verified (unless --force)
        if user_obj.is_verified and not force:
            click.echo(f"⚠️  User {user} is already verified", err=True)
            click.echo(f"💡 Use --force to send anyway", err=True)
            return 1
        
        if user_obj.is_verified and force:
            click.echo(f"⚠️  User is already verified, sending anyway (--force)")
            # Unverify the user first so the token can be created
            services.auth_adapter.update_user(user_obj.id, {"is_verified": False})
            if verbose:
                click.echo(f"🔍 Debug: User is_verified set to False")
        
        # Request verification email with optional template override
        success = services.auth_service.request_verification_email(user, template_set=theme)
        
        if success:
            click.echo(f"✅ Verification email sent successfully")
            click.echo(f"📧 Email: {user}")
            click.echo(f"👤 Username: {user_obj.username}")
            click.echo(f"🆔 User ID: {user_obj.id}")
            if theme:
                click.echo(f"🎨 Template theme: {theme}")
            click.echo(f"💡 The user should check their inbox for the verification link")
            return 0
        else:
            click.echo(f"❌ Failed to send verification email", err=True)
            click.echo(f"💡 Check if email handler is configured and enabled", err=True)
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        if verbose:
            import traceback
            click.echo(f"🔍 Debug traceback: {traceback.format_exc()}")
        return 1


@auth.command('resend-password-reset')
@click.option('--user', '-u', required=True, help='User email address')
@click.option('--theme', '-t', help='Email template theme to use (e.g., default, tech-stripe, enterprise-dark)')
@click.pass_context
def resend_password_reset(ctx, user, theme):
    """
    Resend password reset email to a user
    
    Generates a new password reset token and sends a password reset email
    to the specified user's email address.
    
    Example:
        python cli.py auth resend-password-reset --user=user@example.com
        python cli.py auth resend-password-reset --user=user@example.com --theme=tech-stripe
        python cli.py auth resend-password-reset --user=user@example.com --theme=enterprise-dark
    """
    from domain.entities.auth_models import PasswordResetRequest
    
    services = ctx.obj['services']
    verbose = ctx.obj.get('verbose', False)
    
    click.echo("🔑 Resend Password Reset Email")
    click.echo("=" * 40)
    
    if theme:
        click.echo(f"🎨 Using template theme: {theme}")
    
    try:
        # Look up user by email
        user_obj = services.auth_adapter.get_user_by_email(user)
        
        if not user_obj:
            click.echo(f"❌ User not found: {user}", err=True)
            return 1
        
        if verbose:
            click.echo(f"🔍 Debug: User found - id={user_obj.id}, email={user_obj.email}")
            click.echo(f"🔍 Debug: username={user_obj.username}")
            if theme:
                click.echo(f"🔍 Debug: Template theme override: {theme}")
        
        # Request password reset email with optional template override
        request = PasswordResetRequest(email=user)
        response = services.auth_service.request_password_reset(request, template_set=theme)
        
        if response.status == AuthStatus.SUCCESS:
            click.echo(f"✅ Password reset email sent successfully")
            click.echo(f"📧 Email: {user}")
            click.echo(f"👤 Username: {user_obj.username}")
            click.echo(f"🆔 User ID: {user_obj.id}")
            if theme:
                click.echo(f"🎨 Template theme: {theme}")
            click.echo(f"💡 The user should check their inbox for the password reset link")
            click.echo(f"⏰ The reset link will expire in 24 hours")
            return 0
        else:
            click.echo(f"❌ Failed to send password reset email", err=True)
            click.echo(f"💡 Check if email handler is configured and enabled", err=True)
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        if verbose:
            import traceback
            click.echo(f"🔍 Debug traceback: {traceback.format_exc()}")
        return 1


@auth.command()
@click.option('--username', '-u', prompt=True, help='Username')
@click.option('--email', '-e', prompt=True, help='Email')
@click.option('--password', '-p', prompt=True, hide_input=True, help='Password')
@click.option('--first-name', '-f', help='First name')
@click.option('--last-name', '-l', help='Last name')
@click.option('--role', '-r', type=click.Choice(['user', 'admin', 'moderator']), default='user', help='User role')
@click.pass_context
def create_user(ctx, username, email, password, first_name, last_name, role):
    """
    Create a new user (Admin only, or first user bootstrap)
    
    Create a new user account with specified role and permissions.
    If no users exist in the system, allows bootstrapping the first admin user.
    """
    from domain.entities.auth_models import User, UserRole
    
    services = ctx.obj['services']
    verbose = ctx.obj.get('verbose', False)
    
    # Check if this is a bootstrap scenario (no admin users exist)
    try:
        # Get list of all users to check if any admin exists
        all_users = services.auth_adapter.get_all_users()
        admin_users = [u for u in all_users if u.role == UserRole.ADMIN] if all_users else []
        is_bootstrap = len(admin_users) == 0
        
        if verbose:
            click.echo(f"🔍 Debug: Found {len(all_users) if all_users else 0} total users")
            click.echo(f"🔍 Debug: Found {len(admin_users)} admin users")
            click.echo(f"🔍 Debug: Bootstrap mode: {is_bootstrap}")
    except Exception as e:
        # If we can't check users, assume bootstrap scenario
        if verbose:
            click.echo(f"🔍 Debug: Error checking users, assuming bootstrap: {e}")
        is_bootstrap = True
    
    # Check authentication (unless bootstrapping)
    if not is_bootstrap:
        if not session_manager.is_authenticated():
            click.echo("❌ Authentication required", err=True)
            click.echo("💡 Use 'auth login' to authenticate as admin", err=True)
            return 1
        
        if not session_manager.is_admin():
            click.echo("❌ Admin privileges required", err=True)
            click.echo("💡 Use 'auth login' to authenticate as admin", err=True)
            return 1
    else:
        click.echo("🚀 Bootstrap mode: No admin users found, allowing admin user creation")
        # For bootstrap, suggest admin role but allow other roles too
        if role != 'admin':
            click.echo("⚠️  Note: You're creating a non-admin user in bootstrap mode")
            click.echo("💡 Consider creating an admin user first for system management")
    
    click.echo("👤 Creating New User")
    click.echo("=" * 30)
    
    try:
        # Check for existing username
        existing_user = services.auth_adapter.get_user_by_username(username)
        if existing_user:
            click.echo(f"❌ Username '{username}' already exists", err=True)
            return 1
        
        # Check for existing email
        existing_email = services.auth_adapter.get_user_by_email(email)
        if existing_email:
            click.echo(f"❌ Email '{email}' already exists", err=True)
            return 1
        
        # Convert role string to enum
        user_role = UserRole(role)
        
        # Create user domain object with specified role
        user = User(
            id=0,  # Will be set by database
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=user_role,
            is_active=True,
            is_verified=False
        )
        
        # Create user directly with role
        created_user = services.auth_adapter.create_user(user, password)
        
        if created_user:
            click.echo(f"✅ User created successfully")
            click.echo(f"👤 Username: {username}")
            click.echo(f"📧 Email: {email}")
            click.echo(f"🔑 Role: {created_user.role.value}")
            click.echo(f"🆔 User ID: {created_user.id}")
            
            if is_bootstrap and created_user.role == UserRole.ADMIN:
                click.echo(f"🚀 Bootstrap complete! First admin user created.")
                click.echo(f"💡 You can now use 'auth login' to authenticate as admin.")
            
            return 0
        else:
            click.echo(f"❌ Failed to create user", err=True)
            return 1
            
    except Exception as e:
        click.echo(f"❌ Error creating user: {e}", err=True)
        return 1

@auth.command('cleanup-unverified')
@click.option('--days', default=30, help="Delete unverified users older than N days (default: 30)")
@click.option('--yes', is_flag=True, help="Skip confirmation")
@click.pass_context
def cleanup_unverified(ctx, days, yes):
    """Clean up unverified users older than N days"""
    services = ctx.obj['services']
    verbose = ctx.obj.get('verbose', False)
    
    click.echo("🧹 Cleanup Unverified Users")
    click.echo("=" * 40)
    
    if not yes:
        if not click.confirm(f"⚠️  Are you sure you want to delete unverified users older than {days} days?", default=False):
            click.echo("❌ Operation cancelled")
            return
            
    try:
        count = services.auth_adapter.cleanup_unverified_users(days)
        
        click.echo(f"✅ Cleaned up {count} unverified users.")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        if verbose:
            import traceback
            click.echo(f"🔍 Debug traceback: {traceback.format_exc()}")
        return 1 