import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from 'react-hot-toast';
import { Loader, Lock, Eye, EyeOff, CheckCircle, AlertCircle, Shield } from 'lucide-react';
import { cn } from '@/utils/cn';
import { useCaptcha } from '@/hooks/useCaptcha';
import { CaptchaWidget } from '@/components/CaptchaWidget';
import type { CaptchaWidgetRef } from '@/components/CaptchaWidget';
import { LoginError } from '../services/authRepository';
import { GoogleSignInButton } from './GoogleSignInButton';
import { GitHubSignInButton } from './GitHubSignInButton';
import { FacebookSignInButton } from './FacebookSignInButton';
import { googleConfig, githubConfig, facebookConfig } from '@/config/env';

interface FormErrors {
    email?: string;
    password?: string;
}

interface LoginFormProps {
    onSuccess?: () => void;
    hideLogo?: boolean;
    hideBackHome?: boolean;
    hideRegisterLink?: boolean;
    hideForgotPassword?: boolean;
}

export function LoginForm({ onSuccess, hideLogo = false, hideBackHome = false, hideRegisterLink = false, hideForgotPassword = false }: LoginFormProps) {
    const { login } = useAuth();
    const { isEnabled: captchaEnabled, executeCaptcha, providerName } = useCaptcha();

    const [formData, setFormData] = useState({
        email: '',
        password: '',
        remember_me: false,
    });
    const [errors, setErrors] = useState<FormErrors>({});
    const [showPassword, setShowPassword] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [failedAttempts, setFailedAttempts] = useState(0);
    const [cooldownSeconds, setCooldownSeconds] = useState(0);
    const cooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null);

    // CAPTCHA state — only shown when backend signals captcha_required
    const [captchaRequired, setCaptchaRequired] = useState(false);
    // OAuth-only account detection
    const [oauthOnlyProviders, setOauthOnlyProviders] = useState<string[] | null>(null);
    const [captchaToken, setCaptchaToken] = useState<string | null>(null);
    const captchaWidgetRef = useRef<CaptchaWidgetRef>(null);

    // Escalating cooldown: 0, 0, 2s, 5s, 10s, 30s (after 1, 2, 3, 4, 5, 6+ failures)
    const getCooldownDuration = useCallback((attempts: number): number => {
        if (attempts <= 2) return 0;
        if (attempts === 3) return 2;
        if (attempts === 4) return 5;
        if (attempts === 5) return 10;
        return 30;
    }, []);

    const startCooldown = useCallback((seconds: number) => {
        if (seconds <= 0) return;
        setCooldownSeconds(seconds);
        if (cooldownTimer.current) clearInterval(cooldownTimer.current);
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

    // Email validation
    const validateEmail = (email: string): string | undefined => {
        if (!email.trim()) {
            return 'Email is required';
        }
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            return 'Please enter a valid email address';
        }
        return undefined;
    };

    // Password validation
    const validatePassword = (password: string): string | undefined => {
        if (!password) {
            return 'Password is required';
        }
        return undefined;
    };

    // Real-time validation
    const handleFieldChange = (field: keyof typeof formData, value: string | boolean) => {
        const newFormData = { ...formData, [field]: value };
        setFormData(newFormData);

        // Clear error for this field
        const newErrors = { ...errors };
        if (newErrors[field as keyof FormErrors]) {
            newErrors[field as keyof FormErrors] = undefined;
        }

        // Validate on change (only for string fields)
        if (typeof value === 'string') {
            let error: string | undefined;
            switch (field) {
                case 'email':
                    error = validateEmail(value);
                    break;
                case 'password':
                    error = validatePassword(value);
                    break;
            }

            if (error) {
                newErrors[field as keyof FormErrors] = error;
            }
        }

        setErrors(newErrors);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        // Validate all fields
        const newErrors: FormErrors = {};
        newErrors.email = validateEmail(formData.email);
        newErrors.password = validatePassword(formData.password);

        setErrors(newErrors);

        // Check if there are any errors
        if (Object.values(newErrors).some(error => error !== undefined)) {
            toast.error('Please fill in all required fields');
            return;
        }

        setIsLoading(true);

        try {
            // If CAPTCHA is required, obtain a token before login
            let tokenForLogin = captchaToken;
            if (captchaRequired && captchaEnabled) {
                // For reCAPTCHA v3, execute invisibly; for Turnstile, use the widget token
                if (!tokenForLogin) {
                    tokenForLogin = await executeCaptcha('login');
                }
                if (!tokenForLogin) {
                    toast.error('Please complete the CAPTCHA verification');
                    setIsLoading(false);
                    return;
                }
            }

            await login({
                ...formData,
                ...(tokenForLogin ? { captcha_token: tokenForLogin } : {}),
            });
            setFailedAttempts(0);
            setCaptchaRequired(false);
            setCaptchaToken(null);
            toast.success('Signed in successfully');
            if (onSuccess) onSuccess();
        } catch (error: any) {
            const newFailedCount = failedAttempts + 1;
            setFailedAttempts(newFailedCount);

            // Reset CAPTCHA token so user must re-verify on next attempt
            setCaptchaToken(null);
            if (captchaWidgetRef.current) {
                captchaWidgetRef.current.reset();
            }

            // Detect OAuth-only account
            if (error instanceof LoginError && error.oauthOnly) {
                setOauthOnlyProviders(error.providers);
                setIsLoading(false);
                return; // Don't increment failures or show generic error
            }
            setOauthOnlyProviders(null);

            // Detect captcha_required and retry_after from backend PRL
            if (error instanceof LoginError) {
                if (error.captchaRequired) {
                    setCaptchaRequired(true);
                }
                // Use server-side retry_after if provided, otherwise fall back to client-side cooldown
                if (error.retryAfter > 0) {
                    startCooldown(error.retryAfter);
                } else {
                    const cooldown = getCooldownDuration(newFailedCount);
                    if (cooldown > 0) {
                        startCooldown(cooldown);
                    }
                }
            } else {
                const cooldown = getCooldownDuration(newFailedCount);
                if (cooldown > 0) {
                    startCooldown(cooldown);
                }
            }

            // Handle specific API errors
            // If rate-limited with retry_after, the button already shows "Try again in Xs" — don't show a misleading error
            if (error instanceof LoginError && error.retryAfter > 0) {
                // Clear any previous errors — the cooldown timer on the button is the feedback
                setErrors({});
            } else if (error.message?.includes('Google Sign-In')) {
                setErrors({ ...errors, email: error.message });
            } else if (error.message?.includes('email') || error.message?.includes('Email')) {
                setErrors({ ...errors, email: error.message });
            } else if (error.message?.includes('password') || error.message?.includes('Password')) {
                setErrors({ ...errors, password: error.message });
            } else {
                toast.error(error.message || 'Sign-in failed. Please check your credentials.');
            }
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="w-full">
            {!hideBackHome && (
                <a href="/" className="auth-link auth-mono-label mb-6 inline-flex">
                    ← back to home
                </a>
            )}

            {!hideLogo && (
                <div className="mb-8">
                    <div className="auth-display text-2xl lowercase">maborak</div>
                </div>
            )}

            {(googleConfig.enabled || githubConfig.enabled || facebookConfig.enabled) && (
                <div className="mb-4 space-y-3">
                    {googleConfig.enabled && <GoogleSignInButton onSuccess={onSuccess} />}
                    {githubConfig.enabled && <GitHubSignInButton />}
                    {facebookConfig.enabled && <FacebookSignInButton />}
                    <div className="relative my-4">
                        <div className="absolute inset-0 flex items-center">
                            <div className="w-full h-px" style={{ backgroundColor: 'var(--color-border-primary)' }} />
                        </div>
                        <div className="relative flex justify-center">
                            <span
                                className="auth-mono-label px-3"
                                style={{ backgroundColor: 'var(--color-surface-primary)' }}
                            >
                                or
                            </span>
                        </div>
                    </div>
                </div>
            )}

            <form className="space-y-6" onSubmit={handleSubmit}>
                <div className="space-y-5">
                    {/* Email field */}
                    <div>
                        <label htmlFor="email" className="auth-mono-label mb-2 block">
                            Email
                        </label>
                        <div className="input-underline">
                            <div className="relative">
                                <input
                                    id="email"
                                    name="email"
                                    type="text"
                                    required
                                    className={cn(
                                        "appearance-none block w-full py-2.5 bg-transparent border-b focus:outline-none text-sm transition-colors",
                                        errors.email
                                            ? "border-error-300 placeholder-error-300"
                                            : "border-gray-200 placeholder-gray-400"
                                    )}
                                    style={{
                                        color: 'var(--color-text-primary)',
                                        fontFamily: 'var(--font-mono-display)',
                                    }}
                                    placeholder="you@example.com"
                                    value={formData.email}
                                    onChange={(e) => handleFieldChange('email', e.target.value)}
                                />
                                {formData.email && !errors.email && (
                                    <div className="absolute inset-y-0 right-0 pr-1 flex items-center pointer-events-none">
                                        <CheckCircle className="h-4 w-4 text-success-500" />
                                    </div>
                                )}
                            </div>
                        </div>
                        {errors.email && (
                            <p className="mt-1.5 text-sm flex items-center gap-1" style={{ color: 'var(--color-error-600)' }}>
                                <AlertCircle className="h-3.5 w-3.5" />
                                {errors.email}
                            </p>
                        )}
                    </div>

                    {/* Password field */}
                    <div>
                        <label htmlFor="password" className="auth-mono-label mb-2 block">
                            Password
                        </label>
                        <div className="input-underline">
                            <div className="relative">
                                <input
                                    id="password"
                                    name="password"
                                    type={showPassword ? "text" : "password"}
                                    required
                                    className={cn(
                                        "appearance-none block w-full py-2.5 pr-10 bg-transparent border-b focus:outline-none text-sm transition-colors",
                                        errors.password
                                            ? "border-error-300 placeholder-error-300"
                                            : "border-gray-200 placeholder-gray-400"
                                    )}
                                    style={{
                                        color: 'var(--color-text-primary)',
                                        fontFamily: 'var(--font-mono-display)',
                                    }}
                                    placeholder="••••••••"
                                    value={formData.password}
                                    onChange={(e) => handleFieldChange('password', e.target.value)}
                                />
                                <button
                                    type="button"
                                    className="absolute inset-y-0 right-0 pr-1 flex items-center transition-colors"
                                    style={{ color: 'var(--color-text-tertiary)' }}
                                    onClick={() => setShowPassword(!showPassword)}
                                >
                                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                            </div>
                        </div>
                        {errors.password && (
                            <p className="mt-1.5 text-sm flex items-center gap-1" style={{ color: 'var(--color-error-600)' }}>
                                <AlertCircle className="h-3.5 w-3.5" />
                                {errors.password}
                            </p>
                        )}
                    </div>
                </div>

                {/* OAuth-only account notice */}
                {oauthOnlyProviders && (
                    <div
                        className="rounded-sm border p-4 space-y-2"
                        style={{
                            backgroundColor: 'var(--color-surface-sunken)',
                            borderColor: 'var(--color-border-primary)',
                        }}
                    >
                        <p className="auth-mono-body text-sm">
                            This account uses <strong>{oauthOnlyProviders.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(', ')}</strong> to sign in and does not have a password set.
                        </p>
                        <p className="auth-mono-body text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                            Sign in with {oauthOnlyProviders.includes('google') ? 'Google' : oauthOnlyProviders[0]} above, or set a password from your account settings after signing in.
                        </p>
                    </div>
                )}

                {/* CAPTCHA widget — only shown when backend signals captcha_required */}
                {captchaRequired && captchaEnabled && (
                    <div className="space-y-3">
                        <div
                            className="flex items-center gap-2 text-sm rounded-sm px-3 py-2"
                            style={{
                                backgroundColor: 'var(--color-surface-sunken)',
                                borderLeft: '2px solid var(--color-warning-600)',
                                color: 'var(--color-text-secondary)',
                            }}
                        >
                            <Shield className="h-4 w-4 shrink-0" style={{ color: 'var(--color-warning-600)' }} />
                            <span>Additional verification required</span>
                        </div>
                        <CaptchaWidget
                            ref={captchaWidgetRef}
                            onSuccess={(token) => setCaptchaToken(token)}
                            onError={() => {
                                setCaptchaToken(null);
                                toast.error('CAPTCHA verification failed. Please try again.');
                            }}
                            onExpire={() => setCaptchaToken(null)}
                        />
                    </div>
                )}

                <div className="flex items-center justify-between">
                    <div className="flex items-center">
                        <input
                            id="remember-me"
                            name="remember-me"
                            type="checkbox"
                            className="h-3.5 w-3.5 rounded-sm cursor-pointer accent-primary-600"
                            style={{ borderColor: 'var(--color-border-primary)' }}
                            checked={formData.remember_me}
                            onChange={(e) => handleFieldChange('remember_me', e.target.checked)}
                        />
                        <label
                            htmlFor="remember-me"
                            className="auth-mono-body ml-2 block text-xs cursor-pointer"
                        >
                            Remember me
                        </label>
                    </div>

                    {!hideForgotPassword && (
                        <a href="/forgot-password" className="auth-link text-xs">
                            Forgot password?
                        </a>
                    )}
                </div>

                <button
                    type="submit"
                    disabled={isLoading || cooldownSeconds > 0 || (captchaRequired && captchaEnabled && !captchaToken && providerName === 'Cloudflare Turnstile')}
                    className="btn-primary auth-submit w-full py-3"
                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: '0.02em' }}
                >
                    {isLoading ? (
                        <>
                            <Loader className="w-4 h-4 mr-2 animate-spin" />
                            signing in...
                        </>
                    ) : cooldownSeconds > 0 ? (
                        <>
                            <Lock className="w-4 h-4 mr-2" />
                            try again in {cooldownSeconds}s
                        </>
                    ) : (
                        'sign in →'
                    )}
                </button>
            </form>

            {!hideRegisterLink && (
                <div className="mt-8 text-center">
                    <span className="auth-mono-body text-xs">No account? </span>
                    <a href="/register" className="auth-link text-xs">
                        Create one →
                    </a>
                </div>
            )}
        </div>
    );
}
