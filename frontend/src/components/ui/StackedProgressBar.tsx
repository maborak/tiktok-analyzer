import { cn } from '../../utils/cn';

type Segment = {
  value: number;
  className: string;
};

interface StackedProgressBarProps {
  segments: Segment[];
  className?: string;
}

export function StackedProgressBar({ segments, className }: StackedProgressBarProps) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const widths = segments.map((segment) => (total > 0 ? (segment.value / total) * 100 : 0));
  const offsets = widths.reduce<number[]>((acc, _width, index) => {
    if (index === 0) {
      acc.push(0);
      return acc;
    }
    acc.push(acc[index - 1] + widths[index - 1]);
    return acc;
  }, []);

  return (
    <div className={cn('relative overflow-hidden rounded-full bg-gray-200', className)}>
      {segments.map((segment, index) => {
        const width = widths[index] || 0;
        const left = offsets[index] || 0;
        return (
          <div
            key={`${segment.className}-${index}`}
            className={cn('absolute top-0 h-full transition-all duration-1000 ease-out', segment.className)}
            style={{ left: `${left}%`, width: `${width}%` }}
          />
        );
      })}
    </div>
  );
}
