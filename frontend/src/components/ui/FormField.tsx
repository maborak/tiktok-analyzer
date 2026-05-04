import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface FormFieldProps {
  id: string;
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}

export function FormField({ id, label, required, error, hint, children, className }: FormFieldProps) {
  return (
    <div className={cn('space-y-2', className)}>
      <label htmlFor={id} className="label">
        {label} {required && <span className="text-error-500">*</span>}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-gray-500">{hint}</p>}
      {error && <p className="text-xs text-error-600">{error}</p>}
    </div>
  );
}
