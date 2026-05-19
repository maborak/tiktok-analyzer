import { useEffect, useMemo, useState } from 'react';
import { Link } from '@tanstack/react-router';
import {
  BarChart3,
  ChevronRight,
  Flame,
  RefreshCw,
} from 'lucide-react';
import toast from 'react-hot-toast';

import { Button } from '@/components/ui/Button';
import { MetricCard } from '@/components/ui/MetricCard';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Select } from '@/components/ui/Select';
import { tiktokApi, type TikTokDashboardStats } from '@admin/services/tiktok';
import { StackedAreaChart, eventColor } from '@admin/components/TikTokCharts';
import {
  TikTokTimezoneProvider,
  useTikTokTimezone,
  partsInZone,
} from '@admin/contexts/TikTokTimezoneContext';

const RANGES: Array<{ value: number; label: string; bucket: number }> = [
  { value: 1,   label: 'Last 1 hour',  bucket: 60 },
  { value: 6,   label: 'Last 6 hours', bucket: 600 },
  { value: 24,  label: 'Last 24 hours', bucket: 3600 },
  { value: 168, label: 'Last 7 days',   bucket: 86400 },
];

const PALETTE = [
  '#0ea5e9', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444',
  '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16',
];

export function TikTokDashboard() {
  // Provider wrap so the dashboard's bucket labels (and the API
  // request) respect the user's chosen IANA zone — the same one
  // they picked on the live-detail page (localStorage-shared).
  return (
    <TikTokTimezoneProvider>
      <TikTokDashboardBody />
    </TikTokTimezoneProvider>
  );
}

function TikTokDashboardBody() {
  const { tz } = useTikTokTimezone();
  const [data, setData] = useState<TikTokDashboardStats | null>(null);
  const [hours, setHours] = useState<number>(24);
  const [loading, setLoading] = useState(true);

  const range = useMemo(
    () => RANGES.find((r) => r.value === hours) ?? RANGES[2],
    [hours]
  );

  const refresh = async () => {
    setLoading(true);
    try {
      const d = await tiktokApi.getDashboard({
        since_hours: range.value,
        bucket_seconds: range.bucket,
        tz,
      });
      setData(d);
    } catch (e) {
      console.error(e);
      toast.error('Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, tz]);

  // Build a per-host time series from the bucket rows. We aggregate
  // event types into a single value per host per bucket so the chart
  // stacks by creator (not by event type) — that's the more useful view
  // on the dashboard.
  const { series, labels } = useMemo(() => {
    if (!data) return { series: [], labels: [] as string[] };
    // Collect distinct buckets in order.
    const bucketSet = new Set<string>();
    for (const r of data.buckets) bucketSet.add(r.bucket);
    const buckets = Array.from(bucketSet).sort();
    const bucketIdx = new Map<string, number>();
    buckets.forEach((b, i) => bucketIdx.set(b, i));

    // Per-host series.
    const perHost = new Map<string, number[]>();
    for (const r of data.buckets) {
      const arr = perHost.get(r.host_unique_id) ?? new Array(buckets.length).fill(0);
      const idx = bucketIdx.get(r.bucket);
      if (idx == null) continue;
      arr[idx] = (arr[idx] ?? 0) + r.count;
      perHost.set(r.host_unique_id, arr);
    }

    // Top creators first (more visible bands).
    const top = data.creators.map((c) => c.host_unique_id);
    const ordered = [...top, ...Array.from(perHost.keys()).filter((h) => !top.includes(h))];

    const series = ordered
      .filter((h) => perHost.has(h))
      .map((h, i) => ({
        key: h,
        label: `@${h}`,
        values: perHost.get(h) ?? new Array(buckets.length).fill(0),
        color: PALETTE[i % PALETTE.length],
      }));

    const labels = buckets.map((iso) => formatBucketLabel(iso, range.bucket, tz));
    return { series, labels };
  }, [data, range.bucket, tz]);

  // Aggregate totals across all creators for the top counters.
  const totals = useMemo(() => {
    const out: Record<string, number> = {};
    for (const c of data?.creators ?? []) {
      for (const [k, v] of Object.entries(c.by_type)) {
        out[k] = (out[k] ?? 0) + v;
      }
    }
    return out;
  }, [data]);

  return (
    <PageShell>
      <PageHeader
        title="TikTok Dashboard"
        icon={<BarChart3 className="w-5 h-5" />}
        description="Cross-creator stats over a chosen window."
        actions={
          <div className="flex items-center gap-2">
            <Select
              value={String(hours)}
              onChange={(e) => setHours(Number(e.target.value))}
              className="w-44"
            >
              {RANGES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw className={loading ? 'animate-spin w-4 h-4' : 'w-4 h-4'} />
            </Button>
          </div>
        }
      />

      {/* totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Comments" value={totals.comment ?? 0} variant="primary" />
        <MetricCard label="Gifts" value={totals.gift ?? 0} variant="warning" />
        <MetricCard label="Likes" value={totals.like ?? 0} variant="error" />
        <MetricCard label="Joins" value={totals.join ?? 0} variant="success" />
      </div>

      {/* chart */}
      <section className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="auth-mono-label">Events by creator — {range.label.toLowerCase()}</h2>
          {data && (
            <span className="text-xs text-gray-500 font-mono">
              {data.creators.reduce((acc, c) => acc + c.total, 0)} total
            </span>
          )}
        </div>
        {series.length === 0 ? (
          <p className="text-sm text-gray-500 py-8 text-center">
            {loading ? 'Loading…' : 'No events in this window.'}
          </p>
        ) : (
          <StackedAreaChart series={series} labels={labels} height={240} />
        )}
      </section>

      {/* leaderboard */}
      <section className="card">
        <h2 className="auth-mono-label mb-3 flex items-center gap-2">
          <Flame className="w-4 h-4" />
          Most active creators
        </h2>
        {data && data.creators.length > 0 ? (
          <>
            {/* Desktop: 6-column table (md+). */}
            <table className="hidden md:table w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 auth-mono-label">Creator</th>
                  <th className="text-right py-2 auth-mono-label">Comments</th>
                  <th className="text-right py-2 auth-mono-label">Gifts</th>
                  <th className="text-right py-2 auth-mono-label">Likes</th>
                  <th className="text-right py-2 auth-mono-label">Total</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.creators.map((c, i) => (
                  <tr key={c.host_unique_id} className="border-b border-gray-100">
                    <td className="py-2">
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-sm mr-2 align-middle"
                        style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
                        aria-hidden
                      />
                      <Link
                        to="/tiktok/$handle"
                        params={{ handle: c.host_unique_id }}
                        className="font-mono text-primary-600 hover:underline"
                      >
                        @{c.host_unique_id}
                      </Link>
                    </td>
                    <td className="text-right py-2 font-mono tabular-nums">
                      {c.by_type.comment ?? 0}
                    </td>
                    <td className="text-right py-2 font-mono tabular-nums">
                      <span style={{ color: eventColor('gift') }}>{c.by_type.gift ?? 0}</span>
                    </td>
                    <td className="text-right py-2 font-mono tabular-nums">
                      {c.by_type.like ?? 0}
                    </td>
                    <td className="text-right py-2 font-mono tabular-nums font-semibold">
                      {c.total}
                    </td>
                    <td className="py-2 text-right">
                      <Link
                        to="/tiktok/$handle"
                        params={{ handle: c.host_unique_id }}
                        className="text-gray-400 hover:text-gray-600"
                        aria-label="Drill in"
                      >
                        <ChevronRight className="w-4 h-4 inline" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Mobile: card per creator (below md). Palette dot +
                handle on header row, 4 stats in a grid below. The
                whole card links to the creator's detail page. */}
            <ul className="md:hidden flex flex-col gap-2">
              {data.creators.map((c, i) => (
                <li
                  key={c.host_unique_id}
                  className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5"
                >
                  <Link
                    to="/tiktok/$handle"
                    params={{ handle: c.host_unique_id }}
                    className="block hover:bg-gray-50 dark:hover:bg-white/[0.04] -mx-3 -my-2.5 px-3 py-2.5 rounded-md transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                          style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
                          aria-hidden
                        />
                        <span className="font-mono text-primary-600 truncate">
                          @{c.host_unique_id}
                        </span>
                      </div>
                      <span className="shrink-0 font-mono tabular-nums font-semibold text-sm">
                        {c.total}
                      </span>
                    </div>
                    <div className="pt-2 border-t border-gray-100 grid grid-cols-3 gap-2 text-[11px] font-mono">
                      <div className="flex flex-col">
                        <span className="text-[10px] uppercase tracking-wider text-gray-400">Comments</span>
                        <span className="tabular-nums text-gray-700">{c.by_type.comment ?? 0}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[10px] uppercase tracking-wider text-gray-400">Gifts</span>
                        <span className="tabular-nums" style={{ color: eventColor('gift') }}>
                          {c.by_type.gift ?? 0}
                        </span>
                      </div>
                      <div className="flex flex-col text-right">
                        <span className="text-[10px] uppercase tracking-wider text-gray-400">Likes</span>
                        <span className="tabular-nums text-gray-700">{c.by_type.like ?? 0}</span>
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-sm text-gray-500 py-4 text-center">
            {loading ? 'Loading…' : 'No data yet — subscribe to a creator on the Lives page.'}
          </p>
        )}
      </section>
    </PageShell>
  );
}

function formatBucketLabel(iso: string, bucketSeconds: number, tz: string): string {
  // Render the bucket boundary in the selected zone so the label
  // matches what the user thinks of as "their day / their hour".
  // The backend now returns these ISOs anchored to the same zone,
  // so partsInZone(iso, tz) gives the wall-clock components without
  // any further offset shenanigans.
  const p = partsInZone(iso, tz);
  if (bucketSeconds >= 86400) {
    return `${p.month}/${p.day}`;
  }
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}
