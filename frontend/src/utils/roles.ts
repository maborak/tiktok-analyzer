import type { AuthUser } from '../modules/auth';

/**
 * Canonical user roles used throughout the application.
 * - guest: unauthenticated visitor
 * - user:  authenticated regular user
 * - admin: authenticated administrator
 */
export type UserRole = 'guest' | 'user' | 'admin';

/**
 * Returns the effective role for the current session.
 *
 * This is the single source of truth for role derivation.
 * Works transparently with impersonation: when impersonating,
 * AuthContext swaps the `user` object to the impersonated user,
 * so this function will return the impersonated user's role — by design.
 */
export function getEffectiveRole(
    user: AuthUser | null,
    isAuthenticated: boolean
): UserRole {
    if (!isAuthenticated || !user) return 'guest';
    if (user.role?.toLowerCase() === 'admin') return 'admin';
    return 'user';
}

/** Convenience predicates */
export const isGuest = (role: UserRole) => role === 'guest';
export const isUser = (role: UserRole) => role === 'user' || role === 'admin';
export const isAdmin = (role: UserRole) => role === 'admin';
