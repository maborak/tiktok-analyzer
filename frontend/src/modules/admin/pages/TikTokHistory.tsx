import { useEffect, useState } from 'react';
import { History, RefreshCw, Search } from 'lucide-react';
import toast from 'react-hot-toast';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Select } from '@/components/ui/Select';
import { tiktokApi, type TikTokEvent, type TikTokSubscription } from '@admin/services/tiktok';
import { eventColor } from '@admin/components/TikTokCharts';

const TYPES = ['', 'comment', 'gift', 'like', 'join', 'follow', 'share', 'subscribe'];
const PAGE_LIMIT = 100;

export function TikTokHistory() {
  const [subs, setSubs] = useState<TikTokSubscription[]>([]);
  const [handle, setHandle] = useState<string>('');
  const [type, setType] = useState<string>('');
  const [q, setQ] = useState<string>('');
  const [since, setSince] = useState<string>(''); // datetime-local string
  const [until, setUntil] = useState<string>('');
  const [events, setEvents] = useState<TikTokEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  // Subscriptions for the handle filter dropdown.
  useEffect(() => {
    tiktokApi.listLives().then(setSubs).catch(() => { /* ignore */ });
  }, []);

  const search = async (cursor?: string, append = false) => {
    setLoading(true);
    try {
      const rows = await tiktokApi.searchEvents({
        handle: handle || undefined,
        type: type || undefined,
        q: q || undefined,
        since: since ? new Date(since).toISOString() : undefined,
        until: until ? new Date(until).toISOString() : undefined,
        limit: PAGE_LIMIT,
        before_id: cursor,
      });
      setEvents((prev) => (append ? [...prev, ...rows] : rows));
      setHasMore(rows.length === PAGE_LIMIT);
    } catch (e) {
      console.error(e);
      toast.error('Search failed');
    } finally {
      setLoading(false);
    }
  };

  // Initial load on mount only — afterwards the user clicks "Search".
  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSearch = () => search();

  const onLoadMore = () => {
    const last = events[events.length - 1];
    if (!last) return;
    search(last.id, true);
  };

  const exportCsv = () => {
    if (events.length === 0) return;
    const lines = [
      ['id', 'ts', 'room_id', 'type', 'user_id', 'user_unique_id', 'text', 'gift_name', 'diamonds'].join(','),
      ...events.map((e) => {
        const p = e.payload || {};
        const u = (p.user as { unique_id?: string } | undefined)?.unique_id ?? '';
        return [
          e.id,
          e.ts,
          e.room_id,
          e.type,
          e.user_id ?? '',
          u,
          csvCell(p.text),
          csvCell(p.gift_name),
          csvCell(p.diamond_count),
        ].join(',');
      }),
    ];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tiktok-events-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <PageShell>
      <PageHeader
        title="History"
        icon={<History className="w-5 h-5" />}
        description="Search recorded events across all monitored creators."
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={exportCsv} disabled={events.length === 0}>
              Export CSV
            </Button>
            <Button variant="ghost" onClick={onSearch} disabled={loading}>
              <RefreshCw className={loading ? 'animate-spin w-4 h-4' : 'w-4 h-4'} />
            </Button>
          </div>
        }
      />

      {/* filters */}
      <section className="card">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <div>
            <label className="auth-mono-label block mb-1">Creator</label>
            <Select value={handle} onChange={(e) => setHandle(e.target.value)}>
              <option value="">All</option>
              {subs.map((s) => (
                <option key={s.unique_id} value={s.unique_id}>
                  @{s.unique_id}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="auth-mono-label block mb-1">Type</label>
            <Select value={type} onChange={(e) => setType(e.target.value)}>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t || 'Any'}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="auth-mono-label block mb-1">Since</label>
            <Input
              type="datetime-local"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </div>
          <div>
            <label className="auth-mono-label block mb-1">Until</label>
            <Input
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </div>
          <div>
            <label className="auth-mono-label block mb-1">Search text</label>
            <div className="flex gap-2">
              <Input
                placeholder="payload contains…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && onSearch()}
              />
              <Button onClick={onSearch} disabled={loading}>
                <Search className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* results */}
      <section className="rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left auth-mono-label">When</th>
              <th className="px-4 py-2 text-left auth-mono-label">Type</th>
              <th className="px-4 py-2 text-left auth-mono-label">Room</th>
              <th className="px-4 py-2 text-left auth-mono-label">User</th>
              <th className="px-4 py-2 text-left auth-mono-label">Detail</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  {loading ? 'Loading…' : 'No events match.'}
                </td>
              </tr>
            )}
            {events.map((e) => (
              <EventRow key={e.id} ev={e} />
            ))}
          </tbody>
        </table>
        {hasMore && (
          <div className="bg-gray-50 px-4 py-3 text-center">
            <Button variant="ghost" onClick={onLoadMore} disabled={loading}>
              Load more
            </Button>
          </div>
        )}
      </section>
    </PageShell>
  );
}

interface RowProps {
  ev: TikTokEvent;
}

function EventRow({ ev }: RowProps) {
  const payload = ev.payload || {};
  const user = (payload.user as { unique_id?: string; nickname?: string } | undefined) || {};
  return (
    <tr className="border-t border-gray-200">
      <td className="px-4 py-2 font-mono text-xs text-gray-600 whitespace-nowrap">
        {formatTs(ev.ts)}
      </td>
      <td className="px-4 py-2">
        <span
          className="font-mono text-[10px] px-2 py-0.5 rounded"
          style={{
            color: eventColor(ev.type),
            backgroundColor: `${eventColor(ev.type)}1A`,
          }}
        >
          {ev.type}
        </span>
      </td>
      <td className="px-4 py-2 font-mono text-xs text-gray-600">{ev.room_id}</td>
      <td className="px-4 py-2 text-xs">
        {user.nickname && <span className="font-medium">{user.nickname}</span>}
        {user.unique_id && (
          <span className="ml-1 font-mono text-gray-500">@{user.unique_id}</span>
        )}
      </td>
      <td className="px-4 py-2 text-xs">{summarize(ev)}</td>
    </tr>
  );
}

// ── helpers ────────────────────────────────────────────────────────

function summarize(e: TikTokEvent): string {
  const p = e.payload || {};
  if (e.type === 'comment') return String(p.text ?? '').slice(0, 200);
  if (e.type === 'gift') {
    const base = `${p.gift_name ?? 'gift'} ×${p.repeat_count ?? 1} (${p.diamond_count ?? 0}💎)`;
    const to = p.to_user as { unique_id?: string; nickname?: string } | undefined;
    const dest = to && (to.nickname || to.unique_id);
    return dest ? `${base} → ${to.nickname || `@${to.unique_id}`}` : base;
  }
  if (e.type === 'like') return `liked ×${p.count ?? 1}`;
  if (e.type === 'join') return 'joined';
  return JSON.stringify(p).slice(0, 200);
}

function formatTs(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

function csvCell(v: unknown): string {
  if (v == null) return '';
  const s = String(v);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}
