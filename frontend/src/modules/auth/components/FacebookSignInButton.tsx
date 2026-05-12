import { useCallback } from 'react';
import { facebookConfig } from '@/config/env';
import { startOAuthFlow } from '@/utils/oauthState';

/**
 * Facebook Sign-In button using the full-redirect OAuth flow.
 *
 * Clicking redirects to Facebook's authorization page. After the user authorizes,
 * Facebook redirects back to /auth/facebook/callback with a ?code= parameter.
 * The FacebookCallbackPage handles the code exchange.
 *
 * Embeds a CSPRNG `state` parameter that the callback verifies against
 * sessionStorage. Defends against login-CSRF / account-fixation per
 * audit FE-CRITICAL #2.
 */
export function FacebookSignInButton() {
  const handleClick = useCallback(() => {
    const state = startOAuthFlow('facebook', { intent: 'signin' });
    const redirectUri = `${window.location.origin}/auth/facebook/callback`;
    const params = new URLSearchParams({
      client_id: facebookConfig.appId,
      redirect_uri: redirectUri,
      scope: 'email,public_profile',
      response_type: 'code',
      auth_type: 'rerequest',
      state,
    });
    window.location.href = `https://www.facebook.com/v21.0/dialog/oauth?${params.toString()}`;
  }, []);

  if (!facebookConfig.enabled) return null;

  return (
    <button
      type="button"
      onClick={handleClick}
      className="w-full flex items-center justify-center gap-3 rounded-sm border px-4 py-2.5 text-sm font-medium shadow-sm transition-all hover:opacity-80 hover:shadow focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
      style={{ borderColor: 'var(--color-border-primary)', backgroundColor: 'var(--color-surface-primary)', color: 'var(--color-text-secondary)', fontFamily: 'var(--font-mono-display)' }}
    >
      <svg className="h-5 w-5 flex-shrink-0" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"
          fill="#1877F2"
        />
      </svg>
      <span>Continue with Facebook</span>
    </button>
  );
}
