import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  Loader2,
  Radio,
  ShieldAlert,
  User as UserIcon,
  UserCheck,
  UserMinus,
  Users,
  XCircle,
} from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import {
  type TikTokHandleLookup,
  type TikTokHandleLookupProfile,
  tiktokApi,
} from '@admin/services/tiktok';
import { SafeAvatar } from '@admin/components/SafeAvatar';

interface TikTokAddLiveModalProps {
  isOpen: boolean;
  handle: string;
  onCancel: () => void;
  /** Called when the operator confirms the preview. Receives the
   *  profile snapshot captured during lookup (when present) so the
   *  parent can thread it into `tiktokApi.createLive(handle, true,
   *  profile)` and skip a redundant SIGI / Euler probe. Older parents
   *  that ignore the argument keep their previous behaviour — the
   *  callback signature stays compatible via TS bivariance. */
  onConfirm: (profile?: TikTokHandleLookupProfile | null) => void | Promise<void>;
}

export function TikTokAddLiveModal({
  isOpen,
  handle,
  onCancel,
  onConfirm,
}: TikTokAddLiveModalProps) {
  const [data, setData] = useState<TikTokHandleLookup | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen || !handle) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setData(null);
    tiktokApi
      .lookupHandle(handle)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err) => {
        if (cancelled) return;
        setData({
          handle,
          exists: null,
          is_live: false,
          nickname: null,
          user_id: null,
          avatar_url: null,
          bio: null,
          follower_count: null,
          following_count: null,
          room_id: null,
          title: null,
          viewer_count: null,
          source: null,
          error: err?.message || 'Lookup failed',
          warning: null,
          already_subscribed: false,
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, handle]);

  const canConfirm = !loading && data?.exists !== false;

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      // Forward the captured profile so the parent can pass it to
      // `createLive` and skip a second backend scrape. `null` when
      // the lookup itself failed (network / 404) — parents should
      // fall back to the legacy two-arg create in that case.
      const profile: TikTokHandleLookupProfile | null = data
        ? {
            nickname: data.nickname,
            user_id: data.user_id,
            avatar_url: data.avatar_url,
            bio: data.bio,
            follower_count: data.follower_count,
            following_count: data.following_count,
          }
        : null;
      await Promise.resolve(onConfirm(profile));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      title={`Add @${handle}`}
      onClose={submitting ? undefined : onCancel}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleConfirm}
            disabled={!canConfirm || submitting}
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                Subscribing…
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4 mr-1" />
                Yes, subscribe
              </>
            )}
          </Button>
        </div>
      }
    >
      {loading && <LookupProgress handle={handle} />}
      {!loading && data && <LookupBody data={data} />}
    </Modal>
  );
}

// ─── views ─────────────────────────────────────────────────────────

/** Live progress steps shown while `tiktokApi.lookupHandle(...)` runs.
 *
 *  The backend lookup chain is `validate → SIGI scrape → (fallback)
 *  Euler call → DB check → preview`. We don't get progress events back
 *  over the wire, so the UI advances on elapsed-time heuristics tuned to
 *  the typical timings observed in the worker logs. The final step
 *  stays pending until the request resolves and the modal flips to the
 *  preview body — at which point the spinner unmounts entirely.
 *
 *  Worst-case overrun (slow Euler, retries) just leaves step 3
 *  spinning, which is the correct visual: we're still working. */
const LOOKUP_STEPS = [
  'Validating handle',
  'Fetching TikTok profile',
  'Checking live status',
  'Preparing preview',
] as const;

function LookupProgress({ handle }: { handle: string }) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    // Reset on each handle so reopening the modal for a different
    // user replays the animation instead of jumping straight to done.
    setStep(0);
    const t1 = setTimeout(() => setStep(1), 200);
    const t2 = setTimeout(() => setStep(2), 800);
    const t3 = setTimeout(() => setStep(3), 2000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [handle]);

  // Single indeterminate progress bar + current-step label. Replaces
  // a 4-row "wizard step list" that read as generic onboarding UI —
  // operator just needs to see "we're still working" + roughly where.
  // The bar width is driven by the same `step` counter (25/50/75/100%).
  const stepLabel = LOOKUP_STEPS[Math.min(step, LOOKUP_STEPS.length - 1)];
  const progressPct = Math.min(100, ((step + 1) / LOOKUP_STEPS.length) * 100);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs auth-mono-label text-gray-500">
        <span className="truncate">Looking up @{handle}</span>
        <span className="font-mono tabular-nums shrink-0">{stepLabel}…</span>
      </div>
      <div className="h-0.5 rounded-full bg-gray-200 dark:bg-gray-100/10 overflow-hidden">
        <div
          className="h-full bg-primary-500 transition-[width] duration-500 ease-out"
          style={{ width: `${progressPct}%` }}
        />
      </div>
    </div>
  );
}

function LookupBody({ data }: { data: TikTokHandleLookup }) {
  // Tri-state: TRUE / FALSE / null=unknown. Treat null as a separate
  // visual category so we don't lie about a user being offline when we
  // genuinely couldn't probe them.
  const live = data.is_live === true;
  const offline = data.exists === true && data.is_live === false;
  const unknown = data.exists === true && data.is_live === null;
  const notFound = data.exists === false;

  return (
    <div className="space-y-4">
      {/* Header: avatar + identity */}
      <div className="flex items-start gap-4">
        <SafeAvatar
          src={data.avatar_url}
          size={80}
          className="ring-4 ring-primary-100 shrink-0"
          fallback={
            notFound ? (
              <UserMinus className="w-8 h-8 text-rose-500 dark:text-rose-300" />
            ) : (
              <span className="font-mono text-3xl text-gray-500">
                {(data.handle[0] || '?').toUpperCase()}
              </span>
            )
          }
        />
        <div className="min-w-0 flex-1">
          <div className="text-xl font-bold truncate">
            {data.nickname || (notFound ? 'Unknown user' : `@${data.handle}`)}
          </div>
          <div className="text-sm font-mono text-gray-500 truncate">@{data.handle}</div>
          {data.user_id && (
            <div className="text-xs font-mono text-gray-400 mt-0.5 truncate">
              ID: {data.user_id}
            </div>
          )}
          <StatusBadges
            isLive={live}
            offline={offline}
            unknown={unknown}
            notFound={notFound}
            source={data.source}
            alreadySubscribed={data.already_subscribed}
          />
        </div>
      </div>

      {/* Bio */}
      {data.bio && (
        <p className="text-sm text-gray-700 leading-relaxed">
          {data.bio}
        </p>
      )}

      {/* Stat row */}
      {(data.follower_count != null || data.following_count != null) && (
        <div className="flex gap-2">
          {data.follower_count != null && (
            <StatPill icon={<Users className="w-3.5 h-3.5" />} label="Followers" value={fmtNum(data.follower_count)} />
          )}
          {data.following_count != null && (
            <StatPill icon={<UserCheck className="w-3.5 h-3.5" />} label="Following" value={fmtNum(data.following_count)} />
          )}
        </div>
      )}

      {/* Live-specific block */}
      {live && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-white mr-1 animate-pulse" />
              LIVE NOW
            </span>
            {data.viewer_count != null && (
              <span className="inline-flex items-center gap-1 text-sm font-mono text-rose-700 dark:text-rose-300">
                <Eye className="w-3.5 h-3.5" />
                {fmtNum(data.viewer_count)} watching
              </span>
            )}
          </div>
          {data.title && (
            <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {data.title}
            </div>
          )}
          {data.room_id && (
            <div className="text-[10px] font-mono text-gray-500 mt-1">
              Room {data.room_id}
            </div>
          )}
        </div>
      )}

      {/* Offline block */}
      {offline && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 flex items-center gap-2 text-sm text-gray-600">
          <Radio className="w-4 h-4 text-gray-400" />
          Currently offline. The bot will start tracking the moment they go live.
        </div>
      )}

      {/* Unknown-state block: TikTok blocked our probe. */}
      {unknown && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/30 p-3 flex items-start gap-2 text-sm text-amber-800 dark:text-amber-200">
          <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">Live status: unknown</div>
            <div className="text-xs mt-0.5">
              TikTok refused our preview probe (no session cookie). They might be live, might not — go check the public profile if you want certainty.
            </div>
          </div>
        </div>
      )}

      {/* Already-subscribed warning */}
      {data.already_subscribed && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/30 p-3 flex items-start gap-2 text-sm text-amber-800 dark:text-amber-200">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            You're already subscribed to <span className="font-mono">@{data.handle}</span>.
            Confirming will refresh the existing subscription's "enabled" flag.
          </div>
        </div>
      )}

      {/* Backend warning (e.g. age-restricted) */}
      {data.warning && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/30 p-3 flex items-start gap-2 text-sm text-amber-800 dark:text-amber-200">
          <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{data.warning}</div>
        </div>
      )}

      {/* Lookup error: user-not-found is fatal */}
      {notFound && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 p-3 flex items-start gap-2 text-sm text-rose-700 dark:text-rose-300">
          <XCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">User not found on TikTok</div>
            <div className="text-xs mt-0.5">
              Double-check the handle. Confirming would still write a subscription
              record, but there'd be nothing to listen to.
            </div>
          </div>
        </div>
      )}

      {/* Network / unknown error: warn but allow continue */}
      {!notFound && data.error && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 flex items-start gap-2 text-sm text-gray-600">
          <UserIcon className="w-4 h-4 mt-0.5 shrink-0 text-gray-400" />
          <div>
            <div className="font-medium">Couldn't reach TikTok for a preview</div>
            <div className="text-xs mt-0.5">{data.error}</div>
            <div className="text-xs mt-1 text-gray-500">
              You can still subscribe — the listener will start polling and pick
              up data as soon as TikTok responds.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

interface StatusBadgesProps {
  isLive: boolean;
  offline: boolean;
  unknown: boolean;
  notFound: boolean;
  source: string | null;
  alreadySubscribed: boolean;
}

function StatusBadges({
  isLive,
  offline,
  unknown,
  notFound,
  source,
  alreadySubscribed,
}: StatusBadgesProps) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {isLive && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-mono">
          <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
          LIVE
        </span>
      )}
      {offline && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-200 text-gray-700 dark:bg-gray-100/10 dark:text-gray-300 text-[10px] font-mono">
          <span className="w-1.5 h-1.5 rounded-full bg-gray-500 dark:bg-gray-400" />
          OFFLINE
        </span>
      )}
      {unknown && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300 text-[10px] font-mono">
          STATUS UNKNOWN
        </span>
      )}
      {notFound && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300 text-[10px] font-mono">
          NOT FOUND
        </span>
      )}
      {source === 'cache' && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 dark:bg-gray-100/10 dark:text-gray-400 text-[10px] font-mono">
          from cache
        </span>
      )}
      {alreadySubscribed && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300 text-[10px] font-mono">
          already added
        </span>
      )}
    </div>
  );
}

function StatPill({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-gray-200 bg-white text-xs">
      <span className="text-gray-400">{icon}</span>
      <span className="text-gray-500">{label}</span>
      <span className="font-mono font-semibold tabular-nums text-gray-900">{value}</span>
    </div>
  );
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}
