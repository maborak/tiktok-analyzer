import { useState, useEffect } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { Loader2, Edit, Trash2, AlertTriangle, Lock, Plus, X, Search, Shield } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import type { Role, Permission, PermissionsListResponse, RolePermissionsResponse } from '@/types/api';
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

export function RoleDetail() {
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const { isAuthenticated, user, isLoading: authLoading } = useAuth();
  const loaderData = undefined as {
    role: Role;
    permissions: PermissionsListResponse;
    rolePermissions: RolePermissionsResponse;
  } | undefined;

  const [role, setRole] = useState<Role | null>(loaderData?.role ?? null);
  const [rolePermissions, setRolePermissions] = useState<Permission[]>(
    loaderData?.rolePermissions?.permissions || []
  );
  const [loading, setLoading] = useState(!loaderData);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [deleteRoleId, setDeleteRoleId] = useState<number | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletionProgress, setDeletionProgress] = useState(0);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [availablePermissions, setAvailablePermissions] = useState<Permission[]>(
    loaderData?.permissions?.permissions || []
  );
  const [loadingAvailablePermissions, setLoadingAvailablePermissions] = useState(false);
  const [permissionSearchTerm, setPermissionSearchTerm] = useState('');
  const [permissionCategoryFilter, setPermissionCategoryFilter] = useState('');

  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated || user?.role !== 'admin') {
      toast.error('Access denied. Administrator role required.');
      navigate({ to: '/' });
      return;
    }

    if (id) {
      if (!loaderData) {
        loadRole();
      } else {
        setLoading(false);
      }
    }
  }, [authLoading, isAuthenticated, user, navigate, id, loaderData]);

  useEffect(() => {
    if (!role) return;
    if (!loaderData) {
      loadRolePermissions();
    } else {
      setLoadingPermissions(false);
    }
  }, [role, loaderData]);

  // Listen for unauthorized events
  useEffect(() => {
    const handleUnauthorized = (event: CustomEvent) => {
      console.log('Unauthorized access detected:', event.detail);
      toast.error('Your session has expired. Please log in again.');
      navigate({ to: '/login' });
    };

    window.addEventListener('auth:unauthorized', handleUnauthorized as EventListener);
    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized as EventListener);
    };
  }, [navigate]);

  const loadRole = async () => {
    if (!id) return;
    try {
      setLoading(true);
      const apiClient = getApiClient();
      const roleId = parseInt(id, 10);

      // If the ID is not a valid number, try to find by name from the list
      if (isNaN(roleId)) {
        console.error('Invalid role ID:', id);
        toast.error('Invalid role ID');
        navigate({ to: `/admin/rbac/roles` });
        return;
      }

      try {
        // First try to get role by ID
        const roleData = await apiClient.getRole(roleId);
        setRole(roleData);
      } catch (getError: any) {
        // If getting by ID fails (e.g., endpoint not supported), 
        // fallback to loading from list
        console.warn('getRole by ID failed, trying fallback:', getError);
        const listResponse = await apiClient.listRoles({ page_size: 100 });
        const foundRole = listResponse.roles?.find(r => r.id === roleId);
        if (foundRole) {
          setRole(foundRole);
        } else {
          throw new Error(`Role with ID ${roleId} not found`);
        }
      }
    } catch (error: any) {
      console.error('Failed to load role:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else if (error.response?.status === 404) {
        toast.error('Role not found');
        navigate({ to: `/admin/rbac/roles` });
      } else {
        toast.error(getErrorMessage(error, 'Failed to load role'));
      }
    } finally {
      setLoading(false);
    }
  };

  const loadRolePermissions = async () => {
    if (!role) return;
    try {
      setLoadingPermissions(true);
      const apiClient = getApiClient();
      const response = await apiClient.getRolePermissions(role.id);
      setRolePermissions(response.permissions || []);
    } catch (error: any) {
      console.error('Failed to load role permissions:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(getErrorMessage(error, 'Failed to load role permissions'));
      }
    } finally {
      setLoadingPermissions(false);
    }
  };

  const loadAvailablePermissions = async () => {
    try {
      setLoadingAvailablePermissions(true);
      const apiClient = getApiClient();
      const response = await apiClient.listPermissions({ page: 1, page_size: 100, is_active: true });
      let allPermissions = response.permissions || [];

      // If there are more pages, load them
      if (response.total_pages > 1) {
        for (let page = 2; page <= response.total_pages; page++) {
          const pageResponse = await apiClient.listPermissions({ page, page_size: 100, is_active: true });
          allPermissions = [...allPermissions, ...(pageResponse.permissions || [])];
        }
      }

      setAvailablePermissions(allPermissions);
    } catch (error: any) {
      console.error('Failed to load available permissions:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(getErrorMessage(error, 'Failed to load available permissions'));
      }
    } finally {
      setLoadingAvailablePermissions(false);
    }
  };

  const handleAssignPermission = async (permissionId: number) => {
    if (!role) return;
    try {
      const apiClient = getApiClient();
      await apiClient.assignPermissionToRole(role.id, permissionId);
      toast.success('Permission assigned successfully');
      setShowAssignModal(false);
      setPermissionSearchTerm('');
      setPermissionCategoryFilter('');
      loadRolePermissions();
    } catch (error: any) {
      console.error('Failed to assign permission:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else if (error.response?.status === 409) {
        toast.error(getErrorMessage(error, 'Permission is already assigned to this role'));
      } else {
        toast.error(getErrorMessage(error, 'Failed to assign permission'));
      }
    }
  };

  const handleRemovePermission = async (permissionId: number) => {
    if (!role) return;
    try {
      const apiClient = getApiClient();
      await apiClient.removePermissionFromRole(role.id, permissionId);
      toast.success('Permission removed successfully');
      loadRolePermissions();
    } catch (error: any) {
      console.error('Failed to remove permission:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(getErrorMessage(error, 'Failed to remove permission'));
      }
    }
  };

  const openAssignModal = () => {
    setShowAssignModal(true);
    loadAvailablePermissions();
  };

  const handleDelete = async () => {
    if (!deleteRoleId || !role) return;

    if (role.is_system) {
      toast.error('System roles cannot be deleted');
      setDeleteRoleId(null);
      return;
    }

    setIsDeleting(true);
    setDeletionProgress(0);

    try {
      const apiClient = getApiClient();

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
      navigate({ to: `/admin/rbac/roles` });
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
    setIsDeleting(false);
    setDeletionProgress(0);
    setDeleteRoleId(null);
  };

  if (authLoading || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    );
  }

  if (!role) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Role not found</p>
        <button
          onClick={() => navigate({ to: `/admin/rbac/roles` })}
          className="auth-link mt-4"
          style={{ fontFamily: 'var(--font-mono-display)' }}
        >
          ← back to roles
        </button>
      </div>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={`Role: ${role.name}`}
        description="View and manage role information"
        icon={<Shield className="w-5 h-5" />}
        backTo={`/admin/rbac/roles`}
        backLabel="Back to roles"
        actions={
          <>
            <button
              onClick={() => navigate({ to: `/admin/rbac/roles/${role.id}/edit` })}
              className="btn-secondary auth-submit flex items-center gap-2"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              <Edit className="h-4 w-4" /> edit →
            </button>
            {!role.is_system && (
              <button
                onClick={() => setDeleteRoleId(role.id)}
                className="btn-danger auth-submit flex items-center gap-2"
                style={{ fontFamily: 'var(--font-mono-display)' }}
              >
                <Trash2 className="h-4 w-4" /> delete →
              </button>
            )}
          </>
        }
      />

      {/* Role Information */}
      <div className="card p-0">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2
            className="text-lg font-semibold text-gray-900"
            style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
          >
            Role Information
          </h2>
        </div>
        <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="auth-mono-label">Role Name</label>
            <p className="mt-1 text-sm text-gray-900 font-mono">{role.name}</p>
          </div>
          <div>
            <label className="auth-mono-label">Type</label>
            <p className="mt-1">
              {role.is_system ? (
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-primary-100 text-primary-800">
                  <Lock className="h-3 w-3" />
                  System Role
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                  Custom Role
                </span>
              )}
            </p>
          </div>
          <div className="md:col-span-2">
            <label className="auth-mono-label">Description</label>
            <p className="mt-1 text-sm text-gray-900">{role.description || '—'}</p>
          </div>
          <div>
            <label className="auth-mono-label">Status</label>
            <p className="mt-1">
              <span
                className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${role.is_active
                    ? 'bg-success-50 text-success-700'
                    : 'bg-error-50 text-error-700'
                  }`}
              >
                {role.is_active ? 'Active' : 'Inactive'}
              </span>
            </p>
          </div>
          <div>
            <label className="auth-mono-label">Created</label>
            <p className="mt-1 text-sm text-gray-900">
              {formatRelativeTime(role.created_at)}
            </p>
            <p className="text-xs text-gray-500">
              {new Date(role.created_at).toLocaleString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
              })}
            </p>
          </div>
        </div>
      </div>

      {/* Assigned Permissions */}
      <div className="card p-0">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2
              className="text-lg font-semibold text-gray-900"
              style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
            >
              Assigned Permissions
            </h2>
            <p className="page-subtitle mt-1">
              {rolePermissions.length} permission{rolePermissions.length !== 1 ? 's' : ''} assigned
            </p>
          </div>
          <button
            onClick={openAssignModal}
            className="btn-primary auth-submit"
            style={{ fontFamily: 'var(--font-mono-display)' }}
          >
            <Plus className="h-4 w-4" />
            add permission →
          </button>
        </div>
        <div className="p-6">
          {loadingPermissions ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
            </div>
          ) : rolePermissions.length === 0 ? (
            <p className="text-sm text-gray-500">No permissions assigned to this role.</p>
          ) : (
            <div className="space-y-3">
              {rolePermissions.map((permission) => (
                <div key={permission.id} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">{permission.name}</span>
                      {permission.category && (
                        <span className="text-xs px-2 py-0.5 bg-gray-200 text-gray-600 rounded">
                          {permission.category}
                        </span>
                      )}
                    </div>
                    {permission.description && (
                      <p className="mt-1 text-xs text-gray-600">{permission.description}</p>
                    )}
                  </div>
                  <button
                    onClick={() => handleRemovePermission(permission.id)}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs text-error-600 hover:bg-error-50 rounded border border-error-200 hover:border-error-300 transition-colors"
                  >
                    <X className="h-3 w-3" />
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
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
                    Are you sure you want to delete role "{role.name}"?
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

      {/* Assign Permission Modal */}
      {showAssignModal && (
        <div
          className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setShowAssignModal(false)}
        >
          <div
            className="bg-white rounded-lg shadow-2xl max-w-2xl w-full mx-4 modal-panel-compact flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div>
                  <h3
                    className="text-xl font-semibold text-gray-900"
                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                  >
                    Assign Permission
                  </h3>
                  <p className="page-subtitle mt-1">Select a permission to assign to {role?.name}</p>
                </div>
                <button
                  onClick={() => setShowAssignModal(false)}
                  className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <X className="h-5 w-5 text-gray-500" />
                </button>
              </div>
            </div>

            <div className="p-6 flex-1 overflow-hidden flex flex-col">
              {/* Search and Filter */}
              <div className="mb-4 flex items-center gap-3">
                <div className="flex-1 relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search permissions..."
                    value={permissionSearchTerm}
                    onChange={(e) => setPermissionSearchTerm(e.target.value)}
                    className="input rounded-lg pl-10 pr-4"
                  />
                </div>
                <select
                  value={permissionCategoryFilter}
                  onChange={(e) => setPermissionCategoryFilter(e.target.value)}
                  className="input rounded-lg"
                >
                  <option value="">All Categories</option>
                  {Array.from(new Set(availablePermissions.map((p) => p.category).filter((cat): cat is string => Boolean(cat)))).map((cat) => (
                    <option key={cat} value={cat || ''}>
                      {cat}
                    </option>
                  ))}
                </select>
              </div>

              {/* Permissions List */}
              <div className="flex-1 overflow-y-auto">
                {loadingAvailablePermissions ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
                  </div>
                ) : (() => {
                  const filtered = availablePermissions.filter((perm) => {
                    const alreadyAssigned = rolePermissions.some((rp) => rp.id === perm.id);
                    if (alreadyAssigned) return false;

                    const matchesSearch = !permissionSearchTerm ||
                      perm.name.toLowerCase().includes(permissionSearchTerm.toLowerCase()) ||
                      (perm.description && perm.description.toLowerCase().includes(permissionSearchTerm.toLowerCase()));

                    const matchesCategory = !permissionCategoryFilter || perm.category === permissionCategoryFilter;

                    return matchesSearch && matchesCategory;
                  });

                  return filtered.length === 0 ? (
                    <div className="text-center py-12">
                      <p className="text-sm text-gray-500">No available permissions found</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {filtered.map((permission) => (
                        <div
                          key={permission.id}
                          className="p-4 border border-gray-200 rounded-lg hover:border-primary-300 hover:bg-primary-50 transition-colors cursor-pointer"
                          onClick={() => handleAssignPermission(permission.id)}
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-gray-900">{permission.name}</span>
                                {permission.category && (
                                  <span className="text-xs px-2 py-0.5 bg-gray-200 text-gray-600 rounded">
                                    {permission.category}
                                  </span>
                                )}
                              </div>
                              {permission.description && (
                                <p className="mt-1 text-xs text-gray-600">{permission.description}</p>
                              )}
                            </div>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleAssignPermission(permission.id);
                              }}
                              className="btn-primary auth-submit ml-4 px-3 py-1.5 text-xs"
                              style={{ fontFamily: 'var(--font-mono-display)' }}
                            >
                              assign →
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
