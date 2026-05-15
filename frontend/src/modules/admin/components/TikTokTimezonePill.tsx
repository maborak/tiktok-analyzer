/**
 * Timezone pill — compact dropdown for the TikTok page headers.
 *
 *   <TikTokTimezonePill compact />     // header version (chip + dropdown)
 *   <TikTokTimezonePill />             // full version (live "Now:" preview,
 *                                      // used inside the live-detail profile
 *                                      // header where vertical space is fine)
 *
 * Source of truth is `useTikTokTimezone()`; the dropdown writes through
 * `setTz()` which persists to localStorage and rebroadcasts to other
 * tabs via the `storage` event. Every component that reads time-
 * sensitive data via the same hook will pick up the change.
 */

import { useEffect, useMemo, useState } from 'react';
import { Clock } from 'lucide-react';

import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import {
  useTikTokTimezone,
  fmtFull,
} from '@admin/contexts/TikTokTimezoneContext';
import { TIMEZONE_OPTIONS } from '@admin/contexts/timezoneOptions';

interface Props {
  /** Compact = header pill (just chip + offset badge). Full = same
   *  selector with "Now: …" preview line below — used in-page where
   *  the operator is configuring it from the profile header. */
  compact?: boolean;
}

interface BuiltOption {
  value: string;
  label: string;
  region: string;
  currentOffset: string;
  offsetMinutes: number;
}

function currentTzOffset(tz: string): { display: string; minutes: number } {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      timeZoneName: 'longOffset',
    }).formatToParts(new Date());
    const raw =
      parts.find((p) => p.type === 'timeZoneName')?.value ?? 'GMT+00:00';
    const m = /^GMT([+-])(\d{1,2})(?::?(\d{2}))?$/.exec(raw);
    if (!m) return { display: 'UTC+00:00', minutes: 0 };
    const sign = m[1] === '-' ? -1 : 1;
    const hh = parseInt(m[2], 10);
    const mm = parseInt(m[3] ?? '0', 10);
    const totalMin = sign * (hh * 60 + mm);
    const pad2 = (n: number) => String(n).padStart(2, '0');
    return {
      display: `UTC${sign < 0 ? '-' : '+'}${pad2(hh)}:${pad2(mm)}`,
      minutes: totalMin,
    };
  } catch {
    return { display: 'UTC?', minutes: 0 };
  }
}

export function TikTokTimezonePill({ compact = false }: Props) {
  const { tz, browserTz, setTz, resetTz } = useTikTokTimezone();
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherValue, setOtherValue] = useState('');
  const [otherError, setOtherError] = useState<string | null>(null);

  // Tick every minute so DST flips refresh the visible offset badge
  // + "Now:" preview without a parent re-render.
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, []);

  // Build the options list — browser-local first, then the curated
  // regional list, then the active zone (if user typed a custom one
  // earlier). Each option carries a live UTC offset so the dropdown
  // reads as "(UTC-05:00) Lima — America/Lima".
  const allOptions = useMemo<BuiltOption[]>(() => {
    const seen = new Set<string>();
    const out: BuiltOption[] = [];
    const push = (v: string, label: string, region: string) => {
      if (seen.has(v)) return;
      seen.add(v);
      const { display, minutes } = currentTzOffset(v);
      out.push({
        value: v, label, region,
        currentOffset: display, offsetMinutes: minutes,
      });
    };
    push(browserTz, `Browser local — ${browserTz}`, 'Auto');
    for (const opt of TIMEZONE_OPTIONS) {
      push(opt.value, opt.label, opt.region);
    }
    if (!seen.has(tz)) push(tz, tz, 'Custom');
    return out;
    // `force` tick included so DST shifts refresh offsets.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browserTz, tz]);

  // Group by region (Auto, Americas, Europe, …) for optgroups; within
  // a group sort by offset so the dropdown scans naturally.
  const grouped = useMemo(() => {
    const byRegion: Record<string, BuiltOption[]> = {};
    for (const opt of allOptions) {
      (byRegion[opt.region] ??= []).push(opt);
    }
    for (const region of Object.keys(byRegion)) {
      byRegion[region].sort((a, b) => a.offsetMinutes - b.offsetMinutes);
    }
    return byRegion;
  }, [allOptions]);

  const activeOption = allOptions.find((o) => o.value === tz);
  const nowPreview = fmtFull(new Date(), tz);

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    if (v === '__other__') {
      setOtherValue(tz);
      setOtherOpen(true);
      return;
    }
    setTz(v);
  };

  const submitOther = () => {
    const v = otherValue.trim();
    if (!v) {
      setOtherError('Enter an IANA timezone (e.g. Pacific/Galapagos)');
      return;
    }
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: v }).format(new Date());
    } catch (err) {
      setOtherError(`Unknown timezone: ${(err as Error).message}`);
      return;
    }
    setTz(v);
    setOtherOpen(false);
    setOtherError(null);
  };

  return (
    <>
      <div
        className={
          'flex items-center gap-2 text-[11px] font-mono min-w-0 max-w-full ' +
          (compact ? 'flex-wrap' : 'flex-col items-start')
        }
        title={
          'Every TikTok date/time on this page renders in this zone. '
          + 'Choice persists across pages + tabs (localStorage).'
        }
      >
        <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full">
          <Clock className="w-3.5 h-3.5 text-gray-500 shrink-0" />
          {!compact && <span className="auth-mono-label shrink-0">Timezone</span>}
          <select
            value={tz}
            onChange={handleSelectChange}
            className={
              'px-2 py-1 rounded-md border border-gray-200 text-[11px] '
              + 'font-mono dark:bg-gray-100/5 truncate min-w-0 '
              + (compact
                ? 'max-w-[140px] sm:max-w-[180px]'
                : 'max-w-[160px] sm:max-w-[220px]')
            }
          >
            {Object.entries(grouped).map(([region, opts]) => (
              <optgroup key={region} label={region}>
                {opts.map((o) => (
                  <option key={o.value} value={o.value}>
                    ({o.currentOffset}) {o.label}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value="__other__">Other / paste IANA name…</option>
          </select>
          {activeOption && (
            <span
              className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300"
              title={
                `${activeOption.value} is currently ${activeOption.currentOffset} from UTC. `
                + 'Shifts automatically on DST transitions.'
              }
            >
              {activeOption.currentOffset}
            </span>
          )}
          {tz !== browserTz && (
            <button
              type="button"
              onClick={resetTz}
              className="shrink-0 text-[10px] text-primary-600 hover:text-primary-800 underline decoration-dotted"
              title={`Reset to ${browserTz}`}
            >
              reset
            </button>
          )}
        </div>
        {!compact && (
          <div className="text-[10px] text-gray-500 min-w-0 max-w-full break-words">
            Now: <span className="font-mono text-gray-700 dark:text-gray-300 break-all">{nowPreview}</span>
          </div>
        )}
      </div>

      {otherOpen && (
        <Modal
          isOpen={otherOpen}
          onClose={() => setOtherOpen(false)}
          title="Enter timezone"
          className="max-w-[90vw] sm:max-w-md"
          footer={
            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" onClick={() => setOtherOpen(false)}>Cancel</Button>
              <Button variant="primary" onClick={submitOther}>Use timezone</Button>
            </div>
          }
        >
          <p className="text-xs text-gray-500 mb-2">
            IANA zone name (e.g. <code>America/Lima</code>, <code>Pacific/Galapagos</code>).
            Anything <code>Intl.DateTimeFormat</code> accepts.
          </p>
          <input
            type="text"
            value={otherValue}
            onChange={(e) => {
              setOtherValue(e.target.value);
              setOtherError(null);
            }}
            placeholder="Region/City"
            className="w-full px-2.5 py-1.5 rounded-md border border-gray-200 text-sm font-mono dark:bg-gray-100/5"
            autoFocus
          />
          {otherError && (
            <p className="mt-1 text-xs text-rose-600">{otherError}</p>
          )}
        </Modal>
      )}
    </>
  );
}

export default TikTokTimezonePill;
