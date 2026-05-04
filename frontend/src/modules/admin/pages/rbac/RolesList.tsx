import { useState, useEffect, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Shield, Loader2, Plus, Eye, Edit, Trash2, AlertTriangle, Lock, Search, ChevronLeft, ChevronRight } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import type { Role, RolesListResponse } from '@/types/api';
import { toast } from 'react-hot-toast';
import { formatRelativeTime } from '@/utils/dateUtils';
import { useAuth } from '@/contexts/AuthContext';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

// Helper function to safely extract error message
const getErrorMessage = (error: any, defaultMessage: string): string => {
  if (!error?.response?.data?.detail) {
    return defaultMessage;
  }

  const detail = error.response.data.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail.map((err: any) => {
      if (typeof err === 'string') return err;
      if (err.msg) return err.msg;
      return JSON.stringify(err);
    }).join(', ');
  }

  if (typeof detail === 'object') {
    if (detail.message) return detail.message;
    if (detail.msg) return detail.msg;
    return JSON.stringify(detail);
  }

  return defaultMessage;
};

export function RolesList() {
  const loaderData = undefined as RolesListResponse | undefined;
  const [roles, setRoles] = useState<Role[]>(loaderData?.roles || []);
  const [loading, setLoading] = useState(!loaderData);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(loaderData?.total || 0);
  const [totalPages, setTotalPages] = useState(loaderData?.total_pages || 0);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeSearchTerm, setActiveSearchTerm] = useState('');
  const [activeFilter, setActiveFilter] = useState<string>('');
  const [systemFilter, setSystemFilter] = useState<string>('');
  const [sortBy] = useState('name');
  const [sortOrder] = useState<'asc' | 'desc'>('asc');
  const [deleteRoleId, setDeleteRoleId] = useState<number | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletionProgress, setDeletionProgress] = useState(0);
  const deletionCancelledRef = useRef(false);

  // Ref for tracking previous params to prevent redundant calls
  const prevParamsRef = useRef({
    page: 1,
    pageSize: 10,
    activeFilter: '',
    systemFilter: '',
    sortBy: 'name',
    sortOrder: 'asc' as 'asc' | 'desc',
    activeSearchTerm: '',
    initialized: false
  });

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
      systemFilter,
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
      prev.systemFilter !== systemFilter ||
      prev.sortBy !== sortBy ||
      prev.sortOrder !== sortOrder ||
      prev.activeSearchTerm !== activeSearchTerm;

    // Update ref for next render
    prevParamsRef.current = { ...currentParams, initialized: true };

    // Logic:
    // 1. If loaderData exists and metrics haven't changed, skip using initial data.
    // 2. If params changed, fetch.
    // 3. If no loaderData, fetch.

    if (!prev.initialized && loaderData) {
      setLoading(false);
      return;
    }

    if (!paramsChanged && prev.initialized) {
      return;
    }

    loadRoles();
  }, [authLoading, isAuthenticated, user, navigate, page, pageSize, activeFilter, systemFilter, sortBy, sortOrder, activeSearchTerm]);

  // Listen for unauthorized events
  useEffect(() => {
    const handleUnauthorized = (event: CustomEvent) => {
      console.log('Unauthorized access detected:', event.detail);
      toast.error('Your session has expired. Please log in again.');
      setDeleteRoleId(null);
      navigate({ to: '/login' });
    };

    window.addEventListener('auth:unauthorized', handleUnauthorized as EventListener);
    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized as EventListener);
    };
  }, [navigate]);

  const loadRoles = async () => {
    try {
      setLoading(true);
      const apiClient = getApiClient();
      const params: any = {
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      if (activeSearchTerm) params.search = activeSearchTerm;
      if (activeFilter) params.is_active = activeFilter === 'true';
      if (systemFilter) params.is_system = systemFilter === 'true';

      const response = await apiClient.listRoles(params);
      setRoles(response.roles || []);
      setTotal(response.total || 0);
      setTotalPages(response.total_pages || 0);
    } catch (error: any) {
      console.error('Failed to load roles:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(getErrorMessage(error, 'Failed to load roles'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteRoleId) return;

    const roleToDelete = roles.find((r) => r.id === deleteRoleId);
    if (roleToDelete?.is_system) {
      toast.error('System roles cannot be deleted');
      setDeleteRoleId(null);
      return;
    }

    deletionCancelledRef.current = false;
    setIsDeleting(true);
    setDeletionProgress(0);

    try {
      const apiClient = getApiClient();

      // Simulate progress
      const progressInterval = setInterval(() => {
        setDeletionProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 10;
        });
      }, 100);

      await apiClient.deleteRole(deleteRoleId);
      clearInterval(progressInterval);
      setDeletionProgress(100);
      await new Promise((resolve) => setTimeout(resolve, 300));

      toast.success('Role deleted successfully');
      setDeleteRoleId(null);
      setIsDeleting(false);
      setDeletionProgress(0);
      loadRoles();
    } catch (error: any) {
      console.error('Failed to delete role:', error);
      setIsDeleting(false);
      setDeletionProgress(0);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(getErrorMessage(error, 'Failed to delete role'));
      }
    }
  };

  const handleCancelDelete = () => {
    deletionCancelledRef.current = true;
    setIsDeleting(false);
    setDeletionProgress(0);
    setDeleteRoleId(null);
  };

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Role Management"
        description="Manage user roles and their permissions"
        icon={<Shield className="h-5 w-5" />}
        actions={
          <button
            onClick={() => navigate({ to: `/admin/rbac/roles/new` })}
            className="btn-primary auth-submit"
            style={{ fontFamily: 'var(--font-mono-display)' }}
          >
            <Plus className="h-4 w-4" />
            create role →
          </button>
        }
      />

      {/* Filters */}
      <div className="card p-4">
        <div className="flex flex-wrap items-center gap-4">
          {/* Search */}
          <div className="relative flex-1 min-w-52 flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search roles..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    setActiveSearchTerm(searchTerm);
                    setPage(1);
                  }
                }}
                className="input rounded-lg pl-10 pr-4"
              />
            </div>
            <button
              onClick={() => {
                setActiveSearchTerm(searchTerm);
                setPage(1);
              }}
              className="btn-primary auth-submit"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              search →
            </button>
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-2">
            <label className="auth-mono-label">Status:</label>
            <select
              value={activeFilter}
              onChange={(e) => { setActiveFilter(e.target.value); setPage(1); }}
              className="input py-1.5"
            >
              <option value="">All</option>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
          </div>

          {/* System Filter */}
          <div className="flex items-center gap-2">
            <label className="auth-mono-label">Type:</label>
            <select
              value={systemFilter}
              onChange={(e) => { setSystemFilter(e.target.value); setPage(1); }}
              className="input py-1.5"
            >
              <option value="">All</option>
              <option value="true">System</option>
              <option value="false">Custom</option>
            </select>
          </div>

          {/* Page Size */}
          <div className="flex items-center gap-2">
            <label className="auth-mono-label">Show:</label>
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              className="input py-1.5"
            >
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="20">20</option>
              <option value="50">50</option>
            </select>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="auth-mono-label px-6 py-3 text-left">
                  Name
                </th>
                <th className="auth-mono-label px-6 py-3 text-left">
                  Description
                </th>
                <th className="auth-mono-label px-6 py-3 text-left">
                  Type
                </th>
                <th className="auth-mono-label px-6 py-3 text-left">
                  Status
                </th>
                <th className="auth-mono-label px-6 py-3 text-left">
                  Created
                </th>
                <th className="auth-mono-label px-6 py-3 text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className={`bg-white divide-y divide-gray-200 ${loading ? 'opacity-50' : ''}`}>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center">
                    <div className="flex items-center justify-center">
                      <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
                    </div>
                  </td>
                </tr>
              ) : roles.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center">
                    <Shield className="mx-auto h-12 w-12 text-gray-400" />
                    <h3
                      className="mt-2 text-sm font-medium text-gray-900"
                      style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                      No roles found
                    </h3>
                    <p className="page-subtitle mt-1">Create a new role to get started</p>
                  </td>
                </tr>
              ) : (
                roles.map((role) => (
                  <tr key={role.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <Shield className="h-4 w-4 text-gray-400" />
                        <span className="text-sm font-medium text-gray-900">{role.name}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-600 max-w-md truncate">
                        {role.description || '—'}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {role.is_system ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-primary-100 text-primary-800">
                          <Lock className="h-3 w-3" />
                          System
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                          Custom
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${role.is_active
                          ? 'bg-success-50 text-success-700'
                          : 'bg-error-50 text-error-700'
                          }`}
                      >
                        {role.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-xs text-gray-500">
                        {formatRelativeTime(role.created_at)}
                      </div>
                      <div className="text-xs text-gray-400">
                        {new Date(role.created_at).toLocaleString(undefined, {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit'
                        })}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => navigate({ to: `/admin/rbac/roles/${role.id}` })}
                          className="text-gray-500 hover:text-primary-400 p-1 transition-colors"
                          title="View details"
                        >
                          <Eye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => navigate({ to: `/admin/rbac/roles/${role.id}/edit` })}
                          className="text-gray-500 hover:text-primary-400 p-1 transition-colors"
                          title="Edit role"
                        >
                          <Edit className="h-4 w-4" />
                        </button>
                        {!role.is_system && (
                          <button
                            onClick={() => setDeleteRoleId(role.id)}
                            className="text-gray-500 hover:text-primary-400 p-1 transition-colors"
                            title="Delete role"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                        {role.is_system && (
                          <span className="p-1 text-gray-300" title="System roles cannot be deleted">
                            <Trash2 className="h-4 w-4" />
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
            <div className="text-sm text-gray-600">
              Showing {((page - 1) * pageSize) + 1} - {Math.min(page * pageSize, total)} of {total} roles
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page <= 1}
                className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum;
                if (totalPages <= 5) {
                  pageNum = i + 1;
                } else if (page <= 3) {
                  pageNum = i + 1;
                } else if (page >= totalPages - 2) {
                  pageNum = totalPages - 4 + i;
                } else {
                  pageNum = page - 2 + i;
                }
                return (
                  <button
                    key={pageNum}
                    type="button"
                    onClick={() => setPage(pageNum)}
                    className={`w-10 h-10 rounded-lg text-sm font-medium ${page === pageNum
                      ? 'bg-primary-600 text-white'
                      : 'border border-gray-200 hover:bg-gray-50'
                      }`}
                  >
                    {pageNum}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={() => setPage(Math.min(totalPages, page + 1))}
                disabled={page >= totalPages}
                className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="text-xs text-gray-500 flex items-center gap-2">
        <Lock className="h-3 w-3" />
        <span>System roles (user, moderator, admin) cannot be deleted</span>
      </div>

      {/* Delete Confirmation Modal */}
      {deleteRoleId && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => !isDeleting && handleCancelDelete()}
        >
          <div
            className="bg-white rounded-lg shadow-2xl max-w-md w-full mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              <div className="flex items-start gap-4 mb-6">
                <div className="flex-shrink-0 w-12 h-12 rounded-full bg-error-50 flex items-center justify-center">
                  <AlertTriangle className="h-6 w-6 text-error-600" />
                </div>
                <div className="flex-1">
                  <h3
                    className="text-xl font-semibold text-gray-900 mb-2"
                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                  >
                    Delete Role
                  </h3>
                  <p className="text-sm text-gray-600">
                    Are you sure you want to delete role "{roles.find((r) => r.id === deleteRoleId)?.name}"?
                  </p>
                  <p className="text-xs text-gray-500 mt-2">
                    This action cannot be undone. Make sure there are no users assigned to this role.
                  </p>
                </div>
              </div>

              {isDeleting && (
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-2">
                    <span className="auth-mono-label text-gray-700">Deleting...</span>
                    <span className="text-sm text-gray-500">{deletionProgress}%</span>
                  </div>
                  <ProgressBar
                    value={deletionProgress}
                    className="h-2.5 bg-gray-200"
                    barClassName="bg-error-600 h-2.5"
                  />
                </div>
              )}

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                <button
                  onClick={handleCancelDelete}
                  disabled={isDeleting}
                  className="btn-secondary auth-submit"
                  style={{ fontFamily: 'var(--font-mono-display)' }}
                >
                  cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={isDeleting}
                  className="btn-danger auth-submit flex items-center gap-2"
                  style={{ fontFamily: 'var(--font-mono-display)' }}
                >
                  <Trash2 className="h-4 w-4" />
                  delete role →
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
