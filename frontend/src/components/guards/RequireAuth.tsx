import { useNavigate } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useEffect } from 'react';

/**
 * RequireAuth — wraps routes that require any authenticated user.
 *
 * - While auth state is loading (localStorage rehydration): shows a neutral spinner.
 * - Session expired: keeps rendering the page (AuthModal overlay is shown by AuthContext).
 * - Unauthenticated (no prior session): redirects to '/' — NOT /login — to prevent path enumeration.
 * - Authenticated: renders children.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
    const { isAuthenticated, isLoading, isSessionExpired, user } = useAuth();
    const navigate = useNavigate();

    useEffect(() => {
        if (!isLoading && !isSessionExpired && !isAuthenticated) {
            console.warn(`[RequireAuth] Access denied. Redirecting to /. auth=${isAuthenticated}, role=${user?.role}`);
            navigate({ to: '/', replace: true });
        }
    }, [isLoading, isSessionExpired, isAuthenticated, navigate, user?.role]);

    if (isLoading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gray-50">
                <div className="w-8 h-8 border-4 border-gray-200 border-t-gray-600 rounded-full animate-spin" />
            </div>
        );
    }

    // Session expired: keep the page visible behind the re-login modal
    if (isSessionExpired) {
        return <>{children}</>;
    }

    if (!isAuthenticated) {
        return null;
    }

    return <>{children}</>;
}
