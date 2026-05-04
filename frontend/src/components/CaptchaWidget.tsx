import { forwardRef, useImperativeHandle, useRef, useEffect } from 'react';
import { useCaptcha } from '../hooks/useCaptcha';
import { TurnstileWidget, type TurnstileWidgetRef } from './TurnstileWidget';

export interface CaptchaWidgetProps {
    onSuccess: (token: string) => void;
    onError?: () => void;
    onExpire?: () => void;
    className?: string;
    theme?: 'light' | 'dark' | 'auto';
}

export interface CaptchaWidgetRef {
    reset: () => void;
    hasPermanentError: () => boolean;
    executeInvisible: (action: string) => Promise<string | null>;
}

export const CaptchaWidget = forwardRef<CaptchaWidgetRef, CaptchaWidgetProps>(
    ({ onSuccess, onError, onExpire, className, theme }, ref) => {
        const { isEnabled, provider, executeCaptcha } = useCaptcha();
        const turnstileRef = useRef<TurnstileWidgetRef>(null);

        useImperativeHandle(ref, () => ({
            reset: () => {
                if (provider === 'turnstile') {
                    turnstileRef.current?.reset();
                }
            },
            hasPermanentError: () => {
                if (provider === 'turnstile') {
                    return turnstileRef.current?.hasPermanentError() ?? false;
                }
                return false;
            },
            executeInvisible: async (action: string) => {
                // Only reCAPTCHA and Turnstile in explicit invisible mode support execution this way
                return await executeCaptcha(action);
            }
        }));

        // Auto-trigger success if captcha is disabled globally.
        // Hook must be called unconditionally — gate the side effect inside.
        useEffect(() => {
            if (!isEnabled) {
                onSuccess('captcha-disabled');
            }
        }, [isEnabled, onSuccess]);

        if (!isEnabled) {
            return null;
        }

        if (provider === 'turnstile') {
            return (
                <TurnstileWidget
                    ref={turnstileRef}
                    onSuccess={onSuccess}
                    onError={onError}
                    onExpire={onExpire}
                    className={className}
                    theme={theme}
                />
            );
        }

        // reCAPTCHA v3 or unknown -> Invisible execution, no visible widget needed
        // The consumer should use `executeInvisible` from the ref
        return null;
    }
);

CaptchaWidget.displayName = 'CaptchaWidget';
