/**
 * Typed API client — generated from FastAPI /openapi.json.
 *
 * Gives type-safe request/response contracts for every backend endpoint.
 * The legacy axios client in `src/api/client.ts` remains for advanced use
 * cases (retries, refresh queue, dedupe cache). Migrate services over time
 * by switching imports from `@/api/client` → `@/services/apiClient`.
 *
 * To regenerate types after a backend schema change:
 *   npm run types:api:snapshot
 */
import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from '@/types/api.generated';
import { apiConfig } from '@/config/env';

/**
 * Injects `Authorization: Bearer <token>` from localStorage on every request.
 * Mirrors the auth header logic from src/api/client.ts but without the
 * refresh-queue machinery (add that at call sites if needed).
 */
const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = localStorage.getItem('auth_token');
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`);
    }
    return request;
  },
};

export const apiClient = createClient<paths>({
  baseUrl: apiConfig.baseUrl,
});

apiClient.use(authMiddleware);

/**
 * Re-export the generated path table so call sites can reference
 * individual endpoint types without a second import.
 *
 * Example:
 *   import { apiClient, type paths } from '@/services/apiClient';
 *   type MeResponse = paths['/auth/me']['get']['responses']['200']['content']['application/json'];
 */
export type { paths };
