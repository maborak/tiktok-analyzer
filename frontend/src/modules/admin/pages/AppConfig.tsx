import { useState, useEffect, useCallback } from 'react';
import { Settings, Plus, Trash2, Save, RefreshCw, Database } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Modal } from '@/components/ui/Modal';
import { Switch } from '@/components/ui/Switch';
import { LoadingState } from '@/components/ui/LoadingState';
import { EmptyState } from '@/components/ui/EmptyState';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { apiRequest } from '@/api/client';
import { cn } from '@/utils/cn';
import toast from 'react-hot-toast';
import type { AppConfigEntry } from '@/types/api';

// ─── Response types ─────────────────────────────────────────────────────────

interface NamespacesResponse {
  namespaces: string[];
}

interface ConfigEntriesResponse {
  entries: AppConfigEntry[];
  namespace: string;
}

// ─── Inline edit state ──────────────────────────────────────────────────────

interface EditingState {
  id: number;
  value: string;
}

// ─── Add entry form state ───────────────────────────────────────────────────

interface NewEntryForm {
  key: string;
  value: string;
  value_type: 'int' | 'string' | 'boolean';
  scope: 'global' | 'worker';
  scope_id: string;
}

const EMPTY_FORM: NewEntryForm = {
  key: '',
  value: '',
  value_type: 'string',
  scope: 'global',
  scope_id: '',
};

// ─── Helpers ────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ─── Component ──────────────────────────────────────────────────────────────

export function AppConfig() {
  // Namespace list
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [selectedNamespace, setSelectedNamespace] = useState<string>('');
  const [namespacesLoading, setNamespacesLoading] = useState(false);

  // Config entries
  const [entries, setEntries] = useState<AppConfigEntry[]>([]);
  const [entriesLoading, setEntriesLoading] = useState(false);

  // Inline editing
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [saving, setSaving] = useState(false);

  // Add modal
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm, setAddForm] = useState<NewEntryForm>({ ...EMPTY_FORM });
  const [addSaving, setAddSaving] = useState(false);

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<AppConfigEntry | null>(null);
  const [deleting, setDeleting] = useState(false);

  // ── Fetch namespaces ────────────────────────────────────────────────────

  const fetchNamespaces = useCallback(async () => {
    setNamespacesLoading(true);
    try {
      const data = await apiRequest<NamespacesResponse>({
        method: 'GET',
        url: '/admin/config/namespaces',
      });
      if (data) {
        setNamespaces(data.namespaces);
        // Auto-select first namespace if none selected
        if (!selectedNamespace && data.namespaces.length > 0) {
          setSelectedNamespace(data.namespaces[0]);
        }
      }
    } catch {
      toast.error('Failed to load namespaces');
    } finally {
      setNamespacesLoading(false);
    }
  }, [selectedNamespace]);

  // ── Fetch entries for selected namespace ────────────────────────────────

  const fetchEntries = useCallback(async () => {
    if (!selectedNamespace) return;
    setEntriesLoading(true);
    try {
      const data = await apiRequest<ConfigEntriesResponse>({
        method: 'GET',
        url: `/admin/config/${selectedNamespace}`,
        params: { scope: 'all' },
      });
      if (data) {
        setEntries(data.entries);
      }
    } catch {
      toast.error('Failed to load config entries');
    } finally {
      setEntriesLoading(false);
    }
  }, [selectedNamespace]);

  useEffect(() => {
    fetchNamespaces();
  }, []);

  useEffect(() => {
    if (selectedNamespace) {
      setEditing(null);
      fetchEntries();
    }
  }, [selectedNamespace, fetchEntries]);

  // ── Inline edit handlers ────────────────────────────────────────────────

  const startEditing = (entry: AppConfigEntry) => {
    setEditing({ id: entry.id, value: entry.value });
  };

  const cancelEditing = () => {
    setEditing(null);
  };

  const saveEntry = async (entry: AppConfigEntry) => {
    if (!editing) return;
    if (editing.value === entry.value) {
      setEditing(null);
      return;
    }

    setSaving(true);

    // Optimistic update
    const previousEntries = [...entries];
    setEntries(prev =>
      prev.map(e =>
        e.id === entry.id ? { ...e, value: editing.value } : e
      )
    );
    setEditing(null);

    try {
      await apiRequest({
        method: 'PUT',
        url: `/admin/config/${entry.namespace}/${entry.key}`,
        data: {
          value: editing.value,
          value_type: entry.value_type,
          scope: entry.scope,
          ...(entry.scope_id ? { scope_id: entry.scope_id } : {}),
        },
      });
      toast.success(`Updated ${entry.key}`);
    } catch {
      // Revert optimistic update
      setEntries(previousEntries);
      toast.error(`Failed to update ${entry.key}`);
    } finally {
      setSaving(false);
    }
  };

  // ── Boolean toggle (no inline edit needed) ──────────────────────────────

  const toggleBoolean = async (entry: AppConfigEntry) => {
    const newValue = entry.value === 'true' ? 'false' : 'true';

    // Optimistic update
    const previousEntries = [...entries];
    setEntries(prev =>
      prev.map(e =>
        e.id === entry.id ? { ...e, value: newValue } : e
      )
    );

    try {
      await apiRequest({
        method: 'PUT',
        url: `/admin/config/${entry.namespace}/${entry.key}`,
        data: {
          value: newValue,
          value_type: entry.value_type,
          scope: entry.scope,
          ...(entry.scope_id ? { scope_id: entry.scope_id } : {}),
        },
      });
    } catch {
      // Revert
      setEntries(previousEntries);
      toast.error(`Failed to toggle ${entry.key}`);
    }
  };

  // ── Add entry ───────────────────────────────────────────────────────────

  const openAddModal = () => {
    setAddForm({
      ...EMPTY_FORM,
      value_type: 'string',
      scope: 'global',
    });
    setAddModalOpen(true);
  };

  const handleAdd = async () => {
    if (!addForm.key.trim()) {
      toast.error('Key is required');
      return;
    }

    const namespace = selectedNamespace || addForm.key.split('.')[0];
    if (!namespace) {
      toast.error('Select a namespace first');
      return;
    }

    setAddSaving(true);
    try {
      await apiRequest({
        method: 'PUT',
        url: `/admin/config/${namespace}/${addForm.key}`,
        data: {
          value: addForm.value,
          value_type: addForm.value_type,
          scope: addForm.scope,
          ...(addForm.scope === 'worker' && addForm.scope_id
            ? { scope_id: addForm.scope_id }
            : {}),
        },
      });
      toast.success(`Added ${addForm.key}`);
      setAddModalOpen(false);
      // Refresh both namespaces and entries
      await fetchNamespaces();
      await fetchEntries();
    } catch {
      toast.error('Failed to add config entry');
    } finally {
      setAddSaving(false);
    }
  };

  // ── Delete entry ────────────────────────────────────────────────────────

  const confirmDelete = async () => {
    if (!deleteTarget) return;

    setDeleting(true);

    // Optimistic removal
    const previousEntries = [...entries];
    setEntries(prev => prev.filter(e => e.id !== deleteTarget.id));
    setDeleteTarget(null);

    try {
      await apiRequest({
        method: 'DELETE',
        url: `/admin/config/${deleteTarget.namespace}/${deleteTarget.key}`,
        params: {
          scope: deleteTarget.scope,
          ...(deleteTarget.scope_id ? { scope_id: deleteTarget.scope_id } : {}),
        },
      });
      toast.success(`Deleted ${deleteTarget.key}`);
    } catch {
      // Revert
      setEntries(previousEntries);
      toast.error(`Failed to delete ${deleteTarget.key}`);
    } finally {
      setDeleting(false);
    }
  };

  // ── Refresh all ─────────────────────────────────────────────────────────

  const handleRefresh = async () => {
    await fetchNamespaces();
    if (selectedNamespace) {
      await fetchEntries();
    }
  };

  // ── Value cell renderer ─────────────────────────────────────────────────

  const renderValueCell = (entry: AppConfigEntry) => {
    // Boolean: always show a toggle switch
    if (entry.value_type === 'boolean') {
      return (
        <Switch
          checked={entry.value === 'true'}
          onCheckedChange={() => toggleBoolean(entry)}
          size="sm"
        />
      );
    }

    // Currently editing this row
    if (editing?.id === entry.id) {
      return (
        <div className="flex items-center gap-2">
          <Input
            type={entry.value_type === 'int' ? 'number' : 'text'}
            value={editing.value}
            onChange={e => setEditing({ ...editing, value: e.target.value })}
            onKeyDown={e => {
              if (e.key === 'Enter') saveEntry(entry);
              if (e.key === 'Escape') cancelEditing();
            }}
            className="w-48 text-sm py-1 px-2"
            autoFocus
          />
          <Button
            variant="primary"
            size="sm"
            onClick={() => saveEntry(entry)}
            disabled={saving}
          >
            <Save size={14} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={cancelEditing}
          >
            Cancel
          </Button>
        </div>
      );
    }

    // Display mode: clickable value
    return (
      <button
        onClick={() => startEditing(entry)}
        className="text-left font-mono text-sm text-gray-800 hover:text-primary-600 hover:underline cursor-pointer transition-colors"
        title="Click to edit"
      >
        {entry.value || <span className="text-gray-400 italic">empty</span>}
      </button>
    );
  };

  // ── Scope badge ─────────────────────────────────────────────────────────

  const renderScopeBadge = (entry: AppConfigEntry) => {
    if (entry.scope === 'global') {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
          Global
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
        Worker {entry.scope_id || '?'}
      </span>
    );
  };

  // ── Initial loading ─────────────────────────────────────────────────────

  if (namespacesLoading && namespaces.length === 0) {
    return (
      <PageShell>
        <PageHeader
          title="App Configuration"
          icon={<Settings size={20} />}
        />
        <LoadingState message="Loading configuration..." />
      </PageShell>
    );
  }

  // ── Render ──────────────────────────────────────────────────────────────

  return (
    <PageShell>
      <PageHeader
        title="App Configuration"
        description="Manage app configurations by namespace"
        icon={<Settings size={20} />}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={handleRefresh}>
              <RefreshCw
                size={14}
                className={cn((namespacesLoading || entriesLoading) && 'animate-spin')}
              />
              Refresh
            </Button>
            <Button variant="primary" size="sm" onClick={openAddModal}>
              <Plus size={14} />
              Add Entry
            </Button>
          </div>
        }
      />

      {/* Namespace selector */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex items-center gap-3">
          <Database size={16} className="text-gray-500 shrink-0" />
          <label
            htmlFor="namespace-select"
            className="text-sm font-medium text-gray-700 shrink-0"
          >
            Namespace
          </label>
          <Select
            id="namespace-select"
            value={selectedNamespace}
            onChange={e => setSelectedNamespace(e.target.value)}
            className="w-64 text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            {namespaces.length === 0 && (
              <option value="">No namespaces found</option>
            )}
            {namespaces.map(ns => (
              <option key={ns} value={ns}>
                {ns}
              </option>
            ))}
          </Select>
          <span className="text-xs text-gray-400">
            {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
          </span>
        </div>
      </div>

      {/* Config table */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {entriesLoading && entries.length === 0 ? (
          <div className="flex items-center justify-center py-12">
            <RefreshCw size={20} className="animate-spin text-gray-400" />
            <span className="ml-2 text-gray-500">Loading entries...</span>
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={<Settings size={40} className="text-gray-300" />}
            title="No configuration entries"
            description={
              selectedNamespace
                ? `No entries found in the "${selectedNamespace}" namespace.`
                : 'Select a namespace to view configurations.'
            }
            action={
              selectedNamespace ? (
                <Button variant="primary" size="sm" onClick={openAddModal}>
                  <Plus size={14} />
                  Add Entry
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr className="bg-gray-50">
                  <th className="auth-mono-label px-4 py-3 text-left">
                    Key
                  </th>
                  <th className="auth-mono-label px-4 py-3 text-left">
                    Value
                  </th>
                  <th className="auth-mono-label px-4 py-3 text-left">
                    Type
                  </th>
                  <th className="auth-mono-label px-4 py-3 text-left">
                    Scope
                  </th>
                  <th className="auth-mono-label px-4 py-3 text-left">
                    Updated
                  </th>
                  <th className="auth-mono-label px-4 py-3 text-right">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {entries.map(entry => (
                  <tr
                    key={entry.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm font-medium text-gray-900 whitespace-nowrap">
                      {entry.key}
                    </td>
                    <td className="px-4 py-3">
                      {renderValueCell(entry)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      <span className="inline-flex items-center px-2 py-0.5 rounded bg-gray-100 text-gray-600 font-mono">
                        {entry.value_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {renderScopeBadge(entry)}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      <div>{formatDate(entry.updated_at)}</div>
                      {entry.updated_by && (
                        <div className="text-gray-400 mt-0.5">
                          by {entry.updated_by}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(entry)}
                        className="text-red-500 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Add Entry Modal ──────────────────────────────────────────────── */}
      <Modal
        isOpen={addModalOpen}
        title="Add Configuration"
        onClose={() => setAddModalOpen(false)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setAddModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleAdd}
              disabled={addSaving || !addForm.key.trim()}
            >
              {addSaving ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save size={14} />
                  Save
                </>
              )}
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          {/* Key */}
          <div>
            <label
              htmlFor="add-key"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Key
            </label>
            <Input
              id="add-key"
              value={addForm.key}
              onChange={e =>
                setAddForm(prev => ({ ...prev, key: e.target.value }))
              }
              placeholder="e.g. max_retries"
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-2"
            />
          </div>

          {/* Value type */}
          <div>
            <label
              htmlFor="add-value-type"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Value Type
            </label>
            <Select
              id="add-value-type"
              value={addForm.value_type}
              onChange={e =>
                setAddForm(prev => ({
                  ...prev,
                  value_type: e.target.value as NewEntryForm['value_type'],
                  value:
                    e.target.value === 'boolean' ? 'false' : prev.value,
                }))
              }
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-2"
            >
              <option value="string">string</option>
              <option value="int">int</option>
              <option value="boolean">boolean</option>
            </Select>
          </div>

          {/* Value */}
          <div>
            <label
              htmlFor="add-value"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Value
            </label>
            {addForm.value_type === 'boolean' ? (
              <Switch
                checked={addForm.value === 'true'}
                onCheckedChange={checked =>
                  setAddForm(prev => ({
                    ...prev,
                    value: checked ? 'true' : 'false',
                  }))
                }
                label={addForm.value === 'true' ? 'true' : 'false'}
              />
            ) : (
              <Input
                id="add-value"
                type={addForm.value_type === 'int' ? 'number' : 'text'}
                value={addForm.value}
                onChange={e =>
                  setAddForm(prev => ({ ...prev, value: e.target.value }))
                }
                placeholder={
                  addForm.value_type === 'int' ? 'e.g. 10' : 'e.g. some value'
                }
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-2"
              />
            )}
          </div>

          {/* Scope */}
          <div>
            <label
              htmlFor="add-scope"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Scope
            </label>
            <Select
              id="add-scope"
              value={addForm.scope}
              onChange={e =>
                setAddForm(prev => ({
                  ...prev,
                  scope: e.target.value as NewEntryForm['scope'],
                  scope_id: e.target.value === 'global' ? '' : prev.scope_id,
                }))
              }
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-2"
            >
              <option value="global">Global</option>
              <option value="worker">Worker</option>
            </Select>
          </div>

          {/* Scope ID (only for worker scope) */}
          {addForm.scope === 'worker' && (
            <div>
              <label
                htmlFor="add-scope-id"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Worker ID
              </label>
              <Input
                id="add-scope-id"
                value={addForm.scope_id}
                onChange={e =>
                  setAddForm(prev => ({ ...prev, scope_id: e.target.value }))
                }
                placeholder="e.g. 1"
                className="w-full text-sm border border-gray-300 rounded-md px-3 py-2"
              />
            </div>
          )}
        </div>
      </Modal>

      {/* ── Delete Confirmation Modal ────────────────────────────────────── */}
      <Modal
        isOpen={deleteTarget !== null}
        title="Delete Configuration"
        onClose={() => setDeleteTarget(null)}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDeleteTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={confirmDelete}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  Deleting...
                </>
              ) : (
                <>
                  <Trash2 size={14} />
                  Delete
                </>
              )}
            </Button>
          </div>
        }
      >
        {deleteTarget && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Are you sure you want to delete this configuration? This
              action cannot be undone.
            </p>
            <div className="bg-gray-50 rounded-md p-3 space-y-1">
              <div className="text-sm">
                <span className="text-gray-500">Key:</span>{' '}
                <span className="font-medium text-gray-900">
                  {deleteTarget.key}
                </span>
              </div>
              <div className="text-sm">
                <span className="text-gray-500">Namespace:</span>{' '}
                <span className="font-medium text-gray-900">
                  {deleteTarget.namespace}
                </span>
              </div>
              <div className="text-sm">
                <span className="text-gray-500">Scope:</span>{' '}
                {renderScopeBadge(deleteTarget)}
              </div>
              <div className="text-sm">
                <span className="text-gray-500">Current value:</span>{' '}
                <span className="font-mono text-gray-900">
                  {deleteTarget.value}
                </span>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </PageShell>
  );
}
