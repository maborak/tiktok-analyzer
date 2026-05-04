import { useNavigate } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { useEffect } from 'react';

/**
 * RequireGuest — wraps routes that should only be accessible to unauthenticated users.
 * e.g. /login, /register, /forgot-password
 *
 * - While auth state is loading: shows a neutral spinner.
 * - Authenticated: redirects to '/account' (already logged in, no need to see login page).
 * - Unauthenticated: renders children.
 */
export function RequireGuest({ children }: { children: ReactNode }) {
    const { isAuthenticated, isLoading } = useAuth();
    const navigate = useNavigate();

    useEffect(() => {
        if (!isLoading && isAuthenticated) {
            navigate({ to: '/account', replace: true });
        }
    }, [isLoading, isAuthenticated, navigate]);

    if (isLoading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gray-50">
                <div className="w-8 h-8 border-4 border-gray-200 border-t-gray-600 rounded-full animate-spin" />
            </div>
        );
    }

    if (isAuthenticated) {
        return null;
    }

    return <>{children}</>;
}
