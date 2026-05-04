import { useState, useEffect, useRef, useCallback } from 'react';
import { Mail, Loader, RefreshCw, ShieldAlert, AtSign, Clock, CheckCircle } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { recipientRepository } from '../index';
import type { Recipient } from '../types';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from 'react-hot-toast';
import { cn } from '@/utils/cn';

const MAX_POLL_ATTEMPTS = 60;

interface RecipientWizardProps {
    onRecipientReady: (recipientIds: number[], recipients: Recipient[]) => void;
    onSkipVerification: (recipientId: number) => void;
}

type RecipientMode = 'choose' | 'custom-input' | 'verifying' | 'verified';

export function RecipientWizard({ onRecipientReady, onSkipVerification }: RecipientWizardProps) {
    const { user } = useAuth();
    const isAccountVerified = !!user?.isVerified;

    const [mode, setMode] = useState<RecipientMode>('choose');
    const [customEmail, setCustomEmail] = useState('');
    const [customName, setCustomName] = useState('');
    const [loading, setLoading] = useState(false);
    const verifiedDataRef = useRef<{ recipientId: number; recipients: Recipient[] } | null>(null);
    const [createdId, setCreatedId] = useState<number | null>(null);
    const [createdEmail, setCreatedEmail] = useState('');
    const [pollExpired, setPollExpired] = useState(false);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const pollCountRef = useRef(0);
    const [rateLimitState, setRateLimitState] = useState<{
        retryAfter: number;
        requiresCaptcha: boolean;
        captchaProvider: string | null;
        attempt: number;
        totalTiers: number;
    } | null>(null);
    const [countdown, setCountdown] = useState(0);
    const [showResendModal, setShowResendModal] = useState(false);
    const [captchaToken, setCaptchaToken] = useState<string | null>(null);

    useEffect(() => {
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, []);

    useEffect(() => {
        if (countdown <= 0) return;
        const timer = setInterval(() => setCountdown(c => c - 1), 1000);
        return () => clearInterval(timer);
    }, [countdown]);

    const startPolling = useCallback((recipientId: number) => {
        if (pollRef.current) clearInterval(pollRef.current);
        pollCountRef.current = 0;
        setPollExpired(false);

        pollRef.current = setInterval(async () => {
            pollCountRef.current += 1;
            if (pollCountRef.current >= MAX_POLL_ATTEMPTS) {
                if (pollRef.current) clearInterval(pollRef.current);
                setPollExpired(true);
                return;
            }
            try {
                const res = await recipientRepository.list();
                if (res.success && res.data) {
                    const found = res.data.recipients.find(r => r.id === recipientId);
                    if (found?.isVerified) {
                        if (pollRef.current) clearInterval(pollRef.current);
                        verifiedDataRef.current = { recipientId, recipients: res.data.recipients };
                        setMode('verified');
                    }
                }
            } catch { /* continue polling */ }
        }, 5000);
    }, []);

    const createRecipient = async (email: string, name: string) => {
        setLoading(true);
        try {
            const res = await recipientRepository.create({ type: 'email', value: email, name });
            if (res.success && res.data) {
                setCreatedId(res.data.id);
                setCreatedEmail(email);

                if (email === user?.email && isAccountVerified) {
                    const listRes = await recipientRepository.list();
                    if (listRes.success && listRes.data) {
                        const found = listRes.data.recipients.find(r => r.id === res.data!.id);
                        if (found?.isVerified) {
                            onRecipientReady([res.data.id], listRes.data.recipients);
                            return;
                        }
                    }
                }

                setMode('verifying');
                startPolling(res.data.id);
            } else {
                toast.error(res.message || 'Error creating recipient');
            }
        } catch {
            toast.error('Error creating recipient');
        } finally {
            setLoading(false);
        }
    };

    const handleResend = async () => {
        if (!createdId) return;
        try {
            const res = await recipientRepository.resendVerification(createdId, captchaToken || undefined);
            if (res.success) {
                toast.success('Verification email resent');
                setShowResendModal(false);
                setRateLimitState(null);
                setCaptchaToken(null);
            }
        } catch (err: any) {
            const status = err?.response?.status;
            const data = err?.response?.data;
            const prl = status === 429 ? (data?.detail?.detail === 'progressive_rate_limited' ? data.detail : null) : null;
            if (prl) {
                setRateLimitState({
                    retryAfter: prl.retry_after,
                    requiresCaptcha: prl.requires_captcha,
                    captchaProvider: prl.captcha_provider,
                    attempt: prl.attempt,
                    totalTiers: prl.total_tiers,
                });
                setCountdown(prl.retry_after);
                setCaptchaToken(null);
            } else {
                toast.error('Error resending verification');
            }
        }
    };

    const resendModal = (
        <>
            {showResendModal && (
                <Modal
                    isOpen={showResendModal}
                    onClose={() => setShowResendModal(false)}
                    title="Resend verification email"
                    className="max-w-md"
                >
                    <div className="space-y-4">
                        {countdown > 0 ? (
                            <div className="text-center py-4">
                                <Clock className="w-10 h-10 text-amber-500 mx-auto mb-3" />
                                <p className="text-sm text-gray-700">Please wait before resending</p>
                                <p className="text-2xl font-bold text-gray-900 mt-2">{countdown}s</p>
                            </div>
                        ) : (
                            <>
                                <p className="text-sm text-gray-600">
                                    Send a new verification link to <span className="font-medium text-gray-900">{createdEmail}</span>?
                                </p>
                                {rateLimitState?.requiresCaptcha && (
                                    <div className="border rounded-lg p-4 bg-gray-50">
                                        <p className="text-xs text-gray-500 mb-2">Please verify that you are human</p>
                                        <p className="text-xs text-gray-400 italic">CAPTCHA: {rateLimitState.captchaProvider || 'none'}</p>
                                    </div>
                                )}
                                {rateLimitState && (
                                    <p className="text-xs text-gray-400 text-center">
                                        Attempt {rateLimitState.attempt} of {rateLimitState.totalTiers}
                                    </p>
                                )}
                            </>
                        )}
                        <div className="flex justify-end gap-3">
                            <Button type="button" variant="secondary" onClick={() => setShowResendModal(false)}>
                                Cancel
                            </Button>
                            <Button
                                type="button"
                                onClick={handleResend}
                                disabled={countdown > 0 || (!!rateLimitState?.requiresCaptcha && !captchaToken)}
                            >
                                {countdown > 0 ? `Wait ${countdown}s` : 'Resend'}
                            </Button>
                        </div>
                    </div>
                </Modal>
            )}
        </>
    );

    // Verifying state
    if (mode === 'verifying') {
        return (
            <>
                <div className="space-y-4 text-center">
                    <div className="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center mx-auto">
                        {pollExpired ? <Mail className="w-8 h-8 text-primary-600" /> : <Loader className="w-8 h-8 animate-spin text-primary-600" />}
                    </div>
                    <div>
                        <h3 className="text-lg font-semibold text-gray-900">
                            {pollExpired ? 'Check your inbox' : 'Waiting for email verification'}
                        </h3>
                        <p className="text-sm text-gray-500 mt-1">
                            We sent a verification link to <span className="font-medium text-gray-700">{createdEmail}</span>.
                            {pollExpired && ' Click the link and then return here.'}
                        </p>
                    </div>
                    <div className="flex flex-col gap-2">
                        <button
                            onClick={() => setShowResendModal(true)}
                            disabled={countdown > 0}
                            className="text-sm text-primary-600 hover:text-primary-700 font-medium flex items-center justify-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <RefreshCw className="w-3.5 h-3.5" />
                            {countdown > 0 ? `Resend in ${countdown}s` : 'Resend verification email'}
                        </button>
                        <button
                            onClick={() => { if (pollRef.current) clearInterval(pollRef.current); if (createdId) onSkipVerification(createdId); }}
                            className="text-sm text-gray-500 hover:text-gray-700"
                        >
                            Skip for now
                        </button>
                    </div>
                </div>
                {resendModal}
            </>
        );
    }

    // Verified success screen
    if (mode === 'verified' && verifiedDataRef.current) {
        return (
            <div className="text-center py-6 space-y-4">
                <div className="w-16 h-16 rounded-full bg-success-100 flex items-center justify-center mx-auto">
                    <CheckCircle className="w-8 h-8 text-success-600" />
                </div>
                <div>
                    <h3 className="text-lg font-semibold text-gray-900">Email verified!</h3>
                    <p className="text-sm text-gray-500 mt-1">
                        <span className="font-medium text-gray-700">{createdEmail}</span> is ready to receive notifications.
                    </p>
                </div>
                <Button
                    onClick={() => {
                        if (verifiedDataRef.current) {
                            onRecipientReady([verifiedDataRef.current.recipientId], verifiedDataRef.current.recipients);
                        }
                    }}
                >
                    Continue
                </Button>
            </div>
        );
    }

    // Custom email input
    if (mode === 'custom-input') {
        return (
            <>
                <div className="space-y-4">
                    <div className="text-center mb-2">
                        <AtSign className="w-10 h-10 text-primary-600 mx-auto mb-2" />
                        <h3 className="text-lg font-semibold text-gray-900">Enter your email</h3>
                        <p className="text-sm text-gray-500 mt-1">We will send a verification link to confirm this email.</p>
                    </div>
                    <Input
                        type="email"
                        value={customEmail}
                        onChange={(e) => setCustomEmail(e.target.value)}
                        placeholder="tu@correo.com"
                        className="text-lg"
                        autoFocus
                    />
                    <Input
                        type="text"
                        value={customName}
                        onChange={(e) => setCustomName(e.target.value)}
                        placeholder="Name or label (e.g. Work email)"
                        className="text-sm"
                    />
                    <div className="flex gap-3">
                        <Button type="button" variant="secondary" onClick={() => setMode('choose')} className="flex-1">
                            Back
                        </Button>
                        <Button
                            type="button"
                            onClick={() => createRecipient(customEmail, customName || customEmail.split('@')[0])}
                            disabled={loading || !customEmail.includes('@')}
                            className="flex-1"
                        >
                            {loading ? <Loader className="w-4 h-4 animate-spin mr-2" /> : <Mail className="w-4 h-4 mr-2" />}
                            Send verification
                        </Button>
                    </div>
                </div>
                {resendModal}
            </>
        );
    }

    // Choose mode
    return (
        <>
            <div className="space-y-4">
                <div className="text-center mb-2">
                    <Mail className="w-10 h-10 text-primary-600 mx-auto mb-2" />
                    <h3 className="text-lg font-semibold text-gray-900">Where should we send notifications?</h3>
                    <p className="text-sm text-gray-500 mt-1">Choose where to receive notifications.</p>
                </div>

                {/* Option 1: Use account email */}
                <button
                    onClick={() => isAccountVerified && createRecipient(user!.email, 'Mi Correo')}
                    disabled={loading || !isAccountVerified}
                    className={cn(
                        'w-full p-4 border-2 rounded-xl text-left flex items-center gap-3 transition-all',
                        isAccountVerified
                            ? 'border-primary-200 hover:border-primary-400 hover:bg-primary-50 cursor-pointer'
                            : 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-70'
                    )}
                >
                    <div className={cn(
                        'w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0',
                        isAccountVerified ? 'bg-primary-100' : 'bg-gray-100'
                    )}>
                        <Mail className={cn('w-5 h-5', isAccountVerified ? 'text-primary-600' : 'text-gray-400')} />
                    </div>
                    <div className="min-w-0 flex-1">
                        <p className={cn('font-medium', isAccountVerified ? 'text-gray-900' : 'text-gray-500')}>Use my account email</p>
                        <p className="text-sm text-gray-500 truncate">{user?.email}</p>
                        {!isAccountVerified && (
                            <p className="text-xs text-amber-600 flex items-center gap-1 mt-1">
                                <ShieldAlert className="w-3 h-3" />
                                Your account email is not verified. Verify your account first.
                            </p>
                        )}
                    </div>
                    {loading ? (
                        <Loader className="w-5 h-5 animate-spin text-primary-600 flex-shrink-0" />
                    ) : null}
                </button>

                {/* Option 2: Use a different email */}
                <button
                    onClick={() => setMode('custom-input')}
                    className="w-full p-4 border-2 border-gray-200 rounded-xl hover:border-primary-400 hover:bg-primary-50 transition-all text-left flex items-center gap-3"
                >
                    <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0">
                        <AtSign className="w-5 h-5 text-gray-500" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <p className="font-medium text-gray-900">Use a different email</p>
                        <p className="text-sm text-gray-500">Enter any email address — we will verify it</p>
                    </div>
                </button>
            </div>
            {resendModal}
        </>
    );
}
