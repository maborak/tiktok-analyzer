import { useState, useEffect } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { Loader2, Save, X, Shield } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import type { CreatePermissionRequest, UpdatePermissionRequest } from '@/types/api';
import { toast } from 'react-hot-toast';
import { useAuth } from '@/contexts/AuthContext';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function PermissionForm() {
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const isEditMode = !!id;
  const { isAuthenticated, user, isLoading: authLoading } = useAuth();

  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState<CreatePermissionRequest & { is_active?: boolean }>({
    name: '',
    description: null,
    category: null,
    is_active: true,
  });

  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated || user?.role !== 'admin') {
      toast.error('Access denied. Administrator role required.');
      navigate({ to: '/' });
      return;
    }

    if (isEditMode) {
      loadPermission();
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

  const loadPermission = async () => {
    if (!id) return;
    try {
      setLoading(true);
      const apiClient = getApiClient();
      const permission = await apiClient.getPermission(parseInt(id, 10));
      setFormData({
        name: permission.name,
        description: permission.description || null,
        category: permission.category || null,
        is_active: permission.is_active,
      });
    } catch (error: any) {
      console.error('Failed to load permission:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else if (error.response?.status === 404) {
        toast.error('Permission not found');
        navigate({ to: `/admin/rbac/permissions` });
      } else {
        toast.error(error.response?.data?.detail || 'Failed to load permission');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value, type } = e.target;
    if (type === 'checkbox') {
      const checked = (e.target as HTMLInputElement).checked;
      setFormData((prev) => ({ ...prev, [name]: checked }));
    } else {
      setFormData((prev) => ({
        ...prev,
        [name]: value === '' ? null : value,
      }));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!formData.name || formData.name.trim() === '') {
      toast.error('Permission name is required');
      return;
    }

    // Validate name format (should follow "category:action" pattern)
    if (!/^[a-z0-9_]+:[a-z0-9_]+$/i.test(formData.name)) {
      toast.error('Permission name must follow the "category:action" format (e.g., "admin:read")');
      return;
    }

    try {
      setLoading(true);
      const apiClient = getApiClient();

      if (isEditMode && id) {
        const updateData: UpdatePermissionRequest = {};
        if (formData.description !== undefined) {
          updateData.description = formData.description;
        }
        if (formData.category !== undefined) {
          updateData.category = formData.category;
        }
        if (formData.is_active !== undefined) {
          updateData.is_active = formData.is_active;
        }
        await apiClient.updatePermission(parseInt(id, 10), updateData);
        toast.success('Permission updated successfully');
      } else {
        const createData: CreatePermissionRequest = {
          name: formData.name.trim(),
          description: formData.description || null,
          category: formData.category || null,
        };
        await apiClient.createPermission(createData);
        toast.success('Permission created successfully');
      }

      navigate({ to: `/admin/rbac/permissions` });
    } catch (error: any) {
      console.error('Failed to save permission:', error);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else if (error.response?.status === 409) {
        toast.error(error.response?.data?.detail || 'Permission name already exists');
      } else {
        toast.error(error.response?.data?.detail || `Failed to ${isEditMode ? 'update' : 'create'} permission`);
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
        title={isEditMode ? 'Edit Permission' : 'Create Permission'}
        description={isEditMode ? 'Update permission details' : 'Create a new permission'}
        icon={<Shield className="w-5 h-5" />}
        backTo={`/admin/rbac/permissions`}
        backLabel="Back to permissions"
      />

      <form onSubmit={handleSubmit} className="card p-6">
        <div className="space-y-6">
          {/* Name */}
          <div>
            <label htmlFor="name" className="label">
              Permission Name <span className="text-error-500">*</span>
            </label>
            <input
              type="text"
              id="name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              disabled={isEditMode || loading}
              placeholder="e.g., admin:read, products:write"
              className="input rounded-lg disabled:bg-gray-100 disabled:cursor-not-allowed"
              required
            />
            <p className="mt-1 text-xs text-gray-500">
              Format: category:action (e.g., "admin:read", "products:write"). {isEditMode && 'Name cannot be changed after creation.'}
            </p>
          </div>

          {/* Category */}
          <div>
            <label htmlFor="category" className="label">
              Category
            </label>
            <input
              type="text"
              id="category"
              name="category"
              value={formData.category || ''}
              onChange={handleChange}
              disabled={loading}
              placeholder="e.g., admin, products, monitoring"
              className="input rounded-lg disabled:bg-gray-100 disabled:cursor-not-allowed"
            />
            <p className="mt-1 text-xs text-gray-500">
              Optional category to group permissions (max 50 characters)
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
              placeholder="Readable description of what this permission allows"
              className="input rounded-lg disabled:bg-gray-100 disabled:cursor-not-allowed"
            />
            <p className="mt-1 text-xs text-gray-500">
              Optional description explaining what this permission allows
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
                Inactive permissions are not returned in role/user permission queries
              </p>
            </div>
          )}

          {/* Form Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-200">
            <button
              type="button"
              onClick={() => navigate({ to: `/admin/rbac/permissions` })}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <X className="h-4 w-4" />
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="btn-primary"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {isEditMode ? 'Update Permission' : 'Create Permission'}
            </button>
          </div>
        </div>
      </form>
    </PageShell>
  );
}
