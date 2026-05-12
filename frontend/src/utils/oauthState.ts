/**
 * OAuth `state` parameter handling — CSPRNG-generated, sessionStorage-
 * persisted, single-use. Defends against:
 *
 *  • Login CSRF — attacker hosts a page that redirects a victim to
 *    `/auth/<provider>/callback?code=ATTACKER_CODE`; without state
 *    verification the victim's browser swaps the attacker's session
 *    in.
 *  • Account fixation on the link-from-settings flow — attacker can
 *    have a victim link the attacker's OAuth identity to the victim's
 *    logged-in account, enabling future "sign in with <provider>"
 *    takeover.
 *
 * Audit reference: FE-CRITICAL #2 (2026-05-12).
 *
 * Usage pattern:
 *
 *   // 1. Before redirecting to the provider:
 *   const state = startOAuthFlow('github', { intent: 'link' });
 *   const params = new URLSearchParams({ ..., state });
 *   window.location.href = `${authorizeUrl}?${params}`;
 *
 *   // 2. In the callback handler:
 *   const flow = consumeOAuthFlow('github', searchParams.get('state'));
 *   if (!flow) { reject(); return; }
 *   if (flow.intent === 'link') { linkOAuth(code); } else { signIn(code); }
 *
 * State storage is in sessionStorage (tab-scoped, cleared on tab close)
 * not localStorage — so a foreign tab can't read or replay a different
 * tab's flow.
 */

const STORAGE_KEY_PREFIX = 'oauth_flow_';

export type OAuthIntent = 'signin' | 'link';

export interface OAuthFlow {
  state: string;
  intent: OAuthIntent;
  createdAt: number;
}

/** Max age for a pending OAuth flow. Beyond this we refuse to honour
 *  the callback even if state matches — protects against a state that
 *  was generated but never consumed (browser left open for days).
 *  Most flows complete in under a minute. */
const MAX_FLOW_AGE_MS = 10 * 60 * 1000; // 10 minutes

function storageKey(provider: string): string {
  return `${STORAGE_KEY_PREFIX}${provider}`;
}

/** Generate a 32-byte CSPRNG state and persist it for the provider.
 *  Returns the state string to embed in the authorize URL. */
export function startOAuthFlow(provider: string, opts: { intent: OAuthIntent }): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  // base64url, no padding
  const state = btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  const flow: OAuthFlow = {
    state,
    intent: opts.intent,
    createdAt: Date.now(),
  };
  try {
    sessionStorage.setItem(storageKey(provider), JSON.stringify(flow));
  } catch {
    // sessionStorage may be disabled (Safari private mode). Without
    // it we can't safely complete the flow — the caller should
    // surface this. We still return the state so the caller can
    // decide; consumeOAuthFlow will reject the callback.
  }
  return state;
}

/** Verify the callback's `state` matches the stored flow, then clear
 *  it (single-use). Returns the stored flow on success, or null on
 *  any mismatch / missing / expired condition. */
export function consumeOAuthFlow(
  provider: string,
  returnedState: string | null | undefined,
): OAuthFlow | null {
  if (!returnedState) return null;
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(storageKey(provider));
  } catch {
    return null;
  }
  if (!raw) return null;
  // Single-use: always clear before validation so a replay of the
  // exact same callback URL can't drain the flow twice.
  try {
    sessionStorage.removeItem(storageKey(provider));
  } catch {
    /* ignore */
  }
  let flow: OAuthFlow;
  try {
    flow = JSON.parse(raw) as OAuthFlow;
  } catch {
    return null;
  }
  if (typeof flow.state !== 'string' || typeof flow.createdAt !== 'number') {
    return null;
  }
  if (Date.now() - flow.createdAt > MAX_FLOW_AGE_MS) return null;
  // Constant-time-ish compare. JS doesn't expose `timingSafeEqual`
  // for browser code, so we use a length-and-charcode XOR sweep
  // that's not perfectly constant-time but far better than `===`
  // (which short-circuits on the first mismatch).
  if (flow.state.length !== returnedState.length) return null;
  let diff = 0;
  for (let i = 0; i < flow.state.length; i++) {
    diff |= flow.state.charCodeAt(i) ^ returnedState.charCodeAt(i);
  }
  if (diff !== 0) return null;
  return flow;
}
