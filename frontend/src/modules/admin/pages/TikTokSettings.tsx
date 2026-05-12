/**
 * TikTok Settings tab — consolidated, friendly view of every typed
 * config key in the `tiktok` namespace. Mirrors `/admin/settings/
 * configuration?namespace=tiktok` (the raw view stays the source of
 * truth for *every* namespace), but presents the TikTok keys in
 * grouped sections with TikTok-aware copy and tailored controls:
 *
 *   - Listener — process model, sign engine, sign-broker URL.
 *   - Authentication — session cookies for `SIGN_PROVIDER=session`.
 *     Masked + reveal toggle; never logs.
 *   - Realtime — admin / public WS-vs-poll modes + poll cadence.
 *
 * Reads via `configurationApi.getSection('tiktok')`, writes per-key
 * via `setKey()` — exactly the same backend path the raw page uses.
 * Both pages can be open at once; they don't fight each other.
 */

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  Key,
  Loader2,
  RefreshCw,
  Save,
  Settings as SettingsIcon,
  SlidersHorizontal,
} from 'lucide-react';
import toast from 'react-hot-toast';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Switch } from '@/components/ui/Switch';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import {
  configurationApi,
  type ConfigKeyMetadata,
  type ConfigSource,
} from '@admin/services/configuration';
import { TikTokSignConfigBody } from '@admin/pages/TikTokSignConfig';
import { TikTokListenerStatusCard } from '@admin/components/TikTokListenerStatusCard';

interface Section {
  /** Stable id, used as the section heading anchor. */
  id: string;
  title: string;
  description: string;
  /** Ordered list of registry keys this section renders. Missing
   *  keys are silently skipped so the page is resilient to backend
   *  registry changes. */
  keys: string[];
}

const SECTIONS: Section[] = [
  {
    id: 'listener',
    title: 'Listener',
    description:
      "How the listener pool connects to TikTok's WebCast WebSocket. " +
      "Changing the sign engine usually requires restarting the workers (or the API in `in_process` mode).",
    keys: [
      'TIKTOK_SIGN_PROVIDER',
      'TIKTOK_LOCAL_SIGN_URL',
    ],
  },
  {
    id: 'auth',
    title: 'Authentication',
    description:
      'Session cookies used by `SIGN_PROVIDER=session`. Sensitive — they grant API access tied to your TikTok account. ' +
      'Treat them like a password; rotate immediately on suspected exposure.',
    keys: [
      'TIKTOK_EULER_API_KEY',
      'TIKTOK_SESSION_ID',
      'TIKTOK_SESSION_TT_TARGET_IDC',
    ],
  },
  {
    id: 'realtime',
    title: 'Realtime + Polling',
    description:
      "Frontend strategy for getting fresh data: REST polling, real-time WebSocket, or both. " +
      "Admin and public surfaces have independent modes — typically admin runs 'both' and public starts on 'poll'.",
    keys: [
      'TIKTOK_POLL_INTERVAL_MS',
      'TIKTOK_ADMIN_REALTIME_MODE',
      'TIKTOK_PUBLIC_REALTIME_MODE',
    ],
  },
];

/** Realtime mode options used by both admin + public mode selects. */
const REALTIME_OPTIONS = [
  { value: 'both', label: 'Both — WS events + REST poll (recommended)' },
  { value: 'ws', label: 'WS only — fastest, no REST polling' },
  { value: 'poll', label: 'Poll only — disable WS entirely' },
];

const SIGN_PROVIDER_OPTIONS = [
  { value: 'euler', label: 'EulerStream (default)' },
  { value: 'session', label: 'Session-authenticated EulerStream' },
  { value: 'local', label: 'Local Electron broker' },
];

type SettingsSubTab = 'general' | 'sign-engine' | 'worker';

const SUB_TAB_KEYS: ReadonlySet<SettingsSubTab> = new Set([
  'general',
  'sign-engine',
  'worker',
]);

export function TikTokSettings() {
  const [keys, setKeys] = useState<ConfigKeyMetadata[]>([]);
  const [pending, setPending] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [revealing, setRevealing] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  // Internal sub-tab state — URL-driven so deep-linking + browser
  // back/forward both work. `general` is the default (the typed-
  // config grouped view); `sign-engine` embeds the existing rich
  // sign-config UI; `worker` embeds the listener status card. All
  // three live inside `/admin/tiktok/settings`; nothing here ever
  // navigates away.
  const [subTab, setSubTabState] = useState<SettingsSubTab>(() => {
    if (typeof window === 'undefined') return 'general';
    const v = new URL(window.location.href).searchParams.get('section') as SettingsSubTab | null;
    return v && SUB_TAB_KEYS.has(v) ? v : 'general';
  });
  const setSubTab = (next: SettingsSubTab) => {
    setSubTabState(next);
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (next === 'general') url.searchParams.delete('section');
    else url.searchParams.set('section', next);
    window.history.replaceState({}, '', url);
  };
  // Bumped by the page-header Refresh button when the Worker sub-tab
  // is active — forwards into the embedded status card.
  const [workerRefreshKey, setWorkerRefreshKey] = useState(0);
  // Keep state in sync with browser back/forward.
  useEffect(() => {
    const onPop = () => {
      const v = new URL(window.location.href).searchParams.get('section') as SettingsSubTab | null;
      setSubTabState(v && SUB_TAB_KEYS.has(v) ? v : 'general');
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await configurationApi.getSection('tiktok');
      setKeys(data.keys);
      setPending({});
    } catch (e) {
      console.error(e);
      toast.error('Failed to load TikTok settings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  // Lookup by key — every section indexes off this. Built once per
  // settings refresh; small ( <20 keys ), no `useMemo` ceremony
  // needed beyond stable ref for child renders.
  const byKey = useMemo(() => {
    const m: Record<string, ConfigKeyMetadata> = {};
    for (const k of keys) m[k.key] = k;
    return m;
  }, [keys]);

  const handleChange = (key: string, value: unknown) => {
    setPending((p) => ({ ...p, [key]: value }));
  };

  const handleSave = async (key: string) => {
    if (!(key in pending)) return;
    setSaving(key);
    try {
      const updated = await configurationApi.setKey(key, pending[key]);
      setKeys((prev) => prev.map((k) => (k.key === key ? updated : k)));
      setPending((p) => {
        const next = { ...p };
        delete next[key];
        return next;
      });
      toast.success(`${key} updated`);
    } catch (e) {
      console.error(e);
      toast.error(`Failed to save ${key}`);
    } finally {
      setSaving(null);
    }
  };

  const handleRevert = (key: string) => {
    setPending((p) => {
      const next = { ...p };
      delete next[key];
      return next;
    });
  };

  const toggleReveal = (key: string) => {
    setRevealing((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <PageShell>
      <PageHeader
        title="TikTok Settings"
        icon={<SettingsIcon className="w-5 h-5" />}
        description={
          <>
            All TikTok-related configuration + ops in one place. The General sub-tab mirrors
            <a className="font-mono text-primary-600 mx-1 hover:underline" href="/admin/settings/configuration">
              /admin/settings/configuration
            </a>
            for the `tiktok` namespace (raw view stays the source of truth for every namespace).
            Sign Engine + Worker bring the previously-separate surfaces under the same roof.
          </>
        }
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              if (subTab === 'worker') setWorkerRefreshKey((k) => k + 1);
              else if (subTab === 'general') refresh();
              // Sign Engine sub-tab manages its own data load + has
              // its own Save button; the page Refresh is a no-op there.
            }}
            disabled={subTab === 'general' && loading}
            title={
              subTab === 'worker'
                ? 'Refresh worker status'
                : subTab === 'general'
                  ? 'Reload typed config'
                  : 'Re-open the Sign Engine sub-tab to reload'
            }
          >
            <RefreshCw className={`w-4 h-4 mr-1 ${loading && subTab === 'general' ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        }
      />

      {/* Sub-tab strip. Three concerns under the Settings umbrella:
          General  = typed-config keys (sign provider, auth cookies,
                     poll/realtime modes).
          Sign Engine = rich provider-switching UI (test calls,
                        session login) — embedded TikTokSignConfigBody.
          Worker  = listener-pool operational status. */}
      <div className="flex items-center gap-1 border-b border-gray-200 -mb-px overflow-x-auto">
        <SettingsTabButton active={subTab === 'general'} onClick={() => setSubTab('general')}>
          <SlidersHorizontal className="w-3.5 h-3.5" />
          General
        </SettingsTabButton>
        <SettingsTabButton active={subTab === 'sign-engine'} onClick={() => setSubTab('sign-engine')}>
          <Key className="w-3.5 h-3.5" />
          Sign Engine
        </SettingsTabButton>
        <SettingsTabButton active={subTab === 'worker'} onClick={() => setSubTab('worker')}>
          <Activity className="w-3.5 h-3.5" />
          Worker
        </SettingsTabButton>
      </div>

      <div className="pt-4 flex flex-col gap-6">

      {subTab === 'general' && (
        <>
          {loading && keys.length === 0 && (
            <div className="text-center text-sm text-gray-500 py-12">
              <Loader2 className="w-5 h-5 inline animate-spin mr-2" />
              Loading…
            </div>
          )}

          {!loading && keys.length === 0 && (
            <div className="text-center text-sm text-gray-500 py-12">
              No TikTok keys found in the typed-config registry.
            </div>
          )}

          {keys.length > 0 && SECTIONS.map((section) => {
            const sectionKeys = section.keys
              .map((k) => byKey[k])
              .filter((k): k is ConfigKeyMetadata => !!k);
            if (sectionKeys.length === 0) return null;
            return (
              <section key={section.id} className="card">
                <h3 className="auth-mono-label mb-1">{section.title}</h3>
                <p className="text-xs text-gray-500 mb-4">{section.description}</p>
                <div className="flex flex-col gap-4">
                  {sectionKeys.map((meta) => (
                    <KeyEditor
                      key={meta.key}
                      meta={meta}
                      pendingValue={pending[meta.key]}
                      isDirty={meta.key in pending}
                      saving={saving === meta.key}
                      revealed={revealing.has(meta.key)}
                      onChange={(v) => handleChange(meta.key, v)}
                      onSave={() => handleSave(meta.key)}
                      onRevert={() => handleRevert(meta.key)}
                      onToggleReveal={() => toggleReveal(meta.key)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </>
      )}

      {subTab === 'sign-engine' && <TikTokSignConfigBody />}

      {subTab === 'worker' && <TikTokListenerStatusCard refreshKey={workerRefreshKey} />}

      </div>
    </PageShell>
  );
}

interface SettingsTabButtonProps {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function SettingsTabButton({ active, onClick, children }: SettingsTabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ' +
        (active
          ? 'border-primary-500 text-primary-700 dark:text-primary-300'
          : 'border-transparent text-gray-600 hover:text-gray-900')
      }
    >
      {children}
    </button>
  );
}

// ── Per-key editor ─────────────────────────────────────────────────

interface KeyEditorProps {
  meta: ConfigKeyMetadata;
  pendingValue: unknown;
  isDirty: boolean;
  saving: boolean;
  revealed: boolean;
  onChange: (v: unknown) => void;
  onSave: () => void;
  onRevert: () => void;
  onToggleReveal: () => void;
}

function KeyEditor({
  meta,
  pendingValue,
  isDirty,
  saving,
  revealed,
  onChange,
  onSave,
  onRevert,
  onToggleReveal,
}: KeyEditorProps) {
  const currentValue = isDirty ? pendingValue : meta.value;

  return (
    <div className="flex flex-col gap-2 pb-4 border-b border-gray-100 last:border-b-0 last:pb-0">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-semibold">{meta.key}</span>
            <SourceBadge source={meta.source} />
            {meta.sensitive && (
              <span className="auth-mono-label text-[10px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300">
                sensitive
              </span>
            )}
            {meta.readonly && (
              <span className="auth-mono-label text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600 dark:bg-gray-100/30 dark:text-gray-300">
                readonly
              </span>
            )}
            {meta.bootstrap && (
              <span className="auth-mono-label text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                bootstrap
              </span>
            )}
          </div>
          {meta.description && (
            <p className="text-xs text-gray-500 mt-1">{meta.description}</p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <ValueInput
            meta={meta}
            value={currentValue}
            revealed={revealed}
            onChange={onChange}
          />
        </div>
        {meta.sensitive && meta.value && (
          <button
            type="button"
            onClick={onToggleReveal}
            className="inline-flex items-center justify-center w-8 h-8 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
            aria-label={revealed ? 'Hide value' : 'Reveal value'}
            title={revealed ? 'Hide value' : 'Reveal value'}
          >
            {revealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        )}
        {isDirty && (
          <>
            <Button
              variant="secondary"
              onClick={onRevert}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button onClick={onSave} disabled={saving || meta.readonly}>
              {saving ? (
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <Save className="w-4 h-4 mr-1" />
              )}
              Save
            </Button>
          </>
        )}
        {!isDirty && meta.value === meta.default && (
          <span className="auth-mono-label text-[10px] text-gray-400">default</span>
        )}
      </div>

      {meta.examples && (
        <p className="text-[11px] font-mono text-gray-400">
          examples: {meta.examples}
        </p>
      )}
    </div>
  );
}

// ── Value input — typed by registry value_type + per-key specialisations ─

function ValueInput({
  meta,
  value,
  revealed,
  onChange,
}: {
  meta: ConfigKeyMetadata;
  value: unknown;
  revealed: boolean;
  onChange: (v: unknown) => void;
}) {
  if (meta.readonly) {
    return (
      <div className="font-mono text-sm text-gray-600 px-3 py-1.5 rounded border border-gray-200 bg-gray-50 dark:bg-white/[0.03] flex items-center gap-2">
        <span>{renderValue(meta, value, revealed)}</span>
        <AlertTriangle className="w-3 h-3 text-gray-400" />
      </div>
    );
  }

  // Per-key specialisations — better UX than a raw text input.
  if (meta.key === 'TIKTOK_SIGN_PROVIDER') {
    return (
      <Select
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      >
        {SIGN_PROVIDER_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </Select>
    );
  }
  if (meta.key === 'TIKTOK_ADMIN_REALTIME_MODE' || meta.key === 'TIKTOK_PUBLIC_REALTIME_MODE') {
    return (
      <Select
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      >
        {REALTIME_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </Select>
    );
  }
  if (meta.key === 'TIKTOK_POLL_INTERVAL_MS') {
    return (
      <div className="flex items-center gap-2">
        <Input
          type="number"
          value={String(value ?? '')}
          min={1000}
          max={600000}
          step={1000}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-32"
        />
        <span className="text-xs text-gray-500">ms ({fmtSeconds(Number(value))})</span>
      </div>
    );
  }

  // Generic fallback by value_type.
  if (meta.value_type === 'boolean') {
    return (
      <Switch
        checked={Boolean(value)}
        onCheckedChange={(checked) => onChange(checked)}
      />
    );
  }
  if (meta.value_type === 'int' || meta.value_type === 'float') {
    return (
      <Input
        type="number"
        value={String(value ?? '')}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-40"
      />
    );
  }
  // string + json — masked when sensitive + not revealed.
  if (meta.sensitive && !revealed) {
    return (
      <Input
        type="password"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        placeholder={meta.value ? '••••••••' : '(empty)'}
        autoComplete="new-password"
      />
    );
  }
  return (
    <Input
      type="text"
      value={String(value ?? '')}
      onChange={(e) => onChange(e.target.value)}
      placeholder={meta.examples?.split(',')[0]?.trim() ?? ''}
    />
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function SourceBadge({ source }: { source: ConfigSource }) {
  const cls = {
    db:        'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300',
    env:       'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
    default:   'bg-gray-100 text-gray-600 dark:bg-gray-100/30 dark:text-gray-300',
    bootstrap: 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300',
  }[source];
  return (
    <span className={`auth-mono-label text-[10px] px-1.5 py-0.5 rounded-full ${cls}`}>
      {source}
    </span>
  );
}

function renderValue(meta: ConfigKeyMetadata, value: unknown, revealed: boolean): string {
  if (value == null || value === '') return '(empty)';
  if (meta.sensitive && !revealed) return '••••••••';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function fmtSeconds(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '?';
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s}s`;
  const m = s / 60;
  return `${m.toFixed(1)}m`;
}

/** Visual cue when key is in "Saved!" state — currently unused; kept
 *  for future "just-saved" toast-free indicator. */
export function SavedCheck() {
  return <Check className="w-4 h-4 text-emerald-600" />;
}
