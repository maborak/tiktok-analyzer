import { useState } from 'react';
import { CheckCircle, Mail, ArrowRight } from 'lucide-react';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { LoginForm } from './LoginForm';
import { RegisterForm } from './RegisterForm';

type ViewState = 'login' | 'register' | 'register-success';

interface AuthModalProps {
    isOpen: boolean;
    onClose?: () => void;
    initialView?: 'login' | 'register';
    onSuccess?: () => void;
    notice?: string;
    /** When true, shows only the login form without register toggle or router links. Safe to render outside RouterProvider. */
    loginOnly?: boolean;
    /** Override the default modal title */
    title?: string;
    /** Render a footer below the login form (e.g. escape hatch link) */
    footerContent?: React.ReactNode;
}

export function AuthModal({
    isOpen,
    onClose,
    initialView = 'login',
    onSuccess,
    notice,
    loginOnly = false,
    title: titleOverride,
    footerContent,
}: AuthModalProps) {
    const [view, setView] = useState<ViewState>(initialView);
    const [registeredEmail, setRegisteredEmail] = useState('');

    const handleLoginSuccess = () => {
        if (onSuccess) onSuccess();
        onClose?.();
    };

    const handleRegisterSuccess = ({ email }: { email: string }) => {
        setRegisteredEmail(email);
        setView('register-success');
    };

    const modalTitle = titleOverride
        ? titleOverride
        : view === 'register-success'
            ? "Almost there!"
            : view === 'login'
                ? 'Welcome back'
                : 'Create Account';

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title={modalTitle}
            className="max-w-md"
        >
            <div className="py-2">
                {notice && view !== 'register-success' && (
                    <div className="mb-4 rounded-lg bg-warning-50 border border-warning-200 px-4 py-3 text-sm text-warning-700">
                        {notice}
                    </div>
                )}

                {view === 'register-success' ? (
                    <div className="text-center">
                        <div className="mx-auto w-14 h-14 bg-success-50 rounded-full flex items-center justify-center mb-4">
                            <CheckCircle className="w-7 h-7 text-success-600" />
                        </div>

                        <div className="bg-primary-50 border border-primary-100 rounded-lg p-4 mb-6">
                            <div className="flex items-start gap-3">
                                <Mail className="w-5 h-5 text-primary-600 mt-0.5 shrink-0" />
                                <div className="text-left">
                                    <p className="text-sm text-primary-900 font-medium mb-1">
                                        Verification email sent to:
                                    </p>
                                    <p className="text-sm text-primary-700 font-semibold">
                                        {registeredEmail}
                                    </p>
                                    <p className="text-xs text-primary-600 mt-2 leading-relaxed">
                                        Click the link in the email to activate your account. Check your spam folder if you can't find it.
                                    </p>
                                </div>
                            </div>
                        </div>

                        <Button
                            onClick={() => setView('login')}
                            className="w-full justify-center mb-3"
                        >
                            Go to Login
                            <ArrowRight className="w-4 h-4 ml-2" />
                        </Button>

                        <button
                            type="button"
                            onClick={onClose}
                            className="text-sm text-gray-500 hover:text-gray-700 transition-colors"
                        >
                            Close
                        </button>
                    </div>
                ) : (loginOnly || view === 'login') ? (
                    <>
                        <LoginForm
                            onSuccess={handleLoginSuccess}
                            hideLogo
                            hideBackHome
                            hideRegisterLink
                            hideForgotPassword={loginOnly}
                        />
                        {!loginOnly && (
                            <div className="mt-6 text-center text-sm text-gray-500 border-t pt-4">
                                Don't have an account?{' '}
                                <button
                                    onClick={() => setView('register')}
                                    className="font-medium text-gray-900 hover:text-gray-700 transition-colors"
                                >
                                    Register here
                                </button>
                            </div>
                        )}
                    </>
                ) : (
                    <>
                        <RegisterForm
                            onSuccess={handleRegisterSuccess}
                        />
                        <div className="mt-6 text-center text-sm text-gray-500 border-t pt-4">
                            Already have an account?{' '}
                            <button
                                onClick={() => setView('login')}
                                className="font-medium text-primary-600 hover:text-primary-500 transition-colors"
                            >
                                Login here
                            </button>
                        </div>
                    </>
                )}

                {footerContent && view !== 'register-success' && (
                    <div className="mt-4 pt-3 border-t border-gray-100 text-center">
                        {footerContent}
                    </div>
                )}
            </div>
        </Modal>
    );
}
