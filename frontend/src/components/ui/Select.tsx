import type { SelectHTMLAttributes } from 'react';
import { cn } from '../../utils/cn';

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className, ...props }: SelectProps) {
  return (
    <select
      {...props}
      className={cn('select-reset appearance-none', className)}
    />
  );
}
