import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { cn } from '../../utils/cn';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  badge?: ReactNode;
  icon?: ReactNode;
  backTo?: string;
  backLabel?: string;
  className?: string;
}

export function PageHeader({
  title,
  description,
  actions,
  badge,
  icon,
  backTo,
  backLabel,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn('space-y-3', className)}>
      {backTo && (
        <Link
          to={backTo}
          className="auth-link auth-mono-label"
        >
          ← {backLabel || 'Back'}
        </Link>
      )}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="min-w-0 flex items-center gap-3">
          {icon && (
            <div className="p-2 rounded-lg bg-primary-50 text-primary-600 shrink-0">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <h1 className="page-title truncate">{title}</h1>
              {badge}
            </div>
            {description && <p className="page-subtitle mt-1">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}

interface PageShellProps {
  children: ReactNode;
  className?: string;
}

export function PageShell({ children, className }: PageShellProps) {
  return (
    <div className={cn('space-y-6 animate-fadeIn', className)}>
      {children}
    </div>
  );
}
