import { useEffect, useMemo, useState } from 'react';
import { Activity, Radio, Star, X } from 'lucide-react';
import { Link } from '@tanstack/react-router';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { SafeAvatar } from '@admin/components/SafeAvatar';
import { TikTokGifterModal } from '@admin/components/TikTokGifterModal';
import { TikTokCommonGifterDetailModal } from '@admin/components/TikTokCommonGifterDetailModal';
import { useTikTokApi } from '@admin/contexts/TikTokApiContext';
import { useTikTokRuntimeConfig } from '@admin/contexts/TikTokRuntimeConfigContext';

/** Unified gifter-detail shell. Wraps the two existing per-scope
 *  modals — the in-scope one (`TikTokGifterModal`, gifts/comments/
 *  relationships/matches scoped to a broadcast / day / window / all-
 *  time) and the cross-host one (`TikTokCommonGifterDetailModal`,
 *  profile/timeline/hosts/comments/behavior/network) — under a single
 *  Modal with a two-tab strip:
 *
 *    [Current]   [Profile]
 *
 *  Both inner modals are rendered with `embedded={true}` so they
 *  contribute only their body content — no Modal chrome, no per-modal
 *  identity row, no per-modal footer. The unified shell supplies the
 *  shared identity header at the top and a single Close in the footer.
 *
 *  Tab visibility:
 *    - `Current` is shown when a broadcast/day/all-time scope was
 *      passed in (`roomId` non-null OR `extraRoomIds` non-empty).
 *    - `Profile` is always shown. The public page has a mirror at
 *      `/public/tiktok/common-gifters/{user_id}/detail` that returns
 *      the same payload, so anonymous viewers also get the deep-
 *      analysis tab.
 *    - If only one tab applies, the strip is hidden and that tab's
 *      body renders directly.
 *
 *  `defaultTab` ('current' | 'profile') picks the initial tab; if the
 *  requested tab isn't available it falls through to whichever IS. */
interface UnifiedProps {
  isOpen: boolean;
  onClose: () => void;
  /** Gifter identity. `userId` is the canonical key; the inner modals
   *  treat a `null` userId as "no fetch" and render empty states. */
  userId: string | null;
  uniqueId?: string | null;
  nickname?: string | null;
  avatarUrl?: string | null;
  /** Sticky Enigma flag — when TRUE, renders an ENIGMA badge next to
   *  the profile name in the modal header. Passed through from the
   *  calling table row. */
  isEnigma?: boolean;
  /** Headline diamonds / gifts / comments from the leaderboard row
   *  the user just clicked. Threaded straight to the Current tab so
   *  its scope banner matches the table without an extra fetch. */
  diamondsTotal?: number;
  giftsCount?: number;
  commentsCount?: number;

  /* ───────── Current-scope context (forwarded to TikTokGifterModal) */
  roomId?: string | null;
  extraRoomIds?: string[];
  roomSetLabel?: string;
  windowSince?: string | null;
  windowUntil?: string | null;
  windowLabel?: string;
  currentHandle?: string;
  /** Inner tab pre-selection for the Current view (gifts / comments /
   *  relationships / matches). Forwarded as `defaultTab`. */
  currentInnerTab?: 'gifts' | 'comments' | 'relationships' | 'matches';

  /* ───────── Shell controls */
  /** Which top-level tab is active on open. Defaults to 'current'
   *  when a scope is provided, else 'profile'. */
  defaultTab?: 'current' | 'profile';
  /** Public / read-only context. Hides the Profile tab (admin-only
   *  backend) and forwards `readOnly` to the Current view so its
   *  admin-write affordances stay suppressed. */
  readOnly?: boolean;
}

type ShellTab = 'current' | 'profile';

export function TikTokGifterDetailModal({
  isOpen,
  onClose,
  userId,
  uniqueId,
  nickname,
  avatarUrl,
  isEnigma,
  diamondsTotal,
  giftsCount,
  commentsCount,
  roomId,
  extraRoomIds,
  roomSetLabel,
  windowSince,
  windowUntil,
  windowLabel,
  currentHandle,
  currentInnerTab,
  defaultTab,
  readOnly = false,
}: UnifiedProps) {
  const hasScope = useMemo(() => {
    if (roomId) return true;
    if (extraRoomIds && extraRoomIds.length > 0) return true;
    if (windowSince || windowUntil) return true;
    return false;
  }, [roomId, extraRoomIds, windowSince, windowUntil]);

  const currentAvailable = hasScope;
  // Profile renders for both audiences — admin hits
  // `/admin/tiktok/common-gifters/{id}/detail`, public hits the
  // mirror at `/public/tiktok/common-gifters/{id}/detail`. The
  // surrounding `TikTokApiProvider` decides which namespace the
  // inner modal calls into.
  const profileAvailable = true;

  // Resolve initial tab. If the caller asked for a tab that isn't
  // available, fall through to the other one. This keeps a single
  // "open" code path at every call site — TikTokLives doesn't have
  // to remember to send 'profile' when its row has no roomId.
  const resolveInitial = (): ShellTab => {
    const requested: ShellTab = defaultTab ?? (currentAvailable ? 'current' : 'profile');
    if (requested === 'current' && !currentAvailable) return 'profile';
    if (requested === 'profile' && !profileAvailable) return 'current';
    return requested;
  };

  const [tab, setTab] = useState<ShellTab>(resolveInitial);

  // Re-resolve when the open transition happens. Switching gifters
  // without closing the shell (rare but possible) shouldn't keep the
  // last user's tab if the new user's scope is different.
  useEffect(() => {
    if (!isOpen) return;
    setTab(resolveInitial());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, userId, currentAvailable, profileAvailable, defaultTab]);

  const showTabStrip = currentAvailable && profileAvailable;

  // "Go to Live" affordance — if the gifter's @handle is also one of
  // our monitored hosts (i.e. appears in the subscriptions list), the
  // operator can jump straight to that host's live-detail page. The
  // check uses listLives() which is heavily cached by apiRequest's
  // in-flight dedupe / TTL cache, and is skipped on the public
  // audience (listLives is admin-only).
  const tiktokApi = useTikTokApi();
  const { audience } = useTikTokRuntimeConfig();
  const isAdmin = audience === 'admin';
  const [isMonitored, setIsMonitored] = useState<boolean>(false);
  useEffect(() => {
    if (!isAdmin || !isOpen || !uniqueId) {
      setIsMonitored(false);
      return;
    }
    let cancelled = false;
    tiktokApi
      .listLives()
      .then((rows) => {
        if (cancelled) return;
        const handle = uniqueId.toLowerCase();
        setIsMonitored(rows.some((r) => r.unique_id?.toLowerCase() === handle));
      })
      .catch(() => {
        // Silent — falls back to "not monitored", hiding the button.
      });
    return () => { cancelled = true; };
  }, [isOpen, uniqueId, isAdmin, tiktokApi]);

  // Lightweight fetch of `enigma_aliases` for the modal header. The
  // inner CommonGifterDetailModal already fetches the same endpoint
  // for the Profile tab; both calls dedupe to one round-trip via
  // `getCommonGifterDetail`'s cacheTtlMs + dedupe options.
  // Falls back to the `isEnigma` prop value when the fetch hasn't
  // resolved yet (or fails) so the badge appears immediately.
  const [enigmaAliases, setEnigmaAliases] = useState<string[]>([]);
  const [enigmaFromFetch, setEnigmaFromFetch] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    if (!isOpen || !userId) {
      setEnigmaAliases([]);
      setEnigmaFromFetch(undefined);
      return;
    }
    let cancelled = false;
    tiktokApi
      .getCommonGifterDetail(userId)
      .then((d) => {
        if (cancelled) return;
        setEnigmaAliases(Array.isArray(d?.enigma_aliases) ? d.enigma_aliases : []);
        setEnigmaFromFetch(!!d?.is_enigma);
      })
      .catch(() => {
        // 404 → no event history for this user_id; treat as empty.
      });
    return () => { cancelled = true; };
  }, [isOpen, userId, tiktokApi]);
  const enigmaResolved = enigmaFromFetch ?? isEnigma;

  // The shared identity row at the top. Both inner modals suppress
  // their own identity headers in embedded mode, so this is the sole
  // place identity appears. We only show fields we have — no
  // placeholder text — so a public viewer who only knows
  // (nickname, userId) doesn't see "@undefined" or "0 diamonds".
  const headerStats: { label: string; value: string }[] = [];
  if (typeof diamondsTotal === 'number' && diamondsTotal > 0) {
    headerStats.push({ label: 'Diamonds', value: diamondsTotal.toLocaleString() });
  }
  if (typeof giftsCount === 'number' && giftsCount > 0) {
    headerStats.push({ label: 'Gifts', value: giftsCount.toLocaleString() });
  }
  if (typeof commentsCount === 'number' && commentsCount > 0) {
    headerStats.push({ label: 'Comments', value: commentsCount.toLocaleString() });
  }

  const displayName = nickname || (uniqueId ? `@${uniqueId}` : 'Unknown gifter');
  const avatarChar = (nickname || uniqueId || '?').trim().charAt(0).toUpperCase();

  const header = (
    <div className="flex items-start justify-between gap-4 pb-3 mb-3 border-b border-gray-200">
      <div className="flex items-center gap-3 min-w-0">
        <SafeAvatar
          src={avatarUrl}
          alt=""
          size={40}
          className="flex-shrink-0"
          fallback={
            <span className="text-sm font-bold text-gray-600">{avatarChar}</span>
          }
        />
        <div className="min-w-0">
          <div className="text-base font-bold truncate">{displayName}</div>
          {uniqueId && nickname && (
            <div className="text-xs font-mono text-gray-500 truncate">@{uniqueId}</div>
          )}
          {userId && (
            <div className="text-[10px] font-mono text-gray-400 truncate">ID: {userId}</div>
          )}
          {/* Enigma aliases — visible regardless of which tab is
              active. Outer-header-only render (the inner
              CommonGifterDetailModal previously had a duplicate
              strip below the tabs; removed). Capped at 8 inline;
              the rest collapse into a "+N more" pill with the full
              list in the title. */}
          {enigmaResolved && enigmaAliases.length > 0 && (
            <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px] font-mono">
              <span className="text-gray-500">Seen as ({enigmaAliases.length}):</span>
              {enigmaAliases.slice(0, 8).map((alias) => (
                <span
                  key={alias}
                  className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-700 ring-1 ring-violet-200 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-500/30"
                >
                  {alias}
                </span>
              ))}
              {enigmaAliases.length > 8 && (
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 ring-1 ring-violet-300 dark:bg-violet-500/20 dark:text-violet-200 dark:ring-violet-500/40"
                  title={enigmaAliases.slice(8).join(', ')}
                >
                  +{enigmaAliases.length - 8} more
                </span>
              )}
            </div>
          )}
        </div>
      </div>
      {/* Right block stacks vertically on narrow screens (avatar + 3
          stats + Go-to-Live button used to all fit one row, crowding
          the identity column down to ~30 px and truncating the name).
          On sm+ they sit side-by-side again. */}
      <div className="flex flex-col items-end gap-1.5 flex-shrink-0 min-w-0">
        {headerStats.length > 0 && (
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 justify-end">
            {headerStats.map((s) => (
              <div key={s.label} className="text-right">
                <div className="text-[10px] font-mono uppercase tracking-wider text-gray-500">
                  {s.label}
                </div>
                <div className="text-sm font-bold tabular-nums">{s.value}</div>
              </div>
            ))}
          </div>
        )}
        {/* Go-to-Live shortcut — appears only when the viewer's @handle
            also belongs to a monitored host. Closes the modal on click
            so navigation isn't visually trapped behind the shell. */}
        {isMonitored && uniqueId && (
          <Link
            to="/admin/tiktok/$handle"
            params={{ handle: uniqueId }}
            onClick={onClose}
            className="inline-flex items-center gap-1.5 bg-primary-500 hover:bg-primary-600 text-white px-3 py-1.5 text-xs rounded-md font-medium transition-colors"
            title={`Open @${uniqueId}'s live page`}
          >
            <Radio className="w-3.5 h-3.5" />
            Go to Live
          </Link>
        )}
      </div>
    </div>
  );

  const tabStrip = showTabStrip && (
    <div
      role="tablist"
      className="flex items-center gap-1 mb-3 border-b border-gray-200"
    >
      <ShellTabButton active={tab === 'current'} onClick={() => setTab('current')}>
        <Activity className="w-3.5 h-3.5" />
        Current
      </ShellTabButton>
      <ShellTabButton active={tab === 'profile'} onClick={() => setTab('profile')}>
        <Star className="w-3.5 h-3.5" />
        Profile
      </ShellTabButton>
    </div>
  );

  const body = (
    <>
      {header}
      {tabStrip}
      {tab === 'current' && currentAvailable && (
        <TikTokGifterModal
          embedded
          isOpen={isOpen}
          onClose={onClose}
          userId={userId}
          uniqueId={uniqueId ?? null}
          nickname={nickname ?? null}
          diamondsTotal={diamondsTotal}
          giftsCount={giftsCount}
          commentsCount={commentsCount}
          roomId={roomId}
          extraRoomIds={extraRoomIds}
          roomSetLabel={roomSetLabel}
          windowSince={windowSince}
          windowUntil={windowUntil}
          windowLabel={windowLabel}
          currentHandle={currentHandle}
          defaultTab={currentInnerTab}
          readOnly={readOnly}
        />
      )}
      {tab === 'profile' && profileAvailable && (
        <TikTokCommonGifterDetailModal
          embedded
          isOpen={isOpen}
          onClose={onClose}
          userId={userId}
          initialNickname={nickname ?? null}
          initialUniqueId={uniqueId ?? null}
          initialAvatarUrl={avatarUrl ?? null}
        />
      )}
    </>
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Gifter details"
      className="max-w-4xl"
      footer={
        <div className="flex items-center justify-end w-full">
          <Button variant="ghost" onClick={onClose}>
            <X className="w-4 h-4 mr-1.5" />
            Close
          </Button>
        </div>
      }
    >
      {body}
    </Modal>
  );
}

interface ShellTabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function ShellTabButton({ active, onClick, children }: ShellTabButtonProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={
        'inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ' +
        (active
          ? 'border-primary-500 text-primary-700 dark:text-primary-300'
          : 'border-transparent text-gray-600 hover:text-gray-900')
      }
    >
      {children}
    </button>
  );
}
