import { useEffect, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAuth } from '@/contexts/AuthContext';
import { userRepository } from '@user/index';
import toast from 'react-hot-toast';
import { Loader2 } from 'lucide-react';

/**
 * Handles the GitHub OAuth redirect callback.
 *
 * GitHub redirects here with ?code=... after the user authorizes.
 * We send the code to the backend, which exchanges it for tokens.
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

    processedRef.current = true;

    // Check if this is a link-from-account-settings flow
    const linkIntent = sessionStorage.getItem('oauth_link_intent');
    if (linkIntent) {
      sessionStorage.removeItem('oauth_link_intent');
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
