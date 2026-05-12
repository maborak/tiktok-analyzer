import { useEffect, useState } from 'react';
import { Link, createLazyFileRoute, useParams } from '@tanstack/react-router';
import { EyeOff, Loader2, SearchX } from 'lucide-react';

import { TikTokLiveDetail } from '@admin/pages/TikTokLiveDetail';
import { TikTokApiProvider } from '@admin/contexts/TikTokApiContext';
import type { TikTokApi } from '@admin/contexts/TikTokApiContext';
import { publicTiktokApi } from '@/modules/public/services/publicTiktok';

type GateState =
  | { phase: 'loading' }
  | { phase: 'public' }
  | { phase: 'private'; handle: string }
  | { phase: 'not_found'; handle: string };

/** Public deep-dive route for a single host — `/lives/$handle`.
 *
 *  Visual page is the same `TikTokLiveDetail` as `/admin/tiktok/$handle`
 *  with two flags: `<TikTokApiProvider value={publicTiktokApi}>` swaps
 *  every sub-component's API calls to `/public/tiktok/*`, and
 *  `readOnly` hides admin-write affordances.
 *
 *  Privacy gate: we call `getLiveStatus(handle)` which returns one of
 *  `public` | `private` | `not_found`. The three branches render
 *  distinct UIs (no redirect — the operator's audience needs to know
 *  *why* they're not seeing the page). 30s polling inside the detail
 *  page also re-checks the underlying data endpoints; if the host
 *  goes private mid-session, those calls 404 and the user can refresh
 *  to land on the "private" message. */
function PublicLiveDetailRoute() {
  const { handle } = useParams({ from: '/_public/lives/$handle' });
  const [state, setState] = useState<GateState>({ phase: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: 'loading' });
    publicTiktokApi.getLiveStatus(handle).then((r) => {
      if (cancelled) return;
      if (r.status === 'public') setState({ phase: 'public' });
      else if (r.status === 'private') setState({ phase: 'private', handle: r.handle || handle });
      else setState({ phase: 'not_found', handle: r.handle || handle });
    });
    return () => { cancelled = true; };
  }, [handle]);

  if (state.phase === 'loading') {
    return (
      <div className="py-16 text-center text-sm text-gray-500">
        <Loader2 className="w-4 h-4 inline animate-spin mr-2" />
        Loading…
      </div>
    );
  }

  if (state.phase === 'private') {
    return (
      <PublicGateMessage
        icon={<EyeOff className="w-12 h-12 text-amber-500" strokeWidth={1.5} />}
        title="This live is currently private"
        body={
          <>
            <span className="font-mono">@{state.handle}</span> exists on this server but the operator has not opted in to public viewing yet. Check back later, or ask the operator to flip <span className="font-mono">is_public</span> on in the admin console.
          </>
        }
      />
    );
  }

  if (state.phase === 'not_found') {
    return (
      <PublicGateMessage
        icon={<SearchX className="w-12 h-12 text-gray-400" strokeWidth={1.5} />}
        title="No tracked live for this handle"
        body={
          <>
            We don't have <span className="font-mono">@{state.handle}</span> in our subscription list. Double-check the spelling, or browse the public lives below.
          </>
        }
      />
    );
  }

  return (
    <TikTokApiProvider value={publicTiktokApi as unknown as TikTokApi}>
      <TikTokLiveDetail readOnly />
    </TikTokApiProvider>
  );
}

function PublicGateMessage({ icon, title, body }: { icon: React.ReactNode; title: string; body: React.ReactNode }) {
  return (
    <div className="py-24 flex flex-col items-center text-center max-w-xl mx-auto">
      <div className="mb-6">{icon}</div>
      <h1 className="auth-mono-label text-lg mb-3">{title}</h1>
      <p className="text-sm text-gray-600 mb-8 leading-relaxed">{body}</p>
      <Link
        to="/"
        className="auth-mono-label text-xs px-4 py-2 border border-gray-300 rounded-md hover:bg-gray-50"
      >
        ← Back to lives
      </Link>
    </div>
  );
}

export const Route = createLazyFileRoute('/_public/lives/$handle')({
  component: PublicLiveDetailRoute,
});
