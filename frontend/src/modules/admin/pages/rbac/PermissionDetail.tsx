import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { Loader2, Edit, Trash2, AlertTriangle, Shield } from 'lucide-react';
import { getApiClient } from '@/services/apiClientManager';
import type { Permission } from '@/types/api';
import { toast } from 'react-hot-toast';
import { formatRelativeTime } from '@/utils/dateUtils';
import { useAuth } from '@/contexts/AuthContext';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function PermissionDetail() {
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const { isAuthenticated, user, isLoading: authLoading } = useAuth();
  const loaderData = undefined as { permission: Permission } | undefined;

  const [permission, setPermission] = useState<Permission | null>(loaderData?.permission ?? null);
  const [loading, setLoading] = useState(!loaderData);
  const [deletePermissionId, setDeletePermissionId] = useState<number | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletionProgress, setDeletionProgress] = useState(0);
  const deletionCancelledRef = useRef(false);

  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated || user?.role !== 'admin') {
      toast.error('Access denied. Administrator role required.');
      navigate({ to: '/' });
      return;
    }

    if (id) {
      if (!loaderData) {
        loadPermission();
      } else {
        setLoading(false);
      }
    }
  }, [authLoading, isAuthenticated, user, navigate, id, loaderData]);

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
      const permissionData = await apiClient.getPermission(parseInt(id, 10));
      setPermission(permissionData);
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

  const handleDelete = async () => {
    if (!deletePermissionId) return;

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

      await apiClient.deletePermission(deletePermissionId);
      clearInterval(progressInterval);
      setDeletionProgress(100);
      await new Promise((resolve) => setTimeout(resolve, 300));

      toast.success('Permission deleted successfully');
      navigate({ to: `/admin/rbac/permissions` });
    } catch (error: any) {
      console.error('Failed to delete permission:', error);
      setIsDeleting(false);
      setDeletionProgress(0);
      if (error.response?.status === 401 || error.response?.status === 403) {
        window.dispatchEvent(new CustomEvent('auth:unauthorized', { detail: { error } }));
      } else {
        toast.error(error.response?.data?.detail || 'Failed to delete permission');
      }
    }
  };

  const handleCancelDelete = () => {
    deletionCancelledRef.current = true;
    setIsDeleting(false);
    setDeletionProgress(0);
    setDeletePermissionId(null);
  };

  if (authLoading || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    );
  }

  if (!permission) {
    return (
      <div className="p-6">
        <div className="card p-0 p-6 text-center">
          <p className="text-gray-500">Permission not found</p>
          <button
            onClick={() => navigate({ to: `/admin/rbac/permissions` })}
            className="mt-4 text-primary-600 hover:text-primary-700"
          >
            Back to Permissions
          </button>
        </div>
      </div>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={`Permission: ${permission.name}`}
        description="View and manage permission information"
        icon={<Shield className="w-5 h-5" />}
        backTo={`/admin/rbac/permissions`}
        backLabel="Back to permissions"
        actions={
          <>
            <button onClick={() => navigate({ to: `/admin/rbac/permissions/${permission.id}/edit` })} className="btn-secondary flex items-center gap-2">
              <Edit className="h-4 w-4" /> Edit
            </button>
            <button onClick={() => setDeletePermissionId(permission.id)} className="btn-danger">
              <Trash2 className="h-4 w-4" /> Delete
            </button>
          </>
        }
      />

      {/* Permission Information */}
      <div className="card p-0">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Permission Information</h2>
        </div>
        <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="text-sm font-medium text-gray-500">Permission Name</label>
            <p className="mt-1 text-sm text-gray-900 font-mono">{permission.name}</p>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-500">Category</label>
            <p className="mt-1 text-sm text-gray-900">{permission.category || '—'}</p>
          </div>
          <div className="md:col-span-2">
            <label className="text-sm font-medium text-gray-500">Description</label>
            <p className="mt-1 text-sm text-gray-900">{permission.description || '—'}</p>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-500">Status</label>
            <p className="mt-1">
              <span
                className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${permission.is_active
                    ? 'bg-success-50 text-success-700'
                    : 'bg-error-50 text-error-700'
                  }`}
              >
                {permission.is_active ? 'Active' : 'Inactive'}
              </span>
            </p>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-500">Created</label>
            <p className="mt-1 text-sm text-gray-900">
              {formatRelativeTime(permission.created_at)}
            </p>
            <p className="text-xs text-gray-500">
              {new Date(permission.created_at).toLocaleString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
              })}
            </p>
          </div>
          <div>
            <label className="text-sm font-medium text-gray-500">Last Updated</label>
            <p className="mt-1 text-sm text-gray-900">
              {formatRelativeTime(permission.updated_at)}
            </p>
            <p className="text-xs text-gray-500">
              {new Date(permission.updated_at).toLocaleString(undefined, {
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

      {/* Delete Confirmation Modal */}
      {deletePermissionId && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="h-6 w-6 text-error-600" />
              <h3 className="text-lg font-semibold text-gray-900">Delete Permission</h3>
            </div>
            <p className="text-sm text-gray-600 mb-4">
              Are you sure you want to delete permission "{permission.name}"?
            </p>
            <p className="text-xs text-gray-500 mb-4">
              This will also remove all role and user assignments. This action cannot be undone.
            </p>
            {isDeleting && (
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-600">Deleting...</span>
                  <span className="text-xs text-gray-600">{deletionProgress}%</span>
                </div>
                <ProgressBar
                  value={deletionProgress}
                  className="h-2 bg-gray-200"
                  barClassName="bg-primary-600 h-2"
                />
                <button
                  onClick={handleCancelDelete}
                  className="mt-2 text-xs text-error-600 hover:text-error-700"
                >
                  Cancel Deletion
                </button>
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={handleCancelDelete}
                disabled={isDeleting}
                className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={isDeleting}
                className="btn-danger"
              >
                Delete Permission
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
