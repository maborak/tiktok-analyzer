import { useState, useRef } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from 'react-hot-toast';
import { Loader, Eye, EyeOff, AlertCircle, Shield, Mail } from 'lucide-react';
import { cn } from '@/utils/cn';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useCaptcha } from '@/hooks/useCaptcha';
import { CaptchaWidget } from '@/components/CaptchaWidget';
import type { CaptchaWidgetRef } from '@/components/CaptchaWidget';
import { GoogleSignInButton } from './GoogleSignInButton';
import { GitHubSignInButton } from './GitHubSignInButton';
import { FacebookSignInButton } from './FacebookSignInButton';
import { googleConfig, githubConfig, facebookConfig } from '@/config/env';

interface FormErrors {
    email?: string;
    password?: string;
    confirmPassword?: string;
}

interface PasswordStrength {
    score: number; // 0-4
    feedback: string[];
}

interface RegisterFormProps {
    onSuccess?: (result: { email: string }) => void;
}

export function RegisterForm({ onSuccess }: RegisterFormProps) {
    const { register } = useAuth();
    const { isEnabled: captchaEnabled, providerName } = useCaptcha();

    const [formData, setFormData] = useState({
        email: '',
        password: '',
        confirmPassword: '',
        first_name: '',
        last_name: '',
    });
    const [errors, setErrors] = useState<FormErrors>({});
    const [showPassword, setShowPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);
    const [emailExistsError, setEmailExistsError] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    // When any OAuth provider is enabled, start with OAuth options; email form shown on click
    const [showEmailForm, setShowEmailForm] = useState(!googleConfig.enabled && !githubConfig.enabled && !facebookConfig.enabled);

    // Captcha state
    const [captchaToken, setCaptchaToken] = useState<string | null>(null);
    const captchaWidgetRef = useRef<CaptchaWidgetRef>(null);
    const [captchaRetryCount, setCaptchaRetryCount] = useState(0);

    // Email validation
    const validateEmail = (email: string): string | undefined => {
        if (!email.trim()) {
            return 'Email is required';
        }
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            return 'Please enter a valid email address';
        }
        return undefined;
    };

    // Password strength calculation
    const calculatePasswordStrength = (password: string): PasswordStrength => {
        const feedback: string[] = [];
        let score = 0;

        if (password.length >= 8) {
            score++;
        } else {
            feedback.push('At least 8 characters');
        }

        if (password.length >= 12) {
            score++;
        }

        if (/[a-z]/.test(password) && /[A-Z]/.test(password)) {
            score++;
        } else {
            feedback.push('Mix of uppercase and lowercase');
        }

        if (/\d/.test(password)) {
            score++;
        } else {
            feedback.push('At least one number');
        }

        if (/[^a-zA-Z0-9]/.test(password)) {
            score++;
        } else {
            feedback.push('At least one special character');
        }

        return { score, feedback };
    };

    const passwordStrength = calculatePasswordStrength(formData.password);

    // Captcha handlers with Silent Retry
    const handleCaptchaSuccess = (token: string) => {
        setCaptchaToken(token);
        setCaptchaRetryCount(0); // Reset retry count on success
    };

    const handleCaptchaError = () => {
        setCaptchaToken(null);

        // Silent retry for the first few errors (common during rapid switching)
        if (captchaRetryCount < 3) {
            console.log('[RegisterForm] Captcha error silenced, retrying...', captchaRetryCount);
            setCaptchaRetryCount(prev => prev + 1);
            if (captchaWidgetRef.current) {
                // Short delay to allow internal cleanup
                setTimeout(() => {
                    captchaWidgetRef.current?.reset();
                }, 100);
            }
            return; // Suppress toast and allow retry
        }

        if (captchaWidgetRef.current?.hasPermanentError()) {
            toast.error('Security verification configuration error.');
            return;
        }

        toast.error('Security verification failed. Please try again.');
        // Reset the widget to allow retrying manually
        if (captchaWidgetRef.current) {
            captchaWidgetRef.current.reset();
        }
    };

    const handleCaptchaExpire = () => {
        setCaptchaToken(null);
        if (captchaWidgetRef.current?.hasPermanentError()) {
            return;
        }
        if (captchaWidgetRef.current) {
            captchaWidgetRef.current.reset();
        }
    };

    const validatePassword = (password: string): string | undefined => {
        if (!password) {
            return 'Password is required';
        }
        if (password.length < 8) {
            return 'Password must be at least 8 characters';
        }
        return undefined;
    };

    const validateConfirmPassword = (confirmPassword: string, password: string): string | undefined => {
        if (!confirmPassword) {
            return 'Please confirm your password';
        }
        if (confirmPassword !== password) {
            return 'Passwords do not match';
        }
        return undefined;
    };

    const handleFieldChange = (field: keyof typeof formData, value: string) => {
        const newFormData = { ...formData, [field]: value };
        setFormData(newFormData);

        const newErrors = { ...errors };
        if (newErrors[field as keyof FormErrors]) {
            newErrors[field as keyof FormErrors] = undefined;
        }

        // Reset specific email error state on change
        if (field === 'email') {
            setEmailExistsError(false);
        }

        let error: string | undefined;
        switch (field) {
            case 'email':
                error = validateEmail(value);
                break;
            case 'password':
                error = validatePassword(value);
                if (newFormData.confirmPassword) {
                    newErrors.confirmPassword = validateConfirmPassword(newFormData.confirmPassword, value);
                }
                break;
            case 'confirmPassword':
                error = validateConfirmPassword(value, newFormData.password);
                break;
        }

        if (error) {
            newErrors[field as keyof FormErrors] = error;
        }
        setErrors(newErrors);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setEmailExistsError(false);

        // ... (validation checking)

        setIsLoading(true);
        try {
            // Invisible capture check if needed (e.g. reCAPTCHA)
            let finalCaptchaToken = captchaToken;
            if (captchaEnabled && !finalCaptchaToken) {
                finalCaptchaToken = await captchaWidgetRef.current?.executeInvisible('register') || null;
                if (!finalCaptchaToken) {
                    toast.error('Security verification failed. Please try again.');
                    setIsLoading(false);
                    return;
                }
            }

            await register({
                // ... (fields)
                email: formData.email,
                password: formData.password,
                first_name: formData.first_name || undefined,
                last_name: formData.last_name || undefined,
                captcha_token: finalCaptchaToken || undefined,
            });

            toast.success('Account created. Please check your email to verify.');
            if (onSuccess) onSuccess({ email: formData.email });

        } catch (error: any) {
            // Extract the actual error message from the backend response if available
            const backendError = error.response?.data?.detail || error.response?.data?.message;
            const errorMessage = backendError || error.message || 'Registration failed';

            // Check for Google Sign-In accounts first
            if (errorMessage.includes('Google Sign-In')) {
                setErrors({ ...errors, email: errorMessage });
                setEmailExistsError(false); // Don't show "Reset password" link
            } else if (
                errorMessage.includes('already exists') ||
                errorMessage.includes('already registered') ||
                errorMessage.includes('unique constraint')
            ) {
                setErrors({ ...errors, email: 'This email is already registered.' });
                setEmailExistsError(true);
                toast.error('Account already exists.');
            } else if (errorMessage.includes('email') || errorMessage.includes('Email')) {
                setErrors({ ...errors, email: errorMessage });
            } else {
                toast.error(errorMessage || 'Registration failed.');
            }

            // Reset Captcha on error to prevent "duplicate token" errors on retry
            setCaptchaToken(null);
            if (captchaWidgetRef.current) {
                captchaWidgetRef.current.reset();
            }
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="w-full">
            {/* OAuth providers first */}
            {(googleConfig.enabled || githubConfig.enabled || facebookConfig.enabled) && (
                <div className="space-y-4">
                    {googleConfig.enabled && <GoogleSignInButton />}
                    {githubConfig.enabled && <GitHubSignInButton />}
                    {facebookConfig.enabled && <FacebookSignInButton />}

                    {!showEmailForm && (
                        <>
                            <div className="relative my-4">
                                <div className="absolute inset-0 flex items-center">
                                    <div className="w-full h-px" style={{ backgroundColor: 'var(--color-border-primary)' }} />
                                </div>
                                <div className="relative flex justify-center">
                                    <span className="auth-mono-label px-3" style={{ backgroundColor: 'var(--color-surface-primary)' }}>or</span>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={() => setShowEmailForm(true)}
                                className="w-full flex items-center justify-center gap-3 rounded-sm border px-4 py-2.5 text-sm font-medium shadow-sm transition-all hover:opacity-80 cursor-pointer"
                                style={{
                                    borderColor: 'var(--color-border-primary)',
                                    backgroundColor: 'var(--color-surface-primary)',
                                    color: 'var(--color-text-secondary)',
                                    fontFamily: 'var(--font-mono-display)',
                                }}
                            >
                                <Mail className="h-4 w-4 flex-shrink-0" />
                                <span>sign up with email</span>
                            </button>
                        </>
                    )}

                    {showEmailForm && (
                        <div className="relative my-4">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full h-px" style={{ backgroundColor: 'var(--color-border-primary)' }} />
                            </div>
                            <div className="relative flex justify-center">
                                <span className="auth-mono-label px-3" style={{ backgroundColor: 'var(--color-surface-primary)' }}>or sign up with email</span>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {showEmailForm && <form className="space-y-6" onSubmit={handleSubmit}>
                <div className="space-y-5">
                    {/* Email */}
                    <div>
                        <label htmlFor="email" className="auth-mono-label mb-2 block">Email</label>
                        <div className="input-underline">
                            <input
                                id="email"
                                name="email"
                                type="email"
                                required
                                className={cn(
                                    "appearance-none block w-full py-2.5 bg-transparent border-b focus:outline-none text-sm transition-colors",
                                    errors.email ? "border-error-300 placeholder-error-300" : "border-gray-200 placeholder-gray-400"
                                )}
                                style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono-display)' }}
                                placeholder="you@example.com"
                                value={formData.email}
                                onChange={(e) => handleFieldChange('email', e.target.value)}
                            />
                        </div>
                        {errors.email && (
                            <div className="mt-1.5 flex flex-col gap-1">
                                <p className="text-sm flex items-center gap-1" style={{ color: 'var(--color-error-600)' }}>
                                    <AlertCircle className="h-3.5 w-3.5" />
                                    {errors.email}
                                </p>
                                {emailExistsError && (
                                    <p className="auth-mono-body text-xs ml-5">
                                        Forgot your password?{' '}
                                        <a href="/forgot-password" className="auth-link text-xs">Reset it here</a>
                                    </p>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Name fields */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label htmlFor="first_name" className="auth-mono-label mb-2 block">First name</label>
                            <div className="input-underline">
                                <input
                                    id="first_name"
                                    name="first_name"
                                    type="text"
                                    className="appearance-none block w-full py-2.5 bg-transparent border-b border-gray-200 focus:outline-none text-sm transition-colors placeholder-gray-400"
                                    style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono-display)' }}
                                    placeholder="First"
                                    value={formData.first_name}
                                    onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                                />
                            </div>
                        </div>
                        <div>
                            <label htmlFor="last_name" className="auth-mono-label mb-2 block">Last name</label>
                            <div className="input-underline">
                                <input
                                    id="last_name"
                                    name="last_name"
                                    type="text"
                                    className="appearance-none block w-full py-2.5 bg-transparent border-b border-gray-200 focus:outline-none text-sm transition-colors placeholder-gray-400"
                                    style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono-display)' }}
                                    placeholder="Last"
                                    value={formData.last_name}
                                    onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                                />
                            </div>
                        </div>
                    </div>

                    {/* Password */}
                    <div>
                        <label htmlFor="password" className="auth-mono-label mb-2 block">Password</label>
                        <div className="input-underline">
                            <div className="relative">
                                <input
                                    id="password"
                                    name="password"
                                    type={showPassword ? "text" : "password"}
                                    required
                                    className={cn(
                                        "appearance-none block w-full py-2.5 pr-10 bg-transparent border-b focus:outline-none text-sm transition-colors",
                                        errors.password ? "border-error-300 placeholder-error-300" : "border-gray-200 placeholder-gray-400"
                                    )}
                                    style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono-display)' }}
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
                        {formData.password && (
                            <div className="mt-2 space-y-2">
                                <span className="auth-mono-label">
                                    Strength:{' '}
                                    <span className={cn(
                                        passwordStrength.score <= 1 && "text-error-600",
                                        passwordStrength.score === 2 && "text-warning-600",
                                        passwordStrength.score === 3 && "text-warning-600",
                                        passwordStrength.score >= 4 && "text-success-600"
                                    )}>
                                        {passwordStrength.score <= 1 ? "weak" : passwordStrength.score === 2 ? "fair" : passwordStrength.score === 3 ? "good" : "strong"}
                                    </span>
                                </span>
                                <ProgressBar
                                    value={passwordStrength.score}
                                    max={4}
                                    className="h-1.5 bg-gray-200"
                                    barClassName={cn("h-1.5", passwordStrength.score <= 1 ? "bg-error-500" : passwordStrength.score <= 2 ? "bg-warning-500" : passwordStrength.score <= 3 ? "bg-warning-500" : "bg-success-500")}
                                />
                            </div>
                        )}
                    </div>

                    {/* Confirm password */}
                    <div>
                        <label htmlFor="confirmPassword" className="auth-mono-label mb-2 block">Confirm password</label>
                        <div className="input-underline">
                            <div className="relative">
                                <input
                                    id="confirmPassword"
                                    name="confirmPassword"
                                    type={showConfirmPassword ? "text" : "password"}
                                    required
                                    className={cn(
                                        "appearance-none block w-full py-2.5 pr-10 bg-transparent border-b focus:outline-none text-sm transition-colors",
                                        errors.confirmPassword
                                            ? "border-error-300 placeholder-error-300"
                                            : formData.confirmPassword && formData.confirmPassword === formData.password
                                                ? "border-success-300"
                                                : "border-gray-200 placeholder-gray-400"
                                    )}
                                    style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-mono-display)' }}
                                    placeholder="••••••••"
                                    value={formData.confirmPassword}
                                    onChange={(e) => handleFieldChange('confirmPassword', e.target.value)}
                                />
                                <button
                                    type="button"
                                    className="absolute inset-y-0 right-0 pr-1 flex items-center transition-colors"
                                    style={{ color: 'var(--color-text-tertiary)' }}
                                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                                >
                                    {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                            </div>
                        </div>
                        {errors.confirmPassword && (
                            <p className="mt-1.5 text-sm flex items-center gap-1" style={{ color: 'var(--color-error-600)' }}>
                                <AlertCircle className="h-3.5 w-3.5" />
                                {errors.confirmPassword}
                            </p>
                        )}
                    </div>
                </div>

                <button
                    type="submit"
                    disabled={isLoading || (captchaEnabled && providerName === 'Cloudflare Turnstile' && !captchaToken)}
                    className="btn-primary auth-submit w-full py-3"
                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: '0.02em' }}
                >
                    {isLoading ? (
                        <>
                            <Loader className="w-4 h-4 mr-2 animate-spin" />
                            creating account...
                        </>
                    ) : (
                        'create account →'
                    )}
                </button>

                {captchaEnabled && (
                    <CaptchaWidget
                        ref={captchaWidgetRef}
                        onSuccess={handleCaptchaSuccess}
                        onError={handleCaptchaError}
                        onExpire={handleCaptchaExpire}
                        className="flex justify-center"
                    />
                )}

                {captchaEnabled && providerName && (
                    <p className="auth-mono-body text-xs text-center flex items-center justify-center gap-1">
                        <Shield className="h-3 w-3" />
                        Protected by {providerName}.
                    </p>
                )}
            </form>}
        </div>
    );
}
