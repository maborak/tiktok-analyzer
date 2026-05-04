import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, FileText, Eye, Settings, GitBranch } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column, type FilterConfig } from '@/components/DataTable';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { apiRequest } from '@/api/client';
import { cn } from '@/utils/cn';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import toast from 'react-hot-toast';
import { EventConfigTab } from '../components/EventConfigTab';
import { TraceViewerTab } from '../components/TraceViewerTab';

// ─── Types ──────────────────────────────────────────────────────────

interface HookEventItem {
  id: number;
  event_type: string;
  source: string | null;
  trace_id?: string | null;
  data: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

interface EventListResponse {
  items: HookEventItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

interface EventSummary {
  total_events: number;
  by_event_type: Record<string, number>;
  by_source: Record<string, number>;
  window_hours: number;
}

type TabId = 'events' | 'config' | 'traces';

// ─── Helpers ────────────────────────────────────────────────────────

const EVENT_CATEGORIES: Record<string, string[]> = {
  'User': ['user_registered', 'user_login', 'user_verification_requested', 'user_password_reset_requested'],
  'Handler Outcome': ['email_sent', 'email_failed'],
  'Billing': ['credit_purchased', 'credit_exhausted'],
  'Ticket': ['ticket_created', 'ticket_updated'],
  'System': ['admin_notification', 'config_changed'],
};

function getCategoryForEvent(eventType: string): string {
  for (const [cat, types] of Object.entries(EVENT_CATEGORIES)) {
    if (types.includes(eventType)) return cat;
  }
  return 'Other';
}

const CATEGORY_COLORS: Record<string, string> = {
  User: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300',
  'Handler Outcome': 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  Billing: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  Ticket: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300',
  System: 'bg-slate-100 text-slate-800 dark:bg-slate-900/30 dark:text-slate-300',
  Other: 'bg-gray-100 text-gray-800',
};

function formatEventType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// ─── Tab definitions ────────────────────────────────────────────────

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'events', label: 'Events', icon: <FileText size={14} /> },
  { id: 'config', label: 'Configuration', icon: <Settings size={14} /> },
  { id: 'traces', label: 'Traces', icon: <GitBranch size={14} /> },
];

// ─── Component ──────────────────────────────────────────────────────

export function EventMonitor() {
  const [activeTab, setActiveTab] = useState<TabId>('events');
  const [traceSearchId, setTraceSearchId] = useState<string | undefined>();

  // Summary state
  const [summary, setSummary] = useState<EventSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [windowHours, setWindowHours] = useState(24);

  // Event list state
  const [events, setEvents] = useState<HookEventItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  // Filters
  const [filterType, setFilterType] = useState<string>('');
  const [filterSource, setFilterSource] = useState<string>('');

  // Detail modal
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailEvent, setDetailEvent] = useState<HookEventItem | null>(null);

  // ── Fetch summary ────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const data = await apiRequest<EventSummary>({
        method: 'GET',
        url: '/admin/monitoring/events/summary',
        params: { window_hours: windowHours },
      });
      if (data) {
        setSummary(data);
      }
    } catch {
      toast.error('Failed to load event summary');
    } finally {
      setSummaryLoading(false);
    }
  }, [windowHours]);

  // ── Fetch events ─────────────────────────────────────────────────
  const fetchEvents = useCallback(async () => {
    setEventsLoading(true);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (filterType) params.event_type = filterType;
      if (filterSource) params.source = filterSource;

      const data = await apiRequest<EventListResponse>({
        method: 'GET',
        url: '/admin/monitoring/events',
        params,
      });
      if (data) {
        setEvents(data.items);
        setTotal(data.total);
        setTotalPages(data.total_pages);
      }
    } catch {
      toast.error('Failed to load events');
    } finally {
      setEventsLoading(false);
    }
  }, [page, pageSize, filterType, filterSource]);

  useEffect(() => { if (activeTab === 'events') { fetchSummary(); } }, [fetchSummary, activeTab]);
  useEffect(() => { if (activeTab === 'events') { fetchEvents(); } }, [fetchEvents, activeTab]);

  const refreshAll = () => {
    fetchSummary();
    fetchEvents();
  };

  // Navigate to trace viewer with a trace_id
  const goToTrace = (traceId: string) => {
    setTraceSearchId(traceId);
    setActiveTab('traces');
  };

  // ── Metric helpers ───────────────────────────────────────────────
  const topEventType = summary
    ? Object.entries(summary.by_event_type).sort((a, b) => b[1] - a[1])[0]
    : null;
  const uniqueSources = summary ? Object.keys(summary.by_source).length : 0;
  const eventsPerHour = summary && summary.window_hours > 0
    ? Math.round(summary.total_events / summary.window_hours)
    : 0;

  // ── Table columns ────────────────────────────────────────────────
  const columns: Column<HookEventItem>[] = [
    {
      key: 'id',
      label: 'ID',
      render: (row) => <span className="text-xs text-gray-500 font-mono">{row.id}</span>,
    },
    {
      key: 'event_type',
      label: 'Event',
      render: (row) => {
        const cat = getCategoryForEvent(row.event_type);
        return (
          <span className={cn('inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium', CATEGORY_COLORS[cat])}>
            {formatEventType(row.event_type)}
          </span>
        );
      },
    },
    {
      key: 'source',
      label: 'Source',
      render: (row) => <span className="text-sm text-gray-600">{row.source || '—'}</span>,
    },
    {
      key: 'trace_id',
      label: 'Trace',
      render: (row) => {
        if (!row.trace_id) return <span className="text-xs text-gray-400">—</span>;
        return (
          <button
            onClick={() => goToTrace(row.trace_id!)}
            className="text-xs font-mono text-blue-600 hover:text-blue-800 dark:text-blue-400 hover:underline"
            title={`View trace ${row.trace_id}`}
          >
            {row.trace_id.slice(0, 8)}...
          </button>
        );
      },
    },
    {
      key: 'data',
      label: 'Data Preview',
      render: (row) => {
        const preview = JSON.stringify(row.data);
        const truncated = preview.length > 60 ? preview.slice(0, 60) + '...' : preview;
        return <span className="text-xs font-mono text-gray-500">{truncated}</span>;
      },
    },
    {
      key: 'created_at',
      label: 'Date and Time',
      render: (row) => {
        if (!row.created_at) return '—';
        const d = new Date(row.created_at);
        return <span className="text-xs text-gray-500">{d.toLocaleString()}</span>;
      },
    },
    {
      key: 'actions',
      label: '',
      render: (row) => (
        <button
          onClick={() => { setDetailEvent(row); setDetailOpen(true); }}
          className="p-1 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-700"
          title="View details"
        >
          <Eye size={16} />
        </button>
      ),
    },
  ];

  // ── Filter config for DataTable ──────────────────────────────────
  const allKnownTypes = new Set(Object.values(EVENT_CATEGORIES).flat());
  const dbTypes = summary ? Object.keys(summary.by_event_type) : [];
  const extraDbTypes = dbTypes.filter(t => !allKnownTypes.has(t));

  const eventTypeOptions: { label: string; value: string }[] = [];
  for (const [category, types] of Object.entries(EVENT_CATEGORIES)) {
    eventTypeOptions.push({ label: `── ${category} ──`, value: `__header_${category}`, disabled: true } as { label: string; value: string });
    for (const t of types) {
      const count = summary?.by_event_type[t];
      const label = count !== undefined
        ? `${formatEventType(t)} (${count})`
        : formatEventType(t);
      eventTypeOptions.push({ label, value: t });
    }
  }
  if (extraDbTypes.length > 0) {
    eventTypeOptions.push({ label: '── Other ──', value: '__header_Other', disabled: true } as { label: string; value: string });
    for (const t of extraDbTypes.sort()) {
      const count = summary?.by_event_type[t] ?? 0;
      eventTypeOptions.push({ label: `${formatEventType(t)} (${count})`, value: t });
    }
  }

  const sourceOptions = summary
    ? Object.keys(summary.by_source).sort().map(s => ({ label: s, value: s }))
    : [];

  const filters: FilterConfig[] = [
    {
      key: 'event_type',
      label: 'Event Type',
      value: filterType,
      onChange: (v: string) => { setFilterType(v); setPage(1); },
      options: [{ label: 'All Types', value: '' }, ...eventTypeOptions],
    },
    {
      key: 'source',
      label: 'Source',
      value: filterSource,
      onChange: (v: string) => { setFilterSource(v); setPage(1); },
      options: [{ label: 'All Sources', value: '' }, ...sourceOptions],
    },
  ];

  // ─── Render ──────────────────────────────────────────────────────

  return (
    <PageShell>
      <PageHeader
        title="Event Monitor"
        description="Event audit log, configuration, and trace viewer"
        icon={<FileText className="w-6 h-6" />}
        actions={
          activeTab === 'events' ? (
            <div className="flex items-center gap-3">
              <Select
                value={String(windowHours)}
                onChange={(e) => setWindowHours(Number(e.target.value))}
                className="w-32"
              >
                <option value="1">1 hour</option>
                <option value="6">6 hours</option>
                <option value="12">12 hours</option>
                <option value="24">24 hours</option>
                <option value="72">3 days</option>
                <option value="168">7 days</option>
                <option value="720">30 days</option>
              </Select>
              <Button onClick={refreshAll} variant="secondary" size="sm">
                <RefreshCw size={14} className={cn(summaryLoading && 'animate-spin')} />
                Refresh
              </Button>
            </div>
          ) : undefined
        }
      />

      {/* ── Tab Bar ──────────────────────────────────────────────── */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="flex gap-6" aria-label="Tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-1.5 py-3 px-1 text-sm font-medium border-b-2 transition-colors',
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              )}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* ── Tab Content ──────────────────────────────────────────── */}

      {activeTab === 'events' && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <MetricCard label="Total Events" value={summary?.total_events ?? '—'} sub={`Last ${windowHours}h`} loading={summaryLoading} />
            <MetricCard label="Top Event" value={topEventType ? formatEventType(topEventType[0]) : '—'} sub={topEventType ? `${topEventType[1]} occurrences` : ''} loading={summaryLoading} />
            <MetricCard label="Sources" value={uniqueSources} sub="Unique sources" loading={summaryLoading} />
            <MetricCard label="Events / Hour" value={eventsPerHour} sub="Average rate" loading={summaryLoading} />
          </div>

          {/* Event Type Breakdown */}
          {summary && Object.keys(summary.by_event_type).length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-4 mb-6">
              <h3 className="text-sm font-medium text-gray-700 mb-3">Event Distribution</h3>
              <div className="flex flex-wrap gap-2">
                {Object.entries(summary.by_event_type)
                  .sort((a, b) => b[1] - a[1])
                  .map(([type, count]) => {
                    const cat = getCategoryForEvent(type);
                    return (
                      <button
                        key={type}
                        onClick={() => { setFilterType(type); setPage(1); }}
                        className={cn(
                          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-opacity hover:opacity-80 cursor-pointer',
                          CATEGORY_COLORS[cat],
                          filterType === type && 'ring-2 ring-offset-1 ring-blue-500',
                        )}
                      >
                        {formatEventType(type)}
                        <span className="opacity-70">{count}</span>
                      </button>
                    );
                  })}
                {filterType && (
                  <button
                    onClick={() => { setFilterType(''); setPage(1); }}
                    className="text-xs text-gray-500 hover:text-gray-700 underline ml-2"
                  >
                    Clear filter
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Events Table */}
          <DataTable
            title="Events"
            columns={columns}
            data={events}
            loading={eventsLoading}
            getRowId={(row) => row.id}
            page={page}
            pageSize={pageSize}
            total={total}
            totalPages={totalPages}
            onPageChange={setPage}
            onPageSizeChange={() => {}}
            searchEnabled={false}
            filters={filters}
            emptyTitle="No events registered yet"
            emptyDescription="Events will appear here as the system processes actions"
            emptyIcon={FileText}
          />
        </>
      )}

      {activeTab === 'config' && <EventConfigTab />}

      {activeTab === 'traces' && <TraceViewerTab initialTraceId={traceSearchId} />}

      {/* ── Detail Modal ──────────────────────────────────────────── */}
      <Modal
        isOpen={detailOpen}
        onClose={() => { setDetailOpen(false); setDetailEvent(null); }}
        title={detailEvent ? `Event #${detailEvent.id} — ${formatEventType(detailEvent.event_type)}` : 'Event Details'}
        className="max-w-4xl"
      >
        {detailEvent && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Event Type</span>
                <p className="font-medium">{formatEventType(detailEvent.event_type)}</p>
              </div>
              <div>
                <span className="text-gray-500">Source</span>
                <p className="font-medium">{detailEvent.source || '—'}</p>
              </div>
              <div>
                <span className="text-gray-500">Category</span>
                <p className="font-medium">{getCategoryForEvent(detailEvent.event_type)}</p>
              </div>
              <div>
                <span className="text-gray-500">Date and Time</span>
                <p className="font-medium">
                  {detailEvent.created_at ? new Date(detailEvent.created_at).toLocaleString() : '—'}
                </p>
              </div>
              {detailEvent.trace_id && (
                <div className="col-span-2">
                  <span className="text-gray-500">Trace ID</span>
                  <p className="font-medium font-mono text-xs">
                    <button
                      onClick={() => { setDetailOpen(false); goToTrace(detailEvent.trace_id!); }}
                      className="text-blue-600 hover:underline"
                    >
                      {detailEvent.trace_id}
                    </button>
                  </p>
                </div>
              )}
            </div>

            <div>
              <span className="text-sm text-gray-500 block mb-1">Data (sanitized)</span>
              <pre className="bg-gray-50 rounded-lg p-3 text-xs font-mono overflow-auto max-h-64 border border-gray-200">
                {JSON.stringify(detailEvent.data, null, 2)}
              </pre>
            </div>

            {detailEvent.metadata && Object.keys(detailEvent.metadata).length > 0 && (
              <div>
                <span className="text-sm text-gray-500 block mb-1">Metadata</span>
                <pre className="bg-gray-50 rounded-lg p-3 text-xs font-mono overflow-auto max-h-32 border border-gray-200">
                  {JSON.stringify(detailEvent.metadata, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>
    </PageShell>
  );
}

// ─── MetricCard ─────────────────────────────────────────────────────

function MetricCard({ label, value, sub, loading }: { label: string; value: string | number; sub?: string; loading?: boolean }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <p className="auth-mono-label">{label}</p>
      {loading ? (
        <div className="h-7 w-20 bg-gray-200 rounded animate-pulse mt-1" />
      ) : (
        <p className="text-2xl font-semibold text-gray-900 mt-1">{value}</p>
      )}
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}
