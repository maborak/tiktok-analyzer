import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Settings2,
  RefreshCw,
  Download,
  Upload,
  History,
  Save,
  Undo2,
  Eye,
  ShieldAlert,
  Lock,
  Database,
  AlertTriangle,
  X,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Switch } from '@/components/ui/Switch';
import { Modal } from '@/components/ui/Modal';
import { LoadingState } from '@/components/ui/LoadingState';
import { EmptyState } from '@/components/ui/EmptyState';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { cn } from '@/utils/cn';
import {
  configurationApi,
  type ConfigKeyMetadata,
  type ConfigSection,
  type ConfigPreviewRow,
  type ConfigSnapshot,
  type ConfigSource,
} from '@admin/services/configuration';

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function rawString(value: unknown, valueType: string): string {
  if (value == null) return '';
  if (valueType === 'boolean') return value ? 'true' : 'false';
  if (valueType === 'json') return typeof value === 'string' ? value : JSON.stringify(value);
  return String(value);
}

const SOURCE_LABEL: Record<ConfigSource, string> = {
  db: 'DB',
  env: 'ENV',
  default: 'DEFAULT',
  bootstrap: 'BOOTSTRAP',
};

function SourceBadge({ source }: { source: ConfigSource }) {
  const tone =
    source === 'db'
      ? 'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300'
      : source === 'env'
      ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300'
      : source === 'bootstrap'
      ? 'bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300'
      : 'bg-gray-100 text-gray-600 dark:bg-gray-800/30 dark:text-gray-500';
  return (
    <span
      className={cn(
        'inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[10px] tracking-wider',
        tone,
      )}
    >
      {SOURCE_LABEL[source]}
    </span>
  );
}

function FlagPill({ icon, label, tone }: { icon: React.ReactNode; label: string; tone: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px]', tone)}>
      {icon}
      {label}
    </span>
  );
}

// ─── Key row ────────────────────────────────────────────────────────────────

interface ConfigKeyRowProps {
  meta: ConfigKeyMetadata;
  pendingValue: unknown | undefined;
  onChange: (key: string, value: unknown) => void;
  onClear: (key: string) => void;
  onBooleanWrite: (key: string, value: boolean) => Promise<void>;
}

function ConfigKeyRow({ meta, pendingValue, onChange, onClear, onBooleanWrite }: ConfigKeyRowProps) {
  const isLocked = meta.bootstrap || meta.readonly;
  const hasPending = pendingValue !== undefined;
  const displayValue = hasPending ? pendingValue : meta.value;
  const isSensitiveMasked = meta.sensitive && meta.value === '***';

  const renderInput = () => {
    if (meta.value_type === 'boolean') {
      const checked = Boolean(displayValue);
      return (
        <Switch
          checked={checked}
          onCheckedChange={async next => {
            await onBooleanWrite(meta.key, next);
          }}
          disabled={isLocked}
          size="sm"
        />
      );
    }
    if (meta.value_type === 'int' || meta.value_type === 'float') {
      return (
        <Input
          type="number"
          step={meta.value_type === 'float' ? 'any' : '1'}
          value={rawString(displayValue, meta.value_type)}
          onChange={e => onChange(meta.key, e.target.value)}
          disabled={isLocked}
          className="w-40 font-mono text-sm"
        />
      );
    }
    if (meta.value_type === 'json') {
      return (
        <textarea
          value={rawString(displayValue, meta.value_type)}
          onChange={e => onChange(meta.key, e.target.value)}
          disabled={isLocked}
          rows={3}
          className="w-full font-mono text-xs px-2 py-1.5 rounded border border-gray-300 dark:border-gray-700 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-primary-500"
        />
      );
    }
    // string
    const inputValue = rawString(displayValue, meta.value_type);
    return (
      <Input
        type={meta.sensitive ? 'password' : 'text'}
        value={inputValue}
        onChange={e => onChange(meta.key, e.target.value)}
        placeholder={isSensitiveMasked ? '••• masked — type to overwrite •••' : meta.default || ''}
        disabled={isLocked}
        className="w-full font-mono text-sm"
      />
    );
  };

  const lockTitle = meta.bootstrap
    ? `Bootstrap key — must be set via env (${meta.env_var ?? 'env var'}); requires restart`
    : meta.readonly
    ? 'Readonly — startup-only, requires restart'
    : '';
  return (
    <tr
      className={cn(
        'border-b border-gray-100 dark:border-gray-800 last:border-b-0',
        isLocked && 'border-l-2 border-l-gray-300 dark:border-l-gray-700',
        hasPending && 'bg-amber-50/40 dark:bg-amber-500/5',
      )}
    >
      <td className="px-4 py-3 align-top">
        <div className="flex items-center gap-2 flex-wrap">
          {isLocked && (
            <span title={lockTitle} aria-label={lockTitle} className="inline-flex shrink-0">
              <Lock size={12} className="text-gray-400 dark:text-gray-500" />
            </span>
          )}
          <span className="font-mono text-xs font-semibold text-gray-900 break-all">
            {meta.key}
          </span>
          <SourceBadge source={meta.source} />
          {meta.sensitive && (
            <FlagPill
              icon={<ShieldAlert size={10} />}
              label="SENSITIVE"
              tone="bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
            />
          )}
          {hasPending && (
            <FlagPill
              icon={<AlertTriangle size={10} />}
              label="PENDING"
              tone="bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200"
            />
          )}
        </div>
        {meta.description && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{meta.description}</p>
        )}
        {meta.examples && (
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">e.g. {meta.examples}</p>
        )}
      </td>
      <td className="px-4 py-3 align-top w-[42%]">
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">{renderInput()}</div>
          {hasPending && meta.value_type !== 'boolean' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onClear(meta.key)}
              title="Discard this change"
            >
              <Undo2 size={14} />
            </Button>
          )}
        </div>
        {meta.env_var && (
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500 font-mono">
            env: {meta.env_var}
          </p>
        )}
      </td>
      <td className="px-4 py-3 align-top text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
        {meta.updated_by ? (
          <>
            <div className="font-mono text-gray-700">{meta.updated_by}</div>
            <div>{formatDate(meta.updated_at)}</div>
          </>
        ) : (
          <span className="text-gray-300 dark:text-gray-600">—</span>
        )}
      </td>
    </tr>
  );
}

// ─── Key card (mobile) ─────────────────────────────────────────────────────

function ConfigKeyCard({ meta, pendingValue, onChange, onClear, onBooleanWrite }: ConfigKeyRowProps) {
  const isLocked = meta.bootstrap || meta.readonly;
  const hasPending = pendingValue !== undefined;
  const displayValue = hasPending ? pendingValue : meta.value;
  const isSensitiveMasked = meta.sensitive && meta.value === '***';

  const renderInput = () => {
    if (meta.value_type === 'boolean') {
      const checked = Boolean(displayValue);
      return (
        <Switch
          checked={checked}
          onCheckedChange={async next => {
            await onBooleanWrite(meta.key, next);
          }}
          disabled={isLocked}
          size="sm"
        />
      );
    }
    if (meta.value_type === 'int' || meta.value_type === 'float') {
      return (
        <Input
          type="number"
          step={meta.value_type === 'float' ? 'any' : '1'}
          value={rawString(displayValue, meta.value_type)}
          onChange={e => onChange(meta.key, e.target.value)}
          disabled={isLocked}
          className="w-full font-mono text-sm"
        />
      );
    }
    if (meta.value_type === 'json') {
      return (
        <textarea
          value={rawString(displayValue, meta.value_type)}
          onChange={e => onChange(meta.key, e.target.value)}
          disabled={isLocked}
          rows={3}
          className="w-full font-mono text-xs px-2 py-1.5 rounded border border-gray-300 dark:border-gray-700 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-primary-500"
        />
      );
    }
    const inputValue = rawString(displayValue, meta.value_type);
    return (
      <Input
        type={meta.sensitive ? 'password' : 'text'}
        value={inputValue}
        onChange={e => onChange(meta.key, e.target.value)}
        placeholder={isSensitiveMasked ? '••• masked — type to overwrite •••' : meta.default || ''}
        disabled={isLocked}
        className="w-full font-mono text-sm"
      />
    );
  };

  const lockTitle = meta.bootstrap
    ? `Bootstrap key — must be set via env (${meta.env_var ?? 'env var'}); requires restart`
    : meta.readonly
    ? 'Readonly — startup-only, requires restart'
    : '';

  return (
    <li
      className={cn(
        'rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5',
        isLocked && 'border-l-2 border-l-gray-300 dark:border-l-gray-700',
        hasPending && 'bg-amber-50/40 dark:bg-amber-500/5',
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            {isLocked && (
              <span title={lockTitle} aria-label={lockTitle} className="inline-flex shrink-0">
                <Lock size={12} className="text-gray-400 dark:text-gray-500" />
              </span>
            )}
            <span className="font-mono text-xs font-semibold text-gray-900 break-all">
              {meta.key}
            </span>
          </div>
          <div className="flex items-center gap-1 flex-wrap mt-1">
            <SourceBadge source={meta.source} />
            {meta.sensitive && (
              <FlagPill
                icon={<ShieldAlert size={10} />}
                label="SENSITIVE"
                tone="bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
              />
            )}
            {hasPending && (
              <FlagPill
                icon={<AlertTriangle size={10} />}
                label="PENDING"
                tone="bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200"
              />
            )}
          </div>
        </div>
      </div>
      {meta.description && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{meta.description}</p>
      )}
      {meta.examples && (
        <p className="text-xs text-gray-400 dark:text-gray-500 mb-2">e.g. {meta.examples}</p>
      )}
      <div className="flex items-start gap-2 mb-1">
        <div className="flex-1 min-w-0">{renderInput()}</div>
        {hasPending && meta.value_type !== 'boolean' && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onClear(meta.key)}
            title="Discard this change"
          >
            <Undo2 size={14} />
          </Button>
        )}
      </div>
      {meta.env_var && (
        <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mb-2">
          env: {meta.env_var}
        </p>
      )}
      <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-100">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-400">Updated by</div>
          {meta.updated_by ? (
            <div className="font-mono text-xs text-gray-700 truncate">{meta.updated_by}</div>
          ) : (
            <span className="text-gray-300 dark:text-gray-600 text-xs">—</span>
          )}
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-gray-400">At</div>
          {meta.updated_at ? (
            <div className="text-xs text-gray-500 tabular-nums">{formatDate(meta.updated_at)}</div>
          ) : (
            <span className="text-gray-300 dark:text-gray-600 text-xs">—</span>
          )}
        </div>
      </div>
    </li>
  );
}

// ─── Preview Modal ──────────────────────────────────────────────────────────

interface PreviewModalProps {
  open: boolean;
  rows: ConfigPreviewRow[];
  saving: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

function PreviewModal({ open, rows, saving, onClose, onConfirm }: PreviewModalProps) {
  const errors = rows.filter(r => r.error);
  const changes = rows.filter(r => r.will_change && !r.error);
  return (
    <Modal isOpen={open} onClose={onClose} title="Preview pending changes" className="max-w-4xl">
      <div className="space-y-4">
        {errors.length > 0 && (
          <div className="rounded border border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30 p-3">
            <p className="auth-mono-label text-rose-700 dark:text-rose-200">
              {errors.length} key{errors.length === 1 ? '' : 's'} will be rejected
            </p>
            <ul className="mt-2 space-y-1 text-xs font-mono text-rose-700 dark:text-rose-200">
              {errors.map(r => (
                <li key={r.key}>
                  <span className="font-semibold">{r.key}</span>: {r.error}
                </li>
              ))}
            </ul>
          </div>
        )}
        {changes.length === 0 ? (
          <EmptyState
            icon={<Eye size={32} className="text-gray-300 dark:text-gray-500" />}
            title="No effective changes"
            description="All proposed values match the current resolved values."
          />
        ) : (
          <div className="overflow-auto max-h-[60vh] border border-gray-200 dark:border-gray-700 rounded">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50 dark:bg-gray-100/30 sticky top-0">
                <tr>
                  <th className="auth-mono-label px-3 py-2 text-left">Key</th>
                  <th className="auth-mono-label px-3 py-2 text-left">Current</th>
                  <th className="auth-mono-label px-3 py-2 text-left">Proposed</th>
                </tr>
              </thead>
              <tbody>
                {changes.map(r => (
                  <tr key={r.key} className="border-t border-gray-100 dark:border-gray-800">
                    <td className="px-3 py-2 font-mono align-top">
                      <div>{r.key}</div>
                      {r.current_source && (
                        <div className="mt-1">
                          <SourceBadge source={r.current_source} />
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 align-top font-mono text-gray-500 dark:text-gray-400 break-all">
                      {r.sensitive ? '•••' : String(r.current ?? '')}
                    </td>
                    <td className="px-3 py-2 align-top font-mono text-primary-700 dark:text-primary-300 break-all">
                      {r.sensitive ? '•••' : String(r.proposed ?? '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            disabled={saving || changes.length === 0}
          >
            <Save size={14} />
            Apply {changes.length} change{changes.length === 1 ? '' : 's'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ─── Snapshots Modal ────────────────────────────────────────────────────────

interface SnapshotsModalProps {
  open: boolean;
  onClose: () => void;
  onRestored: () => Promise<void>;
}

function SnapshotsModal({ open, onClose, onRestored }: SnapshotsModalProps) {
  const [snapshots, setSnapshots] = useState<ConfigSnapshot[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const res = await configurationApi.listSnapshots({ limit: 100 });
      setSnapshots(res.items);
      setTotal(res.total);
    } catch {
      toast.error('Failed to load snapshots');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) fetchAll();
  }, [open, fetchAll]);

  const handleCreate = async () => {
    if (!newName.trim()) {
      toast.error('Snapshot name is required');
      return;
    }
    setCreating(true);
    try {
      await configurationApi.createSnapshot(newName.trim(), newDescription.trim() || undefined);
      setNewName('');
      setNewDescription('');
      await fetchAll();
      toast.success('Snapshot created');
    } catch {
      toast.error('Failed to create snapshot');
    } finally {
      setCreating(false);
    }
  };

  const handleRestore = async (snap: ConfigSnapshot) => {
    if (!window.confirm(`Restore snapshot "${snap.name}"? A pre-rollback snapshot is taken first so this is reversible.`)) {
      return;
    }
    setBusy(snap.id);
    try {
      const result = await configurationApi.restoreSnapshot(snap.id);
      toast.success(`Restored ${result.restored} keys (pre-rollback #${result.pre_rollback_snapshot_id})`);
      await fetchAll();
      await onRestored();
    } catch {
      toast.error('Restore failed');
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (snap: ConfigSnapshot) => {
    if (!window.confirm(`Delete snapshot "${snap.name}"? This cannot be undone.`)) return;
    setBusy(snap.id);
    try {
      await configurationApi.deleteSnapshot(snap.id);
      await fetchAll();
      toast.success('Snapshot deleted');
    } catch {
      toast.error('Delete failed');
    } finally {
      setBusy(null);
    }
  };

  const handlePrune = async () => {
    const keep = window.prompt('Keep how many newest non-manual snapshots?', '20');
    if (!keep) return;
    const n = Number(keep);
    if (!Number.isFinite(n) || n < 0) {
      toast.error('Invalid value');
      return;
    }
    try {
      const res = await configurationApi.pruneSnapshots(n);
      toast.success(`Deleted ${res.deleted} non-manual snapshots`);
      await fetchAll();
    } catch {
      toast.error('Prune failed');
    }
  };

  return (
    <Modal isOpen={open} onClose={onClose} title="Snapshot history" className="max-w-4xl">
      <div className="space-y-4">
        <div className="rounded border border-gray-200 dark:border-gray-700 p-3 space-y-2">
          <p className="auth-mono-label text-gray-600 dark:text-gray-300">Take a manual snapshot</p>
          <div className="flex flex-col sm:flex-row gap-2">
            <Input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="Name (required)"
              className="sm:flex-1"
            />
            <Input
              value={newDescription}
              onChange={e => setNewDescription(e.target.value)}
              placeholder="Description (optional)"
              className="sm:flex-1"
            />
            <Button variant="primary" onClick={handleCreate} disabled={creating}>
              <History size={14} />
              Create
            </Button>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {total} snapshot{total === 1 ? '' : 's'} total
          </p>
          <Button variant="ghost" size="sm" onClick={handlePrune}>
            Prune auto-snapshots…
          </Button>
        </div>

        {loading ? (
          <LoadingState message="Loading snapshots…" />
        ) : snapshots.length === 0 ? (
          <EmptyState
            icon={<History size={32} className="text-gray-300 dark:text-gray-500" />}
            title="No snapshots yet"
            description="Snapshots are created on every import and rollback, or manually here."
          />
        ) : (
          <div className="overflow-auto max-h-[55vh] border border-gray-200 dark:border-gray-700 rounded">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50 dark:bg-gray-100/30 sticky top-0">
                <tr>
                  <th className="auth-mono-label px-3 py-2 text-left">ID</th>
                  <th className="auth-mono-label px-3 py-2 text-left">Name</th>
                  <th className="auth-mono-label px-3 py-2 text-left">Trigger</th>
                  <th className="auth-mono-label px-3 py-2 text-left">Keys</th>
                  <th className="auth-mono-label px-3 py-2 text-left">By</th>
                  <th className="auth-mono-label px-3 py-2 text-left">Created</th>
                  <th className="auth-mono-label px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map(s => (
                  <tr key={s.id} className="border-t border-gray-100 dark:border-gray-800">
                    <td className="px-3 py-2 font-mono">#{s.id}</td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900">{s.name}</div>
                      {s.description && (
                        <div className="text-gray-500 dark:text-gray-400">{s.description}</div>
                      )}
                      {s.parent_snapshot_id != null && (
                        <div className="text-[11px] text-gray-400 dark:text-gray-500 font-mono">
                          ↩ from #{s.parent_snapshot_id}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      <span
                        className={cn(
                          'inline-flex items-center px-1.5 py-0.5 rounded text-[10px]',
                          s.trigger === 'manual'
                            ? 'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300'
                            : 'bg-gray-100 text-gray-600 dark:bg-gray-800/30 dark:text-gray-500',
                        )}
                      >
                        {s.trigger}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono">{s.key_count}</td>
                    <td className="px-3 py-2 font-mono text-gray-600 dark:text-gray-300">
                      {s.created_by || '—'}
                    </td>
                    <td className="px-3 py-2 text-gray-500 dark:text-gray-400">
                      {formatDate(s.created_at)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex items-center gap-1">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleRestore(s)}
                          disabled={busy === s.id}
                        >
                          Restore
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(s)}
                          disabled={busy === s.id}
                        >
                          <X size={14} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}

// ─── Import Modal ───────────────────────────────────────────────────────────

interface ImportModalProps {
  open: boolean;
  onClose: () => void;
  onImported: () => Promise<void>;
}

function ImportModal({ open, onClose, onImported }: ImportModalProps) {
  const [json, setJson] = useState('');
  const [snapshotFirst, setSnapshotFirst] = useState(true);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    const text = await file.text();
    setJson(text);
  };

  const parsed = useMemo(() => {
    if (!json.trim()) return { ok: false, entries: {} as Record<string, unknown> };
    try {
      const data = JSON.parse(json);
      // Accept either {entries: {...}} or just {...}
      const entries =
        data && typeof data === 'object' && 'entries' in data
          ? (data as { entries: Record<string, unknown> }).entries
          : (data as Record<string, unknown>);
      if (!entries || typeof entries !== 'object' || Array.isArray(entries)) {
        return { ok: false, error: 'Expected an object of {key: value} pairs', entries: {} };
      }
      return { ok: true, entries };
    } catch (e) {
      return { ok: false, error: (e as Error).message, entries: {} };
    }
  }, [json]);

  const handleImport = async () => {
    if (!parsed.ok) {
      toast.error(parsed.error || 'Invalid JSON');
      return;
    }
    setBusy(true);
    try {
      const res = await configurationApi.importEntries(parsed.entries, snapshotFirst);
      toast.success(
        `Imported ${res.written} keys${res.snapshot_id ? ` (snapshot #${res.snapshot_id})` : ''}`,
      );
      await onImported();
      onClose();
      setJson('');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Import failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen={open} onClose={onClose} title="Import configuration" className="max-w-3xl">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={e => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
            }}
          />
          <Button variant="secondary" size="sm" onClick={() => fileRef.current?.click()}>
            Load file…
          </Button>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Paste JSON below or load from file. Accepts <code className="font-mono">{'{ "KEY": value, ... }'}</code> or
            an object with an <code className="font-mono">entries</code> property.
          </span>
        </div>
        <textarea
          value={json}
          onChange={e => setJson(e.target.value)}
          rows={14}
          spellCheck={false}
          className="w-full font-mono text-xs px-3 py-2 rounded border border-gray-300 dark:border-gray-700 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-primary-500"
          placeholder='{"APP_NAME": "Acme", "JWT_ACCESS_TOKEN_EXPIRY": 3600}'
        />
        {parsed.error && (
          <p className="text-xs text-rose-600 dark:text-rose-300 font-mono">{parsed.error}</p>
        )}
        <label className="inline-flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200 cursor-pointer">
          <input
            type="checkbox"
            checked={snapshotFirst}
            onChange={e => setSnapshotFirst(e.target.checked)}
            className="rounded"
          />
          Take a pre-import snapshot first (recommended)
        </label>
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={handleImport} disabled={busy || !parsed.ok}>
            <Upload size={14} />
            Import
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export function Configuration() {
  const [sections, setSections] = useState<ConfigSection[]>([]);
  const [selectedNs, setSelectedNs] = useState<string>('');
  const [keys, setKeys] = useState<ConfigKeyMetadata[]>([]);
  const [loadingSections, setLoadingSections] = useState(false);
  const [loadingKeys, setLoadingKeys] = useState(false);
  const [pending, setPending] = useState<Record<string, unknown>>({});
  const [previewRows, setPreviewRows] = useState<ConfigPreviewRow[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [snapshotsOpen, setSnapshotsOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchSections = useCallback(async () => {
    setLoadingSections(true);
    try {
      const res = await configurationApi.listSections();
      setSections(res.sections);
      if (!selectedNs && res.sections.length > 0) {
        setSelectedNs(res.sections[0].namespace);
      }
    } catch {
      toast.error('Failed to load sections');
    } finally {
      setLoadingSections(false);
    }
  }, [selectedNs]);

  const fetchSection = useCallback(async (ns: string) => {
    if (!ns) return;
    setLoadingKeys(true);
    try {
      const res = await configurationApi.getSection(ns);
      setKeys(res.keys);
    } catch {
      toast.error(`Failed to load ${ns}`);
    } finally {
      setLoadingKeys(false);
    }
  }, []);

  useEffect(() => {
    fetchSections();
  }, [fetchSections]);

  useEffect(() => {
    if (selectedNs) fetchSection(selectedNs);
  }, [selectedNs, fetchSection]);

  const handleChange = useCallback((key: string, value: unknown) => {
    setPending(prev => ({ ...prev, [key]: value }));
  }, []);

  const handleClear = useCallback((key: string) => {
    setPending(prev => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const handleBooleanWrite = useCallback(
    async (key: string, value: boolean) => {
      try {
        const updated = await configurationApi.setKey(key, value);
        setKeys(prev => prev.map(k => (k.key === key ? updated : k)));
        toast.success(`${key} → ${value ? 'on' : 'off'}`);
      } catch (e: any) {
        toast.error(e?.response?.data?.detail || `Failed to update ${key}`);
      }
    },
    [],
  );

  const pendingCount = Object.keys(pending).length;

  const openPreview = async () => {
    if (pendingCount === 0) {
      toast('No pending changes');
      return;
    }
    try {
      const res = await configurationApi.preview(pending);
      setPreviewRows(res.rows);
      setPreviewOpen(true);
    } catch {
      toast.error('Preview failed');
    }
  };

  const applyChanges = async () => {
    setSaving(true);
    try {
      const res = await configurationApi.bulkSet(pending);
      toast.success(`Saved ${res.written} keys`);
      setPending({});
      setPreviewOpen(false);
      if (selectedNs) await fetchSection(selectedNs);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleExport = async (includeSensitive: boolean) => {
    try {
      const res = await configurationApi.exportAll(includeSensitive);
      const blob = new Blob([JSON.stringify(res.entries, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `config-export-${new Date().toISOString().slice(0, 19)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success(
        includeSensitive
          ? 'Exported with secrets — handle with care'
          : 'Exported (sensitive values masked)',
      );
    } catch {
      toast.error('Export failed');
    }
  };

  const refreshAll = async () => {
    await fetchSections();
    if (selectedNs) await fetchSection(selectedNs);
  };

  if (loadingSections && sections.length === 0) {
    return (
      <PageShell>
        <PageHeader title="Configuration" icon={<Settings2 size={20} />} />
        <LoadingState message="Loading configuration…" />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Configuration"
        description="Runtime config — changes take effect immediately, no redeploy"
        icon={<Settings2 size={20} />}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <Button variant="ghost" size="sm" onClick={refreshAll}>
              <RefreshCw size={14} className={cn(loadingKeys && 'animate-spin')} />
              Refresh
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSnapshotsOpen(true)}>
              <History size={14} />
              Snapshots
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setImportOpen(true)}>
              <Upload size={14} />
              Import
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handleExport(false)}>
              <Download size={14} />
              Export
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handleExport(true)}>
              <Download size={14} />
              Export+secrets
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-4">
        {/* Section rail */}
        <nav
          aria-label="Configuration sections"
          className="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900/40 p-2 h-fit"
        >
          <p className="auth-mono-label px-2 pt-1 pb-2 text-gray-500 dark:text-gray-400">Sections</p>
          <ul className="space-y-0.5">
            {sections.map(s => (
              <li key={s.namespace}>
                <button
                  type="button"
                  onClick={() => setSelectedNs(s.namespace)}
                  className={cn(
                    'w-full flex items-center justify-between gap-2 pl-2.5 pr-2 py-1.5 rounded text-sm font-mono transition-colors border-l-2',
                    selectedNs === s.namespace
                      ? 'bg-primary-50 dark:bg-primary-500/15 text-primary-700 dark:text-primary-300 border-l-primary-500 dark:border-l-primary-400 font-semibold'
                      : 'text-gray-700 dark:text-gray-300 border-l-transparent hover:bg-gray-50 dark:hover:bg-gray-100/30',
                  )}
                >
                  <span className="truncate">{s.namespace}</span>
                  <span className="text-xs text-gray-400 dark:text-gray-500">{s.key_count}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Section editor */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900/40 overflow-hidden">
          {loadingKeys && keys.length === 0 ? (
            <LoadingState message="Loading keys…" />
          ) : keys.length === 0 ? (
            <EmptyState
              icon={<Database size={32} className="text-gray-300 dark:text-gray-500" />}
              title="Empty section"
              description="No keys are registered for this namespace."
            />
          ) : (
            <>
              <table className="hidden md:table min-w-full">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-100/30 border-b border-gray-200 dark:border-gray-700">
                    <th className="auth-mono-label px-4 py-3 text-left">Key</th>
                    <th className="auth-mono-label px-4 py-3 text-left">Value</th>
                    <th className="auth-mono-label px-4 py-3 text-left">Last edit</th>
                  </tr>
                </thead>
                <tbody>
                  {keys.map(meta => (
                    <ConfigKeyRow
                      key={meta.key}
                      meta={meta}
                      pendingValue={pending[meta.key]}
                      onChange={handleChange}
                      onClear={handleClear}
                      onBooleanWrite={handleBooleanWrite}
                    />
                  ))}
                </tbody>
              </table>

              {/* Mobile: card list — one card per config key. */}
              <ul className="md:hidden flex flex-col gap-2 p-2">
                {keys.map(meta => (
                  <ConfigKeyCard
                    key={meta.key}
                    meta={meta}
                    pendingValue={pending[meta.key]}
                    onChange={handleChange}
                    onClear={handleClear}
                    onBooleanWrite={handleBooleanWrite}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      {/* Sticky bottom action bar */}
      {pendingCount > 0 && (
        <div className="fixed bottom-4 inset-x-4 md:left-auto md:right-4 md:max-w-md z-30">
          <div className="rounded-lg border border-amber-300 dark:border-amber-500/40 bg-amber-50 dark:bg-amber-500/10 shadow-lg p-3 flex items-center gap-3">
            <AlertTriangle size={16} className="text-amber-700 dark:text-amber-300 shrink-0" />
            <span className="text-sm text-amber-900 dark:text-amber-100 flex-1">
              {pendingCount} pending change{pendingCount === 1 ? '' : 's'}
            </span>
            <Button variant="ghost" size="sm" onClick={() => setPending({})} disabled={saving}>
              Discard
            </Button>
            <Button variant="primary" size="sm" onClick={openPreview} disabled={saving}>
              <Eye size={14} />
              Review &amp; save
            </Button>
          </div>
        </div>
      )}

      <PreviewModal
        open={previewOpen}
        rows={previewRows}
        saving={saving}
        onClose={() => setPreviewOpen(false)}
        onConfirm={applyChanges}
      />
      <SnapshotsModal
        open={snapshotsOpen}
        onClose={() => setSnapshotsOpen(false)}
        onRestored={refreshAll}
      />
      <ImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={refreshAll}
      />
    </PageShell>
  );
}
