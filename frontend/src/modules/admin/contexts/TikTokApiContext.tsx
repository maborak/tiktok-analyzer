/**
 * TikTok API namespace context.
 *
 * `TikTokLiveDetail` and its sub-components are shared between the
 * admin route (`/admin/tiktok/$handle`) and the unauthenticated public
 * route (`/lives/$handle`). Both need the same React tree but with a
 * different backing API: admin hits `/admin/tiktok/*`, public hits
 * `/public/tiktok/*`.
 *
 * The component tree is too deep (4000+ lines, ~10 sub-components,
 * each with nested helper components) to prop-drill an `api?` prop
 * everywhere it's needed. So instead we expose the namespace through
 * context: the default value is the admin `tiktokApi`, and the public
 * route wraps its body in `<TikTokApiProvider value={publicTiktokApi}>`
 * to switch namespaces for the whole subtree.
 *
 * The two namespaces are structurally identical for the read endpoints
 * the detail page consumes (calendar, rooms, room stats, gifters,
 * recipients, matches, score timeline, gifters-by-side, head-to-head,
 * h2h common gifters, event search/count, user matches). They differ
 * only in URL prefix — same parameter shapes, same response types.
 *
 * Write endpoints (`createLive`, `setLivePublic`, `reconnectLive`,
 * `deleteLive`, `setEnabled`, favourite-gifter mutations, etc.) are
 * NOT mirrored on the public namespace. The public route is also
 * `readOnly` so the buttons that would call those are hidden — but
 * `useTikTokApi` types as the admin shape so the code that calls them
 * still typechecks. Calls would 404 at runtime if reached, but the
 * `readOnly` gates ensure they aren't.
 */

import { createContext, useContext } from 'react';

import { tiktokApi } from '@admin/services/tiktok';

/** The admin tiktok API namespace — the shape every consumer is typed
 *  against. The public namespace is a structural subset (it's missing
 *  the write endpoints + the listener/notification endpoints that are
 *  admin-only). When the public namespace is in effect, calls into the
 *  missing methods would 404 at runtime — but the `readOnly` prop
 *  hides every UI element that would trigger them. */
export type TikTokApi = typeof tiktokApi;

/** Default = admin namespace. Outside the provider this preserves
 *  every existing call site's behaviour — admin pages render the
 *  component without a provider and get the admin API for free. */
const Ctx = createContext<TikTokApi>(tiktokApi);

export function TikTokApiProvider({
  value,
  children,
}: {
  value: TikTokApi;
  children: React.ReactNode;
}) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Read the active TikTok API namespace. Returns the admin `tiktokApi`
 *  when called outside a provider (the default). The public live-detail
 *  page wraps its body in a provider with `publicTiktokApi` so every
 *  component in the subtree reads the public namespace instead. */
export function useTikTokApi(): TikTokApi {
  return useContext(Ctx);
}
