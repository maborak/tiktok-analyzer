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
    <div className={cn('space-y-3', className)} data-debug>
      {backTo && (
        <Link
          to={backTo}
          className="auth-link auth-mono-label"
        >
          ← {backLabel || 'Back'}
        </Link>
      )}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4" data-debug>
        <div className="min-w-0 flex items-center gap-3" data-debug>
          {icon && (
            <div className="p-2 rounded-lg bg-primary-50 text-primary-600 shrink-0" data-debug>
              {icon}
            </div>
          )}
          <div className="min-w-0" data-debug>
            <div className="flex items-center gap-3" data-debug>
              <h1 className="page-title truncate" data-debug>{title}</h1>
              {badge}
            </div>
            {description && <p className="page-subtitle mt-1" data-debug>{description}</p>}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0" data-debug>{actions}</div>}
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
    <div className={cn('space-y-6 animate-fadeIn', className)} data-debug>
      {children}
    </div>
  );
}
