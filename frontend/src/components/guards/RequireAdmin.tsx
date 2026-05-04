import { useNavigate } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useEffect } from 'react';

/**
 * RequireAdmin — wraps routes that require administrator role.
 *
 * - While auth state is loading: shows a neutral spinner.
 * - Unauthenticated or non-admin: redirects to '/' with NO error message and NO toast.
 *   A silent redirect to home gives no hint that the attempted path exists or is admin-only.
 * - Admin: renders children.
 *
 * Note on impersonation: when an admin impersonates a user, AuthContext replaces
 * the `user` object with the impersonated user's data. This guard will correctly
 * deny admin-only routes while impersonating (correct behavior — act as the user).
 */
export function RequireAdmin({ children }: { children: ReactNode }) {
    const { isAuthenticated, isAdmin, isLoading, isSessionExpired, user } = useAuth();
    const navigate = useNavigate();

    useEffect(() => {
        if (!isLoading && !isSessionExpired && (!isAuthenticated || !isAdmin)) {
            console.warn(`[RequireAdmin] Access denied. Redirecting to /. auth=${isAuthenticated}, admin=${isAdmin}, role=${user?.role}`);
            navigate({ to: '/', replace: true });
        }
    }, [isLoading, isSessionExpired, isAuthenticated, isAdmin, navigate, user?.role]);

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

    if (!isAuthenticated || !isAdmin) {
        return null;
    }

    return <>{children}</>;
}
