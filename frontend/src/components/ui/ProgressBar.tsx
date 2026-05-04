import { cn } from '../../utils/cn';

interface ProgressBarProps {
  value: number;
  max?: number;
  className?: string;
  barClassName?: string;
}

export function ProgressBar({ value, max = 100, className, barClassName }: ProgressBarProps) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div className={cn('w-full rounded-full bg-gray-200 overflow-hidden', className)}>
      <div
        className={cn('h-full transition-all duration-300 ease-out', barClassName)}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}
