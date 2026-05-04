import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, Outlet, useRouterState } from '@tanstack/react-router';
import {
  Menu,
  LogIn,
  LogOut,
  User,
  Shield,
  ChevronDown,
  AlertTriangle,
} from 'lucide-react';
import { cn } from '../utils/cn';
import { uiConfig } from '../config/env';
import { useAuth } from '../contexts/AuthContext';
import { toast } from 'react-hot-toast';
import { ProgressIndicator } from './ProgressIndicator';
import { AdminQuickLogin } from '@admin';
import { Sidebar } from './sidebar/Sidebar';

// -- User Dropdown --

interface UserDropdownProps {
  user: { username: string; role?: string } | null;
  handleLogout: () => void;
  isImpersonating?: boolean;
  handleStopImpersonation?: () => void;
}

function UserDropdown({ user, handleLogout, isImpersonating, handleStopImpersonation }: UserDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-md border text-sm font-medium transition-colors",
          isImpersonating
            ? "bg-warning-50 border-warning-200 text-warning-700 hover:bg-warning-50"
            : "hover:opacity-90"
        )}
        style={
          isImpersonating
            ? undefined
            : {
                backgroundColor: 'var(--color-surface-primary)',
                borderColor: 'var(--color-border-primary)',
                color: 'var(--color-text-secondary)',
              }
        }
      >
        <User
          className="h-4 w-4"
          style={{
            color: isImpersonating
              ? 'var(--color-warning-600)'
              : 'var(--color-text-tertiary)',
          }}
        />
        <span className="hidden sm:inline max-w-[120px] truncate">
          {user?.username || 'User'}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 transition-transform duration-200",
            isOpen && "rotate-180"
          )}
          style={{
            color: isImpersonating
              ? 'var(--color-warning-500)'
              : 'var(--color-text-tertiary)',
          }}
        />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-1.5 w-48 rounded-lg shadow-lg border py-1 z-50 animate-fadeIn"
          style={{
            backgroundColor: 'var(--color-surface-primary)',
            borderColor: 'var(--color-border-primary)',
          }}
        >
          <Link
            to="/account"
            onClick={() => setIsOpen(false)}
            className="flex items-center gap-3 px-3 py-2 text-sm transition-colors hover:opacity-90"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <User className="h-4 w-4" style={{ color: 'var(--color-text-tertiary)' }} />
            My Account
          </Link>
          <div className="h-px my-1" style={{ backgroundColor: 'var(--color-border-secondary)' }} />
          <button
            onClick={() => {
              setIsOpen(false);
              if (isImpersonating && handleStopImpersonation) {
                handleStopImpersonation();
              } else {
                handleLogout();
              }
            }}
            className="flex items-center gap-3 w-full px-3 py-2 text-sm transition-colors hover:opacity-90"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <LogOut className="h-4 w-4" style={{ color: 'var(--color-text-tertiary)' }} />
            {isImpersonating ? 'Stop Impersonation' : 'Sign Out'}
          </button>
        </div>
      )}
    </div>
  );
}

// -- Layout --

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { isAuthenticated, isLoading: authLoading, user, logout, isImpersonating, stopImpersonation, isAdmin } = useAuth();
  const navigate = useNavigate();
  const isNavigating = useRouterState({ select: (s) => s.status === 'pending' });

  const handleLogout = async () => {
    try {
      await logout();
      toast.success('Signed out successfully');
      navigate({ to: '/login' });
    } catch (error: any) {
      toast.error(error.message || 'Error signing out');
    }
  };

  const handleStopImpersonation = async () => {
    try {
      await stopImpersonation();
      navigate({ to: '/admin/users' });
      toast.success('Admin session restored');
    } catch (error) {
      console.error('Failed to stop impersonation', error);
      navigate({ to: '/login' });
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--color-surface-secondary)' }}>
        <div className="loading-spinner w-8 h-8" />
      </div>
    );
  }

  return (
    <div className="min-h-screen" style={{ backgroundColor: 'var(--color-surface-secondary)' }}>
      {/* Global Loading Bar */}
      {isNavigating && uiConfig.loaderType === 'progress_bar' && (
        <div
          className="fixed top-0 left-0 right-0 h-0.5 z-[100] overflow-hidden"
          style={{ backgroundColor: 'var(--color-border-secondary)' }}
        >
          <div className="h-full bg-primary-600 animate-loading-bar" />
        </div>
      )}

      {/* Impersonation Banner */}
      {isImpersonating && (
        <div className="bg-warning-600 text-white px-4 py-1.5 text-sm font-medium text-center relative z-[60]">
          <div className="flex items-center justify-center gap-2">
            <Shield className="h-3.5 w-3.5" />
            <span>Impersonating <strong>{user?.username || user?.email}</strong></span>
            <span className="mx-2 opacity-40">|</span>
            <button
              onClick={handleStopImpersonation}
              className="underline hover:text-warning-100 transition-colors"
            >
              Exit
            </button>
          </div>
        </div>
      )}

      {/* Mobile Sidebar */}
      <Sidebar
        isMobile
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        isAuthenticated={isAuthenticated}
        isAdmin={isAdmin}
        isImpersonating={isImpersonating}
        onLogout={handleLogout}
        onStopImpersonation={handleStopImpersonation}
      />

      {/* Desktop Sidebar */}
      <Sidebar
        isAuthenticated={isAuthenticated}
        isAdmin={isAdmin}
        isImpersonating={isImpersonating}
        onLogout={handleLogout}
        onStopImpersonation={handleStopImpersonation}
      />

      {/* Main content */}
      <div className="lg:pl-64">
        {/* Top header */}
        <header className="main-header sticky top-0 z-40">
          <div className="flex h-14 items-center gap-3 px-4 sm:px-6">
            <button
              type="button"
              className="p-1.5 rounded-md transition-colors lg:hidden hover:opacity-80"
              style={{ color: 'var(--color-text-tertiary)' }}
              onClick={() => setSidebarOpen(true)}
              aria-expanded={sidebarOpen}
            >
              <Menu className="h-5 w-5" />
            </button>

            <div
              className="h-5 w-px lg:hidden"
              style={{ backgroundColor: 'var(--color-border-primary)' }}
            />

            {/* Unverified email warning */}
            {isAuthenticated && !user?.isVerified && (
              <Link
                to="/account"
                className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-warning-50 text-warning-700 text-xs font-medium border border-warning-200 hover:bg-warning-100 transition-colors"
                title="Go to My Account to resend verification email"
              >
                <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                Verify your email to unlock features
              </Link>
            )}

            {/* Spacer */}
            <div className="flex-1" />

            {/* Right-side controls */}
            <div className="flex items-center gap-2 sm:gap-3">
              {/* Progress Indicator */}
              <div className="hidden sm:flex items-center">
                <ProgressIndicator />
              </div>

              {/* Admin Quick Login */}
              {isAdmin && !isImpersonating && <AdminQuickLogin />}

              <div
                className="hidden lg:block h-5 w-px"
                style={{ backgroundColor: 'var(--color-border-primary)' }}
              />

              {/* Auth */}
              {isAuthenticated ? (
                <UserDropdown
                  user={user}
                  handleLogout={handleLogout}
                  isImpersonating={isImpersonating}
                  handleStopImpersonation={handleStopImpersonation}
                />
              ) : (
                <Link
                  to="/login"
                  className="btn-primary"
                >
                  <LogIn className="h-4 w-4" />
                  <span className="hidden sm:inline">Sign In</span>
                </Link>
              )}
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="p-4 sm:p-6">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
