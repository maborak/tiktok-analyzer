import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Radio, History as HistoryIcon, Check } from 'lucide-react';

import type { TikTokRoom } from '@admin/services/tiktok';
import {
  useTikTokTimezone,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';

interface BroadcastSelectorProps {
  rooms: TikTokRoom[];
  selectedRoomId: string | null;
  onChange: (roomId: string) => void;
  /** Returns true when the room should be considered active (live now). */
  isLiveRoom?: (room: TikTokRoom) => boolean;
}

/**
 * Visually rich dropdown for picking a past broadcast.
 *
 * Each row shows:
 *   - LIVE badge (red, pulsing) when the broadcast is currently active
 *   - Date / time it started (relative for today, absolute otherwise)
 *   - Duration (or "running" if live)
 *   - Subtle highlight on the currently-selected entry
 *
 * Closes on outside click / Escape. Renders inline (not a portal) so it
 * follows the trigger button in the page layout.
 */
export function TikTokBroadcastSelector({
  rooms,
  selectedRoomId,
  onChange,
  isLiveRoom,
}: BroadcastSelectorProps) {
  const { tz } = useTikTokTimezone();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const selected = rooms.find((r) => r.room_id === selectedRoomId) ?? null;
  const selectedIsLive = !!(selected && isLiveRoom?.(selected));

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-2 rounded-md border border-gray-200 bg-white hover:border-gray-300 transition-colors text-sm w-full sm:min-w-[16rem] sm:w-auto min-w-0"
      >
        {selectedIsLive ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-rose-500 text-white text-[10px] font-mono shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
            LIVE
          </span>
        ) : (
          <HistoryIcon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        )}
        <span className="font-medium text-gray-900 flex-1 text-left truncate min-w-0">
          {selected ? broadcastLabel(selected, selectedIsLive, tz) : 'No broadcast'}
        </span>
        {/* Hidden on phones — the selector trigger is already cramped on
            mobile, the count is redundant with the dropdown header. */}
        <span className="hidden sm:inline text-[10px] text-gray-400 font-mono shrink-0">
          {rooms.length} broadcast{rooms.length === 1 ? '' : 's'}
        </span>
        <ChevronDown
          className={
            'w-4 h-4 text-gray-400 transition-transform shrink-0 ' + (open ? 'rotate-180' : '')
          }
        />
      </button>

      {open && (
        <div
          className="absolute z-50 left-0 right-0 sm:right-auto mt-1 w-auto sm:w-[26rem] max-w-[calc(100vw-2rem)] rounded-lg border border-gray-200 bg-white shadow-lg overflow-hidden"
          role="listbox"
        >
          <div className="max-h-96 overflow-y-auto">
            {rooms.length === 0 && (
              <div className="px-4 py-6 text-center text-sm text-gray-500">
                No broadcasts recorded yet.
              </div>
            )}
            {rooms.map((r, idx) => {
              const isLive = !!isLiveRoom?.(r);
              const isSelected = r.room_id === selectedRoomId;
              return (
                <button
                  key={r.room_id}
                  type="button"
                  onClick={() => {
                    onChange(r.room_id);
                    setOpen(false);
                  }}
                  // The previous `hover:bg-gray-50` was so close to
                  // the panel white it was effectively invisible.
                  // `gray-100` + a left accent strip gives a clear
                  // "this row is under your cursor" cue without
                  // competing with the selected-row indicator.
                  className={
                    'w-full text-left px-3 py-2.5 flex items-start gap-3 ' +
                    'transition-colors border-b border-gray-50 last:border-0 ' +
                    'border-l-2 ' +
                    (isSelected
                      ? 'bg-primary-50 hover:bg-primary-100 dark:bg-primary-500/10 ' +
                        'border-l-primary-500'
                      : 'border-l-transparent hover:bg-gray-100 dark:hover:bg-gray-100/40 ' +
                        'hover:border-l-primary-400')
                  }
                  role="option"
                  aria-selected={isSelected}
                >
                  {/* Status badge */}
                  <div className="pt-0.5 shrink-0">
                    {isLive ? (
                      <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-rose-500 text-white">
                        <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
                      </span>
                    ) : (
                      <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-gray-100 text-gray-400">
                        <Radio className="w-3.5 h-3.5" />
                      </span>
                    )}
                  </div>

                  {/* Body */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <div className="font-medium text-sm truncate">
                        {formatStarted(r.first_seen_at, tz)}
                        {idx === 0 && (
                          <span className="ml-2 text-[10px] font-mono text-gray-400 uppercase">
                            most recent
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-xs text-gray-500 shrink-0">
                        {isLive
                          ? 'running'
                          : formatDuration(r.first_seen_at, r.ended_at ?? r.last_seen_at)}
                      </div>
                    </div>
                    <div className="mt-0.5 text-[11px] font-mono text-gray-400 truncate">
                      {r.title || `Room ${r.room_id}`}
                    </div>
                    {/* Per-broadcast rollups: 💎 / ⚔ / ❤. Each chip is
                        only rendered when it has a non-zero value so
                        empty/early rooms don't get a row of zeros. */}
                    {(r.diamonds || r.matches || r.likes) ? (
                      <div className="mt-1 flex items-center gap-1 flex-wrap text-[10px] font-mono">
                        {!!r.diamonds && (
                          <span
                            title="Total diamonds across all gifts"
                            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                          >
                            💎 {compactCount(r.diamonds)}
                          </span>
                        )}
                        {!!r.matches && (
                          <span
                            title="PK / link-mic battles in this broadcast"
                            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
                          >
                            ⚔ {compactCount(r.matches)}
                          </span>
                        )}
                        {!!r.likes && (
                          <span
                            title="Peak observed like counter (TikTok's cumulative LikeEvent.total)"
                            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300"
                          >
                            ❤ {compactCount(r.likes)}
                          </span>
                        )}
                      </div>
                    ) : null}
                  </div>

                  {/* Selected check */}
                  {isSelected && (
                    <Check className="w-4 h-4 text-primary-600 shrink-0 mt-1" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── helpers ───────────────────────────────────────────────────────

function broadcastLabel(r: TikTokRoom, isLive: boolean, tz: string): string {
  const when = formatStarted(r.first_seen_at, tz);
  if (isLive) return `${when} · LIVE NOW`;
  const dur = formatDuration(r.first_seen_at, r.ended_at ?? r.last_seen_at);
  return `${when} · ${dur}`;
}

function formatStarted(iso: string | null, tz: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  // Compute "Today / Yesterday / N days ago" using calendar dates in
  // the SELECTED zone — otherwise a viewer on May 8 in their browser
  // but May 9 in the selected zone would see "Today" mismatched.
  const dParts = partsInZone(d, tz);
  const nowParts = partsInZone(new Date(), tz);
  const dEpochDay =
    Date.UTC(dParts.year, dParts.month - 1, dParts.day) / 86_400_000;
  const nowEpochDay =
    Date.UTC(nowParts.year, nowParts.month - 1, nowParts.day) / 86_400_000;
  const diffDays = Math.floor(nowEpochDay - dEpochDay);

  const time = `${pad(dParts.hour)}:${pad(dParts.minute)}`;
  if (diffDays === 0) return `Today, ${time}`;
  if (diffDays === 1) return `Yesterday, ${time}`;
  // Anything older: always show the actual date so "which Tuesday?"
  // can't be ambiguous. Short weekday prefix is just a quick hint.
  const dow = d.toLocaleDateString(undefined, { timeZone: tz, weekday: 'short' });
  const monthName = d.toLocaleDateString(undefined, { timeZone: tz, month: 'long' });
  if (dParts.year === nowParts.year) {
    return `${dow} ${dParts.day} of ${monthName}, ${time}`;
  }
  return `${dow} ${dParts.day} of ${monthName} ${dParts.year}, ${time}`;
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '—';
  const a = new Date(start).getTime();
  const b = end ? new Date(end).getTime() : Date.now();
  const sec = Math.max(0, Math.floor((b - a) / 1000));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${pad(s)}s`;
  return `${s}s`;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

/** Compact count for the dropdown chips: 12,345 → 12.3k, 1.2M, etc.
 *  Keeps each pill narrow so three chips fit on one row even on a
 *  16-rem dropdown. */
function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}k`;
  return n.toLocaleString();
}
