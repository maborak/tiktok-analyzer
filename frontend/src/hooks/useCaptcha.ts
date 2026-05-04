import { useEffect, useCallback, useState, useRef } from 'react';

type CaptchaProvider = 'none' | 'recaptcha_v3' | 'turnstile';

declare global {
  interface Window {
    grecaptcha?: {
      ready: (callback: () => void) => void;
      execute: (siteKey: string, options: { action: string }) => Promise<string>;
    };
    turnstile?: {
      render: (container: string | HTMLElement, options: { sitekey: string; callback?: (token: string) => void; 'error-callback'?: (error: any) => void; 'expired-callback'?: () => void; execution?: string; appearance?: string; theme?: string; }) => string;
      reset: (widgetId: string) => void;
      remove: (widgetId: string) => void;
      getResponse: (widgetId: string) => string | null;
      isExpired: (widgetId: string) => boolean;
      execute: (widgetId: string | string) => void;
    };
  }
}

const CAPTCHA_PROVIDER = (import.meta.env.VITE_CAPTCHA_PROVIDER || 'none') as CaptchaProvider;
const RECAPTCHA_SITE_KEY = import.meta.env.VITE_RECAPTCHA_SITE_KEY || '';
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || '';

// Debug: Log the provider value
console.log('[useCaptcha] CAPTCHA_PROVIDER from env:', import.meta.env.VITE_CAPTCHA_PROVIDER);
console.log('[useCaptcha] CAPTCHA_PROVIDER resolved:', CAPTCHA_PROVIDER);

// Global flag to track Turnstile loading state
let turnstileLoading = false;
let turnstileLoadCallbacks: Array<() => void> = [];

export function useCaptcha() {
  const [isLoaded, setIsLoaded] = useState(false);
  const [isEnabled, setIsEnabled] = useState(CAPTCHA_PROVIDER !== 'none');
  const [hasError, setHasError] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const permanentErrorRef = useRef(false); // Prevent retries for configuration errors
  const loadingAttemptedRef = useRef(false); // Prevent multiple loading attempts

  useEffect(() => {
    if (CAPTCHA_PROVIDER === 'none') {
      return;
    }

    // Load reCAPTCHA v3
    if (CAPTCHA_PROVIDER === 'recaptcha_v3') {
      if (!RECAPTCHA_SITE_KEY) {
        console.warn('[useCaptcha] reCAPTCHA v3 site key not configured. Captcha disabled.');
        setIsEnabled(false);
        setHasError(true);
        setErrorMessage('reCAPTCHA site key not configured');
        return;
      }

      // Don't retry if we have a permanent error
      if (permanentErrorRef.current) {
        console.log('[useCaptcha] Permanent reCAPTCHA error detected. Stopping all retries.');
        setHasError(true);
        return;
      }

      // Don't retry if we already attempted loading
      if (loadingAttemptedRef.current) {
        console.log('[useCaptcha] reCAPTCHA script loading already attempted. Skipping to prevent infinite loop.');
        return;
      }

      // Check if script already loaded
      if (window.grecaptcha) {
        setIsLoaded(true);
        return;
      }

      loadingAttemptedRef.current = true;

      // Load the reCAPTCHA script
      const script = document.createElement('script');
      script.src = `https://www.google.com/recaptcha/api.js?render=${RECAPTCHA_SITE_KEY}`;
      script.async = true;
      script.defer = true;

      script.onload = () => {
        console.log('[useCaptcha] reCAPTCHA script loaded');
        try {
          window.grecaptcha?.ready(() => {
            console.log('[useCaptcha] reCAPTCHA ready');

            // Try to execute immediately to catch configuration errors
            window.grecaptcha?.execute(RECAPTCHA_SITE_KEY, { action: 'test' })
              .then(() => {
                console.log('[useCaptcha] reCAPTCHA test execution successful');
                setIsLoaded(true);
                setHasError(false);
              })
              .catch((error: any) => {
                console.error('[useCaptcha] reCAPTCHA test execution failed:', error);
                const errorMsg = (error?.message || String(error)).toLowerCase();
                if (errorMsg.includes('localhost') || errorMsg.includes('site key') || errorMsg.includes('domain') || errorMsg.includes('invalid')) {
                  permanentErrorRef.current = true;
                  setHasError(true);
                  setErrorMessage('reCAPTCHA configuration error: Localhost is not supported by the current site key. Please register localhost in Google reCAPTCHA console.');
                }
                // Still set loaded to true so we can show error in UI
                setIsLoaded(true);
              });
          });
        } catch (error: any) {
          console.error('[useCaptcha] Error in grecaptcha.ready():', error);
          const errorMsg = (error?.message || String(error)).toLowerCase();
          if (errorMsg.includes('localhost') || errorMsg.includes('site key') || errorMsg.includes('domain')) {
            permanentErrorRef.current = true;
            setHasError(true);
            setErrorMessage('reCAPTCHA configuration error: Localhost is not supported by the current site key.');
          }
          // Check for DOM errors after catch
        }
      };

      script.onerror = () => {
        console.error('[useCaptcha] Failed to load reCAPTCHA script');
        setIsEnabled(false);
        setHasError(true);
        setErrorMessage('Failed to load reCAPTCHA script. Check your network connection.');
      };

      document.head.appendChild(script);

      return () => {
        // No explicit DOM observer destruction needed anymore
      };
    }

    // Load Cloudflare Turnstile (Explicit Rendering for SPAs)
    if (CAPTCHA_PROVIDER === 'turnstile') {
      if (!TURNSTILE_SITE_KEY) {
        console.warn('Turnstile site key not configured. Captcha disabled.');
        setIsEnabled(false);
        return;
      }

      // Add preconnect link for Turnstile performance optimization
      if (!document.querySelector('link[href="https://challenges.cloudflare.com"]')) {
        const preconnect = document.createElement('link');
        preconnect.rel = 'preconnect';
        preconnect.href = 'https://challenges.cloudflare.com';
        document.head.appendChild(preconnect);
      }

      // Check if Turnstile is already loaded
      if (window.turnstile && typeof window.turnstile.render === 'function') {
        setIsLoaded(true);
        return;
      }

      // If Turnstile is currently loading, queue this callback
      if (turnstileLoading) {
        turnstileLoadCallbacks.push(() => setIsLoaded(true));
        return;
      }

      // Check if script tag already exists in DOM
      const existingScript = document.querySelector('script[src*="turnstile"]');
      if (existingScript) {
        // Script exists, mark as loading and wait for it
        turnstileLoading = true;
        let checkInterval: ReturnType<typeof setInterval> | null = null;
        let timeoutId: ReturnType<typeof setTimeout> | null = null;

        checkInterval = setInterval(() => {
          if (window.turnstile && typeof window.turnstile.render === 'function') {
            if (checkInterval) clearInterval(checkInterval);
            if (timeoutId) clearTimeout(timeoutId);
            turnstileLoading = false;
            // Execute all callbacks
            setIsLoaded(true);
            turnstileLoadCallbacks.forEach(cb => cb());
            turnstileLoadCallbacks = [];
          }
        }, 100);

        // Timeout after 5 seconds
        timeoutId = setTimeout(() => {
          if (checkInterval) clearInterval(checkInterval);
          turnstileLoading = false;
          if (!window.turnstile) {
            console.error('Turnstile failed to load');
            setIsEnabled(false);
          }
          turnstileLoadCallbacks = [];
        }, 5000);

        return () => {
          if (checkInterval) clearInterval(checkInterval);
          if (timeoutId) clearTimeout(timeoutId);
        };
      }

      // Mark as loading
      turnstileLoading = true;
      const callback = () => setIsLoaded(true);
      turnstileLoadCallbacks.push(callback);

      // Load the Turnstile script with explicit rendering (for SPAs)
      const script = document.createElement('script');
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      script.defer = true; // Use defer for explicit rendering

      let checkInterval: ReturnType<typeof setInterval> | null = null;
      let timeoutId: ReturnType<typeof setTimeout> | null = null;

      script.onerror = () => {
        console.error('Failed to load Turnstile script');
        setIsEnabled(false);
        turnstileLoading = false;
        turnstileLoadCallbacks = [];
        if (checkInterval) clearInterval(checkInterval);
        if (timeoutId) clearTimeout(timeoutId);
      };

      script.onload = () => {
        // Wait for Turnstile to be available after script loads
        checkInterval = setInterval(() => {
          if (window.turnstile && typeof window.turnstile.render === 'function') {
            if (checkInterval) clearInterval(checkInterval);
            if (timeoutId) clearTimeout(timeoutId);
            turnstileLoading = false;
            // Execute all callbacks
            turnstileLoadCallbacks.forEach(cb => cb());
            turnstileLoadCallbacks = [];
          }
        }, 50);

        // Timeout after 3 seconds
        timeoutId = setTimeout(() => {
          if (checkInterval) clearInterval(checkInterval);
          turnstileLoading = false;
          if (!window.turnstile) {
            console.error('Turnstile not available after script load');
            setIsEnabled(false);
          }
          turnstileLoadCallbacks = [];
        }, 3000);
      };

      document.head.appendChild(script);

      return () => {
        if (checkInterval) clearInterval(checkInterval);
        if (timeoutId) clearTimeout(timeoutId);
        // Remove callback if component unmounts before Turnstile loads
        const index = turnstileLoadCallbacks.indexOf(callback);
        if (index > -1) {
          turnstileLoadCallbacks.splice(index, 1);
        }
      };
    }
  }, []);

  const executeCaptcha = useCallback(async (action: string): Promise<string | null> => {
    if (!isEnabled || CAPTCHA_PROVIDER === 'none') {
      return null;
    }

    if (!isLoaded) {
      console.warn('Captcha not loaded yet');
      return null;
    }

    try {
      if (CAPTCHA_PROVIDER === 'recaptcha_v3' && window.grecaptcha) {
        // Don't execute if we have a permanent error
        if (permanentErrorRef.current) {
          console.error('[useCaptcha] Cannot execute reCAPTCHA - permanent error detected');
          setHasError(true);
          return null;
        }

        console.log('[useCaptcha] Executing reCAPTCHA v3 with action:', action);
        try {
          const token = await window.grecaptcha.execute(RECAPTCHA_SITE_KEY, { action });
          console.log('[useCaptcha] reCAPTCHA v3 token received:', token ? 'yes' : 'no');

          if (!token) {
            console.warn('[useCaptcha] reCAPTCHA returned empty token - possible configuration error');
            setHasError(true);
            setErrorMessage('reCAPTCHA verification failed. Check your site key configuration.');
          } else {
            setHasError(false);
            setErrorMessage(null);
          }

          return token;
        } catch (error: any) {
          console.error('[useCaptcha] reCAPTCHA execution error:', error);

          // Check for configuration errors
          const errorMessage = error?.message || String(error);
          if (errorMessage.includes('Invalid site key') ||
            errorMessage.includes('site key') ||
            errorMessage.includes('domain') ||
            errorMessage.includes('invalid')) {
            console.error('[useCaptcha] reCAPTCHA configuration error detected. Stopping retries.');
            permanentErrorRef.current = true;
            setHasError(true);
            setErrorMessage('reCAPTCHA configuration error: Invalid site key or domain not registered.');
          } else {
            setHasError(true);
            setErrorMessage('reCAPTCHA verification failed. Please try again.');
          }

          return null;
        }
      }

      if (CAPTCHA_PROVIDER === 'turnstile' && window.turnstile) {
        console.log('[useCaptcha] Executing Turnstile invisible widget with action:', action);
        // Turnstile explicit rendering - create invisible widget that executes automatically
        return new Promise<string | null>((resolve) => {
          const container = document.createElement('div');
          // Important: Do not use display: none or completely hide off-screen
          // Turnstile "execute" mode is invisible but needs a visible container for the challenge iframe if required
          container.style.position = 'fixed';
          container.style.top = '50%';
          container.style.left = '50%';
          container.style.transform = 'translate(-50%, -50%)';
          container.style.zIndex = '9999';
          // container.style.visibility = 'hidden'; // Removed to allow challenge visibility

          document.body.appendChild(container);

          let resolved = false;
          let currentWidgetId: string | null = null;

          const cleanup = () => {
            if (currentWidgetId && window.turnstile) {
              try {
                window.turnstile.remove(currentWidgetId);
              } catch (e) {
                console.error('Error removing Turnstile widget:', e);
              }
            }
            if (document.body.contains(container)) {
              document.body.removeChild(container);
            }
          };

          try {
            // Render widget with automatic execution
            if (!window.turnstile) {
              throw new Error('Turnstile not available');
            }
            currentWidgetId = window.turnstile.render(container, {
              sitekey: TURNSTILE_SITE_KEY,
              callback: (token: string) => {
                console.log('Turnstile callback received, token length:', token?.length);
                if (!resolved && token) {
                  resolved = true;
                  cleanup();
                  resolve(token);
                }
              },
              'error-callback': (error: any) => {
                console.error('Turnstile error callback:', error);
                if (!resolved) {
                  resolved = true;
                  cleanup();
                  resolve(null);
                }
              },
              execution: 'execute', // Execute challenge automatically
              appearance: 'execute', // Invisible, executes automatically
              theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
            });

            console.log('Turnstile widget rendered with ID:', currentWidgetId);

            // Poll for response as fallback (callback might not fire)
            let pollCount = 0;
            const maxPolls = 30; // 15 seconds total (30 * 500ms)
            const pollInterval = setInterval(() => {
              if (resolved) {
                clearInterval(pollInterval);
                return;
              }

              pollCount++;
              if (currentWidgetId && window.turnstile) {
                try {
                  const response = window.turnstile.getResponse(currentWidgetId);
                  if (response) {
                    console.log('Got Turnstile response via polling:', response.substring(0, 20) + '...');
                    clearInterval(pollInterval);
                    resolved = true;
                    cleanup();
                    resolve(response);
                    return;
                  }
                } catch {
                  // Ignore errors during polling
                }
              }

              if (pollCount >= maxPolls) {
                clearInterval(pollInterval);
                if (!resolved) {
                  console.warn('Turnstile execution timeout - no token received after polling');
                  resolved = true;
                  cleanup();
                  resolve(null);
                }
              }
            }, 500);

            // Timeout after 15 seconds (increased for slower connections)
            setTimeout(() => {
              clearInterval(pollInterval);
              if (!resolved) {
                console.warn('Turnstile execution timeout - no token received');
                resolved = true;
                cleanup();
                resolve(null);
              }
            }, 15000);
          } catch (error) {
            console.error('Error rendering Turnstile widget:', error);
            cleanup();
            resolve(null);
          }
        });
      }
    } catch (error) {
      console.error('Captcha execution failed:', error);
      return null;
    }

    return null;
  }, [isLoaded, isEnabled]);

  const getProviderName = useCallback((): string => {
    if (CAPTCHA_PROVIDER === 'recaptcha_v3') return 'reCAPTCHA';
    if (CAPTCHA_PROVIDER === 'turnstile') return 'Cloudflare Turnstile';
    return '';
  }, []);

  const getPrivacyUrl = useCallback((): string => {
    if (CAPTCHA_PROVIDER === 'recaptcha_v3') return 'https://policies.google.com/privacy';
    if (CAPTCHA_PROVIDER === 'turnstile') return 'https://www.cloudflare.com/privacypolicy/';
    return '';
  }, []);

  const getTermsUrl = useCallback((): string => {
    if (CAPTCHA_PROVIDER === 'recaptcha_v3') return 'https://policies.google.com/terms';
    if (CAPTCHA_PROVIDER === 'turnstile') return 'https://www.cloudflare.com/website-terms/';
    return '';
  }, []);

  // Check if provider uses visible widget
  const useVisibleWidget = CAPTCHA_PROVIDER === 'turnstile';
  console.log('[useCaptcha] useVisibleWidget:', useVisibleWidget, 'provider:', CAPTCHA_PROVIDER);

  return {
    executeCaptcha,
    isLoaded,
    isEnabled,
    provider: CAPTCHA_PROVIDER,
    providerName: getProviderName(),
    privacyUrl: getPrivacyUrl(),
    termsUrl: getTermsUrl(),
    useVisibleWidget, // true for Turnstile, false for reCAPTCHA v3
    hasError, // Error state
    errorMessage, // Error message if any
    hasPermanentError: () => permanentErrorRef.current, // Check if error is permanent
    resetError: () => {
      // Reset error state (for manual retry)
      permanentErrorRef.current = false;
      loadingAttemptedRef.current = false;
      setHasError(false);
      setErrorMessage(null);
    },
  };
}
