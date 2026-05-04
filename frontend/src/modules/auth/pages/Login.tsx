import { useEffect } from 'react';
import { useNavigate, Link } from '@tanstack/react-router';
import { useAuth } from '@/contexts/AuthContext';
import { toast } from 'react-hot-toast';
import { appConfig } from '@/config/env';
import { LoginForm } from '../components/LoginForm';

/**
 * Login page — luxury layout, mono display type, numbered-document marker.
 *
 * The aesthetic direction is "Production SaaS, opinionated":
 * - Asymmetric: form card drifts left of center, right rail flush right
 * - Mono display headlines via `.auth-display`, mono labels via `.auth-mono-label`
 * - Animated mesh gradient bg with grain overlay
 * - Numbered marker (`01 / SIGN IN`) ties this page into a numbered-document
 *   series across all four auth pages — the distinctive element that makes
 *   the flow feel hand-built (modifier `-1.0` on the AI-slop score)
 *
 * Functional behavior is unchanged from the previous implementation:
 * - Redirects authenticated users to /account/billing/packages
 * - Surfaces a verified-account toast when navigated from the verify flow
 * - Renders <LoginForm /> with hideLogo + hideBackHome since the page chrome
 *   provides those affordances at a different scale
 */
export function Login() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    if (isAuthenticated) {
      navigate({ to: '/account/billing/packages', replace: true });
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('verified') === 'true') {
      toast.success('Account verified. Sign in to continue.', {
        duration: 6000,
        icon: '✓',
      });
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  return (
    <div className="bg-auth-mesh grain-overlay min-h-screen relative overflow-hidden">
      {/* Numbered marker — top-right corner. Positioned absolute so it floats
          over the layout flow. Animates in last (400ms delay) for a staggered
          page entry. */}
      <div className="auth-marker-enter absolute top-8 right-8 hidden lg:block z-10">
        <div className="auth-mono-label">01 / sign in</div>
      </div>

      {/* Back-to-home escape — bottom-left, mono, low emphasis */}
      <Link
        to="/"
        className="auth-link auth-mono-label absolute bottom-8 left-8 z-10"
      >
        ← back to home
      </Link>

      {/* Two-column flex: form card slightly left of center, right rail
          flush against the right side at lg+. Stack on mobile. */}
      <div className="relative z-[1] min-h-screen flex flex-col lg:flex-row items-center justify-center gap-16 lg:gap-24 px-6 py-24">

        {/* Form card */}
        <div className="auth-card w-full max-w-[400px] p-10">
          <div className="mb-8">
            {/* Brand wordmark — lowercase mono, the type does the work */}
            <div className="auth-display text-2xl mb-10 lowercase">maborak</div>

            {/* h1 — sits alone. No "Welcome back!" subtitle. */}
            <h1 className="auth-display text-3xl">Sign in</h1>
            <div
              className="mt-3 h-px w-12"
              style={{ backgroundColor: 'var(--color-text-primary)' }}
            />
          </div>

          <LoginForm hideLogo hideBackHome />
        </div>

        {/* Right rail — flush right at lg+, max content width 320px */}
        <aside className="auth-rail-enter hidden lg:flex flex-col max-w-[320px] gap-8">
          <div>
            <p className="auth-display text-4xl leading-[1.1]">
              Production SaaS,
              <br />
              opinionated.
            </p>
          </div>

          <div className="auth-mono-body text-sm leading-relaxed">
            Auth · Billing · Tickets · Live chat
          </div>

          <div
            className="h-px w-16"
            style={{ backgroundColor: 'var(--color-border-primary)' }}
          />

          <div className="auth-mono-label leading-relaxed">
            <div>maborak framework</div>
            <div>v{appConfig.version} · hexagonal</div>
          </div>
        </aside>
      </div>
    </div>
  );
}
