import { Search, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../../utils/cn';

interface FilterBarProps {
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
  };
  filters?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function FilterBar({ search, filters, actions, className }: FilterBarProps) {
  return (
    <div className={cn(
      'flex flex-col sm:flex-row items-stretch sm:items-center gap-3',
      className,
    )}>
      {search && (
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          <input
            type="text"
            value={search.value}
            onChange={(e) => search.onChange(e.target.value)}
            placeholder={search.placeholder ?? 'Buscar...'}
            className="input pl-9 pr-8"
          />
          {search.value && (
            <button
              onClick={() => search.onChange('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}
      {filters && <div className="flex items-center gap-2 flex-wrap">{filters}</div>}
      {actions && <div className="flex items-center gap-2 sm:ml-auto">{actions}</div>}
    </div>
  );
}
