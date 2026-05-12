/**
 * Runtime knobs for the TikTok admin + public surfaces.
 *
 * Two backing endpoints, picked by the provider's `audience` prop:
 *
 *   - `audience="admin"` → `GET /admin/tiktok/runtime-config` (auth).
 *     Returns all three keys:
 *       - `TIKTOK_POLL_INTERVAL_MS`     (number, default 30000)
 *       - `TIKTOK_ADMIN_REALTIME_MODE`  ('poll' | 'ws' | 'both', default 'both')
 *       - `TIKTOK_PUBLIC_REALTIME_MODE` ('poll' | 'ws' | 'both', default 'poll')
 *
 *   - `audience="public"` → `GET /public/tiktok/runtime-config` (no auth).
 *     Returns only the public-safe slice:
 *       - `poll_interval_ms`
 *       - `public_realtime`
 *     `admin_realtime` is `undefined` on the public side — public
 *     pages never need to know what admin uses, and the policy is
 *     "admin config under admin auth."
 *
 * Why a Context (and not, say, a module-level singleton) — the values
 * are fetched ONCE at provider mount and propagated via React state.
 * Without that propagation, components that mount after the fetch
 * resolves would not re-render with the new config.
 *
 * Changes via the admin Configuration UI take effect on the NEXT
 * page reload — both endpoints set `Cache-Control: no-store`.
 */

import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { apiRequest } from '@/api/client';

export type TikTokRealtimeMode = 'poll' | 'ws' | 'both';
export type TikTokConfigAudience = 'admin' | 'public';

export interface TikTokRuntimeConfig {
  /** Poll cadence in milliseconds. Clamped server-side to [1000, 600000]. */
  pollIntervalMs: number;
  /** How admin pages get updates. `undefined` when audience='public' —
   *  public clients never receive the admin mode value. */
  adminRealtime?: TikTokRealtimeMode;
  /** How public pages get updates. */
  publicRealtime: TikTokRealtimeMode;
  /** Which endpoint produced this config, for downstream code that
   *  needs to know its rendering context. */
  audience: TikTokConfigAudience;
  /** True until the first fetch resolves. */
  loading: boolean;
}

const PUBLIC_DEFAULTS: TikTokRuntimeConfig = {
  pollIntervalMs: 30000,
  adminRealtime: undefined,
  publicRealtime: 'poll',
  audience: 'public',
  loading: true,
};

const ADMIN_DEFAULTS: TikTokRuntimeConfig = {
  pollIntervalMs: 30000,
  adminRealtime: 'both',
  publicRealtime: 'poll',
  audience: 'admin',
  loading: true,
};

const TikTokRuntimeConfigContext = createContext<TikTokRuntimeConfig>(PUBLIC_DEFAULTS);

interface AdminApiShape {
  poll_interval_ms: number;
  admin_realtime: TikTokRealtimeMode;
  public_realtime: TikTokRealtimeMode;
}

interface PublicApiShape {
  poll_interval_ms: number;
  public_realtime: TikTokRealtimeMode;
}

interface ProviderProps {
  children: ReactNode;
  /** Which endpoint to read. Admin pages pass `"admin"` (auth'd,
   *  returns full set); public pages pass `"public"` (anonymous,
   *  returns a sanitised slice). Default `"public"` — safer when
   *  unspecified, since admin endpoint would 401 anonymous callers
   *  and the provider would fall back to defaults anyway. */
  audience?: TikTokConfigAudience;
}

/** Provider — fetches the runtime config once at mount and exposes
 *  it to descendants. Errors fall back to audience-typed defaults so
 *  the app is always functional even if the backend is offline. */
export function TikTokRuntimeConfigProvider({
  children,
  audience = 'public',
}: ProviderProps) {
  const initial = audience === 'admin' ? ADMIN_DEFAULTS : PUBLIC_DEFAULTS;
  const [cfg, setCfg] = useState<TikTokRuntimeConfig>(initial);

  useEffect(() => {
    let cancelled = false;
    const url = audience === 'admin'
      ? '/admin/tiktok/runtime-config'
      : '/public/tiktok/runtime-config';
    apiRequest<AdminApiShape | PublicApiShape>({ method: 'GET', url })
      .then((data) => {
        if (cancelled) return;
        if (audience === 'admin') {
          const d = data as AdminApiShape;
          setCfg({
            pollIntervalMs: d.poll_interval_ms,
            adminRealtime: d.admin_realtime,
            publicRealtime: d.public_realtime,
            audience: 'admin',
            loading: false,
          });
        } else {
          const d = data as PublicApiShape;
          setCfg({
            pollIntervalMs: d.poll_interval_ms,
            adminRealtime: undefined,
            publicRealtime: d.public_realtime,
            audience: 'public',
            loading: false,
          });
        }
      })
      .catch(() => {
        if (cancelled) return;
        setCfg({ ...initial, loading: false });
      });
    return () => { cancelled = true; };
    // initial is derived from audience, so audience alone is the dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audience]);

  return (
    <TikTokRuntimeConfigContext.Provider value={cfg}>
      {children}
    </TikTokRuntimeConfigContext.Provider>
  );
}

/** Hook — read the typed config from anywhere inside the provider. */
export function useTikTokRuntimeConfig(): TikTokRuntimeConfig {
  return useContext(TikTokRuntimeConfigContext);
}
