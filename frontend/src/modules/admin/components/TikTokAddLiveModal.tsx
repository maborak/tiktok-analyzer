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
  tiktokApi,
} from '@admin/services/tiktok';

interface TikTokAddLiveModalProps {
  isOpen: boolean;
  handle: string;
  onCancel: () => void;
  onConfirm: () => void; // proceeds with creating the subscription
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
      await Promise.resolve(onConfirm());
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
      {loading && <LookupSkeleton />}
      {!loading && data && <LookupBody data={data} />}
    </Modal>
  );
}

// ─── views ─────────────────────────────────────────────────────────

function LookupSkeleton() {
  return (
    <div className="flex items-center gap-4 animate-pulse">
      <div className="w-20 h-20 rounded-full bg-gray-200 shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-5 w-1/2 bg-gray-200 rounded" />
        <div className="h-4 w-1/3 bg-gray-200 rounded" />
        <div className="h-4 w-2/3 bg-gray-200 rounded" />
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
        {data.avatar_url ? (
          <img
            src={data.avatar_url}
            alt=""
            className="w-20 h-20 rounded-full object-cover ring-4 ring-primary-100 shrink-0"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div
            className={
              'w-20 h-20 rounded-full flex items-center justify-center text-3xl font-bold shrink-0 ' +
              (notFound ? 'bg-rose-100 text-rose-500' : 'bg-gray-100 text-gray-400')
            }
          >
            {notFound ? <UserMinus className="w-8 h-8" /> : (data.handle[0] || '?').toUpperCase()}
          </div>
        )}
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
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-200 text-gray-700 text-[10px] font-mono">
          <span className="w-1.5 h-1.5 rounded-full bg-gray-500" />
          OFFLINE
        </span>
      )}
      {unknown && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-mono">
          STATUS UNKNOWN
        </span>
      )}
      {notFound && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 text-[10px] font-mono">
          NOT FOUND
        </span>
      )}
      {source === 'cache' && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 text-[10px] font-mono">
          from cache
        </span>
      )}
      {alreadySubscribed && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[10px] font-mono">
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
