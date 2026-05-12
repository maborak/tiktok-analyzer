import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import {
  Shield,
  Plus,
  Eye,
  Pencil,
  Trash2,
  CheckCircle,
  XCircle,
} from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import type { Permission, PermissionsListResponse } from '@/types/api';
import { toast } from 'react-hot-toast';
import { formatRelativeTime } from '@/utils/dateUtils';
import { useAuth } from '@/contexts/AuthContext';
import { DataTable } from '@/components/DataTable';
import type { Column, FilterConfig, RowAction } from '@/components/DataTable';

export function PermissionsList() {
  const loaderData = undefined as PermissionsListResponse | undefined;
  const [permissions, setPermissions] = useState<Permission[]>(loaderData?.permissions || []);
  const [loading, setLoading] = useState(!loaderData);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);
  const [total, setTotal] = useState(loaderData?.total || 0);
  const [totalPages, setTotalPages] = useState(loaderData?.total_pages || 0);
  const [categoryFilter] = useState<string>('');
  const [activeFilter, setActiveFilter] = useState<string>('');
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy] = useState('name');
  const [sortOrder] = useState<'asc' | 'desc'>('asc');

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<number | string>>(new Set());

  // Deletion state
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteSelectedConfirm, setDeleteSelectedConfirm] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [bulkDeletionProgress, setBulkDeletionProgress] = useState(0);
  const deletionCancelledRef = useRef(false);
  const [activeSearchTerm, setActiveSearchTerm] = useState('');

  // Ref for tracking previous params to prevent redundant calls
  const prevParamsRef = useRef({
    page: 1,
    pageSize: 10,
    activeFilter: '',
    sortBy: 'slug',
    sortOrder: 'asc' as 'asc' | 'desc',
    activeSearchTerm: '',
    initialized: false

  });

  const handleSearchSubmit = (term: string) => {
    setActiveSearchTerm(term);
    setPage(1);
  };

  const navigate = useNavigate();
  const { isAuthenticated, user, isLoading: authLoading } = useAuth();

  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated || user?.role !== 'admin') {
      toast.error('Access denied. Administrator role required.');
      navigate({ to: '/' });
      return;
    }

    // Current params
    const currentParams = {
      page,
      pageSize,
      activeFilter,
      sortBy,
      sortOrder,
      activeSearchTerm
    };

    // Check if params actually changed
    const prev = prevParamsRef.current;
    const paramsChanged =
      prev.page !== page ||
      prev.pageSize !== pageSize ||
      prev.activeFilter !== activeFilter ||
      prev.sortBy !== sortBy ||
      prev.sortOrder !== sortOrder ||
      prev.activeSearchTerm !== activeSearchTerm;

    // Update ref for next render
    prevParamsRef.current = { ...currentParams, initialized: true };

    if (!prev.initialized && loaderData) {
      setLoading(false);
      return;
    }

    if (!paramsChanged && prev.initialized) {
      return;
    }

    loadPermissions();
  }, [authLoading, isAuthenticated, user, navigate, page, pageSize, activeFilter, sortBy, sortOrder, activeSearchTerm]);

  // Listen for unauthorized events
  useEffect(() => {
    const handleUnauthorized = () => {
      toast.error('Your session has expired. Please log in again.');
      setSelectedIds(new Set());
      setDeleteConfirmId(null);
      setDeleteSelectedConfirm(false);
      navigate({ to: '/login' });
    };

    window.addEventListener('auth:unauthorized', handleUnauthorized as EventListener);
    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized as EventListener);
    };
  }, [navigate]);

  const loadPermissions = async () => {
    try {
      setLoading(true);
      const apiClient = getApiClient();
      const params: any = {
        page: page || 1,
        page_size: pageSize || 5,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      if (activeFilter === 'active') {
        params.is_active = true;
      } else if (activeFilter === 'inactive') {
        params.is_active = false;
      }
      if (activeSearchTerm) params.search = activeSearchTerm;
      const response = await apiClient.listPermissions(params);
      setPermissions(response.permissions || []);
      setTotal(response.total || 0);
      setTotalPages(response.total_pages || 0);
    } catch (error: any) {
      console.error('Failed to load permissions:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(error.response?.data?.detail || 'Failed to load permissions');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (permissionId: number) => {
    try {
      setDeleting(true);
      const apiClient = getApiClient();
      await apiClient.deletePermission(permissionId);
      toast.success('Permission deleted successfully');
      setDeleteConfirmId(null);

      if (permissions.length === 1 && page > 1) {
        setPage(page - 1);
      } else {
        loadPermissions();
      }
    } catch (error: any) {
      console.error('Failed to delete permission:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(error.response?.data?.detail || 'Failed to delete permission');
      }
    } finally {
      setDeleting(false);
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedIds.size === 0) return;

    try {
      setIsBulkDeleting(true);
      deletionCancelledRef.current = false;
      setBulkDeletionProgress(0);

      const apiClient = getApiClient();
      const idsToDelete = Array.from(selectedIds) as number[];
      let deleted = 0;

      for (const id of idsToDelete) {
        if (deletionCancelledRef.current) {
          toast('Deletion cancelled');
          break;
        }

        try {
          await apiClient.deletePermission(id);
          deleted++;
          setBulkDeletionProgress(Math.round((deleted / idsToDelete.length) * 100));
        } catch (error) {
          console.error(`Failed to delete permission ${id}:`, error);
        }
      }

      if (!deletionCancelledRef.current) {
        toast.success(`Deleted ${deleted} of ${idsToDelete.length} permissions`);
      }

      setSelectedIds(new Set());
      setDeleteSelectedConfirm(false);
      loadPermissions();
    } catch (error) {
      console.error('Failed to delete permissions:', error);
      toast.error('Error deleting permissions');
    } finally {
      setIsBulkDeleting(false);
      setBulkDeletionProgress(0);
    }
  };

  const handleCancelBulkDelete = () => {
    deletionCancelledRef.current = true;
  };

  const handleSort = (field: string) => {
    // Sorting is fixed to 'slug' asc based on the provided instruction
    // If dynamic sorting is desired, sortBy and sortOrder should be useState with setters.
    // For now, this function will not change the sort state.
    console.log(`Attempted to sort by ${field}. Sorting is currently fixed to '${sortBy}' '${sortOrder}'.`);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };



  // Define columns
  const columns: Column<Permission>[] = [
    {
      key: 'name',
      label: 'Name',
      sortable: true,
      render: (permission) => (
        <span className="text-sm font-medium text-gray-900">
          {permission.name}
        </span>
      ),
    },
    {
      key: 'category',
      label: 'Category',
      sortable: true,
      render: (permission) => (
        <span className="text-sm text-gray-600">
          {permission.category || '—'}
        </span>
      ),
    },
    {
      key: 'description',
      label: 'Description',
      render: (permission) => (
        <div className="text-sm text-gray-600 max-w-md truncate">
          {permission.description || '—'}
        </div>
      ),
    },
    {
      key: 'is_active',
      label: 'Status',
      render: (permission) => (
        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${permission.is_active
          ? 'bg-success-50 text-success-700'
          : 'bg-gray-100 text-gray-800'
          }`}>
          {permission.is_active ? (
            <CheckCircle className="w-3 h-3 mr-1" />
          ) : (
            <XCircle className="w-3 h-3 mr-1" />
          )}
          {permission.is_active ? 'Active' : 'Inactive'}
        </span>
      ),
    },
    {
      key: 'created_at',
      label: 'Created',
      sortable: true,
      render: (permission) => (
        <div>
          <div className="text-sm text-gray-500">
            {formatRelativeTime(permission.created_at)}
          </div>
          <div className="text-xs text-gray-400">
            {formatDate(permission.created_at)}
          </div>
        </div>
      ),
    },
  ];

  // Define filters
  const filters: FilterConfig[] = [
    {
      key: 'status',
      value: activeFilter,
      onChange: (value) => {
        setActiveFilter(value);
        setPage(1);
      },
      placeholder: 'All Statuses',
      options: [
        { value: 'active', label: 'Active' },
        { value: 'inactive', label: 'Inactive' },
      ],
    },
  ];

  // Define row actions
  const getRowActions = (permission: Permission): RowAction[] => [
    {
      icon: Eye,
      label: 'View',
      href: `/management/rbac/permissions/${permission.id}`,
    },
    {
      icon: Pencil,
      label: 'Edit',
      href: `/management/rbac/permissions/${permission.id}/edit`,
    },
    {
      icon: Trash2,
      label: 'Delete',
      onClick: () => setDeleteConfirmId(permission.id),
      variant: 'danger',
    },
  ];

  // Get delete modal content
  const getDeleteModalContent = () => {
    const permissionToDelete = permissions.find((p) => p.id === deleteConfirmId);
    if (!permissionToDelete) return null;

    return (
      <div className="bg-gray-50 rounded-lg p-4 mb-4 border border-gray-200">
        <div className="flex items-center gap-3">
          <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary-50 flex items-center justify-center">
            <Shield className="h-5 w-5 text-primary-600" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-900">
              {permissionToDelete.name}
            </p>
            <p className="text-sm text-gray-500">
              {permissionToDelete.category || 'Uncategorized'}
            </p>
          </div>
        </div>
      </div>
    );
  };



  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-96">
        <div className="w-8 h-8 animate-spin text-primary-600 border-4 border-primary-600 border-t-transparent rounded-full" />
        <span className="ml-3 text-gray-600">Loading...</span>
      </div>
    );
  }

  return (
    <DataTable<Permission>
      // Data
      data={permissions}
      loading={loading}
      getRowId={(permission) => permission.id}

      // Header
      title="Permission Management"
      subtitle="Manage role-based access control permissions"
      icon={Shield}
      headerAction={
        <Link
          to={`/admin/rbac/permissions/new`}
          className="btn-primary"
        >
          <Plus className="w-4 h-4 mr-2" />
          Create Permission
        </Link>
      }

      // Columns
      columns={columns}

      // Pagination
      page={page}
      pageSize={pageSize}
      total={total}
      totalPages={totalPages}
      onPageChange={setPage}
      onPageSizeChange={setPageSize}
      pageSizeOptions={[5, 10, 20, 50, 100]}

      // Search
      searchEnabled={true}
      searchTerm={searchTerm}
      onSearchChange={setSearchTerm}
      onSearchSubmit={handleSearchSubmit}
      searchPlaceholder="Search permissions..."

      // Sorting
      sortBy={sortBy}
      sortOrder={sortOrder}
      onSort={handleSort}

      // Filters
      filters={filters}

      // Selection
      selectable={true}
      selectedIds={selectedIds}
      onSelectionChange={setSelectedIds}

      // Row Actions
      rowActions={getRowActions}

      onRowClick={(permission) => navigate({ to: `/management/rbac/permissions/${permission.id}` })}
      mobileCard={(permission) => (
        <div className="px-4 py-3 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-gray-900 truncate">
                {permission.name}
              </div>
              {permission.category && (
                <div className="text-xs text-gray-500 mt-0.5">{permission.category}</div>
              )}
            </div>
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium shrink-0 ${permission.is_active
              ? 'bg-success-50 text-success-700'
              : 'bg-gray-100 text-gray-800'
              }`}>
              {permission.is_active ? (
                <CheckCircle className="w-3 h-3 mr-1" />
              ) : (
                <XCircle className="w-3 h-3 mr-1" />
              )}
              {permission.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
          {permission.description && (
            <div className="text-xs text-gray-600 line-clamp-2">
              {permission.description}
            </div>
          )}
          <div className="text-[10px] uppercase tracking-wider text-gray-400 pt-1">
            Created <span className="normal-case tracking-normal text-gray-500">{formatRelativeTime(permission.created_at)}</span>
          </div>
        </div>
      )}

      // Bulk Actions
      bulkActions={[
        {
          icon: Trash2,
          label: 'Delete Selected',
          onClick: () => setDeleteSelectedConfirm(true),
          variant: 'danger',
        },
      ]}

      // Delete Modal
      deleteModal={deleteConfirmId !== null ? {
        show: true,
        title: 'Delete Permission',
        message: 'This will also remove all role and user assignments. This action cannot be undone.',
        content: getDeleteModalContent(),
        onConfirm: () => handleDelete(deleteConfirmId),
        onCancel: () => setDeleteConfirmId(null),
        loading: deleting,
      } : deleteSelectedConfirm ? {
        show: true,
        title: `Delete ${selectedIds.size} Permissions`,
        message: `Are you sure you want to delete ${selectedIds.size} permissions? This will also remove all role and user assignments. This action cannot be undone.`,
        onConfirm: handleDeleteSelected,
        onCancel: () => setDeleteSelectedConfirm(false),
        showProgress: isBulkDeleting,
        progress: bulkDeletionProgress,
        onCancelProgress: handleCancelBulkDelete,
      } : undefined}

      // Empty state
      emptyIcon={Shield}
      emptyTitle="No permissions found"
      emptyDescription={
        searchTerm || categoryFilter || activeFilter
          ? 'Try adjusting your filters'
          : 'Add your first permission to get started'
      }
      emptyAction={
        !searchTerm && !categoryFilter && !activeFilter ? (
          <Link
            to={`/admin/rbac/permissions/new`}
            className="btn-primary mt-4"
          >
            <Plus className="w-4 h-4 mr-2" />
            Create Permission
          </Link>
        ) : undefined
      }
    />
  );
}
