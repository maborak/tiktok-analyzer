import { Link } from '@tanstack/react-router';
import { Radio, ArrowRight, LogIn } from 'lucide-react';

import { appConfig } from '@/config/env';

/** Anonymous landing page at `/`.
 *
 *  Two-sentence pitch + a single primary CTA into the public lives
 *  index at `/lives`. A secondary "Sign in" link points at `/login`
 *  for operators returning to the admin shell. Deliberately spare —
 *  the goal is to give anonymous visitors a one-click path to the
 *  live-stream browser, not to be a marketing page.
 *
 *  Renders inside the shared `_public.tsx` Layout chrome (sidebar +
 *  topbar), so the page itself just supplies the centered hero. */
export function Landing() {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center px-6 py-12">
      <div className="max-w-2xl w-full text-center">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-primary-50 dark:bg-primary-500/10 mb-6">
          <Radio className="w-7 h-7 text-primary-600 dark:text-primary-300" />
        </div>

        <h1
          className="text-3xl sm:text-4xl font-bold tracking-tight mb-4 text-gray-900"
          style={{ fontFamily: 'var(--font-mono-display)' }}
        >
          Live-stream battle telemetry for{' '}
          <span className="text-primary-600 dark:text-primary-400">
            TikTok creators
          </span>
        </h1>

        <p className="text-base text-gray-600 leading-relaxed mb-10 max-w-xl mx-auto">
          {appConfig.name} watches PK battles in real time and surfaces
          who's winning, who's gifting, and how the score moves across
          every monitored broadcast. Browse the public scoreboard below
          — no account required.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to="/lives"
            className="inline-flex items-center justify-center gap-2 px-5 py-3 rounded-md bg-primary-600 text-white text-sm font-semibold tracking-wide hover:bg-primary-700 transition-colors shadow-sm w-full sm:w-auto"
          >
            Browse live streams
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/login"
            className="inline-flex items-center justify-center gap-1.5 px-4 py-3 text-sm text-gray-600 hover:text-gray-900 transition-colors"
          >
            <LogIn className="w-3.5 h-3.5" />
            Operator sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
