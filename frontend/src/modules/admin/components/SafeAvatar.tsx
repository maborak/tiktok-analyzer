/**
 * SafeAvatar — image-load-failure-tolerant avatar.
 *
 * TikTok CDN avatar URLs go stale (401, 404, signed-URL expiry) often
 * enough that bare `<img>` tags litter the UI with broken-image icons.
 * This wrapper falls back to a neutral incognito-style placeholder
 * when the image fails to load (or when `src` is missing entirely).
 *
 * Migration note: other components (`TikTokCommonGifterDetailModal`,
 * `TikTokGifterDetailModal`, `TikTokGifterModal`, the gifters tables,
 * the host cards, etc.) should switch their `<img>` avatar usages to
 * this component over time. Don't migrate them in this commit — other
 * agents may be touching those files concurrently. Use SafeAvatar for
 * every NEW avatar render and migrate existing call sites individually
 * once their owning agents are done.
 *
 * Usage:
 *   <SafeAvatar src={user.avatar_url} alt={user.nickname} size={40} />
 *   <SafeAvatar src={url} size={64} rounded={false} className="ring-2 ring-white" />
 */

import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { UserCircle2 } from 'lucide-react';

interface SafeAvatarProps {
  src: string | null | undefined;
  alt?: string;
  /** Square dimension in px. Default 40. */
  size?: number;
  /** Extra classes (ring, shadow, etc.). */
  className?: string;
  /** Rounded-full (default) vs rounded-md. */
  rounded?: boolean;
  /** Optional custom fallback rendered when the image is missing or
   *  fails to load. Common pattern: a single uppercase letter from
   *  the nickname (e.g. `seed="A"`). When omitted, an incognito
   *  `<UserCircle2>` icon renders — the visual cue that "this
   *  avatar is being processed / TikTok's signed URL expired". */
  fallback?: ReactNode;
}

export function SafeAvatar({
  src,
  alt,
  size = 40,
  className = '',
  rounded = true,
  fallback,
}: SafeAvatarProps) {
  const [errored, setErrored] = useState(false);

  // Reset the error flag when `src` flips to a new URL — the previous
  // failure shouldn't poison a freshly-passed avatar.
  useEffect(() => {
    setErrored(false);
  }, [src]);

  const shouldShowImage = !!src && !errored;
  const dims = { width: size, height: size };
  const baseCls = `${rounded ? 'rounded-full' : 'rounded-md'} object-cover bg-gray-100 dark:bg-gray-100/10`;

  if (shouldShowImage) {
    return (
      <img
        src={src}
        alt={alt || ''}
        style={dims}
        className={`${baseCls} ${className}`}
        onError={() => setErrored(true)}
        loading="lazy"
        referrerPolicy="no-referrer"
      />
    );
  }

  // Fallback: either caller-supplied (letter-initial) or the default
  // incognito icon. Subtle "being processed" vibe so operators see
  // that the absence isn't permanent — TikTok's signed-URL refresh
  // cadence usually catches up within a cycle.
  return (
    <div
      style={dims}
      className={`${baseCls} flex items-center justify-center text-gray-400 ${className}`}
      title={src ? 'Avatar unavailable — being processed' : 'No avatar'}
    >
      {fallback ?? <UserCircle2 className="w-2/3 h-2/3" />}
    </div>
  );
}

export default SafeAvatar;
