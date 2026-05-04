import { useState, useEffect } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { Loader2, Edit, Trash2, CheckCircle, XCircle, Shield, User as UserIcon, Clock, Plus, Search, X } from 'lucide-react';
import { adminUserRepository } from '../../services';
import type {
    AdminUser,
    Permission,
    PermissionListResponse,
} from '../../types';
import { toast } from 'react-hot-toast';
import { useAuth } from '@/contexts/AuthContext';
import { formatRelativeTime } from '@/utils/dateUtils';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

interface UserDetailData {
    user: AdminUser;
    // Using explicit types to match what we expect from the API
    roles: any;
    permissions: PermissionListResponse;
    userPermissions: { permissions: Permission[] };
    rolePermissions: { permissions: Permission[] } | null;
}

export function UserDetail() {
    const { id } = useParams({ strict: false }) as { id: string };
    const navigate = useNavigate();
    const loaderData = undefined as UserDetailData | undefined;
    const { isAuthenticated, user: currentUser, isLoading: authLoading } = useAuth();

    const [loading, setLoading] = useState(!loaderData);
    const [user, setUser] = useState<AdminUser | null>(loaderData?.user || null);
    const [userPermissions, setUserPermissions] = useState<Permission[]>(
        loaderData?.userPermissions?.permissions || []
    );
    const [rolePermissions, setRolePermissions] = useState<Permission[]>(
        loaderData?.rolePermissions?.permissions || []
    );

    // For permission assignment modal
    const [showAssignModal, setShowAssignModal] = useState(false);
    const [availablePermissions, setAvailablePermissions] = useState<Permission[]>(
        loaderData?.permissions?.permissions || []
    );
    const [permissionSearchTerm, setPermissionSearchTerm] = useState('');

    // Delete user state
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleting, setDeleting] = useState(false);

    useEffect(() => {
        if (loaderData) {
            setUser(loaderData.user);
            setUserPermissions(loaderData.userPermissions?.permissions || []);
            setRolePermissions(loaderData.rolePermissions?.permissions || []);
            setAvailablePermissions(loaderData.permissions?.permissions || []);
            setLoading(false);
        }
    }, [loaderData]);

    useEffect(() => {
        if (authLoading) return;

        if (!isAuthenticated || currentUser?.role !== 'admin') {
            toast.error('Access denied. Administrator role required.');
            navigate({ to: '/' });
            return;
        }

        if (!loaderData && id) {
            loadUser();
        }
    }, [authLoading, isAuthenticated, currentUser, navigate, id, loaderData]);

    const loadUser = async () => {
        if (!id) return;
        try {
            setLoading(true);
            const res = await adminUserRepository.get(Number(id));
            if (res.success && res.data) {
                setUser(res.data.user);
                setUserPermissions(res.data.userPermissions.permissions);
                setRolePermissions(res.data.rolePermissions?.permissions || []);
                // Note: roles and permissions lists are also returned but we focus on user data here
                // Ideally we should update availablePermissions too if they changed
                setAvailablePermissions(res.data.permissions.permissions);
            }
        } catch (error: any) {
            console.error('Failed to load user:', error);
            toast.error('Failed to load user details');
            navigate({ to: `/admin/users` });
        } finally {
            setLoading(false);
        }
    };

    const refreshPermissions = async () => {
        if (!id) return;
        try {
            // Just re-fetch the user details to get updated permissions
            const res = await adminUserRepository.get(Number(id));
            if (res.success && res.data) {
                setUserPermissions(res.data.userPermissions.permissions);
            }
        } catch (error) {
            console.error('Failed to refresh permissions:', error);
        }
    };

    const handleDelete = async () => {
        if (!user) return;
        try {
            setDeleting(true);
            await adminUserRepository.delete(user.id);
            toast.success('User deleted successfully');
            navigate({ to: `/admin/users` });
        } catch (error: any) {
            console.error('Failed to delete user:', error);
            if (error.response?.status === 403) {
                toast.error('You cannot delete your own account');
            } else {
                toast.error('Failed to delete user');
            }
        } finally {
            setDeleting(false);
            setShowDeleteModal(false);
        }
    };

    const handleRemovePermission = async (permissionId: number) => {
        if (!user) return;
        try {
            await adminUserRepository.removePermission(user.id, permissionId);
            toast.success('Permission removed successfully');
            await refreshPermissions();
        } catch (error: any) {
            console.error('Failed to remove permission:', error);
            toast.error('Failed to remove permission');
        }
    };

    const handleAssignPermission = async (permissionId: number) => {
        if (!user) return;
        try {
            await adminUserRepository.assignPermission(user.id, permissionId);
            toast.success('Permission assigned successfully');
            setShowAssignModal(false);
            await refreshPermissions();
        } catch (error: any) {
            console.error('Failed to assign permission:', error);
            toast.error('Failed to assign permission');
        }
    };

    // Filter available permissions (excluding already assigned ones)
    const getFilteredPermissions = () => {
        const assignedIds = new Set([
            ...userPermissions.map(p => p.id),
            ...rolePermissions.map(p => p.id)
        ]);

        return availablePermissions
            .filter(p => !assignedIds.has(p.id))
            .filter(p =>
                p.name.toLowerCase().includes(permissionSearchTerm.toLowerCase()) ||
                (p.description && p.description.toLowerCase().includes(permissionSearchTerm.toLowerCase()))
            );
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-96">
                <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
            </div>
        );
    }

    if (!user) {
        return (
            <div className="text-center py-12">
                <p className="text-gray-500">User not found</p>
                <button
                    onClick={() => navigate({ to: `/admin/users` })}
                    className="mt-4 btn-secondary auth-submit"
                    style={{ fontFamily: 'var(--font-mono-display)' }}
                >
                    back to users →
                </button>
            </div>
        );
    }

    return (
        <PageShell>
            <PageHeader
                title={user.username}
                description={user.email}
                icon={<UserIcon className="w-5 h-5" />}
                backTo={`/admin/users`}
                backLabel="Back to users"
                badge={user.id === currentUser?.id ? (
                    <span className="auth-mono-label text-primary-600 bg-primary-50 px-2 py-0.5 rounded-full">you</span>
                ) : undefined}
                actions={
                    <>
                        <button
                            onClick={() => navigate({ to: `/admin/users/${user.id}/edit` })}
                            className="btn-secondary auth-submit flex items-center gap-2"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            <Edit className="h-4 w-4" /> edit profile →
                        </button>
                        {user.id !== currentUser?.id && (
                            <button
                                onClick={() => setShowDeleteModal(true)}
                                className="btn-danger auth-submit flex items-center gap-2"
                                style={{ fontFamily: 'var(--font-mono-display)' }}
                            >
                                <Trash2 className="h-4 w-4" /> delete user →
                            </button>
                        )}
                    </>
                }
            />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* User Profile Card */}
                <div className="lg:col-span-1 space-y-6">
                    <div className="card p-0 overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50 flex items-center gap-2">
                            <UserIcon className="h-5 w-5 text-gray-500" />
                            <h2
                                className="text-lg font-semibold text-gray-900"
                                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                            >
                                Profile
                            </h2>
                        </div>
                        <div className="p-6 space-y-4">
                            <div>
                                <span className="auth-mono-label block mb-1">Full Name</span>
                                <span className="text-gray-900">
                                    {user.fullName || 'Not set'}
                                </span>
                            </div>

                            <div>
                                <span className="auth-mono-label block mb-1">Role</span>
                                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${user.role === 'admin' ? 'bg-error-50 text-error-700' : 'bg-primary-50 text-primary-700'
                                    }`}>
                                    <Shield className="w-3 h-3 mr-1" />
                                    {user.role}
                                </span>
                            </div>

                            <div>
                                <span className="auth-mono-label block mb-1">Status</span>
                                <div className="flex gap-2">
                                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${user.isActive ? 'bg-success-50 text-success-700' : 'bg-gray-100 text-gray-800'
                                        }`}>
                                        {user.isActive ? <CheckCircle className="w-3 h-3 mr-1" /> : <XCircle className="w-3 h-3 mr-1" />}
                                        {user.isActive ? 'Active' : 'Inactive'}
                                    </span>
                                    {user.isVerified && (
                                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary-50 text-primary-700">
                                            <CheckCircle className="w-3 h-3 mr-1" />
                                            Verified
                                        </span>
                                    )}
                                </div>
                            </div>

                            <div className="pt-4 border-t border-gray-200 space-y-3">
                                <div className="flex items-center text-sm text-gray-500">
                                    <Clock className="w-4 h-4 mr-2" />
                                    Created {formatRelativeTime(user.createdAt)}
                                </div>
                                {user.lastLogin && (
                                    <div className="flex items-center text-sm text-gray-500">
                                        <LogIn className="w-4 h-4 mr-2" />
                                        Last login {formatRelativeTime(user.lastLogin)}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="card p-0 overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50 flex items-center gap-2">
                            <Shield className="h-5 w-5 text-gray-500" />
                            <h2
                                className="text-lg font-semibold text-gray-900"
                                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                            >
                                Security
                            </h2>
                        </div>
                        <div className="p-6 space-y-4">
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <span className="auth-mono-label block mb-1">Failed Attempts</span>
                                    <span className="text-gray-900 font-mono">{user.failedLoginAttempts || 0}</span>
                                </div>
                                <div>
                                    <span className="auth-mono-label block mb-1">Locked Until</span>
                                    <span className="text-gray-900 text-sm">
                                        {user.lockedUntil ? formatRelativeTime(user.lockedUntil) : 'Not locked'}
                                    </span>
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-200">
                                <div>
                                    <span className="auth-mono-label block mb-1">API Limit</span>
                                    <span className="text-gray-900 font-mono">{user.apiRateLimit}/hr</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Permissions Column */}
                <div className="lg:col-span-2 space-y-6">
                    {/* Direct Permissions */}
                    <div className="card p-0">
                        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
                            <h2
                                className="text-lg font-semibold text-gray-900"
                                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                            >
                                Direct Permissions
                            </h2>
                            <button
                                onClick={() => setShowAssignModal(true)}
                                className="btn-secondary auth-submit text-xs flex items-center gap-1"
                                style={{ fontFamily: 'var(--font-mono-display)' }}
                            >
                                <Plus className="w-3 h-3" />
                                assign permission →
                            </button>
                        </div>
                        <div className="p-6">
                            {userPermissions.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {userPermissions.map(permission => (
                                        <span
                                            key={permission.id}
                                            className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-primary-100 text-primary-800 border border-primary-200"
                                        >
                                            {permission.name}
                                            <button
                                                onClick={() => handleRemovePermission(permission.id)}
                                                className="ml-2 hover:text-primary-900 focus:outline-none"
                                                title="Remove permission"
                                            >
                                                <X className="w-3 h-3" />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-gray-500 italic">No direct permissions assigned.</p>
                            )}
                        </div>
                    </div>

                    {/* Inherited Permissions */}
                    <div className="card p-0 opacity-80">
                        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50">
                            <h2
                                className="text-lg font-semibold text-gray-900"
                                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                            >
                                Inherited from {user.role}
                            </h2>
                        </div>
                        <div className="p-6">
                            {rolePermissions.length > 0 ? (
                                <div className="flex flex-wrap gap-2">
                                    {rolePermissions.map(permission => (
                                        <span
                                            key={permission.id}
                                            className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-800 border border-gray-200"
                                        >
                                            <Shield className="w-3 h-3 mr-1 text-gray-500" />
                                            {permission.name}
                                        </span>
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-gray-500 italic">No inherited permissions.</p>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Delete Modal */}
            {showDeleteModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
                    <div className="bg-white rounded-lg max-w-md w-full p-6 space-y-4">
                        <h3
                            className="text-lg font-semibold text-gray-900"
                            style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                        >
                            Delete User
                        </h3>
                        <p className="text-gray-600">
                            Are you sure you want to delete <span className="font-semibold">{user.username}</span>?
                            This action cannot be undone.
                        </p>
                        <div className="flex justify-end gap-3 pt-4">
                            <button
                                onClick={() => setShowDeleteModal(false)}
                                className="btn-secondary auth-submit"
                                style={{ fontFamily: 'var(--font-mono-display)' }}
                                disabled={deleting}
                            >
                                cancel
                            </button>
                            <button
                                onClick={handleDelete}
                                className="btn-danger auth-submit flex items-center gap-2"
                                style={{ fontFamily: 'var(--font-mono-display)' }}
                                disabled={deleting}
                            >
                                {deleting && <Loader2 className="w-4 h-4 animate-spin" />}
                                delete user →
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Assign Permission Modal */}
            {showAssignModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
                    <div className="bg-white rounded-lg max-w-lg w-full p-6 space-y-4 max-h-[80vh] flex flex-col">
                        <div className="flex justify-between items-center">
                            <h3
                                className="text-lg font-semibold text-gray-900"
                                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                            >
                                Assign Permission
                            </h3>
                            <button onClick={() => setShowAssignModal(false)} className="text-gray-500 hover:text-gray-700">
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                            <input
                                type="text"
                                placeholder="Search permissions..."
                                value={permissionSearchTerm}
                                onChange={(e) => setPermissionSearchTerm(e.target.value)}
                                className="input pl-9 pr-3"
                            />
                        </div>

                        <div className="flex-1 overflow-y-auto min-h-[200px] border border-gray-200 rounded-md p-2">
                            <div className="space-y-1">
                                {getFilteredPermissions().map(permission => (
                                    <button
                                        key={permission.id}
                                        onClick={() => handleAssignPermission(permission.id)}
                                        className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-gray-50 flex items-center justify-between group"
                                    >
                                        <div>
                                            <span className="font-medium text-gray-900 block">{permission.name}</span>
                                            {permission.description && (
                                                <span className="text-gray-500 text-xs">{permission.description}</span>
                                            )}
                                        </div>
                                        <Plus className="w-4 h-4 text-gray-400 group-hover:text-primary-600" />
                                    </button>
                                ))}
                                {getFilteredPermissions().length === 0 && (
                                    <p className="text-center text-gray-500 py-4 text-sm">No matching permissions found.</p>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </PageShell>
    );
}
function LogIn(props: any) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
            <polyline points="10 17 15 12 10 7" />
            <line x1="15" x2="3" y1="12" y2="12" />
        </svg>
    )
}
