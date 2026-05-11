/**
 * TikTok timezone context.
 *
 * One source of truth for "which IANA zone is this page rendering
 * timestamps in?". The zone defaults to the browser's local zone but
 * can be overridden by the user via the dropdown in the live-detail
 * profile header. Persists to localStorage so the choice survives
 * navigation + reload, and applies across every TikTok admin page.
 *
 * All persisted DB timestamps are UTC; this context only changes how
 * they're rendered. No write-side semantics ride on it.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

const LS_KEY = 'tiktok.tz.iana';

function detectBrowserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

interface TikTokTimezoneCtx {
  /** IANA zone string in effect, e.g. "America/Lima". */
  tz: string;
  /** The browser's auto-detected zone (read-only convenience). */
  browserTz: string;
  /** Set the active zone and persist it. */
  setTz: (zone: string) => void;
  /** Reset to whatever the browser reports. */
  resetTz: () => void;
}

const Ctx = createContext<TikTokTimezoneCtx | null>(null);

export function TikTokTimezoneProvider({ children }: { children: React.ReactNode }) {
  const browserTz = useMemo(detectBrowserTz, []);
  const [tz, setTzState] = useState<string>(() => {
    try {
      const stored = localStorage.getItem(LS_KEY);
      if (stored && stored.trim()) return stored;
    } catch {
      /* localStorage may be blocked — fall through */
    }
    return browserTz;
  });

  const setTz = useCallback((zone: string) => {
    setTzState(zone);
    try {
      localStorage.setItem(LS_KEY, zone);
    } catch {
      /* ignore */
    }
  }, []);

  const resetTz = useCallback(() => {
    setTzState(browserTz);
    try {
      localStorage.removeItem(LS_KEY);
    } catch {
      /* ignore */
    }
  }, [browserTz]);

  // Re-broadcast across tabs so a user changing the zone in one tab
  // sees the rest of their open admin tabs follow.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== LS_KEY) return;
      const next = e.newValue && e.newValue.trim() ? e.newValue : browserTz;
      setTzState(next);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [browserTz]);

  const value = useMemo<TikTokTimezoneCtx>(
    () => ({ tz, browserTz, setTz, resetTz }),
    [tz, browserTz, setTz, resetTz],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTikTokTimezone(): TikTokTimezoneCtx {
  const v = useContext(Ctx);
  if (!v) {
    // Defensive default: outside the provider, fall back to browser
    // local — keeps shared utilities (e.g., the calendar) usable in
    // contexts that haven't been wrapped yet.
    const browserTz = detectBrowserTz();
    return {
      tz: browserTz,
      browserTz,
      setTz: () => undefined,
      resetTz: () => undefined,
    };
  }
  return v;
}

// ── Formatters ─────────────────────────────────────────────────────
//
// All accept either an ISO string or a Date and return a string.
// Pass `tz` from the context. We deliberately don't `useContext`
// inside these helpers — they're called inside `useMemo` blocks and
// from non-component utility code, so they need to be pure functions
// of (date, tz). Components should call `useTikTokTimezone()` and
// pass `tz` through.

function asDate(input: string | Date | null | undefined): Date | null {
  if (input == null) return null;
  if (input instanceof Date) return Number.isFinite(input.getTime()) ? input : null;
  const d = new Date(input);
  return Number.isFinite(d.getTime()) ? d : null;
}

/** "HH:MM" in the given zone (24h). */
export function fmtHM(input: string | Date | null | undefined, tz: string): string {
  const d = asDate(input);
  if (!d) return '—';
  return d.toLocaleTimeString(undefined, {
    timeZone: tz,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** "Tue 6 May" (or locale equivalent) in the given zone. */
export function fmtShortDate(input: string | Date | null | undefined, tz: string): string {
  const d = asDate(input);
  if (!d) return '—';
  return d.toLocaleDateString(undefined, {
    timeZone: tz,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

/** "May 6, 14:32" in the given zone. */
export function fmtMonthDayTime(input: string | Date | null | undefined, tz: string): string {
  const d = asDate(input);
  if (!d) return '—';
  return d.toLocaleString(undefined, {
    timeZone: tz,
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Full "Wed May 6 2026, 14:32:05" — used in tooltips. */
export function fmtFull(input: string | Date | null | undefined, tz: string): string {
  const d = asDate(input);
  if (!d) return '—';
  return d.toLocaleString(undefined, {
    timeZone: tz,
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/** Returns a stable {year, month, day, hour, minute, second} block in
 *  the given zone, integers. Useful when you need to compute on the
 *  zone-shifted parts (e.g., "is this date the same as that one in
 *  this zone?") rather than render a string. */
export function partsInZone(
  input: string | Date,
  tz: string,
): { year: number; month: number; day: number; hour: number; minute: number; second: number } {
  const d = asDate(input);
  if (!d) {
    return { year: 0, month: 0, day: 0, hour: 0, minute: 0, second: 0 };
  }
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const parts: Record<string, string> = {};
  for (const p of fmt.formatToParts(d)) {
    if (p.type !== 'literal') parts[p.type] = p.value;
  }
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour) % 24, // "24" can sneak in for midnight in some locales
    minute: Number(parts.minute),
    second: Number(parts.second),
  };
}

/** YYYY-MM-DD bucketing key in the given zone. Used by the calendar
 *  + day-aggregate logic so "what day is this event on" honours the
 *  user's selected zone. */
export function dateKeyInZone(input: string | Date, tz: string): string {
  const p = partsInZone(input, tz);
  return `${p.year.toString().padStart(4, '0')}-${p.month
    .toString()
    .padStart(2, '0')}-${p.day.toString().padStart(2, '0')}`;
}

/** UTC `Date` for midnight on `dateYmd` (`YYYY-MM-DD`) in the given
 *  zone. Iterates twice to settle around DST transitions where the
 *  zone offset for "midnight" differs from the offset 24h earlier
 *  (the first iteration would otherwise overshoot by an hour). */
export function zoneDayStartUtc(dateYmd: string, tz: string): Date {
  const [y, m, d] = dateYmd.split('-').map((s) => Number(s));
  if (!y || !m || !d) return new Date(NaN);
  // Initial guess: pretend the date is UTC midnight.
  const wallUtc = Date.UTC(y, m - 1, d, 0, 0, 0);
  let result = wallUtc;
  for (let i = 0; i < 2; i += 1) {
    const parts = partsInZone(new Date(result), tz);
    const partsAsUtc = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
    );
    // `offset` = how far ahead the zone is of UTC at `result`.
    const offset = partsAsUtc - result;
    // We want a UTC instant that, when rendered in zone, reads as
    // wall-clock midnight on dateYmd → result = wallUtc - offset.
    result = wallUtc - offset;
  }
  return new Date(result);
}

/** Half-open UTC bounds of `dateYmd` in zone `tz` —
 *  `[start, nextDayStart)` ISO strings. Used by the day-aggregate
 *  fetcher so a "May 7 in Lima" view actually queries `[05:00 UTC May 7,
 *  05:00 UTC May 8)` and includes any cross-midnight broadcast's tail. */
export function zoneDayBoundsUtc(
  dateYmd: string,
  tz: string,
): { since: string; until: string } {
  const start = zoneDayStartUtc(dateYmd, tz);
  // Add 24h *to the wall-clock day*, not 24h to the UTC instant —
  // DST transitions make the latter wrong by ±1h. Re-resolve next-day
  // midnight so the bound is always exactly the day's last instant.
  const [y, m, d] = dateYmd.split('-').map((s) => Number(s));
  const next = new Date(Date.UTC(y, m - 1, d) + 86_400_000);
  const nextYmd =
    `${next.getUTCFullYear().toString().padStart(4, '0')}-` +
    `${(next.getUTCMonth() + 1).toString().padStart(2, '0')}-` +
    `${next.getUTCDate().toString().padStart(2, '0')}`;
  const end = zoneDayStartUtc(nextYmd, tz);
  return { since: start.toISOString(), until: end.toISOString() };
}
