import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface LoadingStateProps {
  message?: string;
  icon?: ReactNode;
  className?: string;
}

export function LoadingState({ message = 'Loading...', icon, className }: LoadingStateProps) {
  return (
    <div className={cn('flex items-center justify-center min-h-96', className)}>
      {icon || <div className="w-8 h-8 animate-spin border-4 border-gray-200 border-t-gray-600 rounded-full" />}
      <span className="ml-3 text-gray-600">{message}</span>
    </div>
  );
}
