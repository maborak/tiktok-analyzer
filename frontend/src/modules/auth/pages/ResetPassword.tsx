import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { toast } from 'react-hot-toast';
import { Lock, Loader, CheckCircle, Eye, EyeOff } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import { useCaptcha } from '@/hooks/useCaptcha';
import { TurnstileWidget } from '@/components/TurnstileWidget';
import type { TurnstileWidgetRef } from '@/components/TurnstileWidget';

export function ResetPassword() {
  const navigate = useNavigate();
  const token = new URLSearchParams(window.location.search).get('token');
  const { executeCaptcha, isEnabled: captchaEnabled, useVisibleWidget, errorMessage: captchaErrorMessage, hasPermanentError } = useCaptcha();

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const turnstileWidgetRef = useRef<TurnstileWidgetRef>(null);

  // Redirect if no token
  useEffect(() => {
    if (!token) {
      toast.error('Invalid reset token. Please request a new password reset.');
      navigate({ to: '/forgot-password', replace: true });
    }
  }, [token, navigate]);

  const handleTurnstileSuccess = (token: string) => {
    console.log('[ResetPassword] Turnstile success, token received');
    setTurnstileToken(token);
  };

  const handleTurnstileError = () => {
    console.error('[ResetPassword] Turnstile error');
    setTurnstileToken(null);
    // Check if it's a permanent configuration error - don't reset in that case
    if (turnstileWidgetRef.current?.hasPermanentError()) {
      toast.error('Security verification configuration error.');
      return;
    }
    toast.error('Security verification failed. Please try again.');
    turnstileWidgetRef.current?.reset();
  };

  const handleTurnstileExpire = () => {
    console.log('[ResetPassword] Turnstile expired');
    setTurnstileToken(null);
    // Check if it's a permanent configuration error - don't reset in that case
    if (turnstileWidgetRef.current?.hasPermanentError()) {
      return;
    }
    toast.error('Security verification expired. Please complete it again.');
    turnstileWidgetRef.current?.reset();
  };

  const resetTurnstileWidget = () => {
    if (turnstileWidgetRef.current) {
      turnstileWidgetRef.current.reset();
      setTurnstileToken(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!token) {
      toast.error('Invalid reset token');
      return;
    }

    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }

    setIsLoading(true);

    try {
      // Get captcha token if enabled
      let captchaToken: string | null = null;
      if (captchaEnabled) {
        if (useVisibleWidget) {
          // Use visible Turnstile widget token
          if (!turnstileToken) {
            toast.error('Please complete the security verification');
            setIsLoading(false);
            return;
          }
          captchaToken = turnstileToken;
        } else {
          // Use invisible captcha (reCAPTCHA v3)
          captchaToken = await executeCaptcha('reset-password');
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
      const response = await apiClient.resetPassword(token, newPassword, captchaToken || undefined);

      if (response.success) {
        setIsSuccess(true);
        // Use server message if available
        toast.success(response.message || 'Password reset successfully. You can now sign in.');
        // Redirect to login after a short delay
        setTimeout(() => {
          navigate({ to: '/login' });
        }, 2000);
      } else {
        throw new Error(response.message || 'Failed to reset password');
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
        serverMessage = error.message || 'Failed to reset password.';
      }

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

  if (!token) {
    return null; // Will redirect in useEffect
  }

  if (isSuccess) {
    return (
      <div className="bg-auth-mesh grain-overlay min-h-screen relative overflow-hidden">
        <div className="relative z-[1] flex items-center justify-center min-h-screen px-6">
          <div className="auth-card w-full max-w-[400px] p-10 text-center">
            <CheckCircle className="h-12 w-12 mx-auto mb-4" style={{ color: 'var(--color-success-600)' }} />
            <h2 className="auth-display text-xl mb-2">Password reset</h2>
            <p className="auth-mono-body text-sm mb-6">
              Redirecting to sign in...
            </p>
            <Link to="/login" className="auth-link auth-mono-label">
              go to sign in →
            </Link>
          </div>
        </div>
      </div>
    );
  }

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

          <form className="space-y-6" onSubmit={handleSubmit}>
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
                    type={showPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={8}
                    className="input pl-10 pr-10"
                    placeholder="Enter your new password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                  >
                    {showPassword ? (
                      <EyeOff className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                    ) : (
                      <Eye className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                    )}
                  </button>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  Must be at least 8 characters
                </p>
              </div>

              <div>
                <label htmlFor="confirmPassword" className="label">
                  Confirm New Password *
                </label>
                <div className="mt-1 relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Lock className="h-5 w-5 text-gray-400" />
                  </div>
                  <input
                    id="confirmPassword"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                    minLength={8}
                    className="input pl-10 pr-10"
                    placeholder="Confirm your new password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                  >
                    {showConfirmPassword ? (
                      <EyeOff className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                    ) : (
                      <Eye className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                    )}
                  </button>
                </div>
              </div>
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

            {/* Submit button */}
            <div>
              <button
                type="submit"
                disabled={isLoading || (useVisibleWidget && captchaEnabled && !turnstileToken)}
                className="btn-primary w-full"
              >
                {isLoading ? (
                  <>
                    <Loader className="animate-spin -ml-1 mr-2 h-4 w-4" />
                    Resetting password...
                  </>
                ) : (
                  'Reset Password'
                )}
              </button>
              {useVisibleWidget && captchaEnabled && !turnstileToken && (
                <p className="mt-2 text-sm text-gray-600 text-center">
                  Please complete the security verification below to continue
                </p>
              )}
            </div>
          </form>

        </div>
      </div>
    </div>
  );
}
