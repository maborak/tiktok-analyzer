import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import {
    Users,
    Plus,
    Eye,
    Pencil,
    Trash2,
    CheckCircle,
    XCircle,
    Shield,
    User as UserIcon,
    LogIn,
} from 'lucide-react';
import { adminUserRepository, rbacRepository } from '../../services';
import type { AdminUser, Role, AdminUserListResponse } from '../../types';
import { cn } from '@/utils/cn';
import { toast } from 'react-hot-toast';
import { useAuth } from '@/contexts/AuthContext';

import { DataTable } from '@/components/DataTable';
import type { Column, FilterConfig, RowAction } from '@/components/DataTable';

export function UsersList() {
    const loaderData = undefined as AdminUserListResponse | undefined;
    
    const [users, setUsers] = useState<AdminUser[]>(loaderData?.users || []);
    const [loading, setLoading] = useState(!loaderData);
    const [total, setTotal] = useState(loaderData?.pagination?.total || 0);
    const [totalPages, setTotalPages] = useState(loaderData?.pagination?.totalPages || 0);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);

    // Search state: separate input from active fetching term
    const [searchTerm, setSearchTerm] = useState('');
    const [activeSearchTerm, setActiveSearchTerm] = useState('');

    const [roleFilter, setRoleFilter] = useState<string>('');
    const [statusFilter, setStatusFilter] = useState<string>('');
    const [roles, setRoles] = useState<Role[]>([]);
    const [sortBy, setSortBy] = useState<string>('created_at');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

    // Selection state
    const [selectedIds, setSelectedIds] = useState<Set<number | string>>(new Set());

    // Deletion state
    const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [deleteSelectedConfirm, setDeleteSelectedConfirm] = useState(false);
    const [isBulkDeleting, setIsBulkDeleting] = useState(false);
    const [bulkDeletionProgress, setBulkDeletionProgress] = useState(0);
    const deletionCancelledRef = useRef(false);

    // Ref for tracking previous params to prevent redundant calls
    const prevParamsRef = useRef({
        page: 1,
        pageSize: 10,
        roleFilter: '',
        statusFilter: '',
        sortBy: 'created_at',
        sortOrder: 'desc',
        activeSearchTerm: '',
        initialized: false
    });

    // Track if roles are loaded
    const rolesLoadedRef = useRef(false);

    // Impersonation state
    const [impersonateConfirmId, setImpersonateConfirmId] = useState<number | null>(null);
    const [impersonating, setImpersonating] = useState(false);

    const navigate = useNavigate();
    const { isAuthenticated, user: currentUser, isLoading: authLoading, impersonate } = useAuth();

    // Sync state with loaderData when it changes (after revalidation)
    useEffect(() => {
        if (loaderData) {
            setUsers(loaderData.users || []);
            setTotal(loaderData.pagination?.total || 0);
            setTotalPages(loaderData.pagination?.totalPages || 0);
            setLoading(false);

            // Should potentially update initialized ref here if needed, 
            // but loader data usually means we are good.
        }
    }, [loaderData]);

    useEffect(() => {
        if (authLoading) return;

        if (!isAuthenticated || currentUser?.role !== 'admin') {
            toast.error('Access denied. Administrator role required.');
            navigate({ to: '/' });
            return;
        }

        // Always load roles, but only once
        if (!rolesLoadedRef.current) {
            loadRoles();
            rolesLoadedRef.current = true;
        }

        // Current params
        const currentParams = {
            page,
            pageSize,
            roleFilter,
            statusFilter,
            sortBy,
            sortOrder,
            activeSearchTerm
        };

        // Check if params actually changed
        const prev = prevParamsRef.current;
        const paramsChanged =
            prev.page !== page ||
            prev.pageSize !== pageSize ||
            prev.roleFilter !== roleFilter ||
            prev.statusFilter !== statusFilter ||
            prev.sortBy !== sortBy ||
            prev.sortOrder !== sortOrder ||
            prev.activeSearchTerm !== activeSearchTerm;

        // Update ref for next render
        prevParamsRef.current = { ...currentParams, initialized: true };

        // Logic:
        // 1. If loaderData exists and metrics haven't changed, skip (used initial data).
        // 2. If params changed, fetch.
        // 3. If no loaderData (e.g. client nav without loader), fetch.

        // On very first run (initialized=false), if we have loaderData, we skip.
        // This relies on the fact that loaderData matches the initial default/empty state.
        if (!prev.initialized && loaderData) {
            setLoading(false);
            return;
        }

        // If nothing changed and we are initialized (and plausibly have data), skip.
        if (!paramsChanged && prev.initialized) {
            return;
        }

        // Do the fetch
        loadUsers();
    }, [authLoading, isAuthenticated, currentUser, page, pageSize, roleFilter, statusFilter, sortBy, sortOrder, activeSearchTerm]);

    // Listen for unauthorized events
    useEffect(() => {
        const handleUnauthorized = () => {
            toast.error('Your session has expired. Please log in again.');
            setSelectedIds(new Set());
            setDeleteConfirmId(null);
            setDeleteSelectedConfirm(false);
            setImpersonateConfirmId(null);
            navigate({ to: '/login' });
        };

        window.addEventListener('auth:unauthorized', handleUnauthorized as EventListener);
        return () => {
            window.removeEventListener('auth:unauthorized', handleUnauthorized as EventListener);
        };
    }, [navigate]);

    const loadRoles = async () => {
        try {
            const response = await rbacRepository.listRoles({ page_size: 100, is_active: true });
            if (response.success && response.data) {
                setRoles(response.data.roles || []);
            }
        } catch (error) {
            console.error('Failed to load roles:', error);
        }
    };

    const loadUsers = async () => {
        try {
            setLoading(true);
            const params: any = {
                page,
                page_size: pageSize,
                sort_by: sortBy,
                sort_order: sortOrder,
            };

            if (roleFilter) {
                params.role_id = parseInt(roleFilter, 10);
            }

            if (statusFilter === 'true') {
                params.is_active = true;
            } else if (statusFilter === 'false') {
                params.is_active = false;
            }

            if (activeSearchTerm.trim()) {
                params.search = activeSearchTerm.trim();
            }

            const response = await adminUserRepository.list(params);
            if (response.success && response.data) {
                setUsers(response.data.users || []);
                setTotal(response.data.pagination.total || 0);
                setTotalPages(response.data.pagination.totalPages || 0);
            }
        } catch (error: any) {
            console.error('Failed to load users:', error);
            toast.error('Failed to load users');
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async (userId: number) => {
        try {
            setDeleting(true);
            await adminUserRepository.delete(userId);
            toast.success('User deleted successfully');
            setDeleteConfirmId(null);

            // Remove deleted user from selection if selected
            setSelectedIds(prev => {
                const newSet = new Set(prev);
                newSet.delete(userId);
                return newSet;
            });

            // Reload users with current filters/search to refresh the table
            await loadUsers();
            // Also revalidate loader data for consistency
            // Data already refreshed by loadUsers() above
        } catch (error: any) {
            console.error('Failed to delete user:', error);
            if (error.response?.status === 403) {
                toast.error('You cannot delete your own account');
            } else {
                const errorMessage = error.response?.data?.detail || 'Failed to delete user';
                toast.error(typeof errorMessage === 'string' ? errorMessage : 'Failed to delete user');
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

            const idsToDelete = Array.from(selectedIds) as number[];
            let deleted = 0;

            for (const id of idsToDelete) {
                if (deletionCancelledRef.current) {
                    toast('Deletion cancelled');
                    break;
                }

                try {
                    await adminUserRepository.delete(id);
                    deleted++;
                    setBulkDeletionProgress(Math.round((deleted / idsToDelete.length) * 100));
                } catch (error: any) {
                    console.error(`Failed to delete user ${id}:`, error);
                    if (error.response?.status === 403) {
                        toast.error('You cannot delete your own account');
                    }
                }
            }

            if (!deletionCancelledRef.current) {
                toast.success(`Deleted ${deleted} of ${idsToDelete.length} users`);
            }

            setSelectedIds(new Set());
            setDeleteSelectedConfirm(false);

            // Reload users with current filters/search to refresh the table
            await loadUsers();
            // Also revalidate loader data for consistency
            // Data already refreshed by loadUsers() above
        } catch (error) {
            console.error('Failed to delete users:', error);
            toast.error('Failed to delete users');
        } finally {
            setIsBulkDeleting(false);
            setBulkDeletionProgress(0);
        }
    };

    const handleImpersonate = async (userId: number) => {
        try {
            setImpersonating(true);
            const res = await adminUserRepository.impersonate(userId);
            const data = res.data;

            if (data && data.access_token) {
                toast.success(`Switching session to user...`);
                // Wait briefly for toast
                setTimeout(() => {
                    // Perform the impersonation (updates context and localStorage)
                    // Map flat ImpersonationResponse to LoginResponse structure
                    const loginResponse: any = {
                        user: data.user,
                        tokens: {
                            access_token: data.access_token,
                            refresh_token: data.refresh_token,
                            token_type: data.token_type,
                            expires_in: data.expires_in
                        }
                    };

                    impersonate(loginResponse);
                    // Redirect to dashboard as the target user
                    navigate({ to: '/' });
                    // Force a reload to ensure all states are clean
                    window.location.reload();
                }, 800);
            } else {
                toast.error('Failed to impersonate user');
            }
        } catch (error: any) {
            console.error('Failed to impersonate user:', error);
            if (error.response?.status === 400) {
                toast.error(error.response.data.message || 'Cannot impersonate this user');
            } else {
                toast.error('Failed to impersonate user');
            }
        } finally {
            setImpersonating(false);
            setImpersonateConfirmId(null);
        }
    };

    const handleCancelBulkDelete = () => {
        deletionCancelledRef.current = true;
    };

    const handleSort = (field: string) => {
        if (sortBy === field) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(field);
            setSortOrder('desc');
        }
        setPage(1);
    };

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleString();
    };

    const getRoleColor = (role: string) => {
        switch (role?.toLowerCase()) {
            case 'admin':
                return 'bg-error-50 text-error-700';
            case 'moderator':
                return 'bg-primary-50 text-primary-700';
            default:
                return 'bg-gray-100 text-gray-800';
        }
    };

    const getRoleIcon = (role: string) => {
        switch (role?.toLowerCase()) {
            case 'admin':
            case 'moderator':
                return <Shield className="w-3 h-3 mr-1" />;
            default:
                return <UserIcon className="w-3 h-3 mr-1" />;
        }
    };

    // Define columns
    const columns: Column<AdminUser>[] = [
        {
            key: 'username',
            label: 'User',
            sortable: true,
            render: (user) => (
                <div className="flex items-center">
                    <div className="flex-shrink-0 h-10 w-10 rounded-full bg-primary-50 flex items-center justify-center">
                        <UserIcon className="h-5 w-5 text-primary-600" />
                    </div>
                    <div className="ml-4">
                        <div className="text-sm font-medium text-gray-900">
                            {user.firstName || user.lastName
                                ? `${user.firstName || ''} ${user.lastName || ''}`.trim()
                                : user.username}
                            {user.id === currentUser?.id && (
                                <span className="auth-mono-label ml-2 text-primary-600">(you)</span>
                            )}
                        </div>
                        <div className="text-sm text-gray-500">{user.email}</div>
                    </div>
                </div>
            ),
        },
        {
            key: 'role',
            label: 'Role',
            render: (user) => (
                <span className={cn(
                    'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium',
                    getRoleColor(user.role)
                )}>
                    {getRoleIcon(user.role)}
                    {user.role}
                </span>
            ),
        },
        {
            key: 'status',
            label: 'Status',
            render: (user) => (
                <div className="flex items-center gap-2">
                    <span className={cn(
                        'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium',
                        user.isActive
                            ? 'bg-success-50 text-success-700'
                            : 'bg-gray-100 text-gray-800'
                    )}>
                        {user.isActive ? (
                            <CheckCircle className="w-3 h-3 mr-1" />
                        ) : (
                            <XCircle className="w-3 h-3 mr-1" />
                        )}
                        {user.isActive ? 'Active' : 'Inactive'}
                    </span>
                    {user.isVerified && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-primary-50 text-primary-700">
                            Verified
                        </span>
                    )}
                </div>
            ),
        },
        {
            key: 'lastLogin',
            label: 'Last Login',
            sortable: true,
            render: (user) => (
                <span className="text-sm text-gray-500">
                    {user.lastLogin ? formatDate(user.lastLogin) : 'Never'}
                </span>
            ),
        },
        {
            key: 'createdAt',
            label: 'Created',
            sortable: true,
            render: (user) => (
                <span className="text-sm text-gray-500">
                    {formatDate(user.createdAt)}
                </span>
            ),
        },
    ];

    // Define filters
    const filters: FilterConfig[] = [
        {
            key: 'role',
            value: roleFilter,
            onChange: (value) => {
                setRoleFilter(value);
                setPage(1);
            },
            placeholder: 'All Roles',
            options: roles.map((role) => ({
                value: role.id.toString(),
                label: role.name,
            })),
        },
        {
            key: 'status',
            value: statusFilter,
            onChange: (value) => {
                setStatusFilter(value);
                setPage(1);
            },
            placeholder: 'All Statuses',
            options: [
                { value: 'true', label: 'Active' },
                { value: 'false', label: 'Inactive' },
            ],
        },
        {
            key: 'sortBy',
            value: sortBy,
            onChange: (value) => {
                setSortBy(value);
                setPage(1);
            },
            options: [
                { value: 'created_at', label: 'Sort by Created' },
                { value: 'updated_at', label: 'Sort by Updated' },
                { value: 'username', label: 'Sort by Username' },
                { value: 'email', label: 'Sort by Email' },
                { value: 'last_login', label: 'Sort by Last Login' },
            ],
        },
    ];

    // Define row actions
    const getRowActions = (user: AdminUser): RowAction[] => [
        {
            icon: Eye,
            label: 'View',
            href: `/admin/users/${user.id}`,
        },
        {
            icon: Pencil,
            label: 'Edit',
            href: `/admin/users/${user.id}/edit`,
        },
        {
            icon: LogIn,
            label: 'Login As',
            onClick: () => setImpersonateConfirmId(user.id),
            disabled: user.id === currentUser?.id,
            title: user.id === currentUser?.id ? 'You cannot impersonate yourself' : 'Login as this user',
        },
        {
            icon: Trash2,
            label: user.id === currentUser?.id ? "You cannot delete your own account" : 'Delete',
            onClick: () => setDeleteConfirmId(user.id),
            disabled: user.id === currentUser?.id,
            variant: 'danger',
        },
    ];

    // Get delete modal content
    const getDeleteModalContent = () => {
        const userToDelete = users.find((u) => u.id === deleteConfirmId);
        if (!userToDelete) return null;

        return (
            <div className="bg-gray-50 rounded-lg p-4 mb-4 border border-gray-200">
                <div className="flex items-center gap-3">
                    <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary-50 flex items-center justify-center">
                        <UserIcon className="h-5 w-5 text-primary-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">
                            {userToDelete.username}
                        </p>
                        <p className="text-sm text-gray-500 truncate">
                            {userToDelete.email}
                        </p>
                    </div>
                </div>
            </div>
        );
    };

    const getImpersonateModalContent = () => {
        const userToImpersonate = users.find((u) => u.id === impersonateConfirmId);
        if (!userToImpersonate) return null;

        return (
            <div className="bg-warning-50 rounded-lg p-4 mb-4 border border-warning-200">
                <div className="flex items-start gap-3">
                    <div className="flex-shrink-0">
                        <Shield className="h-5 w-5 text-warning-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <h4 className="text-sm font-medium text-warning-700 mb-1" style={{ fontFamily: 'var(--font-mono-display)' }}>Warning: Admin Action</h4>
                        <p className="text-sm text-warning-700 mb-3">
                            You are about to log in as <strong>{userToImpersonate.username}</strong>.
                            You will have full access to their account as if you were that person.
                        </p>
                        <p className="text-xs text-warning-600">
                            To return to your admin account, you will need to log out and log in again.
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
        <>
            <DataTable<AdminUser>
                data={users}
                loading={loading}
                getRowId={(user) => user.id}
                title="Users"
                subtitle="Manage user accounts, roles, and access"
                icon={Users}
                headerAction={
                    <Link
                        to={`/admin/users/new`}
                        className="btn-primary auth-submit w-full sm:w-auto"
                        style={{ fontFamily: 'var(--font-mono-display)' }}
                    >
                        <Plus className="w-4 h-4 mr-2" />
                        add user →
                    </Link>
                }
                columns={columns}
                page={page}
                pageSize={pageSize}
                total={total}
                totalPages={totalPages}
                onPageChange={setPage}
                onPageSizeChange={setPageSize}
                searchEnabled={true}
                searchTerm={searchTerm}
                onSearchChange={setSearchTerm}
                onSearchSubmit={(term) => {
                    setActiveSearchTerm(term);
                    setPage(1);
                }}
                searchPlaceholder="Search by username, email, or name..."
                sortBy={sortBy}
                sortOrder={sortOrder}
                onSort={handleSort}
                filters={filters}
                selectable={true}
                selectedIds={selectedIds}
                onSelectionChange={setSelectedIds}
                isRowSelectable={(user) => user.id !== currentUser?.id}
                rowActions={getRowActions}
                bulkActions={[
                    {
                        icon: Trash2,
                        label: 'Delete Selected',
                        onClick: () => setDeleteSelectedConfirm(true),
                        variant: 'danger',
                    },
                ]}
                deleteModal={deleteConfirmId !== null ? {
                    show: true,
                    title: 'Delete User',
                    message: 'Are you sure you want to delete this user? This action cannot be undone.',
                    content: getDeleteModalContent(),
                    onConfirm: () => handleDelete(deleteConfirmId),
                    onCancel: () => setDeleteConfirmId(null),
                    loading: deleting,
                } : deleteSelectedConfirm ? {
                    show: true,
                    title: `Delete ${selectedIds.size} Users`,
                    message: `Are you sure you want to delete ${selectedIds.size} users? This action cannot be undone.`,
                    onConfirm: handleDeleteSelected,
                    onCancel: () => setDeleteSelectedConfirm(false),
                    showProgress: isBulkDeleting,
                    progress: bulkDeletionProgress,
                    onCancelProgress: handleCancelBulkDelete,
                } : impersonateConfirmId !== null ? {
                    show: true,
                    title: 'Login As User',
                    message: 'Are you sure you want to impersonate this user?',
                    content: getImpersonateModalContent(),
                    confirmLabel: 'Login As User',
                    confirmVariant: 'warning',
                    onConfirm: () => handleImpersonate(impersonateConfirmId),
                    onCancel: () => setImpersonateConfirmId(null),
                    loading: impersonating,
                } : undefined}
                emptyIcon={Users}
                emptyTitle="No users found"
                emptyDescription={
                    searchTerm || roleFilter || statusFilter
                        ? 'Try adjusting your filters'
                        : 'Add your first user to get started'
                }
                emptyAction={
                    !searchTerm && !roleFilter && !statusFilter ? (
                        <Link
                            to={`/admin/users/new`}
                            className="btn-primary auth-submit mt-4"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            <Plus className="w-4 h-4 mr-2" />
                            add user →
                        </Link>
                    ) : undefined
                }
            />
        </>
    );
}
