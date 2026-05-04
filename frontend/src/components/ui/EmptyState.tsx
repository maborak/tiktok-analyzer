import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('text-center py-12', className)}>
      {icon && <div className="mx-auto mb-4 flex items-center justify-center">{icon}</div>}
      <h3 className="auth-display text-lg mb-2">{title}</h3>
      {description && <p className="auth-mono-body text-sm mb-4">{description}</p>}
      {action}
    </div>
  );
}
