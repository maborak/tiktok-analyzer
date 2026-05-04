import { useState, useEffect } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { Loader2, Save, X, Lock, Plus, Search, Shield } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import type { CreateRoleRequest, UpdateRoleRequest, Permission } from '@/types/api';
import { toast } from 'react-hot-toast';
import { useAuth } from '@/contexts/AuthContext';
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

export function RoleForm() {
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const isEditMode = !!id;
  const { isAuthenticated, user, isLoading: authLoading } = useAuth();

  const [loading, setLoading] = useState(false);
  const [isSystemRole, setIsSystemRole] = useState(false);
  const [formData, setFormData] = useState<CreateRoleRequest & { is_active?: boolean }>({
    name: '',
    description: null,
    is_active: true,
  });

  // Permission management state (for edit mode)
  const [rolePermissions, setRolePermissions] = useState<Permission[]>([]);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [availablePermissions, setAvailablePermissions] = useState<Permission[]>([]);
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

    if (isEditMode) {
      loadRole();
    }
  }, [authLoading, isAuthenticated, user, navigate, id, isEditMode]);

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

      if (isNaN(roleId)) {
        toast.error('Invalid role ID');
        navigate({ to: `/admin/rbac/roles` });
        return;
      }

      let role;
      try {
        // First try to get role by ID
        role = await apiClient.getRole(roleId);
      } catch (getError: any) {
        // If getting by ID fails, fallback to loading from list
        console.warn('getRole by ID failed, trying fallback:', getError);
        const listResponse = await apiClient.listRoles({ page_size: 100 });
        role = listResponse.roles?.find(r => r.id === roleId);
        if (!role) {
          throw new Error(`Role with ID ${roleId} not found`);
        }
      }

      setIsSystemRole(role.is_system);
      setFormData({
        name: role.name,
        description: role.description || null,
        is_active: role.is_active,
      });

      // Load role permissions
      loadRolePermissions(roleId);
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

  const loadRolePermissions = async (roleId: number) => {
    try {
      setLoadingPermissions(true);
      const apiClient = getApiClient();
      const response = await apiClient.getRolePermissions(roleId);
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
    if (!id) return;
    try {
      const apiClient = getApiClient();
      await apiClient.assignPermissionToRole(parseInt(id, 10), permissionId);
      toast.success('Permission assigned successfully');
      setShowAssignModal(false);
      setPermissionSearchTerm('');
      setPermissionCategoryFilter('');
      loadRolePermissions(parseInt(id, 10));
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
    if (!id) return;
    try {
      const apiClient = getApiClient();
      await apiClient.removePermissionFromRole(parseInt(id, 10), permissionId);
      toast.success('Permission removed successfully');
      loadRolePermissions(parseInt(id, 10));
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

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value, type } = e.target;
    if (type === 'checkbox') {
      const checked = (e.target as HTMLInputElement).checked;
      setFormData((prev) => ({ ...prev, [name]: checked }));
    } else {
      // For name field, convert to lowercase and replace spaces with underscores
      if (name === 'name') {
        const sanitizedValue = value.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
        setFormData((prev) => ({
          ...prev,
          [name]: sanitizedValue,
        }));
      } else {
        setFormData((prev) => ({
          ...prev,
          [name]: value === '' ? null : value,
        }));
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!formData.name || formData.name.trim() === '') {
      toast.error('Role name is required');
      return;
    }

    // Validate name format (lowercase alphanumeric with underscores)
    if (!/^[a-z][a-z0-9_]*$/.test(formData.name)) {
      toast.error('Role name must start with a letter and contain only lowercase letters, numbers, and underscores');
      return;
    }

    try {
      setLoading(true);
      const apiClient = getApiClient();

      if (isEditMode && id) {
        const updateData: UpdateRoleRequest = {};
        if (!isSystemRole && formData.name !== undefined) {
          updateData.name = formData.name;
        }
        if (formData.description !== undefined) {
          updateData.description = formData.description;
        }
        if (formData.is_active !== undefined) {
          updateData.is_active = formData.is_active;
        }
        await apiClient.updateRole(parseInt(id, 10), updateData);
        toast.success('Role updated successfully');
      } else {
        const createData: CreateRoleRequest = {
          name: formData.name.trim(),
          description: formData.description || null,
        };
        await apiClient.createRole(createData);
        toast.success('Role created successfully');
      }

      navigate({ to: `/admin/rbac/roles` });
    } catch (error: any) {
      console.error('Failed to save role:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else if (error.response?.status === 409) {
        toast.error(getErrorMessage(error, 'Role name already exists'));
      } else {
        toast.error(getErrorMessage(error, `Failed to ${isEditMode ? 'update' : 'create'} role`));
      }
    } finally {
      setLoading(false);
    }
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
        title={isEditMode ? 'Edit Role' : 'Create Role'}
        description={isEditMode ? 'Update role details' : 'Create a new user role'}
        icon={<Shield className="w-5 h-5" />}
        backTo={`/admin/rbac/roles`}
        backLabel="Back to roles"
      />

      {isSystemRole && (
        <div className="bg-primary-50 border border-primary-200 rounded-lg p-4 flex items-center gap-3">
          <Lock className="h-5 w-5 text-primary-600" />
          <div>
            <p
              className="text-sm font-medium text-primary-900"
              style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
            >
              System Role
            </p>
            <p className="text-xs text-primary-700">
              This is a system role. The name cannot be changed and the role cannot be deleted.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="card p-6">
        <div className="space-y-6">
          {/* Name */}
          <div>
            <label htmlFor="name" className="label">
              Role Name <span className="text-error-500">*</span>
            </label>
            <input
              type="text"
              id="name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              disabled={isSystemRole || loading}
              placeholder="e.g., viewer, analyst, support_agent"
              className="input rounded-lg disabled:bg-gray-100 disabled:cursor-not-allowed"
              required
            />
            <p className="mt-1 text-xs text-gray-500">
              Only lowercase letters, numbers, and underscores. {isSystemRole && 'System role names cannot be changed.'}
            </p>
          </div>

          {/* Description */}
          <div>
            <label htmlFor="description" className="label">
              Description
            </label>
            <textarea
              id="description"
              name="description"
              value={formData.description || ''}
              onChange={handleChange}
              disabled={loading}
              rows={3}
              placeholder="Readable description of the purpose of this role"
              className="input rounded-lg disabled:bg-gray-100 disabled:cursor-not-allowed"
            />
            <p className="mt-1 text-xs text-gray-500">
              Optional description explaining what this role is for
            </p>
          </div>

          {/* Is Active (only for edit mode) */}
          {isEditMode && (
            <div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  name="is_active"
                  checked={formData.is_active || false}
                  onChange={handleChange}
                  disabled={loading}
                  className="w-4 h-4 text-primary-600 border-gray-200 rounded focus:ring-primary-500 disabled:opacity-50"
                />
                <span className="text-sm font-medium text-gray-700">Active</span>
              </label>
              <p className="mt-1 text-xs text-gray-500">
                Inactive roles cannot be assigned to users
              </p>
            </div>
          )}

          {/* Form Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-200">
            <button
              type="button"
              onClick={() => navigate({ to: `/admin/rbac/roles` })}
              disabled={loading}
              className="btn-secondary auth-submit flex items-center gap-2"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              <X className="h-4 w-4" />
              cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary auth-submit"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {isEditMode ? 'save role →' : 'create role →'}
            </button>
          </div>
        </div>
      </form>

      {/* Permissions Management Section (Edit Mode Only) */}
      {isEditMode && (
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
                {rolePermissions.length} permission{rolePermissions.length !== 1 ? 's' : ''} assigned to this role
              </p>
            </div>
            <button
              type="button"
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
                      type="button"
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
                  <p className="page-subtitle mt-1">Select a permission to assign to this role</p>
                </div>
                <button
                  type="button"
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
                              type="button"
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
