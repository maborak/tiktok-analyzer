import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import {
  Search,
  Loader,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Trash2,
  AlertTriangle,
  X,
  XCircle,
  LayoutGrid,
  List,
} from 'lucide-react';
import { cn } from '../utils/cn';
import { ProgressBar } from './ui/ProgressBar';
import { Skeleton } from './ui/Skeleton';

// Types
export interface Column<T> {
  key: string;
  label: string;
  sortable?: boolean;
  render: (row: T) => ReactNode;
  headerClassName?: string;
  cellClassName?: string;
}

export interface FilterOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface FilterConfig {
  key: string;
  label?: string;
  type?: 'select' | 'number' | 'text';
  value: string;
  onChange: (value: string) => void;
  options?: FilterOption[];
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
}

export interface ActiveFilter {
  key: string;
  label: string;
  onRemove: () => void;
}

export interface RowAction {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  variant?: 'default' | 'danger';
  hidden?: boolean;
  title?: string;
}

export interface BulkAction {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  variant?: 'default' | 'danger';
}

export interface DataTableProps<T> {
  // Data
  data: T[];
  loading: boolean;

  // Identification
  getRowId: (row: T) => number | string;

  // Header
  title: string;
  subtitle?: string;
  icon?: React.ComponentType<{ className?: string }>;
  headerAction?: ReactNode;

  // Columns
  columns: Column<T>[];

  // Pagination
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  pageSizeOptions?: number[];

  // Search
  searchEnabled?: boolean;
  searchTerm?: string;
  onSearchChange?: (term: string) => void;
  onSearchSubmit?: (term: string) => void;
  searchPlaceholder?: string;

  // Sorting
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
  onSort?: (field: string) => void;

  // Filters
  filters?: FilterConfig[];
  filtersGrid?: boolean;                    // render filters in a grid (vs inline row)
  onApplyFilters?: () => void;              // shows "Filter" apply button
  onClearFilters?: () => void;              // shows "Clear" button
  applyLabel?: string;
  isFiltering?: boolean;                    // loading state for apply button
  activeFilters?: ActiveFilter[];           // filter pills
  filterError?: string;                     // validation error

  // View mode toggle
  viewMode?: 'grid' | 'list';
  onViewModeChange?: (mode: 'grid' | 'list') => void;

  // Selection
  selectable?: boolean;
  selectedIds?: Set<number | string>;
  onSelectionChange?: (ids: Set<number | string>) => void;
  isRowSelectable?: (row: T) => boolean;

  // Row Actions
  rowActions?: (row: T) => RowAction[];

  // Bulk Actions
  bulkActions?: BulkAction[];
  onBulkDelete?: () => void;

  // Delete Modal
  deleteModal?: {
    show: boolean;
    title: string;
    message: string;
    content?: ReactNode;
    onConfirm: () => void;
    onCancel: () => void;
    loading?: boolean;
    progress?: number;
    showProgress?: boolean;
    onCancelProgress?: () => void;
    confirmLabel?: string;
    confirmVariant?: 'danger' | 'warning' | 'primary';
    icon?: React.ComponentType<{ className?: string }>;
  };

  // Empty state
  emptyIcon?: React.ComponentType<{ className?: string }>;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;

  // Row styling
  getRowClassName?: (row: T) => string;
}

export function DataTable<T>({
  // Data
  data,
  loading,
  getRowId,

  // Header
  title,
  subtitle,
  icon: Icon,
  headerAction,

  // Columns
  columns,

  // Pagination
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [5, 10, 25, 50],

  // Search
  searchEnabled = true,
  searchTerm = '',
  onSearchChange,
  onSearchSubmit,
  searchPlaceholder = 'Search...',

  // Sorting
  sortBy,
  sortOrder = 'asc',
  onSort,

  // Filters
  filters = [],
  filtersGrid = false,
  onApplyFilters,
  onClearFilters,
  applyLabel = 'Filter',
  isFiltering = false,
  activeFilters = [],
  filterError,

  // View mode
  viewMode,
  onViewModeChange,

  // Selection
  selectable = false,
  selectedIds = new Set(),
  onSelectionChange,
  isRowSelectable = () => true,

  // Row Actions
  rowActions,

  // Bulk Actions
  bulkActions = [],

  // Delete Modal
  deleteModal,

  // Empty state
  emptyIcon: EmptyIcon,
  emptyTitle = 'No data found',
  emptyDescription = 'Try adjusting your filters or add new items',
  emptyAction,

  // Row styling
  getRowClassName,
}: DataTableProps<T>) {

  // Selection handlers
  const selectableRows = Array.isArray(data) ? data.filter(isRowSelectable) : [];
  const allSelected = selectableRows.length > 0 && selectableRows.every(row => selectedIds.has(getRowId(row)));

  const toggleSelectAll = () => {
    if (!onSelectionChange) return;

    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(selectableRows.map(row => getRowId(row))));
    }
  };

  const toggleSelect = (row: T) => {
    if (!onSelectionChange || !isRowSelectable(row)) return;

    const id = getRowId(row);
    const newSelected = new Set(selectedIds);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    onSelectionChange(newSelected);
  };

  // Sort icon helper
  const getSortIcon = (field: string) => {
    if (sortBy !== field) {
      return <ChevronsUpDown className="w-4 h-4 text-gray-300" />;
    }
    return sortOrder === 'asc'
      ? <ChevronUp className="w-4 h-4 text-gray-700" />
      : <ChevronDown className="w-4 h-4 text-gray-700" />;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="page-title truncate flex items-center gap-2">
              {Icon && <Icon className="w-5 h-5 text-gray-400" />}
              {title}
            </h1>
          </div>
          {subtitle && (
            <p className="page-subtitle mt-1">{subtitle}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">{headerAction}</div>
      </div>

      {/* Filters */}
      <div className="card p-4">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search */}
          {searchEnabled && onSearchChange && (
            <div className="relative flex-1 min-w-[50%]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input
                type="text"
                placeholder={searchPlaceholder}
                value={searchTerm}
                onChange={(e) => onSearchChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && onSearchSubmit) {
                    onSearchSubmit(searchTerm);
                  }
                }}
                className="input pl-9 pr-8"
              />
            </div>
          )}

          {/* Search Button (Manual Trigger) */}
          {searchEnabled && onSearchSubmit && (
            <button
              type="button"
              onClick={() => onSearchSubmit(searchTerm || '')}
              className="btn-primary"
            >
              <Search className="w-4 h-4" />
              Search
            </button>
          )}

          {/* Inline Filters (non-grid mode) */}
          {!filtersGrid && filters.map((filter) => {
            const type = filter.type || 'select';
            if (type === 'select') {
              return (
                <select key={filter.key} value={filter.value} onChange={(e) => filter.onChange(e.target.value)} className={cn("input", filter.className)}>
                  {filter.placeholder && <option value="">{filter.placeholder}</option>}
                  {(filter.options || []).map((opt) => <option key={opt.value} value={opt.value} disabled={opt.disabled}>{opt.label}</option>)}
                </select>
              );
            }
            if (type === 'number') {
              return <input key={filter.key} type="number" value={filter.value} onChange={(e) => filter.onChange(e.target.value)} placeholder={filter.placeholder} min={filter.min} max={filter.max} step={filter.step} className={cn("input w-full", filter.className)} />;
            }
            return <input key={filter.key} type="text" value={filter.value} onChange={(e) => filter.onChange(e.target.value)} placeholder={filter.placeholder} className={cn("input", filter.className)} />;
          })}

          {/* Sort Order Toggle */}
          {onSort && (
            <button type="button" onClick={() => onSort(sortBy || '')} className="btn-secondary p-2" title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}>
              {sortOrder === 'asc' ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          )}

          {/* Page Size */}
          <select value={pageSize} onChange={(e) => { onPageSizeChange(Number(e.target.value)); onPageChange(1); }} className="input w-auto">
            {pageSizeOptions.map((size) => <option key={size} value={size}>{size} per page</option>)}
          </select>

          {/* View Mode Toggle */}
          {viewMode && onViewModeChange && (
            <div className="bg-gray-100 p-0.5 rounded-lg flex gap-0.5">
              <button type="button" onClick={() => onViewModeChange('grid')}
                className={cn('inline-flex items-center px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors',
                  viewMode === 'grid' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700')}>
                <LayoutGrid className="w-3.5 h-3.5 mr-1.5" /> Grid
              </button>
              <button type="button" onClick={() => onViewModeChange('list')}
                className={cn('inline-flex items-center px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors',
                  viewMode === 'list' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700')}>
                <List className="w-3.5 h-3.5 mr-1.5" /> List
              </button>
            </div>
          )}
        </div>

        {/* Grid Filters (advanced layout) */}
        {filtersGrid && filters.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 mt-4">
            {filters.map((filter) => {
              const type = filter.type || 'select';
              if (type === 'select') {
                return (
                  <select key={filter.key} value={filter.value} onChange={(e) => filter.onChange(e.target.value)} className={cn("input w-full bg-gray-50", filter.className)}>
                    {filter.placeholder && <option value="">{filter.placeholder}</option>}
                    {(filter.options || []).map((opt) => <option key={opt.value} value={opt.value} disabled={opt.disabled}>{opt.label}</option>)}
                  </select>
                );
              }
              if (type === 'number') {
                return <input key={filter.key} type="number" value={filter.value} onChange={(e) => filter.onChange(e.target.value)} placeholder={filter.placeholder} min={filter.min} max={filter.max} step={filter.step} className={cn("input w-full bg-gray-50", filter.className)} />;
              }
              return <input key={filter.key} type="text" value={filter.value} onChange={(e) => filter.onChange(e.target.value)} placeholder={filter.placeholder} className={cn("input w-full bg-gray-50", filter.className)} />;
            })}
          </div>
        )}

        {/* Apply / Clear Buttons */}
        {onApplyFilters && (
          <div className="flex gap-3 mt-4">
            <button type="button" onClick={onApplyFilters} disabled={isFiltering}
              className="btn-primary flex-1 px-6 py-2.5 shadow-lg shadow-primary-200/70 hover:shadow-xl transition-all duration-200">
              {isFiltering ? <><Loader className="w-5 h-5 mr-2 animate-spin" /> Filtering...</> : <><Search className="w-5 h-5 mr-2" /> {applyLabel}</>}
            </button>
            {onClearFilters && (
              <button type="button" onClick={onClearFilters} className="btn-secondary py-2.5">
                <X className="w-4 h-4 mr-1.5" /> Clear
              </button>
            )}
          </div>
        )}

        {/* Filter Error */}
        {filterError && (
          <div className="bg-error-50 border border-error-200 rounded-lg p-3 mt-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-error-500 flex-shrink-0" />
              <span className="text-sm text-error-700">{filterError}</span>
            </div>
          </div>
        )}

        {/* Active Filter Pills */}
        {activeFilters.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap mt-3">
            <span className="text-xs font-medium text-gray-500">Active filters:</span>
            <button onClick={onClearFilters} className="text-xs text-gray-500 hover:text-gray-700 underline">Clear All</button>
            {activeFilters.map((af) => (
              <span key={af.key} className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-50 text-primary-700 border border-primary-200 rounded-full text-xs">
                {af.label}
                <button onClick={af.onRemove}><XCircle className="w-3 h-3" /></button>
              </span>
            ))}
          </div>
        )}

        {/* Bulk Actions */}
        {selectable && selectedIds.size > 0 && (
          <div className="mt-3 flex items-center gap-3 p-3 bg-gray-50 rounded-md border border-gray-200">
            <span className="text-sm text-gray-700 font-medium tabular-nums">
              {selectedIds.size} selected
            </span>
            {bulkActions.map((action, index) => (
              <button
                key={index}
                type="button"
                onClick={action.onClick}
                className={cn(
                  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  action.variant === 'danger'
                    ? "btn-danger"
                    : "btn-primary"
                )}
              >
                <action.icon className="w-4 h-4" />
                {action.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => onSelectionChange?.(new Set())}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden relative min-h-[400px]">
        {loading && data.length > 0 && (
          <div className="absolute inset-0 z-10 bg-white/60 backdrop-blur-[1px] flex items-center justify-center">
            <div className="bg-white p-3 rounded-full shadow-md border border-gray-200">
              <Loader className="w-5 h-5 text-primary-600 animate-spin" />
            </div>
          </div>
        )}

        {loading && data.length === 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead className="bg-gray-50/80 border-b border-gray-200">
                <tr>
                  {selectable && (
                    <th className="px-6 py-3 text-left">
                      <div className="h-4 w-4 bg-gray-200 rounded animate-pulse" />
                    </th>
                  )}
                  {columns.map((column) => (
                    <th
                      key={column.key}
                      className={cn(
                        "px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider",
                        column.headerClassName
                      )}
                    >
                      {column.label}
                    </th>
                  ))}
                  {rowActions && (
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100/80">
                {[...Array(5)].map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    {selectable && (
                      <td className="px-6 py-4">
                        <Skeleton className="h-4 w-4" />
                      </td>
                    )}
                    {columns.map((column) => (
                      <td key={column.key} className="px-6 py-4">
                        <Skeleton className="h-4 w-3/4" />
                      </td>
                    ))}
                    {rowActions && (
                      <td className="px-6 py-4 text-right">
                        <div className="flex justify-end gap-2">
                          <Skeleton className="h-8 w-8 rounded" />
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : data.length === 0 ? (
          <div className="text-center py-16 px-6">
            {EmptyIcon && <EmptyIcon className="w-10 h-10 text-gray-300 mx-auto mb-3" />}
            <h3 className="text-base font-medium text-gray-900 mb-1">{emptyTitle}</h3>
            <p className="text-sm text-gray-500 mb-4 max-w-sm mx-auto">{emptyDescription}</p>
            {emptyAction}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead className="bg-gray-50/80 border-b border-gray-200">
                  <tr>
                    {selectable && (
                      <th className="px-6 py-3 text-left">
                        <input
                          type="checkbox"
                          checked={allSelected}
                          onChange={toggleSelectAll}
                          className="rounded border-gray-200 text-gray-900 focus:ring-gray-500"
                        />
                      </th>
                    )}
                    {columns.map((column) => (
                      <th
                        key={column.key}
                        className={cn(
                          "px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider",
                          column.headerClassName
                        )}
                      >
                        {column.sortable && onSort ? (
                          <button
                            type="button"
                            onClick={() => onSort(column.key)}
                            className="flex items-center gap-1 hover:text-gray-700 transition-colors"
                          >
                            {column.label}
                            {getSortIcon(column.key)}
                          </button>
                        ) : (
                          column.label
                        )}
                      </th>
                    ))}
                    {rowActions && (
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100/80">
                  {data.map((row, index) => {
                    const rowId = getRowId(row);
                    const isSelected = selectedIds.has(rowId);
                    const canSelect = isRowSelectable(row);
                    const actions = rowActions?.(row).filter(a => !a.hidden) || [];

                    return (
                      <tr
                        key={`${rowId}_${index}`}
                        className={cn(
                          "hover:bg-gray-50 transition-colors",
                          isSelected && "bg-gray-50",
                          getRowClassName?.(row)
                        )}
                      >
                        {selectable && (
                          <td className="px-6 py-4">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelect(row)}
                              disabled={!canSelect}
                              className={cn(
                                "rounded border-gray-200 text-gray-900 focus:ring-gray-500",
                                !canSelect && "opacity-50 cursor-not-allowed"
                              )}
                            />
                          </td>
                        )}
                        {columns.map((column) => (
                          <td
                            key={column.key}
                            className={cn(
                              "px-6 py-4 whitespace-nowrap text-sm",
                              column.cellClassName
                            )}
                          >
                            {column.render(row)}
                          </td>
                        ))}
                        {rowActions && actions.length > 0 && (
                          <td className="px-6 py-4 whitespace-nowrap text-right">
                            <div className="flex items-center justify-end gap-1">
                              {actions.map((action, index) => {
                                const ActionIcon = action.icon;
                                const className = cn(
                                  "p-1.5 rounded-md transition-colors",
                                  action.disabled
                                    ? "text-gray-300 cursor-not-allowed"
                                    : action.variant === 'danger'
                                      ? "text-gray-400 hover:text-error-600 hover:bg-error-50"
                                      : "text-gray-400 hover:text-gray-700 hover:bg-gray-100"
                                );

                                if (action.href && !action.disabled) {
                                  return (
                                    <Link
                                      key={index}
                                      to={action.href}
                                      className={className}
                                      title={action.label}
                                    >
                                      <ActionIcon className="w-4 h-4" />
                                    </Link>
                                  );
                                }

                                return (
                                  <button
                                    key={index}
                                    type="button"
                                    onClick={action.onClick}
                                    disabled={action.disabled}
                                    className={className}
                                    title={action.label}
                                  >
                                    <ActionIcon className="w-4 h-4" />
                                  </button>
                                );
                              })}
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="px-6 py-3 border-t border-gray-200 flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="text-sm text-gray-500 tabular-nums">
                Showing {((page - 1) * pageSize) + 1} to {Math.min(page * pageSize, total)} of {total}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onPageChange(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="p-1.5 border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="text-sm text-gray-600 px-2 tabular-nums">
                  {page} / {totalPages || 1}
                </span>
                <button
                  type="button"
                  onClick={() => onPageChange(Math.min(totalPages, page + 1))}
                  disabled={page >= totalPages}
                  className="p-1.5 border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {deleteModal?.show && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg max-w-md w-full mx-4 p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className={cn(
                "p-2 rounded-lg",
                deleteModal.confirmVariant === 'warning' ? "bg-warning-50 text-warning-600" :
                  deleteModal.confirmVariant === 'primary' ? "bg-primary-50 text-primary-600" :
                    "bg-error-50 text-error-600"
              )}>
                {deleteModal.icon ? (
                  <deleteModal.icon className="w-5 h-5" />
                ) : (
                  <AlertTriangle className="w-5 h-5" />
                )}
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{deleteModal.title}</h3>
            </div>

            {deleteModal.content}

            {deleteModal.showProgress ? (
              <div className="space-y-4">
                <p className="text-gray-600 text-sm tabular-nums">Deleting... {deleteModal.progress || 0}%</p>
                <ProgressBar
                  value={deleteModal.progress || 0}
                  className="h-1.5 bg-gray-100 rounded-full"
                  barClassName="bg-error-600 h-1.5 rounded-full"
                />
                {deleteModal.onCancelProgress && (
                  <button
                    onClick={deleteModal.onCancelProgress}
                    className="btn-secondary w-full justify-center"
                  >
                    <X className="w-4 h-4" />
                    Cancel
                  </button>
                )}
              </div>
            ) : (
              <>
                <p className="text-gray-500 text-sm mb-6">{deleteModal.message}</p>
                <div className="flex justify-end gap-3">
                  <button
                    onClick={deleteModal.onCancel}
                    disabled={deleteModal.loading}
                    className="btn-secondary"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={deleteModal.onConfirm}
                    disabled={deleteModal.loading}
                    className={cn(
                      "inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium text-white transition-colors disabled:opacity-50",
                      deleteModal.confirmVariant === 'warning' ? "bg-warning-500 hover:bg-warning-700" :
                        deleteModal.confirmVariant === 'primary' ? "bg-primary-600 hover:bg-primary-700" :
                          "bg-error-600 hover:bg-error-700"
                    )}
                  >
                    {deleteModal.loading && <Loader className="w-4 h-4 animate-spin" />}
                    {deleteModal.confirmLabel || (
                      <>
                        <Trash2 className="w-4 h-4" />
                        Delete
                      </>
                    )}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
