import { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { Modal } from '@/components/ui/Modal';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { Link2, AlertTriangle, Shield, RefreshCw } from 'lucide-react';
import { GoogleSignInButton } from './GoogleSignInButton';
import { GitHubSignInButton } from './GitHubSignInButton';
import { FacebookSignInButton } from './FacebookSignInButton';
import toast from 'react-hot-toast';
import { LoginError } from '../services/authRepository';
import { useCaptcha } from '@/hooks/useCaptcha';
import { CaptchaWidget } from '@/components/CaptchaWidget';
import type { CaptchaWidgetRef } from '@/components/CaptchaWidget';

/**
 * Modal shown when an OAuth login detects an existing account
 * with a matching verified email. User must enter their existing
 * password to prove ownership and complete the link.
 *
 * Same brute-force protection as LoginForm:
 * - Progressive delay (backend)
 * - CAPTCHA required after threshold failures (backend signals, frontend shows widget)
 */
export function LinkAccountModal() {
  const { oauthLinkData, confirmOAuthLink, clearOAuthLinkData } = useAuth();
  const { isEnabled: captchaEnabled } = useCaptcha();
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const cooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const captchaWidgetRef = useRef<CaptchaWidgetRef>(null);

  const startCooldown = useCallback((seconds: number) => {
    if (cooldownTimer.current) clearInterval(cooldownTimer.current);
    setCooldownSeconds(seconds);
    cooldownTimer.current = setInterval(() => {
      setCooldownSeconds(prev => {
        if (prev <= 1) {
          if (cooldownTimer.current) clearInterval(cooldownTimer.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  useEffect(() => {
    return () => { if (cooldownTimer.current) clearInterval(cooldownTimer.current); };
  }, []);

  if (!oauthLinkData) return null;

  const provider = oauthLinkData.provider || 'OAuth';
  const providerName = provider.charAt(0).toUpperCase() + provider.slice(1);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setError('Please enter your password');
      return;
    }

    setLoading(true);
    setError('');
    try {
      await confirmOAuthLink(password, captchaToken || undefined);
      toast.success(`${providerName} account successfully linked`);
    } catch (err: any) {
      // Reset CAPTCHA token so user must re-verify on next attempt
      setCaptchaToken(null);
      if (captchaWidgetRef.current) {
        captchaWidgetRef.current.reset();
      }

      // Detect expired link token
      const msg = err.message || 'Incorrect password. Please try again.';
      if (msg.toLowerCase().includes('expired') || msg.toLowerCase().includes('invalid link')) {
        setExpired(true);
        setError(msg);
        return;
      }

      // Detect PRL signals from backend (same pattern as LoginForm)
      if (err instanceof LoginError) {
        if (err.captchaRequired) setCaptchaRequired(true);
        if (err.retryAfter > 0) startCooldown(err.retryAfter);
      }

      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setPassword('');
    setError('');
    setCaptchaRequired(false);
    setCaptchaToken(null);
    clearOAuthLinkData();
  };

  return (
    <Modal
      isOpen={!!oauthLinkData}
      title={`Link your ${providerName} account`}
      onClose={handleClose}
    >
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-lg p-3" style={{ backgroundColor: 'var(--color-surface-sunken)' }}>
          <Link2 className="h-5 w-5 mt-0.5 flex-shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
          <div className="text-sm">
            <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Existing account found</p>
            <p className="mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              An account already exists with <strong>{oauthLinkData.email}</strong>.
              Enter your password to link your {providerName} login to this account.
            </p>
          </div>
        </div>

        {expired ? (
          <div className="space-y-4 text-center">
            <RefreshCw className="h-8 w-8 mx-auto" style={{ color: 'var(--color-text-secondary)' }} />
            <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Your link request has expired. Please try again.
            </p>
            <div className="pt-2">
              {provider === 'google' && <GoogleSignInButton onSuccess={handleClose} />}
              {provider === 'github' && <GitHubSignInButton />}
              {provider === 'facebook' && <FacebookSignInButton />}
            </div>
            <Button variant="secondary" onClick={handleClose} className="w-full">Cancel</Button>
          </div>
        ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="link-password" className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>
              Account Password
            </label>
            <Input
              id="link-password"
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError(''); }}
              placeholder="Enter your current password"
              autoFocus
              disabled={loading}
            />
          </div>

          {/* CAPTCHA widget — shown when backend signals captcha_required after failed attempts */}
          {captchaRequired && captchaEnabled && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm rounded-lg px-3 py-2" style={{ backgroundColor: 'var(--color-surface-sunken)', color: 'var(--color-text-secondary)' }}>
                <Shield className="h-4 w-4 shrink-0" />
                <span>Additional verification required due to multiple failed attempts</span>
              </div>
              <CaptchaWidget
                ref={captchaWidgetRef}
                onSuccess={(token) => setCaptchaToken(token)}
                onError={() => setCaptchaToken(null)}
                onExpire={() => setCaptchaToken(null)}
                className="flex justify-center"
              />
            </div>
          )}

          {error && (
            <div className="flex items-center justify-center gap-2 text-sm text-center" style={{ color: 'var(--color-error-600, #dc2626)' }}>
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex justify-between items-center">
            <a
              href="/forgot-password"
              className="text-sm hover:underline" style={{ color: 'var(--color-primary-600)' }}
              onClick={handleClose}
            >
              Forgot your password?
            </a>
            <div className="flex gap-3">
              <Button
                type="button"
                variant="secondary"
                onClick={handleClose}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={loading || !password.trim() || cooldownSeconds > 0 || (captchaRequired && captchaEnabled && !captchaToken)}
              >
                {loading ? 'Connecting...' : cooldownSeconds > 0 ? `Wait ${cooldownSeconds}s` : 'Confirm and Sign In'}
              </Button>
            </div>
          </div>
        </form>
        )}
      </div>
    </Modal>
  );
}
