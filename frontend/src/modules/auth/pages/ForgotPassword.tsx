import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from 'react-hot-toast';
import { Mail, Lock, Loader, CheckCircle, Shield } from 'lucide-react';
import { TurnstileWidget } from '@/components/TurnstileWidget';
import type { TurnstileWidgetRef } from '@/components/TurnstileWidget';
import { getApiClient } from '@/services/apiClientManager';
import { useCaptcha } from '@/hooks/useCaptcha';

export function ForgotPassword() {
  const navigate = useNavigate();
  const token = new URLSearchParams(window.location.search).get('token');
  const { resetPassword, isAuthenticated } = useAuth();
  const { executeCaptcha, isEnabled: captchaEnabled, providerName, privacyUrl, termsUrl, useVisibleWidget, hasError: captchaError, errorMessage: captchaErrorMessage, hasPermanentError, resetError } = useCaptcha();
  const [email, setEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [serverMessage, setServerMessage] = useState<string | null>(null);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const turnstileWidgetRef = useRef<TurnstileWidgetRef>(null);

  // Redirect if already authenticated (unless they have a reset token)
  useEffect(() => {
    if (isAuthenticated && !token) {
      navigate({ to: '/', replace: true });
    }
  }, [isAuthenticated, token, navigate]);

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email.trim());
  };

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
    resetTurnstileWidget();
  };

  const handleTurnstileExpire = () => {
    setTurnstileToken(null);

    // Check if it's a permanent configuration error - don't reset in that case
    if (turnstileWidgetRef.current?.hasPermanentError()) {
      return; // Don't reset - it will just fail again
    }

    toast.error('Security verification expired. Please complete it again.');
    resetTurnstileWidget();
  };

  const resetTurnstileWidget = () => {
    setTurnstileToken(null);
    if (turnstileWidgetRef.current) {
      turnstileWidgetRef.current.reset();
    }
  };

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validate email
    if (!email.trim()) {
      toast.error('Please enter your email address');
      return;
    }

    if (!validateEmail(email)) {
      toast.error('Please enter a valid email address');
      return;
    }

    setIsLoading(true);

    try {
      // Get captcha token if enabled
      let captchaToken: string | null = null;
      if (captchaEnabled) {
        if (useVisibleWidget) {
          // Use visible Turnstile widget token
          console.log('[ForgotPassword] Using Turnstile visible widget');
          if (!turnstileToken) {
            toast.error('Please complete the security verification');
            setIsLoading(false);
            return;
          }
          captchaToken = turnstileToken;
        } else {
          // Use invisible captcha (reCAPTCHA v3)
          console.log('[ForgotPassword] Using reCAPTCHA v3 invisible captcha');
          captchaToken = await executeCaptcha('forgot-password');
          console.log('[ForgotPassword] reCAPTCHA v3 token received:', captchaToken ? 'yes' : 'no');
          if (!captchaToken) {
            // Check if it's a permanent configuration error
            if (hasPermanentError()) {
              toast.error(captchaErrorMessage || 'reCAPTCHA configuration error.');
            } else {
              toast.error(captchaErrorMessage || 'CAPTCHA verification failed. Please try again.');
            }
            setIsLoading(false);
            return;
          }
        }
      }

      const apiClient = getApiClient();
      const response = await apiClient.requestPasswordReset({
        email: email.trim(),
        captcha_token: captchaToken || undefined,
      });

      if (response.success) {
        setEmailSent(true);
        setTurnstileToken(null);
        // Store the server message to display in the UI
        setServerMessage(response.message || 'Password reset email sent. Please check your inbox.');
        // Also show it as a toast
        toast.success(response.message || 'Password reset email sent. Please check your inbox.');
      } else {
        throw new Error(response.message || 'Failed to send password reset email');
      }
    } catch (error: any) {
      // Extract server error message - handle different formats
      let serverMessage: string;

      if (error.response?.data?.detail) {
        const detail = error.response.data.detail;

        // If detail is a string, use it directly
        if (typeof detail === 'string') {
          serverMessage = detail;
        }
        // If detail is an array (validation errors), format them
        else if (Array.isArray(detail)) {
          serverMessage = detail.map((err: any) => {
            if (typeof err === 'string') return err;
            if (err.msg) return err.msg;
            return JSON.stringify(err);
          }).join(', ');
        }
        // If detail is an object, try to extract a message
        else if (typeof detail === 'object') {
          serverMessage = detail.message || detail.msg || JSON.stringify(detail);
        }
        else {
          serverMessage = String(detail);
        }
      } else {
        serverMessage = error.message || 'Failed to send password reset email';
      }

      // Always show the server message
      toast.error(serverMessage);

      // Reset Turnstile widget if it's a captcha-related error
      if (serverMessage.toLowerCase().includes('turnstile') ||
        serverMessage.toLowerCase().includes('captcha') ||
        serverMessage.toLowerCase().includes('verification')) {
        setTurnstileToken(null);
        resetTurnstileWidget();
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }

    if (!token) {
      toast.error('Invalid reset token');
      return;
    }

    setIsLoading(true);

    try {
      await resetPassword(token, newPassword);
      toast.success('Password reset successfully. You can now sign in.');
      // Redirect to login after a short delay
      setTimeout(() => {
        navigate({ to: '/login' });
      }, 2000);
    } catch (error: any) {
      // Extract server error message - handle different formats
      let serverMessage: string;

      if (error.response?.data?.detail) {
        const detail = error.response.data.detail;

        // If detail is a string, use it directly
        if (typeof detail === 'string') {
          serverMessage = detail;
        }
        // If detail is an array (validation errors), format them
        else if (Array.isArray(detail)) {
          serverMessage = detail.map((err: any) => {
            if (typeof err === 'string') return err;
            if (err.msg) return err.msg;
            return JSON.stringify(err);
          }).join(', ');
        }
        // If detail is an object, try to extract a message
        else if (typeof detail === 'object') {
          serverMessage = detail.message || detail.msg || JSON.stringify(detail);
        }
        else {
          serverMessage = String(detail);
        }
      } else {
        serverMessage = error.message || 'Failed to reset password.';
      }

      toast.error(serverMessage);
    } finally {
      setIsLoading(false);
    }
  };

  // If token is present, show reset password form
  if (token) {
    return (
      <div className="bg-auth-mesh grain-overlay min-h-screen relative overflow-hidden">
        <div className="auth-marker-enter text-center mt-12 mb-4">
          <div className="auth-mono-label">04 / new password</div>
        </div>
        <Link to="/login" className="auth-link auth-mono-label absolute bottom-8 left-8 z-10">← back to sign in</Link>
        <div className="relative z-[1] flex items-center justify-center min-h-[calc(100vh-120px)] px-6">
          <div className="auth-card w-full max-w-[400px] p-10">
            <div className="mb-8">
              <div className="auth-display text-2xl mb-10 lowercase">maborak</div>
              <h1 className="auth-display text-3xl">Set new password</h1>
              <div className="mt-3 h-px w-12" style={{ backgroundColor: 'var(--color-text-primary)' }} />
              <p className="auth-mono-body text-sm mt-4">Pick something memorable. Min 8 characters.</p>
            </div>
            <form className="space-y-6" onSubmit={handleResetPassword}>
              <div className="space-y-4">
                <div>
                  <label htmlFor="newPassword" className="label">
                    New Password *
                  </label>
                  <div className="mt-1 relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Lock className="h-5 w-5 text-gray-400" />
                    </div>
                    <input
                      id="newPassword"
                      name="newPassword"
                      type="password"
                      required
                      minLength={8}
                      className="input pl-10 py-2.5 placeholder-gray-500"
                      placeholder="New password (min. 8 characters)"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="confirmPassword" className="label">
                    Confirm Password *
                  </label>
                  <div className="mt-1 relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Lock className="h-5 w-5 text-gray-400" />
                    </div>
                    <input
                      id="confirmPassword"
                      name="confirmPassword"
                      type="password"
                      required
                      className="input pl-10 py-2.5 placeholder-gray-500"
                      placeholder="Confirm password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="btn-primary w-full py-3"
                >
                  {isLoading ? (
                    <>
                      <Loader className="w-5 h-5 mr-2 animate-spin" />
                      Resetting password...
                    </>
                  ) : (
                    <>
                      <Lock className="w-5 h-5 mr-2" />
                      Reset password
                    </>
                  )}
                </button>
              </div>

              <div className="text-center">
                <Link
                  to="/login"
                  className="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-500"
                >
                  ← Back to sign in
                </Link>
              </div>

              {/* Captcha Notice */}
              {captchaEnabled && providerName && (
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
            </form>
          </div>
        </div>
      </div>
    );
  }

  // Show email request form
  return (
    <div className="bg-auth-mesh grain-overlay min-h-screen relative overflow-hidden">
      <div className="auth-marker-enter text-center mt-12 mb-4">
        <div className="auth-mono-label">03 / reset</div>
      </div>
      <Link to="/login" className="auth-link auth-mono-label absolute bottom-8 left-8 z-10">← back to sign in</Link>
      <div className="relative z-[1] flex items-center justify-center min-h-[calc(100vh-120px)] px-6">
        <div className="auth-card w-full max-w-[400px] p-10">
          <div className="mb-8">
            <div className="auth-display text-2xl mb-10 lowercase">maborak</div>
            <h1 className="auth-display text-3xl">Forgot password</h1>
            <div className="mt-3 h-px w-12" style={{ backgroundColor: 'var(--color-text-primary)' }} />
            <p className="auth-mono-body text-sm mt-4">Enter your email. We'll send a reset link.</p>
          </div>

          {emailSent ? (
            <div className="bg-success-50 border border-success-200 rounded-md p-4">
              <div className="flex items-center justify-center">
                <CheckCircle className="h-5 w-5 text-success-400 mr-2" />
                <p className="text-sm text-success-700 text-center">
                  {serverMessage || 'Password reset email sent. Check your inbox and follow the instructions.'}
                </p>
              </div>
              <div className="mt-4 text-center">
                <Link
                  to="/login"
                  className="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-500"
                >
                  ← Back to sign in
                </Link>
              </div>
            </div>
          ) : (
            <form className="space-y-6" onSubmit={handleRequestReset}>
              <div>
                <label htmlFor="email" className="label">
                  Email *
                </label>
                <div className="mt-1 relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Mail className="h-5 w-5 text-gray-400" />
                  </div>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    required
                    className="input pl-10 py-2.5 placeholder-gray-500"
                    placeholder="Enter your email address"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <button
                  type="submit"
                  disabled={isLoading || !email.trim() || !validateEmail(email) || (useVisibleWidget && captchaEnabled && !turnstileToken)}
                  className="btn-primary w-full py-3.5 text-base font-semibold shadow-md hover:shadow-lg transform hover:-translate-y-0.5 disabled:transform-none"
                >
                  {isLoading ? (
                    <>
                      <Loader className="w-5 h-5 mr-2 animate-spin" />
                      Sending...
                    </>
                  ) : (
                    <>
                      <Mail className="w-5 h-5 mr-2" />
                      Send reset link
                    </>
                  )}
                </button>
                {!isLoading && email.trim() && validateEmail(email) && useVisibleWidget && captchaEnabled && !turnstileToken && (
                  <p className="mt-2 text-sm text-gray-600 text-center">
                    Please complete the security verification below to continue
                  </p>
                )}
              </div>

              {/* Turnstile Widget - Only show for visible widget */}
              {useVisibleWidget && captchaEnabled && (
                <TurnstileWidget
                  ref={turnstileWidgetRef}
                  onSuccess={handleTurnstileSuccess}
                  onError={handleTurnstileError}
                  onExpire={handleTurnstileExpire}
                  className="flex justify-center"
                />
              )}

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

            </form>
          )}
        </div>
      </div>
    </div>
  );
}

