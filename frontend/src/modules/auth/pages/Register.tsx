import { useEffect } from 'react';
import { useNavigate, Link } from '@tanstack/react-router';
import { useAuth } from '@/contexts/AuthContext';
import { appConfig } from '@/config/env';
import { RegisterForm } from '../components/RegisterForm';

/**
 * Register page — luxury layout, mono display type, numbered-document marker.
 *
 * Two-column variant matching Login.tsx:
 * - Asymmetric: form card drifts left of center, right rail flush right
 * - Mono display headlines via `.auth-display`, mono labels via `.auth-mono-label`
 * - Animated mesh gradient bg with grain overlay
 * - Numbered marker (`02 / create account`) ties this into the auth document series
 *
 * Killed:
 * - Radar logo lockup + ArrowLeft back link
 * - bg-white hardcoded panel
 * - bg-gradient-to-br decorative blob right panel
 * - Bolivian-legal-AI copy (TrendingDown / Bell / BarChart3 icon tiles)
 * - "Create your account" / generic subtitle / "Free registration" footer
 *
 * Functional behavior preserved:
 * - Redirects authenticated users to /
 * - Passes onSuccess to RegisterForm for navigation to /registration-success
 */
export function Register() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    if (isAuthenticated) {
      navigate({ to: '/', replace: true });
    }
  }, [isAuthenticated, navigate]);

  return (
    <div className="bg-auth-mesh grain-overlay min-h-screen relative overflow-hidden">
      {/* Numbered marker — top-right corner, staggered entry */}
      <div className="auth-marker-enter absolute top-8 right-8 hidden lg:block z-10">
        <div className="auth-mono-label">02 / create account</div>
      </div>

      {/* Back link — bottom-left, mono, low emphasis */}
      <Link
        to="/login"
        className="auth-link auth-mono-label absolute bottom-8 left-8 z-10"
      >
        ← back to sign in
      </Link>

      {/* Two-column flex: form card + right rail */}
      <div className="relative z-[1] min-h-screen flex flex-col lg:flex-row items-center justify-center gap-16 lg:gap-24 px-6 py-24">

        {/* Form card */}
        <div className="auth-card w-full max-w-[400px] p-10">
          <div className="mb-8">
            <div className="auth-display text-2xl mb-10 lowercase">maborak</div>

            <h1 className="auth-display text-3xl">Create account</h1>
            <div
              className="mt-3 h-px w-12"
              style={{ backgroundColor: 'var(--color-text-primary)' }}
            />
          </div>

          <RegisterForm
            onSuccess={() => navigate({ to: '/registration-success' })}
          />
        </div>

        {/* Right rail — flush right at lg+, max content width 320px */}
        <aside className="auth-rail-enter hidden lg:flex flex-col max-w-[320px] gap-8">
          <div>
            <p className="auth-display text-4xl leading-[1.1]">
              Start shipping.
              <br />
              Today.
            </p>
          </div>

          <div className="auth-mono-body text-sm leading-relaxed">
            Free tier. No credit card. Ship from commit zero.
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
