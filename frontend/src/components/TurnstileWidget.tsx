import { useEffect, useRef, useState, useImperativeHandle, forwardRef } from 'react';

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || '';

interface TurnstileWidgetProps {
  onSuccess: (token: string) => void;
  onError?: () => void;
  onExpire?: () => void;
  className?: string;
  theme?: 'light' | 'dark' | 'auto';
}

export interface TurnstileWidgetRef {
  reset: () => void;
  hasPermanentError: () => boolean;
}

const TurnstileWidgetComponent = forwardRef<TurnstileWidgetRef, TurnstileWidgetProps>(
  ({ onSuccess, onError, onExpire, className, theme }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const widgetIdRef = useRef<string | null>(null);
    const [hasError, setHasError] = useState(false);

    // Callbacks ref to avoid effect re-runs
    const callbacksRef = useRef({ onSuccess, onError, onExpire });
    useEffect(() => {
      callbacksRef.current = { onSuccess, onError, onExpire };
    }, [onSuccess, onError, onExpire]);

    const renderWidget = () => {
      if (!containerRef.current || !window.turnstile || !TURNSTILE_SITE_KEY) return;

      // Cleanup existing if any
      if (widgetIdRef.current) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }

      try {
        const id = window.turnstile.render(containerRef.current, {
          sitekey: TURNSTILE_SITE_KEY,
          callback: (token: string) => callbacksRef.current.onSuccess(token),
          'error-callback': (code: any) => {
            console.error('[Turnstile] Error:', code);
            setHasError(true);
            callbacksRef.current.onError?.();
          },
          'expired-callback': () => callbacksRef.current.onExpire?.(),
          appearance: 'always',
          theme: theme || (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'),
        });
        widgetIdRef.current = id;
        setHasError(false);
      } catch (err) {
        console.error('[Turnstile] Render failed', err);
        setHasError(true);
        callbacksRef.current.onError?.();
      }
    };

    const reset = () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
      setHasError(false);
      renderWidget();
    };

    useImperativeHandle(ref, () => ({
      reset,
      hasPermanentError: () => false, // Simplified
    }));

    useEffect(() => {
      // Wait for script if needed
      if (!window.turnstile) {
        // Assume script is being loaded by useCaptcha hook or globally.
        // We can poll briefly or just wait.
        // Ideally, useCaptcha hook notifies us. 
        // But for independence, let's poll.
        const interval = setInterval(() => {
          if (window.turnstile) {
            clearInterval(interval);
            queueMicrotask(renderWidget);
          }
        }, 100);
        return () => clearInterval(interval);
      } else {
        // Defer past the current render tick to avoid cascading setState warning.
        queueMicrotask(renderWidget);
      }

      return () => {
        if (widgetIdRef.current && window.turnstile) {
          window.turnstile.remove(widgetIdRef.current);
          widgetIdRef.current = null;
        }
      };
    }, []);

    if (!TURNSTILE_SITE_KEY) return null;

    return (
      <div
        ref={containerRef}
        className={className}
        style={{ minHeight: '65px' }}
      >
        {hasError && (
          <div className="text-center text-sm text-error-600 py-2">
            <p>Verification failed.</p>
            <button onClick={reset} className="underline text-xs">Retry</button>
          </div>
        )}
      </div>
    );
  }
);

TurnstileWidgetComponent.displayName = 'TurnstileWidget';

export const TurnstileWidget = TurnstileWidgetComponent;
