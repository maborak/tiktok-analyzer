import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

type MetricVariant = 'primary' | 'success' | 'warning' | 'error' | 'gray';

const iconStyles: Record<MetricVariant, string> = {
  primary: 'bg-primary-50 text-primary-600',
  success: 'bg-success-50 text-success-600',
  warning: 'bg-warning-50 text-warning-600',
  error:   'bg-error-50 text-error-600',
  gray:    'bg-gray-100 text-gray-500',
};

interface MetricCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  change?: {
    value: string;
    positive: boolean;
  };
  icon?: ReactNode;
  variant?: MetricVariant;
  loading?: boolean;
  className?: string;
  children?: ReactNode;
}

export function MetricCard({
  label,
  value,
  subtext,
  change,
  icon,
  variant = 'primary',
  loading = false,
  className,
  children,
}: MetricCardProps) {
  return (
    <div className={cn('card', className)}>
      <div className="flex items-start gap-4">
        {icon && (
          <div className={cn('p-2.5 rounded-lg shrink-0', iconStyles[variant])}>
            {icon}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="auth-mono-label truncate">{label}</p>
          {loading ? (
            <div className="mt-1 h-7 w-20 bg-gray-200 animate-pulse rounded" />
          ) : (
            <p
              className="mt-0.5 text-2xl font-bold tabular-nums"
              style={{
                fontFamily: 'var(--font-mono-display)',
                letterSpacing: 'var(--tracking-display-tight)',
                color: 'var(--color-text-primary)',
              }}
            >
              {value}
            </p>
          )}
          {change && !loading && (
            <p className={cn(
              'mt-0.5 text-xs font-medium',
              change.positive ? 'text-success-700' : 'text-error-700',
            )}>
              {change.positive ? '+' : ''}{change.value}
            </p>
          )}
          {subtext && !loading && (
            <p className="mt-0.5 text-xs text-gray-400">{subtext}</p>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
