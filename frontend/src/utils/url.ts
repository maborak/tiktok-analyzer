import { apiConfig } from '../config/env';

/**
 * Resolves a URL to its full absolute form if it's relative to the API base.
 * Also appends the auth token as a query parameter if requested (for direct browser access).
 * 
 * @param url The URL or path to resolve
 * @param includeToken Whether to append the localStorage auth token
 * @returns The resolved absolute URL
 */
export function resolveApiUrl(url: string | undefined | null, includeToken: boolean = false): string {
    if (!url) return '';

    // If already an absolute URL (starts with http://, https://, or //)
    if (/^(https?:)?\/\//i.test(url)) {
        return appendToken(url, includeToken);
    }

    // Ensure leading slash for relative paths
    const path = url.startsWith('/') ? url : `/${url}`;
    const baseUrl = apiConfig.baseUrl.endsWith('/')
        ? apiConfig.baseUrl.slice(0, -1)
        : apiConfig.baseUrl;

    return appendToken(`${baseUrl}${path}`, includeToken);
}

function appendToken(url: string, includeToken: boolean): string {
    if (!includeToken) return url;

    const token = localStorage.getItem('auth_token');
    if (!token) return url;

    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}token=${token}`;
}

/**
 * Resolves a ticket media URL to its absolute form (no token in URL).
 * Use this for /media/tickets/... paths only.
 */
export function resolveTicketMediaUrl(url: string | undefined | null): string {
    return resolveApiUrl(url, false);
}

/**
 * Securely downloads a file using Authorization header (never leaks token in URL).
 * Returns a blob URL suitable for triggering a browser download.
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

/**
 * Resolves a livechat media URL with dual-auth support.
 * Needed for inline <img src> rendering — browsers can't send Authorization headers for image tags.
 * For pure downloads, prefer secureDownload() instead.
 */
export function resolveLivechatMediaUrl(url: string | undefined | null, sessionToken?: string | null): string {
    if (!url) return '';

    const resolved = resolveApiUrl(url, false);

    // Prefer JWT if available (authenticated user)
    const jwt = localStorage.getItem('auth_token');
    if (jwt) {
        const sep = resolved.includes('?') ? '&' : '?';
        return `${resolved}${sep}token=${jwt}`;
    }

    // Fall back to session token (anonymous guest)
    if (sessionToken) {
        const sep = resolved.includes('?') ? '&' : '?';
        return `${resolved}${sep}session_token=${sessionToken}`;
    }

    return resolved;
}
