import { useEffect, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAuth } from '@/contexts/AuthContext';
import { userRepository } from '@user/index';
import { consumeOAuthFlow } from '@/utils/oauthState';
import toast from 'react-hot-toast';
import { Loader2 } from 'lucide-react';

/**
 * Handles the Facebook OAuth redirect callback.
 *
 * Facebook redirects here with ?code=... after the user authorizes.
 * We send the code + redirect_uri to the backend for token exchange.
 *
 * Verifies the CSPRNG `state` parameter we set when starting the
 * flow. Mismatch rejects the callback — defends against login-CSRF /
 * account-fixation per audit FE-CRITICAL #2.
 */
export function FacebookCallback() {
  const searchParams = new URLSearchParams(window.location.search);
  const navigate = useNavigate();
  const { facebookLogin, isAuthenticated } = useAuth();
  const processedRef = useRef(false);

  useEffect(() => {
    if (processedRef.current) return;

    const code = searchParams.get('code');
    const error = searchParams.get('error');
    const returnedState = searchParams.get('state');

    if (error) {
      if (error === 'access_denied') {
        // User clicked "Cancel" on Facebook -- not an error, just go back
        navigate({ to: '/login', replace: true });
      } else {
        const reason = searchParams.get('error_description') || error;
        toast.error(`Facebook sign-in error: ${reason}`);
        navigate({ to: '/login', replace: true });
      }
      return;
    }

    if (!code) {
      toast.error('Facebook authorization code not received');
      navigate({ to: '/login', replace: true });
      return;
    }

    // State verification — see GitHubCallback for rationale.
    const flow = consumeOAuthFlow('facebook', returnedState);
    if (!flow) {
      toast.error('Facebook sign-in rejected — invalid state. Please try again from the sign-in page.');
      navigate({ to: '/login', replace: true });
      return;
    }

    processedRef.current = true;

    const redirectUri = `${window.location.origin}/auth/facebook/callback`;

    if (flow.intent === 'link') {
      userRepository.linkOAuthProvider('facebook', code, redirectUri)
        .then((res) => {
          if (res.success) {
            toast.success(res.message || 'Facebook account connected');
          } else {
            toast.error(res.message || 'Failed to connect Facebook');
          }
          navigate({ to: '/account', hash: 'sign-in-methods', replace: true });
        })
        .catch((err: any) => {
          toast.error(err.message || 'Failed to connect Facebook');
          navigate({ to: '/account', hash: 'sign-in-methods', replace: true });
        });
      return;
    }

    facebookLogin(code, redirectUri)
      .then(() => {
        navigate({ to: '/account/billing/packages', replace: true });
      })
      .catch((err: any) => {
        toast.error(err.message || 'Failed to sign in with Facebook');
        navigate({ to: '/login', replace: true });
      });
  }, [searchParams, navigate, facebookLogin]);

  useEffect(() => {
    if (isAuthenticated) {
      navigate({ to: '/account/billing/packages', replace: true });
    }
  }, [isAuthenticated, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-900">
      <div className="text-center space-y-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        <p className="text-sm text-gray-600 dark:text-gray-400">Signing in with Facebook...</p>
      </div>
    </div>
  );
}
