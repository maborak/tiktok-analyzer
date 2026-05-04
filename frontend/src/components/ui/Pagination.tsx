import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from 'lucide-react';
import { cn } from '../../utils/cn';
import type { PaginationMeta } from '../../types/api';

interface PaginationProps {
  pagination: PaginationMeta;
  currentPage: number;
  onPageChange: (page: number) => void;
  /** Position affects top/bottom spacing */
  position?: 'top' | 'bottom';
  className?: string;
}

/**
 * Compact, modern pagination bar.
 *
 * Layout:
 *   [<<] [<]  1 2 (3) 4 5  [>] [>>]     12 of 340
 *
 * Mobile:
 *   [<]  3 / 17  [>]
 */
export function Pagination({
  pagination,
  currentPage,
  onPageChange,
  position = 'bottom',
  className,
}: PaginationProps) {
  const { total_pages, total_items, has_previous, has_next } = pagination;

  if (total_pages <= 1) {
    return (
      <div className={cn(
        'flex justify-center text-xs text-gray-400',
        position === 'bottom' && 'pt-4 mt-4 border-t border-gray-200',
        position === 'top' && 'pb-4 mb-2',
        className,
      )}>
        {total_items} {total_items === 1 ? 'result' : 'results'}
      </div>
    );
  }

  // Build visible page numbers (max 5, centered on current)
  const pages = getPageNumbers(currentPage, total_pages, 5);

  return (
    <div className={cn(
      'flex items-center justify-between gap-4',
      position === 'bottom' && 'pt-4 mt-4 border-t border-gray-200',
      position === 'top' && 'pb-4 mb-2',
      className,
    )}>
      {/* Desktop navigation */}
      <nav className="hidden sm:flex items-center gap-1">
        {/* First page */}
        <NavButton
          onClick={() => onPageChange(1)}
          disabled={!has_previous}
          title="First page"
        >
          <ChevronsLeft className="w-3.5 h-3.5" />
        </NavButton>

        {/* Previous */}
        <NavButton
          onClick={() => onPageChange(currentPage - 1)}
          disabled={!has_previous}
          title="Previous page"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </NavButton>

        {/* Page numbers */}
        <div className="flex items-center gap-0.5 mx-1">
          {pages[0] > 1 && (
            <span className="w-8 text-center text-xs text-gray-300 select-none">...</span>
          )}
          {pages.map((pageNum) => (
            <button
              key={pageNum}
              onClick={() => onPageChange(pageNum)}
              className={cn(
                'w-8 h-8 rounded-lg text-xs font-medium transition-all duration-150',
                pageNum === currentPage
                  ? 'bg-primary-600 text-white shadow-sm shadow-primary-200'
                  : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900'
              )}
            >
              {pageNum}
            </button>
          ))}
          {pages[pages.length - 1] < total_pages && (
            <span className="w-8 text-center text-xs text-gray-300 select-none">...</span>
          )}
        </div>

        {/* Next */}
        <NavButton
          onClick={() => onPageChange(currentPage + 1)}
          disabled={!has_next}
          title="Next page"
        >
          <ChevronRight className="w-3.5 h-3.5" />
        </NavButton>

        {/* Last page */}
        <NavButton
          onClick={() => onPageChange(total_pages)}
          disabled={!has_next}
          title="Last page"
        >
          <ChevronsRight className="w-3.5 h-3.5" />
        </NavButton>
      </nav>

      {/* Mobile navigation */}
      <nav className="flex sm:hidden items-center gap-2 mx-auto">
        <NavButton
          onClick={() => onPageChange(currentPage - 1)}
          disabled={!has_previous}
          title="Previous page"
        >
          <ChevronLeft className="w-4 h-4" />
        </NavButton>

        <span className="text-xs text-gray-500 tabular-nums min-w-[4rem] text-center">
          <span className="font-semibold text-gray-900">{currentPage}</span>
          {' / '}
          {total_pages}
        </span>

        <NavButton
          onClick={() => onPageChange(currentPage + 1)}
          disabled={!has_next}
          title="Next page"
        >
          <ChevronRight className="w-4 h-4" />
        </NavButton>
      </nav>

      {/* Results count (desktop only) */}
      <span className="hidden sm:block text-xs text-gray-400 tabular-nums whitespace-nowrap">
        {total_items.toLocaleString()} {total_items === 1 ? 'result' : 'results'}
      </span>
    </div>
  );
}

/** Small icon-only nav button */
function NavButton({
  children,
  onClick,
  disabled,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled: boolean;
  title: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        'w-8 h-8 inline-flex items-center justify-center rounded-lg text-gray-400 transition-colors',
        'hover:bg-gray-100 hover:text-gray-700',
        'disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-gray-400',
      )}
    >
      {children}
    </button>
  );
}

/**
 * Compute which page numbers to show, centered on `current`.
 * Always returns `maxVisible` numbers (or fewer if total_pages < maxVisible).
 */
function getPageNumbers(current: number, total: number, maxVisible: number): number[] {
  if (total <= maxVisible) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const half = Math.floor(maxVisible / 2);
  let start = current - half;
  let end = current + half;

  if (start < 1) {
    start = 1;
    end = maxVisible;
  } else if (end > total) {
    end = total;
    start = total - maxVisible + 1;
  }

  return Array.from({ length: end - start + 1 }, (_, i) => start + i);
}
