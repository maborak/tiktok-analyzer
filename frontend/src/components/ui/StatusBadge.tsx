import { cn } from '../../utils/cn';

type StatusVariant = 'success' | 'error' | 'warning' | 'info' | 'gray' | 'primary';

interface StatusBadgeProps {
  variant: StatusVariant;
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
}

const variantStyles: Record<StatusVariant, string> = {
  success: 'bg-success-50 text-success-700 border-success-500/20',
  error:   'bg-error-50 text-error-700 border-error-500/20',
  warning: 'bg-warning-50 text-warning-700 border-warning-500/20',
  info:    'bg-info-50 text-info-700 border-info-500/20',
  gray:    'bg-gray-100 text-gray-600 border-gray-200',
  primary: 'bg-primary-50 text-primary-700 border-primary-200',
};

const dotColors: Record<StatusVariant, string> = {
  success: 'bg-success-500',
  error:   'bg-error-500',
  warning: 'bg-warning-500',
  info:    'bg-info-500',
  gray:    'bg-gray-400',
  primary: 'bg-primary-500',
};

export function StatusBadge({ variant, children, dot = false, className }: StatusBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border',
      variantStyles[variant],
      className,
    )}>
      {dot && <span className={cn('w-1.5 h-1.5 rounded-full', dotColors[variant])} />}
      {children}
    </span>
  );
}
