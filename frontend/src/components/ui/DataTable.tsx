import { useState, useMemo } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import { cn } from '../../utils/cn';
import { EmptyState } from './EmptyState';
import { Skeleton } from './Skeleton';

/* ─── Types ─── */
export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  sortable?: boolean;
  sortFn?: (a: T, b: T) => number;
  align?: 'left' | 'center' | 'right';
  className?: string;
  /** Hide on mobile (below sm breakpoint) */
  hideOnMobile?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (row: T) => string | number;
  loading?: boolean;
  emptyState?: {
    icon?: React.ReactNode;
    title: string;
    description?: string;
    action?: React.ReactNode;
  };
  onRowClick?: (row: T) => void;
  /** Render each row as a card on mobile instead of a table */
  mobileCard?: (row: T) => React.ReactNode;
  className?: string;
}

type SortDirection = 'asc' | 'desc';

/* ─── Component ─── */
export function DataTable<T>({
  columns,
  data,
  keyExtractor,
  loading = false,
  emptyState,
  onRowClick,
  mobileCard,
  className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDirection>('asc');

  const handleSort = (col: Column<T>) => {
    if (!col.sortable) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(col.key);
      setSortDir('asc');
    }
  };

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortFn) return data;
    const sorted = [...data].sort(col.sortFn);
    return sortDir === 'desc' ? sorted.reverse() : sorted;
  }, [data, sortKey, sortDir, columns]);

  /* Loading skeleton */
  if (loading) {
    return (
      <div className={cn('card p-0 overflow-hidden', className)}>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                {columns.filter(c => !c.hideOnMobile).map((col) => (
                  <th key={col.key}>{col.header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 5 }).map((_, i) => (
                <tr key={i}>
                  {columns.filter(c => !c.hideOnMobile).map((col) => (
                    <td key={col.key}>
                      <Skeleton className="h-4 w-full max-w-[120px]" />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  /* Empty state */
  if (sortedData.length === 0 && emptyState) {
    return (
      <div className={cn('card', className)}>
        <EmptyState {...emptyState} />
      </div>
    );
  }

  return (
    <div className={cn('card p-0 overflow-hidden', className)}>
      {/* Mobile card layout */}
      {mobileCard && (
        <div className="sm:hidden divide-y divide-gray-100">
          {sortedData.map((row) => (
            <div
              key={keyExtractor(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(onRowClick && 'cursor-pointer')}
            >
              {mobileCard(row)}
            </div>
          ))}
        </div>
      )}

      {/* Desktop table */}
      <div className={cn('overflow-x-auto', mobileCard && 'hidden sm:block')}>
        <table className="table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    col.align === 'right' && 'text-right',
                    col.align === 'center' && 'text-center',
                    col.hideOnMobile && 'hidden sm:table-cell',
                    col.sortable && 'cursor-pointer select-none hover:text-gray-700',
                    col.className,
                  )}
                  onClick={() => handleSort(col)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.header}
                    {col.sortable && (
                      <span className="text-gray-300">
                        {sortKey === col.key ? (
                          sortDir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />
                        ) : (
                          <ArrowUpDown className="w-3 h-3" />
                        )}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedData.map((row) => (
              <tr
                key={keyExtractor(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(onRowClick && 'cursor-pointer')}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={cn(
                      col.align === 'right' && 'text-right',
                      col.align === 'center' && 'text-center',
                      col.hideOnMobile && 'hidden sm:table-cell',
                      col.className,
                    )}
                  >
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
