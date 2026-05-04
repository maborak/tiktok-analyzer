import { useState, useEffect } from 'react';
// Loader data removed during TanStack Router migration
import {
    ShieldAlert, Unlock, User as UserIcon,
    CheckCircle, XCircle, AlertTriangle,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { DataTable } from '@/components/DataTable';
import type { Column, RowAction } from '@/components/DataTable';
import { Modal } from '@/components/ui/Modal';
import { cn } from '@/utils/cn';
import { securityRepository } from '../../services';

interface LockedUser {
    id: number;
    username: string;
    email: string;
    firstName: string | null;
    lastName: string | null;
    isActive: boolean;
    isVerified: boolean;
    failedLoginAttempts: number;
    lockedUntil: string | null;
    lastLogin: string | null;
}

export function AccountLockouts() {
    const loaderData = undefined as any;

    const [users, setUsers] = useState<LockedUser[]>(loaderData?.users || []);
    const [loading, setLoading] = useState(!loaderData);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(20);
    const [total, setTotal] = useState(loaderData?.pagination?.total || 0);
    const [totalPages, setTotalPages] = useState(loaderData?.pagination?.totalPages || 0);
    const [sortBy, setSortBy] = useState('failed_login_attempts');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
    const [searchTerm, setSearchTerm] = useState('');
    const [activeSearchTerm, setActiveSearchTerm] = useState('');
    const [selectedIds, setSelectedIds] = useState<Set<number | string>>(new Set());
    const [unlockAllConfirm, setUnlockAllConfirm] = useState(false);
    const [unlocking, setUnlocking] = useState(false);

    const loadLockouts = async () => {
        try {
            setLoading(true);
            const params: any = {
                page,
                page_size: pageSize,
                sort_by: sortBy,
                sort_order: sortOrder,
            };
            if (activeSearchTerm.trim()) {
                params.search = activeSearchTerm.trim();
            }
            const response = await securityRepository.listLockouts(params);
            if (response.success && response.data) {
                setUsers(response.data.users || []);
                setTotal(response.data.pagination.total || 0);
                setTotalPages(response.data.pagination.totalPages || 0);
            }
        } catch {
            toast.error('Error loading lockouts');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadLockouts();
    }, [page, pageSize, sortBy, sortOrder, activeSearchTerm]);

    const handleUnlock = async (userId: number) => {
        const response = await securityRepository.unlockUser(userId);
        if (response.success) {
            toast.success(response.message || 'User unlocked');
            loadLockouts();
        } else {
            toast.error(response.message || 'Error unlocking user');
        }
    };

    const handleUnlockSelected = async () => {
        const ids = Array.from(selectedIds) as number[];
        let successCount = 0;
        for (const id of ids) {
            const response = await securityRepository.unlockUser(id);
            if (response.success) successCount++;
        }
        toast.success(`Unlocked ${successCount} of ${ids.length} user(s)`);
        setSelectedIds(new Set());
        loadLockouts();
    };

    const handleUnlockAll = async () => {
        setUnlocking(true);
        try {
            const response = await securityRepository.unlockAll();
            if (response.success) {
                toast.success(response.message || 'All users unlocked');
                setUnlockAllConfirm(false);
                setSelectedIds(new Set());
                loadLockouts();
            } else {
                toast.error(response.message || 'Error unlocking all users');
            }
        } finally {
            setUnlocking(false);
        }
    };

    const handleSort = (field: string) => {
        if (field === sortBy) {
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

    const isCurrentlyLocked = (user: LockedUser) => {
        if (!user.lockedUntil) return false;
        return new Date(user.lockedUntil) > new Date();
    };

    const columns: Column<LockedUser>[] = [
        {
            key: 'username',
            label: 'User',
            sortable: true,
            render: (user) => (
                <div className="flex items-center">
                    <div className="flex-shrink-0 h-10 w-10 rounded-full bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
                        <UserIcon className="h-5 w-5 text-primary-600 dark:text-primary-400" />
                    </div>
                    <div className="ml-4">
                        <div className="text-sm font-medium text-gray-900">
                            {user.firstName || user.lastName
                                ? `${user.firstName || ''} ${user.lastName || ''}`.trim()
                                : user.username}
                        </div>
                        <div className="text-sm text-gray-500">{user.email}</div>
                    </div>
                </div>
            ),
        },
        {
            key: 'failed_login_attempts',
            label: 'Failed Attempts',
            sortable: true,
            render: (user) => (
                <span className={cn(
                    'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold',
                    user.failedLoginAttempts >= 10
                        ? 'bg-error-50 text-error-700 dark:bg-error-900/30 dark:text-error-400'
                        : user.failedLoginAttempts >= 5
                            ? 'bg-warning-50 text-warning-700 dark:bg-warning-900/30 dark:text-warning-400'
                            : 'bg-gray-100 text-gray-700'
                )}>
                    {user.failedLoginAttempts}
                </span>
            ),
        },
        {
            key: 'locked_until',
            label: 'Lock Status',
            sortable: true,
            render: (user) => {
                const locked = isCurrentlyLocked(user);
                return locked ? (
                    <div className="flex items-center gap-1.5">
                        <AlertTriangle className="w-4 h-4 text-error-500" />
                        <span className="text-sm text-error-600 dark:text-error-400 font-medium">
                            Until {formatDate(user.lockedUntil!)}
                        </span>
                    </div>
                ) : (
                    <span className="text-sm text-gray-500">
                        Lock expired
                    </span>
                );
            },
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
            key: 'status',
            label: 'Status',
            render: (user) => (
                <div className="flex items-center gap-2">
                    <span className={cn(
                        'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium',
                        user.isActive
                            ? 'bg-success-50 text-success-700 dark:bg-success-900/30 dark:text-success-400'
                            : 'bg-gray-100 text-gray-800'
                    )}>
                        {user.isActive ? (
                            <CheckCircle className="w-3 h-3 mr-1" />
                        ) : (
                            <XCircle className="w-3 h-3 mr-1" />
                        )}
                        {user.isActive ? 'Active' : 'Inactive'}
                    </span>
                </div>
            ),
        },
    ];

    const getRowActions = (user: LockedUser): RowAction[] => [
        {
            icon: Unlock,
            label: 'Unlock',
            onClick: () => handleUnlock(user.id),
        },
    ];

    return (
        <>
            <DataTable<LockedUser>
                data={users}
                loading={loading}
                getRowId={(user) => user.id}
                title="Account Lockouts"
                subtitle="Users with failed login attempts — unlock to reset their rate limiting"
                icon={ShieldAlert}
                headerAction={
                    total > 0 ? (
                        <button
                            onClick={() => setUnlockAllConfirm(true)}
                            className="btn-primary w-full sm:w-auto"
                        >
                            <Unlock className="w-4 h-4 mr-2" />
                            Unlock All ({total})
                        </button>
                    ) : undefined
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
                searchPlaceholder="Search by email, username, or name..."
                sortBy={sortBy}
                sortOrder={sortOrder}
                onSort={handleSort}
                selectable={true}
                selectedIds={selectedIds}
                onSelectionChange={setSelectedIds}
                rowActions={getRowActions}
                bulkActions={[
                    {
                        icon: Unlock,
                        label: 'Unlock Selected',
                        onClick: handleUnlockSelected,
                    },
                ]}
                emptyIcon={ShieldAlert}
                emptyTitle="No locked accounts"
                emptyDescription="All user accounts are in good standing — no failed login attempts detected."
            />

            {unlockAllConfirm && (
                <Modal
                    isOpen={unlockAllConfirm}
                    title="Unlock All Users"
                    onClose={() => setUnlockAllConfirm(false)}
                    footer={
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={() => setUnlockAllConfirm(false)}
                                className="btn-secondary"
                                disabled={unlocking}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleUnlockAll}
                                className="btn-primary"
                                disabled={unlocking}
                            >
                                {unlocking ? 'Unlocking...' : `Unlock All (${total})`}
                            </button>
                        </div>
                    }
                >
                    <p className="text-sm text-gray-600">
                        This will reset failed login attempts and remove lockouts for
                        <strong> {total} user(s)</strong>. They will be able to log in immediately.
                    </p>
                </Modal>
            )}
        </>
    );
}
