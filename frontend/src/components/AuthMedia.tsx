import { useEffect, useState } from 'react';
import { apiConfig } from '@/config/env';
import { resolveApiUrl, secureDownload } from '@/utils/url';

/** Image/link helpers for authenticated media endpoints.
 *
 *  Why these exist: `<img src="...?token=<JWT>">` leaks the JWT to
 *  webserver access logs, the Referer header on any outbound link from
 *  the viewing page, browser history, and autocomplete — a session-
 *  takeover primitive. The backend `/media/*` routes no longer accept
 *  `?token=` query authentication; they require either an
 *  `Authorization: Bearer` header (for operators) or a `?session_token=`
 *  query parameter (for anonymous livechat guests — session-token leak
 *  is bounded to one chat session's lifetime, much smaller blast radius
 *  than a JWT).
 *
 *  Components in this file pick the right strategy automatically based
 *  on whether a `sessionToken` was passed in:
 *    - sessionToken provided → use `?session_token=` URL directly (guest)
 *    - no sessionToken → fetch via Authorization header + blob URL
 *      (logged-in operator)
 *
 *  Anchor downloads route through `secureDownload()` (already
 *  Authorization-header based for the operator path) or directly with
 *  `?session_token=` for the guest path.
 */

interface AuthImageProps extends Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  /** Server-relative URL (e.g. `/media/livechat/...`). Absolute URLs
   *  are passed through unchanged. */
  src: string | null | undefined;
  /** When provided, the image is served via `?session_token=` (the
   *  anonymous-guest path). When omitted, the operator path is used
   *  (Authorization header + blob URL). */
  sessionToken?: string | null;
}

/** `<img>` replacement that handles auth for `/media/*` URLs. */
export function AuthImage({ src, sessionToken, ...rest }: AuthImageProps) {
  const resolved = resolveApiUrl(src);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);

  // Guest path — session token in query is fine, render directly.
  const useGuestPath = !!sessionToken;
  const directUrl = useGuestPath
    ? `${resolved}${resolved.includes('?') ? '&' : '?'}session_token=${encodeURIComponent(sessionToken!)}`
    : null;

  useEffect(() => {
    if (useGuestPath) return;
    if (!resolved) return;
    let revoke: string | null = null;
    let cancelled = false;
    const token = localStorage.getItem('auth_token');
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    fetch(resolved, { headers })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.blob();
      })
      .then((b) => {
        if (cancelled) return;
        const u = URL.createObjectURL(b);
        revoke = u;
        setBlobUrl(u);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [resolved, useGuestPath]);

  if (error) {
    return (
      <div
        className="inline-flex items-center justify-center text-[10px] text-rose-600 dark:text-rose-300"
        title="Failed to load image"
      >
        ⚠
      </div>
    );
  }

  if (useGuestPath) {
    // eslint-disable-next-line jsx-a11y/alt-text
    return <img {...rest} src={directUrl!} />;
  }

  if (!blobUrl) {
    return (
      <div
        className="inline-block w-6 h-6 rounded bg-gray-100 dark:bg-white/10 animate-pulse"
        aria-label="Loading image"
      />
    );
  }

  // eslint-disable-next-line jsx-a11y/alt-text
  return <img {...rest} src={blobUrl} />;
}

interface AuthLinkProps {
  href: string | null | undefined;
  fileName?: string;
  sessionToken?: string | null;
  className?: string;
  title?: string;
  children: React.ReactNode;
}

/** Anchor replacement for downloadable attachments. Guest path uses
 *  the session-token URL directly (the link works on click without an
 *  intermediate fetch). Operator path opens the file via
 *  `secureDownload()` — same Authorization-header flow used for the
 *  ticket-detail download button. */
export function AuthLink({
  href,
  fileName,
  sessionToken,
  className,
  title,
  children,
}: AuthLinkProps) {
  const resolved = resolveApiUrl(href);
  if (sessionToken) {
    const sep = resolved.includes('?') ? '&' : '?';
    const directUrl = `${resolved}${sep}session_token=${encodeURIComponent(sessionToken)}`;
    return (
      <a
        href={directUrl}
        target="_blank"
        rel="noopener noreferrer"
        download={fileName}
        className={className}
        title={title}
      >
        {children}
      </a>
    );
  }
  return (
    <button
      type="button"
      onClick={() => {
        if (!href) return;
        const url = href.startsWith('http') ? href : `${apiConfig.baseUrl}${href}`;
        secureDownload(url, fileName || 'attachment').catch(() => {
          // secureDownload already throws; we swallow so the click
          // handler doesn't surface an unhandled rejection.
        });
      }}
      className={className}
      title={title}
    >
      {children}
    </button>
  );
}
