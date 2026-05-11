/** Renders a number that pulses with a floating `+N` delta whenever
 *  its value increases. Used on PK scoreboards so the operator sees
 *  gift impact, not just a silent number swap.
 *
 *  - Tracks the previous value via `useRef` so we only animate on
 *    actual transitions, not on every render.
 *  - Each delta gets a unique key + auto-cleanup timeout so multiple
 *    increases in quick succession stack ("+50" rising while "+200"
 *    is still mid-flight).
 *  - Skips the initial mount (no "+N" on first render) and skips
 *    decreases (TikTok scores monotonically increase during a battle;
 *    a decrease is a data-shape change we shouldn't dramatize).
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react';

interface AnimatedScoreProps {
  value: number;
  /** When set, override the rendered number (e.g. with a compacted
   *  form). The animation still keys off `value`. */
  display?: string;
  className?: string;
  style?: CSSProperties;
  /** Tone for the floating `+N` chip — defaults to a muted gray. */
  tone?: 'emerald' | 'rose' | 'amber' | 'default';
  /** Render larger / smaller delta chip text. */
  deltaSize?: 'xs' | 'sm' | 'md';
}

export function AnimatedScore({
  value,
  display,
  className,
  style,
  tone = 'default',
  deltaSize = 'xs',
}: AnimatedScoreProps) {
  const prevRef = useRef<number | null>(null);
  const [deltas, setDeltas] = useState<Array<{ id: number; amount: number }>>([]);
  const counterRef = useRef(0);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;
    if (prev == null) return; // first mount — skip
    const diff = value - prev;
    if (diff <= 0) return;
    const id = ++counterRef.current;
    setDeltas((d) => [...d, { id, amount: diff }]);
    const t = setTimeout(() => {
      setDeltas((d) => d.filter((x) => x.id !== id));
    }, 1400);
    return () => clearTimeout(t);
  }, [value]);

  const toneCls = (() => {
    switch (tone) {
      case 'emerald': return 'text-emerald-600 dark:text-emerald-300';
      case 'rose':    return 'text-rose-600 dark:text-rose-300';
      case 'amber':   return 'text-amber-600 dark:text-amber-300';
      default:        return 'text-gray-600 dark:text-gray-300';
    }
  })();

  const sizeCls = deltaSize === 'md'
    ? 'text-base'
    : deltaSize === 'sm'
      ? 'text-xs'
      : 'text-[10px]';

  return (
    <span
      className={`relative inline-block tabular-nums ${className ?? ''}`}
      style={style}
    >
      {display ?? value.toLocaleString()}
      {deltas.map((d) => (
        <span
          key={d.id}
          className={`absolute left-1/2 -top-1 -translate-x-1/2 font-mono ${sizeCls} font-bold whitespace-nowrap pointer-events-none ${toneCls}`}
          style={{ animation: 'tt-score-pop 1.4s ease-out forwards' }}
        >
          +{d.amount.toLocaleString()}
        </span>
      ))}
      <style>{`
        @keyframes tt-score-pop {
          0%   { opacity: 0; transform: translate(-50%, 6px) scale(0.85); }
          15%  { opacity: 1; transform: translate(-50%, 0) scale(1); }
          70%  { opacity: 1; transform: translate(-50%, -14px) scale(1); }
          100% { opacity: 0; transform: translate(-50%, -28px) scale(0.95); }
        }
      `}</style>
    </span>
  );
}
