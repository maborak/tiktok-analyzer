import { useState, useCallback, useEffect, useRef } from 'react';
import { Search, ChevronDown, ChevronRight, Clock, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { apiRequest } from '@/api/client';
import { cn } from '@/utils/cn';
import toast from 'react-hot-toast';

interface TraceEvent {
  id: number;
  event_type: string;
  source: string | null;
  trace_id: string;
  data: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

interface TraceDetail {
  trace_id: string;
  events: TraceEvent[];
  total: number;
  duration_ms: number | null;
}

interface TraceSummary {
  trace_id: string;
  first_event: string | null;
  last_event: string | null;
  event_count: number;
  started_at: string | null;
  duration_ms: number | null;
}

interface TracesListResponse {
  traces: TraceSummary[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

const CATEGORY_COLORS: Record<string, string> = {
  User: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300',
  'Handler Outcome': 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  Billing: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  Ticket: 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300',
  System: 'bg-slate-100 text-slate-800 dark:bg-slate-900/30 dark:text-slate-300',
  Other: 'bg-gray-100 text-gray-800',
};

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

function formatEventType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface TraceViewerTabProps {
  initialTraceId?: string;
}

export function TraceViewerTab({ initialTraceId }: TraceViewerTabProps) {
  const [searchInput, setSearchInput] = useState(initialTraceId || '');
  const [loading, setLoading] = useState(false);

  // Traces list mode
  const [tracesList, setTracesList] = useState<TracesListResponse | null>(null);
  const [page, setPage] = useState(1);

  // Single trace detail mode
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null);
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  const isTraceId = (input: string) => {
    // UUID format: 8-4-4-4-12 hex chars
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(input);
  };

  const searchTraces = useCallback(async (query?: string) => {
    const q = query ?? searchInput;
    if (!q.trim()) return;

    setLoading(true);
    setTraceDetail(null);
    setTracesList(null);

    try {
      if (isTraceId(q.trim())) {
        const data = await apiRequest<TraceDetail>({
          method: 'GET',
          url: `/admin/monitoring/events/trace/${q.trim()}`,
        });
        if (data) {
          setTraceDetail(data);
        }
      } else {
        // Search by keyword
        const data = await apiRequest<TracesListResponse>({
          method: 'GET',
          url: '/admin/monitoring/events/traces',
          params: { search: q.trim(), page, page_size: 20 },
        });
        if (data) {
          setTracesList(data);
        }
      }
    } catch {
      toast.error('Failed to search traces');
    } finally {
      setLoading(false);
    }
  }, [searchInput, page]);

  const loadTraceDetail = async (traceId: string) => {
    if (expandedTraceId === traceId) {
      setExpandedTraceId(null);
      return;
    }
    try {
      const data = await apiRequest<TraceDetail>({
        method: 'GET',
        url: `/admin/monitoring/events/trace/${traceId}`,
      });
      if (data) {
        setTraceDetail(data);
        setExpandedTraceId(traceId);
      }
    } catch {
      toast.error('Failed to load trace');
    }
  };

  // Auto-search when initialTraceId changes (e.g. click from Events tab)
  const prevTraceId = useRef(initialTraceId);
  useEffect(() => {
    if (initialTraceId && initialTraceId !== prevTraceId.current) {
      prevTraceId.current = initialTraceId;
      setSearchInput(initialTraceId);
      searchTraces(initialTraceId);
    }
  }, [initialTraceId, searchTraces]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    searchTraces();
  };

  return (
    <div>
      {/* Search bar */}
      <form onSubmit={handleSubmit} className="flex gap-2 mb-6">
        <div className="flex-1">
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by trace ID (UUID) or keyword..."
            className="w-full"
          />
        </div>
        <Button type="submit" disabled={loading || !searchInput.trim()}>
          <Search size={14} />
          Search
        </Button>
      </form>

      {loading && (
        <div className="flex items-center justify-center py-12 text-gray-500">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-gray-400 mr-2" />
          Searching...
        </div>
      )}

      {/* Single trace detail view */}
      {traceDetail && !tracesList && (
        <TraceTimeline trace={traceDetail} />
      )}

      {/* Traces list view */}
      {tracesList && (
        <div className="space-y-2">
          <p className="text-sm text-gray-500 mb-3">
            Found {tracesList.total} trace{tracesList.total !== 1 ? 's' : ''}
          </p>
          {tracesList.traces.map(trace => (
            <div key={trace.trace_id} className="bg-white rounded-lg border border-gray-200">
              <button
                onClick={() => loadTraceDetail(trace.trace_id)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 transition-colors rounded-lg"
              >
                <div className="flex items-center gap-3">
                  {expandedTraceId === trace.trace_id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <code className="text-xs text-gray-500 font-mono">{trace.trace_id.slice(0, 8)}...</code>
                  {trace.first_event && (
                    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', CATEGORY_COLORS[getCategoryForEvent(trace.first_event)])}>
                      {formatEventType(trace.first_event)}
                    </span>
                  )}
                  {trace.last_event && trace.last_event !== trace.first_event && (
                    <>
                      <ArrowRight size={12} className="text-gray-400" />
                      <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', CATEGORY_COLORS[getCategoryForEvent(trace.last_event)])}>
                        {formatEventType(trace.last_event)}
                      </span>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  <span>{trace.event_count} events</span>
                  <span className="flex items-center gap-1">
                    <Clock size={12} />
                    {formatDuration(trace.duration_ms)}
                  </span>
                  {trace.started_at && (
                    <span>{new Date(trace.started_at).toLocaleString()}</span>
                  )}
                </div>
              </button>
              {expandedTraceId === trace.trace_id && traceDetail && (
                <div className="border-t border-gray-200 px-4 py-3">
                  <TraceTimeline trace={traceDetail} compact />
                </div>
              )}
            </div>
          ))}

          {/* Pagination */}
          {tracesList.total_pages > 1 && (
            <div className="flex justify-center gap-2 mt-4">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => { setPage(p => p - 1); searchTraces(); }}
              >
                Previous
              </Button>
              <span className="text-sm text-gray-500 py-1">
              Page {tracesList.page} of {tracesList.total_pages}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= tracesList.total_pages}
                onClick={() => { setPage(p => p + 1); searchTraces(); }}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!loading && !traceDetail && !tracesList && (
        <div className="text-center py-12 text-gray-500">
          <Search size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Enter a trace ID (UUID) or keyword to search for event traces</p>
          <p className="text-xs mt-1">Traces show the full chain: worker data &rarr; price change &rarr; alert &rarr; email</p>
        </div>
      )}
    </div>
  );
}

// ─── Trace Timeline ──────────────────────────────────────────────────

function TraceTimeline({ trace, compact }: { trace: TraceDetail; compact?: boolean }) {
  const firstTime = trace.events[0]?.created_at ? new Date(trace.events[0].created_at).getTime() : 0;

  return (
    <div>
      {!compact && (
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-medium text-gray-700">
              Trace: <code className="text-xs font-mono text-gray-500">{trace.trace_id}</code>
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {trace.total} events &middot; Duration: {formatDuration(trace.duration_ms)}
            </p>
          </div>
        </div>
      )}

      <div className="relative">
        {/* Vertical timeline line */}
        <div className="absolute left-4 top-0 bottom-0 w-px bg-gray-200" />

        <div className="space-y-1">
          {trace.events.map((event, idx) => {
            const cat = getCategoryForEvent(event.event_type);
            const eventTime = event.created_at ? new Date(event.created_at).getTime() : 0;
            const delta = eventTime - firstTime;

            return (
              <div key={event.id} className="relative flex items-start gap-3 pl-8">
                {/* Timeline dot */}
                <div className={cn(
                  'absolute left-2.5 top-2 w-3 h-3 rounded-full border-2 border-white',
                  idx === 0 ? 'bg-blue-500' : idx === trace.events.length - 1 ? 'bg-green-500' : 'bg-gray-400'
                )} />

                <div className="flex-1 py-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', CATEGORY_COLORS[cat])}>
                      {formatEventType(event.event_type)}
                    </span>
                    <span className="text-xs text-gray-400">{event.source || ''}</span>
                    <span className="text-xs text-gray-400 font-mono">+{formatDuration(delta)}</span>
                  </div>
                  {event.data && Object.keys(event.data).length > 0 && (
                    <pre className="text-xs font-mono text-gray-500 mt-1 overflow-hidden max-w-xl truncate">
                      {JSON.stringify(event.data)}
                    </pre>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
