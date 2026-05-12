import { apiConfig } from '../config/env';

/**
 * Resolves a URL to its full absolute form if it's relative to the
 * API base. Never appends auth tokens — see the JWT-in-URL audit
 * finding (2026-05-12): tokens leaked via the URL query string land
 * in webserver access logs, the Referer header on any outbound link
 * from the viewing page, browser history, and autocomplete. The
 * `?token=<JWT>` codepath was removed both server- and client-side.
 *
 * For authenticated media (images, downloads), use the helpers in
 * `@/components/AuthMedia` which fetch via `Authorization: Bearer`
 * header and render the result as a blob URL (operator path), or
 * pass a session-token via the `sessionToken` prop (bounded-blast-
 * radius livechat-guest path).
 */
export function resolveApiUrl(url: string | undefined | null): string {
    if (!url) return '';

    // If already an absolute URL (starts with http://, https://, or //)
    if (/^(https?:)?\/\//i.test(url)) {
        return url;
    }

    // Ensure leading slash for relative paths
    const path = url.startsWith('/') ? url : `/${url}`;
    const baseUrl = apiConfig.baseUrl.endsWith('/')
        ? apiConfig.baseUrl.slice(0, -1)
        : apiConfig.baseUrl;

    return `${baseUrl}${path}`;
}

/**
 * Resolves a ticket media URL to its absolute form (no token in URL).
 * Use this for /media/tickets/... paths only.
 */
export function resolveTicketMediaUrl(url: string | undefined | null): string {
    return resolveApiUrl(url);
}

/**
 * Securely downloads a file using Authorization header (never leaks
 * the token in URL). Returns a blob URL suitable for triggering a
 * browser download.
 */
export async function secureDownload(fileUrl: string, fileName: string): Promise<void> {
    const url = fileUrl.startsWith('http') ? fileUrl : `${apiConfig.baseUrl}${fileUrl}`;
    const token = localStorage.getItem('auth_token');
    const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error('Failed to download attachment');
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = fileName;
    a.click();
    URL.revokeObjectURL(blobUrl);
}
