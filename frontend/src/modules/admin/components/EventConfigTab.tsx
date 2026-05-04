import { useState, useEffect, useCallback, Fragment } from 'react';
import { RefreshCw, Settings, ToggleLeft, ToggleRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Switch } from '@/components/ui/Switch';
import { apiRequest } from '@/api/client';
import { cn } from '@/utils/cn';
import toast from 'react-hot-toast';

interface EventConfigEntry {
  event_type: string;
  handler_name: string;
  enabled: boolean;
}

interface EventConfigResponse {
  configs: EventConfigEntry[];
  handlers: string[];
  event_types: string[];
}

const EVENT_CATEGORIES: Record<string, string[]> = {
  'User': ['user_registered', 'user_login', 'user_verification_requested', 'user_password_reset_requested'],
  'Handler Outcome': ['email_sent', 'email_failed'],
  'Billing': ['credit_purchased', 'credit_exhausted'],
  'Ticket': ['ticket_created', 'ticket_updated'],
  'System': ['admin_notification', 'config_changed'],
};

function formatEventType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatHandlerName(name: string): string {
  return name.replace(/Handler$/, '').replace(/([A-Z])/g, ' $1').trim();
}

export function EventConfigTab() {
  const [config, setConfig] = useState<EventConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [bulkLoading, setBulkLoading] = useState(false);
  // Local override map for optimistic updates
  const [localOverrides, setLocalOverrides] = useState<Record<string, boolean>>({});

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiRequest<EventConfigResponse>({
        method: 'GET',
        url: '/admin/monitoring/events/config',
      });
      if (data) {
        setConfig(data);
        setLocalOverrides({});
      }
    } catch {
      toast.error('Failed to load event config');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  const isEnabled = (eventType: string, handler: string): boolean => {
    const key = `${eventType}:${handler}`;
    if (key in localOverrides) return localOverrides[key];
    const entry = config?.configs.find(c => c.event_type === eventType && c.handler_name === handler);
    return entry ? entry.enabled : true; // Default enabled
  };

  const toggleConfig = async (eventType: string, handler: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    const key = `${eventType}:${handler}`;

    // Optimistic update
    setLocalOverrides(prev => ({ ...prev, [key]: newEnabled }));

    try {
      await apiRequest({
        method: 'PUT',
        url: '/admin/monitoring/events/config',
        data: { event_type: eventType, handler_name: handler, enabled: newEnabled },
      });
    } catch {
      // Revert optimistic update
      setLocalOverrides(prev => ({ ...prev, [key]: currentEnabled }));
      toast.error('Failed to update config');
    }
  };

  // Bulk toggle: set all event types for a handler to enabled/disabled
  const bulkToggleHandler = async (handler: string, enabled: boolean) => {
    if (!config) return;
    const allTypes = [...Object.values(EVENT_CATEGORIES).flat(), ...config.event_types.filter(t => !Object.values(EVENT_CATEGORIES).flat().includes(t))];
    const updates = allTypes.map(et => ({ event_type: et, handler_name: handler, enabled }));

    // Optimistic
    const overrides: Record<string, boolean> = {};
    for (const et of allTypes) overrides[`${et}:${handler}`] = enabled;
    setLocalOverrides(prev => ({ ...prev, ...overrides }));

    setBulkLoading(true);
    try {
      await apiRequest({
        method: 'PUT',
        url: '/admin/monitoring/events/config/bulk',
        data: { updates },
      });
      toast.success(`${formatHandlerName(handler)}: all ${enabled ? 'enabled' : 'disabled'}`);
    } catch {
      // Revert
      const revert: Record<string, boolean> = {};
      for (const et of allTypes) revert[`${et}:${handler}`] = !enabled;
      setLocalOverrides(prev => ({ ...prev, ...revert }));
      toast.error('Bulk update failed');
    } finally {
      setBulkLoading(false);
    }
  };

  // Bulk toggle: set all handlers for a category's event types
  const bulkToggleCategory = async (types: string[], enabled: boolean) => {
    if (!config) return;
    const updates = types.flatMap(et => config.handlers.map(h => ({ event_type: et, handler_name: h, enabled })));

    // Optimistic
    const overrides: Record<string, boolean> = {};
    for (const u of updates) overrides[`${u.event_type}:${u.handler_name}`] = enabled;
    setLocalOverrides(prev => ({ ...prev, ...overrides }));

    setBulkLoading(true);
    try {
      await apiRequest({
        method: 'PUT',
        url: '/admin/monitoring/events/config/bulk',
        data: { updates },
      });
      toast.success(`Category ${enabled ? 'enabled' : 'disabled'}`);
    } catch {
      const revert: Record<string, boolean> = {};
      for (const u of updates) revert[`${u.event_type}:${u.handler_name}`] = !enabled;
      setLocalOverrides(prev => ({ ...prev, ...revert }));
      toast.error('Bulk update failed');
    } finally {
      setBulkLoading(false);
    }
  };

  // Check if all items in a set are enabled
  const allEnabled = (types: string[], handlers: string[]): boolean => {
    return types.every(et => handlers.every(h => isEnabled(et, h)));
  };
  const someEnabled = (types: string[], handlers: string[]): boolean => {
    return types.some(et => handlers.some(h => isEnabled(et, h)));
  };

  if (loading && !config) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw size={20} className="animate-spin text-gray-400" />
        <span className="ml-2 text-gray-500">Loading configuration...</span>
      </div>
    );
  }

  if (!config) return null;

  const handlers = config.handlers;
  const categorized = Object.entries(EVENT_CATEGORIES);
  const knownTypes = new Set(Object.values(EVENT_CATEGORIES).flat());
  const unknownTypes = config.event_types.filter(t => !knownTypes.has(t));
  const allEventTypes = [...Object.values(EVENT_CATEGORIES).flat(), ...unknownTypes];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm text-gray-500">
            Enable or disable the handlers that process each event type. Changes take effect in ~30 seconds.
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            Click column or category headers to toggle in bulk.
          </p>
        </div>
        <Button onClick={fetchConfig} variant="secondary" size="sm">
          <RefreshCw size={14} className={cn(loading && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 overflow-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead>
            <tr className="bg-gray-50">
              <th className="auth-mono-label px-4 py-3 text-left sticky left-0 bg-gray-50 z-10">
                Event Type
              </th>
              {handlers.map(h => {
                const colAllOn = allEnabled(allEventTypes, [h]);
                const colSomeOn = someEnabled(allEventTypes, [h]);
                return (
                  <th key={h} className="auth-mono-label px-4 py-3 text-center whitespace-nowrap">
                    <div className="flex flex-col items-center gap-1.5">
                      <span>{formatHandlerName(h)}</span>
                      <button
                        onClick={() => bulkToggleHandler(h, !colAllOn)}
                        disabled={bulkLoading}
                        className={cn(
                          'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                          colAllOn
                            ? 'bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50'
                            : colSomeOn
                            ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:hover:bg-yellow-900/50'
                            : 'bg-gray-100 text-gray-500 hover:bg-gray-200',
                          bulkLoading && 'opacity-50 cursor-not-allowed'
                        )}
                        title={colAllOn ? 'Disable all' : 'Enable all'}
                      >
                        {colAllOn ? <ToggleRight size={10} /> : <ToggleLeft size={10} />}
                        {colAllOn ? 'All on' : colSomeOn ? 'Mixed' : 'All off'}
                      </button>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {categorized.map(([category, types]) => {
              const catAllOn = allEnabled(types, handlers);
              const catSomeOn = someEnabled(types, handlers);
              return (
                <Fragment key={`cat-${category}`}>
                  <tr className="bg-gray-50/50">
                    <td colSpan={handlers.length + 1} className="px-4 py-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1.5">
                          <Settings size={12} />
                          {category}
                        </span>
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => bulkToggleCategory(types, true)}
                            disabled={bulkLoading || catAllOn}
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                              catAllOn
                                ? 'bg-green-100/50 text-green-400 cursor-default dark:bg-green-900/10 dark:text-green-600'
                                : 'bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50',
                              bulkLoading && 'opacity-50 cursor-not-allowed'
                            )}
                          >
                            All on
                          </button>
                          <button
                            onClick={() => bulkToggleCategory(types, false)}
                            disabled={bulkLoading || (!catSomeOn)}
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                              !catSomeOn
                                ? 'bg-gray-100/50 text-gray-400 cursor-default'
                                : 'bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50',
                              bulkLoading && 'opacity-50 cursor-not-allowed'
                            )}
                          >
                            All off
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                  {types.map(eventType => (
                    <tr key={eventType} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2 text-sm text-gray-700 sticky left-0 bg-white z-10 whitespace-nowrap">
                        {formatEventType(eventType)}
                      </td>
                      {handlers.map(handler => {
                        const enabled = isEnabled(eventType, handler);
                        return (
                          <td key={handler} className="px-4 py-2 text-center">
                            <Switch
                              checked={enabled}
                              onCheckedChange={() => toggleConfig(eventType, handler, enabled)}
                              size="sm"
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              );
            })}
            {unknownTypes.length > 0 && (
              <Fragment key="cat-other">
                <tr className="bg-gray-50/50">
                  <td colSpan={handlers.length + 1} className="px-4 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                        Other
                      </span>
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => bulkToggleCategory(unknownTypes, true)}
                          disabled={bulkLoading || allEnabled(unknownTypes, handlers)}
                          className={cn(
                            'px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                            allEnabled(unknownTypes, handlers)
                              ? 'bg-green-100/50 text-green-400 cursor-default dark:bg-green-900/10 dark:text-green-600'
                              : 'bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50',
                            bulkLoading && 'opacity-50 cursor-not-allowed'
                          )}
                        >
                          All on
                        </button>
                        <button
                          onClick={() => bulkToggleCategory(unknownTypes, false)}
                          disabled={bulkLoading || !someEnabled(unknownTypes, handlers)}
                          className={cn(
                            'px-2 py-0.5 rounded text-[10px] font-medium transition-colors',
                            !someEnabled(unknownTypes, handlers)
                              ? 'bg-gray-100/50 text-gray-400 cursor-default'
                              : 'bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50',
                            bulkLoading && 'opacity-50 cursor-not-allowed'
                          )}
                        >
                          All off
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
                {unknownTypes.map(eventType => (
                  <tr key={eventType} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-2 text-sm text-gray-700 sticky left-0 bg-white z-10">
                      {formatEventType(eventType)}
                    </td>
                    {handlers.map(handler => {
                      const enabled = isEnabled(eventType, handler);
                      return (
                        <td key={handler} className="px-4 py-2 text-center">
                          <Switch
                            checked={enabled}
                            onCheckedChange={() => toggleConfig(eventType, handler, enabled)}
                            size="sm"
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </Fragment>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
