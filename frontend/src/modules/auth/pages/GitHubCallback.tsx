import { useEffect, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAuth } from '@/contexts/AuthContext';
import { userRepository } from '@user/index';
import { consumeOAuthFlow } from '@/utils/oauthState';
import toast from 'react-hot-toast';
import { Loader2 } from 'lucide-react';

/**
 * Handles the GitHub OAuth redirect callback.
 *
 * GitHub redirects here with ?code=... after the user authorizes.
 * We send the code to the backend, which exchanges it for tokens.
 *
 * Verifies the CSPRNG `state` parameter we set when starting the
 * flow. Any callback whose `state` doesn't match the value we stashed
 * in sessionStorage at button-click time is rejected — this is the
 * defense against login-CSRF / account-fixation (FE-CRITICAL #2).
 */
export function GitHubCallback() {
  const searchParams = new URLSearchParams(window.location.search);
  const navigate = useNavigate();
  const { githubLogin, isAuthenticated } = useAuth();
  const processedRef = useRef(false);

  useEffect(() => {
    if (processedRef.current) return;

    const code = searchParams.get('code');
    const error = searchParams.get('error');
    const returnedState = searchParams.get('state');

    if (error) {
      toast.error(`GitHub authorization error: ${error}`);
      navigate({ to: '/login', replace: true });
      return;
    }

    if (!code) {
      toast.error('GitHub authorization code not received');
      navigate({ to: '/login', replace: true });
      return;
    }

    // State verification — refuses the callback if `state` is
    // missing, doesn't match what we stashed, or the stored flow has
    // expired. This is the single defense against an attacker
    // tricking the victim's browser into completing the flow with
    // an attacker-controlled `code`. consumeOAuthFlow clears the
    // stored value on every call, so a replay can't drain it twice.
    const flow = consumeOAuthFlow('github', returnedState);
    if (!flow) {
      toast.error('GitHub sign-in rejected — invalid state. Please try again from the sign-in page.');
      navigate({ to: '/login', replace: true });
      return;
    }

    processedRef.current = true;

    if (flow.intent === 'link') {
      userRepository.linkOAuthProvider('github', code)
        .then((res) => {
          if (res.success) {
            toast.success(res.message || 'GitHub account connected');
          } else {
            toast.error(res.message || 'Failed to connect GitHub');
          }
          navigate({ to: '/account', hash: 'sign-in-methods', replace: true });
        })
        .catch((err: any) => {
          toast.error(err.message || 'Failed to connect GitHub');
          navigate({ to: '/account', hash: 'sign-in-methods', replace: true });
        });
      return;
    }

    githubLogin(code)
      .then(() => {
        navigate({ to: '/account/billing/packages', replace: true });
      })
      .catch((err: any) => {
        toast.error(err.message || 'Failed to sign in with GitHub');
        navigate({ to: '/login', replace: true });
      });
  }, [searchParams, navigate, githubLogin]);

  // If already authenticated (link_required sets oauthLinkData but doesn't authenticate),
  // redirect to tracked products
  useEffect(() => {
    if (isAuthenticated) {
      navigate({ to: '/account/billing/packages', replace: true });
    }
  }, [isAuthenticated, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-white dark:bg-gray-900">
      <div className="text-center space-y-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        <p className="text-sm text-gray-600 dark:text-gray-400">Signing in with GitHub...</p>
      </div>
    </div>
  );
}
