import { useState } from 'react';
import { useNavigate, Link } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { CheckCircle, XCircle, Loader2, Shield, ArrowRight } from 'lucide-react';
import { apiRequest } from '@/api/client';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';

type VerificationState = 'idle' | 'verifying' | 'success' | 'error';

export function VerifyRecipient() {
    const searchParams = new URLSearchParams(window.location.search);
    const navigate = useNavigate();
    const token = searchParams.get('token');

    const [state, setState] = useState<VerificationState>('idle');
    const [errorMessage, setErrorMessage] = useState<string>('');

    const handleVerify = async () => {
        if (!token) return;

        try {
            setState('verifying');
            await apiRequest({
                method: 'POST',
                url: '/user/account/recipients/verify',
                data: { token },
            });
            setState('success');
            toast.success('Recipient verified successfully!');

            setTimeout(() => {
                navigate({ to: routes.account.recipients });
            }, 2000);
        } catch (error: unknown) {
            setState('error');
            const err = error as { response?: { data?: { detail?: string } } };
            const message = err.response?.data?.detail || 'Failed to verify recipient. The link may have expired.';
            setErrorMessage(message);
            toast.error(message);
        }
    };

    if (!token) {
        return (
            <div className="min-h-[60vh] flex items-center justify-center px-4">
                <div className="max-w-md w-full text-center">
                    <div className="w-16 h-16 rounded-full bg-error-50 flex items-center justify-center mx-auto mb-6">
                        <XCircle className="w-8 h-8 text-error-600" />
                    </div>
                    <h1
                        className="text-xl font-semibold text-gray-900 mb-2"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                        Invalid verification link
                    </h1>
                    <p className="text-gray-600 mb-6">
                        The verification link is invalid or incomplete. Please check your email for the correct link.
                    </p>
                    <Link to="/">
                        <Button variant="secondary">
                            Go to Home
                            <ArrowRight className="w-4 h-4 ml-2" />
                        </Button>
                    </Link>
                </div>
            </div>
        );
    }

    if (state === 'success') {
        return (
            <div className="min-h-[60vh] flex items-center justify-center px-4">
                <div className="max-w-md w-full text-center">
                    <div className="w-16 h-16 rounded-full bg-success-50 flex items-center justify-center mx-auto mb-6 animate-pulse">
                        <CheckCircle className="w-8 h-8 text-success-600" />
                    </div>
                    <h1
                        className="text-xl font-semibold text-gray-900 mb-2"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                        Recipient verified!
                    </h1>
                    <p className="text-gray-600 mb-6">
                        The recipient email has been verified successfully. Redirecting...
                    </p>
                    <div className="flex items-center justify-center gap-2 text-sm text-gray-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Redirecting...
                    </div>
                </div>
            </div>
        );
    }

    if (state === 'error') {
        return (
            <div className="min-h-[60vh] flex items-center justify-center px-4">
                <div className="max-w-md w-full text-center">
                    <div className="w-16 h-16 rounded-full bg-error-50 flex items-center justify-center mx-auto mb-6">
                        <XCircle className="w-8 h-8 text-error-600" />
                    </div>
                    <h1
                        className="text-xl font-semibold text-gray-900 mb-2"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                        Verification failed
                    </h1>
                    <p className="text-gray-600 mb-6">{errorMessage}</p>
                    <div className="flex flex-col sm:flex-row gap-3 justify-center">
                        <Button variant="secondary" onClick={() => setState('idle')}>
                            Try again
                        </Button>
                        <Link to={routes.account.recipients}>
                            <Button>
                                Go to Recipients
                                <ArrowRight className="w-4 h-4 ml-2" />
                            </Button>
                        </Link>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-[60vh] flex items-center justify-center px-4">
            <div className="max-w-md w-full">
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center">
                    <div className="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center mx-auto mb-6">
                        <Shield className="w-8 h-8 text-primary-600" />
                    </div>

                    <h1
                        className="text-xl font-semibold text-gray-900 mb-2"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                        Verify recipient email
                    </h1>
                    <p className="text-gray-600 mb-8">
                        Click the button below to verify this email address as a notification recipient.
                    </p>

                    <Button
                        onClick={handleVerify}
                        disabled={state === 'verifying'}
                        className="w-full sm:w-auto px-8 auth-submit lowercase"
                        size="lg"
                        style={{ fontFamily: 'var(--font-mono-display)' }}
                    >
                        {state === 'verifying' ? (
                            <>
                                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                                verifying...
                            </>
                        ) : (
                            <>
                                <CheckCircle className="w-5 h-5 mr-2" />
                                verify recipient →
                            </>
                        )}
                    </Button>

                    <p className="mt-6 text-sm text-gray-500">
                        Having issues?{' '}
                        <Link to={routes.account.recipients} className="text-primary-600 hover:text-primary-700 font-medium">
                            Go to recipient management
                        </Link>
                    </p>
                </div>
            </div>
        </div>
    );
}
