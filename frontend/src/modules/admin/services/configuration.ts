import { apiRequest } from '@/api/client';

// ─── Types ──────────────────────────────────────────────────────────────────

export type ConfigSource = 'db' | 'env' | 'default' | 'bootstrap';
export type ConfigValueType = 'string' | 'int' | 'boolean' | 'float' | 'json';
export type SnapshotTrigger = 'manual' | 'pre_import' | 'pre_seed' | 'pre_rollback';

export interface ConfigKeyMetadata {
  key: string;
  namespace: string;
  value_type: ConfigValueType;
  value: unknown;
  raw_value: string;
  default: string;
  source: ConfigSource;
  sensitive: boolean;
  readonly: boolean;
  bootstrap: boolean;
  description: string;
  examples: string;
  env_var: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface ConfigSection {
  namespace: string;
  key_count: number;
}

export interface ConfigExportRow {
  key: string;
  namespace: string;
  value_type: ConfigValueType;
  value: unknown;
  default: string;
  source: ConfigSource;
  sensitive: boolean;
  readonly: boolean;
  bootstrap: boolean;
  updated_at: string | null;
  updated_by: string | null;
}

export interface ConfigPreviewRow {
  key: string;
  namespace?: string;
  value_type?: ConfigValueType;
  sensitive?: boolean;
  readonly?: boolean;
  bootstrap?: boolean;
  current?: unknown;
  current_source?: ConfigSource;
  proposed?: unknown;
  will_change: boolean;
  error?: string;
}

export interface ConfigSnapshot {
  id: number;
  name: string;
  description: string | null;
  trigger: SnapshotTrigger;
  key_count: number;
  parent_snapshot_id: number | null;
  created_by: string | null;
  created_at: string | null;
  payload?: string;
}

export interface SnapshotListResponse {
  items: ConfigSnapshot[];
  total: number;
}

export interface ImportResult {
  written: number;
  snapshot_id: number | null;
}

export interface RestoreResult {
  restored: number;
  pre_rollback_snapshot_id: number;
  from_snapshot_id: number;
}

// ─── Client ─────────────────────────────────────────────────────────────────

const BASE = '/admin/configuration';

export const configurationApi = {
  // Sections + keys

  listSections(): Promise<{ sections: ConfigSection[] }> {
    return apiRequest({ method: 'GET', url: `${BASE}/sections` });
  },

  getSection(namespace: string): Promise<{ namespace: string; keys: ConfigKeyMetadata[] }> {
    return apiRequest({ method: 'GET', url: `${BASE}/sections/${namespace}` });
  },

  getKey(key: string): Promise<ConfigKeyMetadata> {
    return apiRequest({ method: 'GET', url: `${BASE}/keys/${key}` });
  },

  setKey(key: string, value: unknown): Promise<ConfigKeyMetadata> {
    return apiRequest({ method: 'PUT', url: `${BASE}/keys/${key}`, data: { value } });
  },

  bulkSet(entries: Record<string, unknown>): Promise<{ written: number }> {
    return apiRequest({ method: 'POST', url: `${BASE}/bulk`, data: { entries } });
  },

  // Export / Import / Preview

  exportAll(includeSensitive = false): Promise<{ entries: ConfigExportRow[] }> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/export`,
      params: { include_sensitive: includeSensitive },
    });
  },

  importEntries(entries: Record<string, unknown>, snapshotFirst = true): Promise<ImportResult> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/import`,
      data: { entries, snapshot_first: snapshotFirst },
    });
  },

  preview(entries: Record<string, unknown>): Promise<{ rows: ConfigPreviewRow[] }> {
    return apiRequest({ method: 'POST', url: `${BASE}/preview`, data: { entries } });
  },

  // Snapshots

  createSnapshot(name: string, description?: string): Promise<ConfigSnapshot> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/snapshots`,
      data: { name, description: description ?? null },
    });
  },

  listSnapshots(params: {
    limit?: number;
    offset?: number;
    trigger?: SnapshotTrigger;
  } = {}): Promise<SnapshotListResponse> {
    return apiRequest({ method: 'GET', url: `${BASE}/snapshots`, params });
  },

  getSnapshot(id: number, includePayload = false): Promise<ConfigSnapshot> {
    return apiRequest({
      method: 'GET',
      url: `${BASE}/snapshots/${id}`,
      params: { include_payload: includePayload },
    });
  },

  deleteSnapshot(id: number): Promise<{ deleted: boolean }> {
    return apiRequest({ method: 'DELETE', url: `${BASE}/snapshots/${id}` });
  },

  restoreSnapshot(id: number): Promise<RestoreResult> {
    return apiRequest({ method: 'POST', url: `${BASE}/snapshots/${id}/restore` });
  },

  pruneSnapshots(keep: number): Promise<{ deleted: number; kept_min: number }> {
    return apiRequest({
      method: 'POST',
      url: `${BASE}/snapshots/prune`,
      params: { keep },
    });
  },
};
