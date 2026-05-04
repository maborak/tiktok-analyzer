import { useState, useRef } from 'react';
import { useNavigate, Link } from '@tanstack/react-router';
import { CheckCircle, XCircle, Loader2, Shield, ArrowRight } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { useCaptcha } from '@/hooks/useCaptcha';
import { TurnstileWidget } from '@/components/TurnstileWidget';
import type { TurnstileWidgetRef } from '@/components/TurnstileWidget';

type VerificationState = 'idle' | 'verifying' | 'success' | 'error';

export function VerifyAccount() {
  const searchParams = new URLSearchParams(window.location.search);
  const navigate = useNavigate();
  const token = searchParams.get('token');
  const { executeCaptcha, isEnabled: captchaEnabled, providerName, privacyUrl, termsUrl, useVisibleWidget, hasError: captchaError, errorMessage: captchaErrorMessage, hasPermanentError, resetError } = useCaptcha();

  const [state, setState] = useState<VerificationState>('idle');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const turnstileWidgetRef = useRef<TurnstileWidgetRef>(null);

  // Turnstile widget handlers
  const handleTurnstileSuccess = (token: string) => {
    setTurnstileToken(token);
  };

  const handleTurnstileError = () => {
    setTurnstileToken(null);

    // Check if it's a permanent configuration error - don't reset in that case
    if (turnstileWidgetRef.current?.hasPermanentError()) {
      toast.error('Security verification configuration error.');
      return; // Don't reset - it will just fail again
    }

    toast.error('Security verification failed. Please try again.');
    if (turnstileWidgetRef.current) {
      turnstileWidgetRef.current.reset();
    }
  };

  const handleTurnstileExpire = () => {
    setTurnstileToken(null);

    // Check if it's a permanent configuration error - don't reset in that case
    if (turnstileWidgetRef.current?.hasPermanentError()) {
      return; // Don't reset - it will just fail again
    }

    toast.error('Security verification expired. Please complete it again.');
    if (turnstileWidgetRef.current) {
      turnstileWidgetRef.current.reset();
    }
  };

  const handleVerify = async () => {
    if (!token) return;

    try {
      setState('verifying');

      // Get captcha token if enabled
      let captchaToken: string | null = null;
      if (captchaEnabled) {
        if (useVisibleWidget) {
          // Use visible Turnstile widget token
          if (!turnstileToken) {
            toast.error('Please complete the security verification');
            setState('idle');
            return;
          }
          captchaToken = turnstileToken;
        } else {
          // Use invisible captcha (reCAPTCHA v3)
          captchaToken = await executeCaptcha('verify');
          if (!captchaToken) {
            // Check if it's a permanent configuration error
            if (hasPermanentError()) {
              toast.error(captchaErrorMessage || 'reCAPTCHA configuration error.');
            } else {
              toast.error(captchaErrorMessage || 'CAPTCHA verification failed. Please try again.');
            }
            setState('idle');
            return;
          }
        }
      }

      const apiClient = getApiClient();
      await apiClient.verifyAccount(token, captchaToken || undefined);
      setState('success');
      toast.success('Your account has been verified!');

      setTimeout(() => {
        navigate({ to: '/login', search: { verified: 'true' } });
      }, 2000);
    } catch (error: unknown) {
      setState('error');
      const err = error as { response?: { data?: { detail?: string } } };
      const message = err.response?.data?.detail || 'Failed to verify account. The link may have expired.';
      setErrorMessage(message);
      toast.error(message);
    }
  };

  // No token provided
  if (!token) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center px-4">
        <div className="max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-error-50 flex items-center justify-center mx-auto mb-6">
            <XCircle className="w-8 h-8 text-error-600" />
          </div>
          <h1 className="page-title mb-2">Invalid Verification Link</h1>
          <p className="text-gray-600 mb-6">
            The verification link is invalid or incomplete. Check your email for the correct link.
          </p>
          <Link to="/login">
            <Button variant="secondary">
              Go to Sign In
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  // Success state
  if (state === 'success') {
    return (
      <div className="min-h-[60vh] flex items-center justify-center px-4">
        <div className="max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-success-50 flex items-center justify-center mx-auto mb-6 animate-pulse">
            <CheckCircle className="w-8 h-8 text-success-600" />
          </div>
          <h1 className="page-title mb-2">Account Verified!</h1>
          <p className="text-gray-600 mb-6">
            Your email has been verified successfully. Redirecting to sign in...
          </p>
          <div className="flex items-center justify-center gap-2 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Redirecting...
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (state === 'error') {
    return (
      <div className="min-h-[60vh] flex items-center justify-center px-4">
        <div className="max-w-md w-full text-center">
          <div className="w-16 h-16 rounded-full bg-error-50 flex items-center justify-center mx-auto mb-6">
            <XCircle className="w-8 h-8 text-error-600" />
          </div>
          <h1 className="page-title mb-2">Verification Failed</h1>
          <p className="text-gray-600 mb-6">{errorMessage}</p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <Button variant="secondary" onClick={() => setState('idle')}>
              Try Again
            </Button>
            <Link to="/login">
              <Button variant="primary">
                Go to Sign In
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Idle / Verifying state
  return (
    <div className="min-h-[60vh] flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="card text-center">
          <div className="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center mx-auto mb-6">
            <Shield className="w-8 h-8 text-primary-600" />
          </div>

          <h1 className="page-title mb-2">Verify Your Account</h1>
          <p className="text-gray-600 mb-8">
            Click the button below to verify your email and activate your account.
          </p>

          <Button
            onClick={handleVerify}
            disabled={state === 'verifying' || (useVisibleWidget && captchaEnabled && !turnstileToken)}
            className="w-full sm:w-auto px-8"
            size="lg"
          >
            {state === 'verifying' ? (
              <>
                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                Verifying...
              </>
            ) : (
              <>
                <CheckCircle className="w-5 h-5 mr-2" />
                Verify My Account
              </>
            )}
          </Button>

          {state !== 'verifying' && useVisibleWidget && captchaEnabled && !turnstileToken && (
            <p className="mt-2 text-sm text-gray-600 text-center">
              Please complete the security verification below to continue
            </p>
          )}

          {/* Turnstile Widget - Only show for visible widget */}
          {useVisibleWidget && captchaEnabled && (
            <div className="mt-4">
              <TurnstileWidget
                ref={turnstileWidgetRef}
                onSuccess={handleTurnstileSuccess}
                onError={handleTurnstileError}
                onExpire={handleTurnstileExpire}
                className="flex justify-center"
              />
            </div>
          )}

          <p className="mt-6 text-sm text-gray-500">
            Having trouble?{' '}
            <Link to="/account" className="text-primary-600 hover:text-primary-700 font-medium">
              Go to your account
            </Link>
            {' '}to resend the verification email.
          </p>

          {/* Captcha Error - Show for reCAPTCHA v3 errors */}
          {captchaEnabled && !useVisibleWidget && captchaError && (
            <div className="mt-4 p-3 border border-error-200 bg-error-50 rounded-lg">
              <p className="text-sm font-medium text-error-700 mb-1">
                Security Verification Error
              </p>
              <p className="text-xs text-error-600 mb-2">
                {captchaErrorMessage || 'reCAPTCHA verification failed'}
              </p>
              {hasPermanentError() && (
                <div className="text-xs text-gray-600 mb-2">
                  <p className="mb-1">Please verify:</p>
                  <ul className="list-disc list-inside space-y-1">
                    <li>The site key is correct in the .env file</li>
                    <li>The domain is registered in the Google reCAPTCHA console</li>
                    <li>The domain matches exactly (including localhost/192.168.0.40)</li>
                  </ul>
                </div>
              )}
              {!hasPermanentError() && (
                <button
                  onClick={() => {
                    resetError();
                    toast.success('Retrying CAPTCHA verification...');
                  }}
                  className="text-xs text-primary-600 hover:text-primary-700 underline"
                >
                  Try again
                </button>
              )}
            </div>
          )}

          {/* Captcha Notice - Only show for invisible captcha when no error */}
          {captchaEnabled && !useVisibleWidget && providerName && !captchaError && (
            <p className="mt-4 text-xs text-gray-500 text-center flex items-center justify-center gap-1">
              <Shield className="h-3 w-3" />
              Protected by {providerName}.{' '}
              {privacyUrl && (
                <>
                  <a href={privacyUrl} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
                    Privacy
                  </a>
                  {' · '}
                </>
              )}
              {termsUrl && (
                <a href={termsUrl} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">
                  Terms
                </a>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
