import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import type { ReactNode } from 'react';
import { authRepository } from '../modules/auth';
import type { AuthUser } from '../modules/auth';
import type { LoginResponse, LoginRequest, RegisterRequest } from '../types/api';
import { onReLoginSuccess, onReLoginDismissed } from '../api/client';
import { AuthModal, LinkAccountModal } from '@auth';

const IMPERSONATION_KEY = 'auth_is_impersonating';

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isImpersonating: boolean;
  /** True when the session expired and the re-login modal is showing. */
  isSessionExpired: boolean;
  /** True only when authenticated AND role === 'admin'. Impersonation-aware: false while impersonating a non-admin. */
  isAdmin: boolean;
  /** True when not authenticated (guest visitor). */
  isGuest: boolean;
  login: (credentials: LoginRequest) => Promise<void>;
  register: (data: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
  impersonate: (data: LoginResponse) => Promise<void>;
  stopImpersonation: () => Promise<void>;
  requestPasswordReset: (email: string, captchaToken?: string) => Promise<void>;
  resetPassword: (token: string, newPassword: string, captchaToken?: string) => Promise<void>;
  refreshAccessToken: () => Promise<void>;
  googleLogin: (idToken: string) => Promise<void>;
  githubLogin: (code: string) => Promise<void>;
  facebookLogin: (code: string, redirectUri: string) => Promise<void>;
  confirmOAuthLink: (password: string, captchaToken?: string) => Promise<void>;
  oauthLinkData: any | null;
  clearOAuthLinkData: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'auth_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const USER_KEY = 'auth_user';

const ADMIN_TOKEN_KEY = 'admin_auth_token';
const ADMIN_USER_KEY = 'admin_auth_user';

// Helper to map API user to Domain user if needed (for legacy storage migration or impersonate)
const mapApiUserToDomain = (apiUser: any): AuthUser => {
  if (apiUser.fullName) return apiUser as AuthUser; // Already domain format
  return {
    id: apiUser.id,
    username: apiUser.username,
    email: apiUser.email,
    fullName: apiUser.full_name,
    role: apiUser.role,
    isVerified: apiUser.is_verified,
  };
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isImpersonating, setIsImpersonating] = useState(false);
  const [isSessionExpired, setIsSessionExpired] = useState(false);
  const [oauthLinkData, setOauthLinkData] = useState<any | null>(() => {
    try {
      const stored = sessionStorage.getItem('oauth_link_data');
      if (stored) {
        sessionStorage.removeItem('oauth_link_data');
        return JSON.parse(stored);
      }
    } catch { /* ignore */ }
    return null;
  });
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Stable ref so the proactive timer always calls the latest version of refreshAccessToken
  const refreshAccessTokenRef = useRef<(() => Promise<void>) | undefined>(undefined);

  const scheduleProactiveRefresh = useCallback((accessToken: string) => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    try {
      const payload = JSON.parse(atob(accessToken.split('.')[1]));
      const msLeft = payload.exp * 1000 - Date.now();
      if (msLeft <= 0) return;
      const delay = Math.max(msLeft * 0.8, 30_000); // refresh at 80% of lifetime, min 30s
      console.log(`[AuthContext] Proactive refresh scheduled in ${Math.round(delay / 1000)}s`);
      refreshTimerRef.current = setTimeout(async () => {
        try { await refreshAccessTokenRef.current?.(); } catch { /* logout handled inside */ }
      }, delay);
    } catch {
      // Malformed token — skip scheduling
    }
  }, []);

  const refreshAccessToken = async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) {
      throw new Error('No refresh token available');
    }

    try {
      const response = await authRepository.refreshToken(refreshToken);

      if (response.success && response.data) {
        const tokens = response.data; // AuthTokens
        const newAccessToken = tokens.accessToken;
        const newRefreshToken = tokens.refreshToken || refreshToken;

        if (!newAccessToken) {
          throw new Error('Refresh returned empty access token');
        }

        setToken(newAccessToken);
        localStorage.setItem(TOKEN_KEY, newAccessToken);
        if (newRefreshToken) {
          localStorage.setItem(REFRESH_TOKEN_KEY, newRefreshToken);
        }
        scheduleProactiveRefresh(newAccessToken);
      } else {
        throw new Error(response.message || 'Failed to refresh token');
      }
    } catch (error: any) {
      // If refresh fails, show re-login modal instead of silently logging out
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      setToken(null);
      setIsSessionExpired(true);
      window.dispatchEvent(new CustomEvent('auth:session-expired'));
      throw error;
    }
  };

  // Keep ref in sync so the proactive timer always calls the latest closure
  refreshAccessTokenRef.current = refreshAccessToken;

  // Load auth state from localStorage on mount — scheduleProactiveRefresh is stable (useCallback [])
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);
    const storedImpersonation = localStorage.getItem(IMPERSONATION_KEY);

    console.log('[AuthContext] checking localStorage for', { token: !!storedToken, user: !!storedUser, impersonating: !!storedImpersonation });
    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser);
        const domainUser = mapApiUserToDomain(parsedUser);
        setToken(storedToken);
        setUser(domainUser);
        setIsImpersonating(storedImpersonation === 'true');
        scheduleProactiveRefresh(storedToken);
        console.log('[AuthContext] Auth state restored');

        // Refresh from backend so fields like isVerified stay current
        // (cached user may be stale after email verification or role change)
        authRepository.getCurrentUser()
          .then((resp) => {
            if (resp.success && resp.data) {
              setUser(resp.data);
              localStorage.setItem(USER_KEY, JSON.stringify(resp.data));
            }
          })
          .catch((err) => {
            console.warn('[AuthContext] Failed to refresh current user:', err);
          });
      } catch (error) {
        console.error('Error parsing stored user data:', error);
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        localStorage.removeItem(IMPERSONATION_KEY);
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        localStorage.removeItem(ADMIN_USER_KEY);
      }
    }
    setIsLoading(false);
  }, [scheduleProactiveRefresh]);

  // Listen for unauthorized events and clear auth state
  useEffect(() => {
    const handleUnauthorized = () => {
      console.log('AuthContext: Unauthorized event received, clearing auth state');
      setToken(null);
      setUser(null);
      setIsImpersonating(false);
      localStorage.removeItem(IMPERSONATION_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);
      setIsLoading(false);
    };

    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized);
    };
  }, []);

  // Listen for session-expired events — show re-login modal instead of redirecting
  useEffect(() => {
    const handleSessionExpired = () => {
      console.log('[AuthContext] Session expired — showing re-login modal');
      setIsSessionExpired(true);
    };

    window.addEventListener('auth:session-expired', handleSessionExpired);
    return () => {
      window.removeEventListener('auth:session-expired', handleSessionExpired);
    };
  }, []);

  // Called when user successfully re-logs in via the session-expired modal
  const handleReLoginSuccess = useCallback(() => {
    setIsSessionExpired(false);
    const newToken = localStorage.getItem(TOKEN_KEY);
    if (newToken) {
      onReLoginSuccess(newToken);
      scheduleProactiveRefresh(newToken);
    }
  }, [scheduleProactiveRefresh]);

  const login = async (credentials: LoginRequest) => {
    const response = await authRepository.login(credentials);

    if (response.success && response.data) {
      const { user, tokens } = response.data;
      const accessToken = tokens.accessToken;
      const refreshToken = tokens.refreshToken;

      setToken(accessToken);
      setUser(user);
      setIsImpersonating(false);
      localStorage.removeItem(IMPERSONATION_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);

      // Store in localStorage
      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      }
      if (user) {
        localStorage.setItem(USER_KEY, JSON.stringify(user));
      }
      scheduleProactiveRefresh(accessToken);
    } else {
      const errorMessage = response.message || 'Login failed. Please check your credentials.';
      console.error('Login failed:', response);
      throw new Error(errorMessage);
    }
  };

  const googleLogin = async (idToken: string) => {
    const response = await authRepository.googleLogin(idToken);

    if (response.success && response.data) {
      const { action } = response.data;

      if (action === 'link_required') {
        // Store link data for the confirmation modal — persist to sessionStorage
        // so it survives GitHub/Facebook redirect navigation
        const linkData = response.data.link_data;
        setOauthLinkData(linkData);
        try { sessionStorage.setItem('oauth_link_data', JSON.stringify(linkData)); } catch { /* ignore */ }
        return; // Don't throw — the modal will handle it
      }

      // Normal login (logged_in or account_created)
      const { user, tokens } = response.data;
      const accessToken = tokens.accessToken;
      const refreshToken = tokens.refreshToken;

      setToken(accessToken);
      setUser(user);
      setIsImpersonating(false);
      localStorage.removeItem(IMPERSONATION_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);

      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      }
      if (user) {
        localStorage.setItem(USER_KEY, JSON.stringify(user));
      }
      scheduleProactiveRefresh(accessToken);
    } else {
      throw new Error(response.message || 'Google login failed');
    }
  };

  const githubLogin = async (code: string) => {
    const response = await authRepository.githubLogin(code);

    if (response.success && response.data) {
      const { action } = response.data;

      if (action === 'link_required') {
        const linkData = response.data.link_data;
        setOauthLinkData(linkData);
        try { sessionStorage.setItem('oauth_link_data', JSON.stringify(linkData)); } catch { /* ignore */ }
        return;
      }

      const { user, tokens } = response.data;
      const accessToken = tokens.accessToken;
      const refreshToken = tokens.refreshToken;

      setToken(accessToken);
      setUser(user);
      setIsImpersonating(false);
      localStorage.removeItem(IMPERSONATION_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);

      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      }
      if (user) {
        localStorage.setItem(USER_KEY, JSON.stringify(user));
      }
      scheduleProactiveRefresh(accessToken);
    } else {
      throw new Error(response.message || 'GitHub login failed');
    }
  };

  const facebookLogin = async (code: string, redirectUri: string) => {
    const response = await authRepository.facebookLogin(code, redirectUri);

    if (response.success && response.data) {
      const { action } = response.data;

      if (action === 'link_required') {
        const linkData = response.data.link_data;
        setOauthLinkData(linkData);
        try { sessionStorage.setItem('oauth_link_data', JSON.stringify(linkData)); } catch { /* ignore */ }
        return;
      }

      const { user, tokens } = response.data;
      const accessToken = tokens.accessToken;
      const refreshToken = tokens.refreshToken;

      setToken(accessToken);
      setUser(user);
      setIsImpersonating(false);
      localStorage.removeItem(IMPERSONATION_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);

      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      }
      if (user) {
        localStorage.setItem(USER_KEY, JSON.stringify(user));
      }
      scheduleProactiveRefresh(accessToken);
    } else {
      throw new Error(response.message || 'Facebook login failed');
    }
  };

  const confirmOAuthLink = async (password: string, captchaToken?: string) => {
    if (!oauthLinkData) throw new Error('No pending OAuth link');

    const response = await authRepository.confirmOAuthLink({
      link_token: oauthLinkData.link_token,
      password,
      ...(captchaToken ? { captcha_token: captchaToken } : {}),
    });

    if (response.success && response.data) {
      const { user, tokens } = response.data;
      const accessToken = tokens.accessToken;
      const refreshToken = tokens.refreshToken;

      setToken(accessToken);
      setUser(user);
      setOauthLinkData(null);
      localStorage.setItem(TOKEN_KEY, accessToken);
      if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
      scheduleProactiveRefresh(accessToken);
    } else {
      throw new Error(response.message || 'Account linking failed');
    }
  };

  const clearOAuthLinkData = () => {
    setOauthLinkData(null);
    try { sessionStorage.removeItem('oauth_link_data'); } catch { /* ignore */ }
  };

  const impersonate = async (loginData: LoginResponse) => {
    if (loginData.tokens && loginData.tokens.access_token) {
      // Map API user to Domain user
      const domainUser = mapApiUserToDomain(loginData.user);

      // If NOT already impersonating, save the current admin session
      if (!isImpersonating && token && user) {
        localStorage.setItem(ADMIN_TOKEN_KEY, token);
        localStorage.setItem(ADMIN_USER_KEY, JSON.stringify(user));
      }

      const accessToken = loginData.tokens.access_token;
      const refreshToken = loginData.tokens.refresh_token;

      setToken(accessToken);
      setUser(domainUser);
      setIsImpersonating(true);

      // Store in localStorage
      localStorage.setItem(TOKEN_KEY, accessToken);
      localStorage.setItem(IMPERSONATION_KEY, 'true');
      if (refreshToken) {
        localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
      }
      if (domainUser) {
        localStorage.setItem(USER_KEY, JSON.stringify(domainUser));
      }
    } else {
      throw new Error('Invalid login response: missing tokens');
    }
  };

  const stopImpersonation = async () => {
    // Check if we have a stored admin session
    const adminToken = localStorage.getItem(ADMIN_TOKEN_KEY);
    const adminUserStr = localStorage.getItem(ADMIN_USER_KEY);

    if (adminToken && adminUserStr) {
      try {
        const adminUser = JSON.parse(adminUserStr); // This should be AuthUser domain object already if saved correctly
        const domainUser = mapApiUserToDomain(adminUser); // Ensure it's domain

        // Restore Admin Session
        setToken(adminToken);
        setUser(domainUser);
        setIsImpersonating(false);

        // Update LocalStorage
        localStorage.setItem(TOKEN_KEY, adminToken);
        localStorage.setItem(USER_KEY, JSON.stringify(domainUser));

        // Clean up impersonation data
        localStorage.removeItem(IMPERSONATION_KEY);
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        localStorage.removeItem(ADMIN_USER_KEY);

        return;
      } catch (e) {
        console.error("Failed to restore admin session", e);
      }
    }

    // Fallback if no backup found: logout completely
    await logout();
  };

  const register = async (data: RegisterRequest) => {
    const response = await authRepository.register(data);

    if (!response.success) {
      throw new Error(response.message || 'Registration failed');
    }
  };

  const logout = async () => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    try {
      await authRepository.logout();
    } catch (error) {
      console.error('Error during logout:', error);
    } finally {
      setToken(null);
      setUser(null);
      setIsImpersonating(false);
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(IMPERSONATION_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);
    }
  };

  const requestPasswordReset = async (email: string, captchaToken?: string) => {
    const response = await authRepository.requestPasswordReset({ email, captcha_token: captchaToken });

    if (!response.success) {
      throw new Error(response.message || 'Failed to request password reset');
    }
  };

  const resetPassword = async (token: string, newPassword: string, captchaToken?: string) => {
    const response = await authRepository.resetPassword(token, newPassword, captchaToken);

    if (!response.success) {
      throw new Error(response.message || 'Failed to reset password');
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token,
        isLoading,
        isImpersonating,
        isSessionExpired,
        isAdmin: !!token && user?.role?.toLowerCase() === 'admin',
        isGuest: !token,
        login,
        register,
        logout,
        impersonate,
        stopImpersonation,
        requestPasswordReset,
        resetPassword,
        refreshAccessToken,
        googleLogin,
        githubLogin,
        facebookLogin,
        confirmOAuthLink,
        oauthLinkData,
        clearOAuthLinkData,
      }}
    >
      {children}
      <LinkAccountModal />
      <AuthModal
        isOpen={isSessionExpired}
        onClose={undefined}
        initialView="login"
        loginOnly
        title="Session Expired"
        onSuccess={handleReLoginSuccess}
        notice="Your session has expired for security reasons. Please sign in again to continue — your work on this page has been preserved."
        footerContent={
          <button
            type="button"
            onClick={() => {
              onReLoginDismissed();
              setIsSessionExpired(false);
              logout();
            }}
            className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            Sign out and return to home
          </button>
        }
      />
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

