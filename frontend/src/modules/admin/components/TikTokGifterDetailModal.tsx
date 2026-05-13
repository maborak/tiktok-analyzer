import { useEffect, useMemo, useState } from 'react';
import { Activity, Star, X } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { TikTokGifterModal } from '@admin/components/TikTokGifterModal';
import { TikTokCommonGifterDetailModal } from '@admin/components/TikTokCommonGifterDetailModal';

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
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt=""
            className="w-10 h-10 rounded-full object-cover flex-shrink-0"
          />
        ) : (
          <div className="w-10 h-10 rounded-full bg-gray-100 dark:bg-gray-100/30 flex items-center justify-center text-sm font-bold text-gray-600 flex-shrink-0">
            {avatarChar}
          </div>
        )}
        <div className="min-w-0">
          <div className="text-base font-bold truncate">{displayName}</div>
          {uniqueId && nickname && (
            <div className="text-xs font-mono text-gray-500 truncate">@{uniqueId}</div>
          )}
          {userId && (
            <div className="text-[10px] font-mono text-gray-400 truncate">ID: {userId}</div>
          )}
        </div>
      </div>
      {headerStats.length > 0 && (
        <div className="flex items-baseline gap-4 flex-shrink-0">
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
