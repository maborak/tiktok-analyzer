/**
 * Compact identity-pill row for a TikTok user.
 *
 * Reads the `payload.user.identity` block the live-client adapter
 * emits on every event:
 *   { is_follower, is_following, is_moderator, is_subscribe,
 *     is_top_gifter, member_level, gifter_level, anchor_level,
 *     fan_ticket_count, fans_club: { name, level } }
 *
 * Renders ONLY the flags that are truthy / non-zero, in a stable
 * order. Designed to fit in a comment-row gutter without breaking
 * the layout — each pill is ~10–12px tall.
 */

import { Crown, Gem, Heart, ShieldCheck, Star } from 'lucide-react';

export type IdentityBlock = Partial<{
  is_follower: boolean;
  is_following: boolean;
  is_moderator: boolean;
  is_subscribe: boolean;
  is_top_gifter: boolean;
  member_level: number;
  gifter_level: number;
  anchor_level: number;
  fan_ticket_count: number;
  fans_club: { name?: string | null; level?: number | null } | null;
}>;

interface Props {
  identity?: IdentityBlock | null;
  /** When true, show the lower-priority flags (follower, follower-of) too.
   *  Default false — keep the default presentation tight. */
  verbose?: boolean;
}

export function TikTokUserBadges({ identity, verbose = false }: Props) {
  if (!identity) return null;

  const pills: Array<{
    key: string;
    label: string;
    icon: React.ReactNode;
    tone: string;
    title?: string;
  }> = [];

  if (identity.is_moderator) {
    pills.push({
      key: 'mod',
      label: 'MOD',
      icon: <ShieldCheck className="w-2.5 h-2.5" />,
      tone: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
      title: 'Room moderator',
    });
  }
  if (identity.is_subscribe) {
    pills.push({
      key: 'sub',
      label: 'SUB',
      icon: <Star className="w-2.5 h-2.5" />,
      tone: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
      title: 'Subscribed to creator',
    });
  }
  if (identity.is_top_gifter) {
    pills.push({
      key: 'top',
      label: 'TOP',
      icon: <Crown className="w-2.5 h-2.5" />,
      tone: 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300',
      title: 'Top gifter (this room)',
    });
  }
  if (identity.fans_club?.name) {
    const lvl = identity.fans_club.level;
    pills.push({
      key: 'fc',
      label: lvl ? `${identity.fans_club.name} L${lvl}` : identity.fans_club.name,
      icon: <Heart className="w-2.5 h-2.5" />,
      tone: 'bg-pink-50 text-pink-700 dark:bg-pink-500/10 dark:text-pink-300',
      title: 'Fans club member',
    });
  }
  if ((identity.gifter_level ?? 0) > 0) {
    pills.push({
      key: 'glv',
      label: `LV${identity.gifter_level}`,
      icon: <Gem className="w-2.5 h-2.5" />,
      tone: 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300',
      title: `Gifter level ${identity.gifter_level}`,
    });
  }
  if (verbose && identity.is_follower) {
    pills.push({
      key: 'fol',
      label: 'FOLLOWER',
      icon: null,
      tone: 'bg-gray-100 text-gray-600',
      title: 'Follows the creator',
    });
  }

  if (pills.length === 0) return null;

  return (
    <span className="inline-flex items-center gap-1 align-middle">
      {pills.map((p) => (
        <span
          key={p.key}
          title={p.title}
          className={`inline-flex items-center gap-0.5 px-1 py-px rounded font-mono text-[9px] leading-none ${p.tone}`}
        >
          {p.icon}
          {p.label}
        </span>
      ))}
    </span>
  );
}
