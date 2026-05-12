import { useState, useEffect } from 'react';
import { CreditCard, CheckCircle, XCircle, RefreshCw, User as UserIcon } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { adminBillingApi } from '../../services/billing';
import type { AdminUser } from '../../types';
import { adminUserRepository } from '../../services/index';
import type { AdminPendingPayment } from '@/types/api';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function PendingPayments() {
    const [payments, setPayments] = useState<AdminPendingPayment[]>([]);
    const [loading, setLoading] = useState(true);
    const [processingId, setProcessingId] = useState<string | null>(null);
    const [page, setPage] = useState(1);
    const [totalItems, setTotalItems] = useState(0);
    const pageSize = 20;

    // Mass actions
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

    // User Modal
    const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
    const [isUserModalOpen, setIsUserModalOpen] = useState(false);
    const [loadingUser, setLoadingUser] = useState(false);

    const fetchPayments = async () => {
        setLoading(true);
        setSelectedIds(new Set());
        try {
            const response = await adminBillingApi.getPendingPayments({ page, page_size: pageSize });
            if (response.success && response.data) {
                setPayments(response.data.transactions);
                setTotalItems(response.data.total);
            } else {
                toast.error(response.message || 'Failed to load pending payments');
            }
        } catch {
            toast.error('An error occurred loading pending payments');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchPayments();
    }, [page]);

    const handleVerify = async (transactionId: string, action: 'approve' | 'reject') => {
        if (!window.confirm(`Are you sure you want to ${action} this payment?`)) return;

        setProcessingId(transactionId);
        try {
            const notes = prompt(`Optional: Enter notes for ${action}ing this payment:`);
            const response = await adminBillingApi.verifyPendingPayment(transactionId, {
                action,
                notes: notes || undefined
            });

            if (response.success) {
                toast.success(response.message || `Payment ${action}d successfully`);
                await fetchPayments();
            } else {
                toast.error(response.message || `Failed to ${action} payment`);
            }
        } catch {
            toast.error(`An error occurred trying to ${action} payment`);
        } finally {
            setProcessingId(null);
        }
    };

    const handleMassVerify = async (action: 'approve' | 'reject') => {
        if (selectedIds.size === 0) return;
        if (!window.confirm(`Are you sure you want to ${action} ${selectedIds.size} payments?`)) return;

        toast.loading(`Processing mass ${action}...`, { id: 'mass-verify' });

        let successCount = 0;
        let failCount = 0;

        for (const transactionId of Array.from(selectedIds)) {
            try {
                const response = await adminBillingApi.verifyPendingPayment(transactionId, {
                    action,
                    notes: `Mass ${action}d by administrator.`
                });
                if (response.success) {
                    successCount++;
                } else {
                    failCount++;
                }
            } catch {
                failCount++;
            }
        }

        toast.dismiss('mass-verify');

        if (successCount > 0) {
            toast.success(`Successfully ${action}d ${successCount} payments.`);
        }
        if (failCount > 0) {
            toast.error(`Failed to process ${failCount} payments.`);
        }

        await fetchPayments();
    };

    const toggleSelection = (id: string) => {
        const newSelection = new Set(selectedIds);
        if (newSelection.has(id)) {
            newSelection.delete(id);
        } else {
            newSelection.add(id);
        }
        setSelectedIds(newSelection);
    };

    const toggleAll = () => {
        if (selectedIds.size === payments.length) {
            setSelectedIds(new Set());
        } else {
            setSelectedIds(new Set(payments.map(p => p.id)));
        }
    };

    const viewUserDetails = async (userId: number) => {
        setLoadingUser(true);
        setIsUserModalOpen(true);
        try {
            const response = await adminUserRepository.get(userId);

            if (response.success && response.data?.user) {
                setSelectedUser(response.data.user);
            } else {
                toast.error("User details not found");
                setIsUserModalOpen(false);
            }
        } catch {
            toast.error("Error fetching user details");
            setIsUserModalOpen(false);
        } finally {
            setLoadingUser(false);
        }
    };

    return (
        <PageShell>
            <PageHeader
                title="Pending Manual Payments"
                description="Review and verify manual payments (Bitcoin, Bank Transfer) from users to issue credits"
                icon={<CreditCard className="h-5 w-5" />}
                actions={
                    <div className="flex gap-2">
                        {selectedIds.size > 0 && (
                            <>
                                <button
                                    onClick={() => handleMassVerify('approve')}
                                    className="btn-success"
                                >
                                    <CheckCircle className="h-4 w-4" />
                                    Approve Selected ({selectedIds.size})
                                </button>
                                <button
                                    onClick={() => handleMassVerify('reject')}
                                    className="btn-danger"
                                >
                                    <XCircle className="h-4 w-4" />
                                    Reject Selected ({selectedIds.size})
                                </button>
                            </>
                        )}
                        <button
                            onClick={() => fetchPayments()}
                            disabled={loading}
                            className="btn-secondary"
                        >
                            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                            Refresh
                        </button>
                    </div>
                }
            />

            {/* List */}
            <div className="card p-0 overflow-hidden">
                {loading && payments.length === 0 ? (
                    <div className="p-8 flex justify-center">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                    </div>
                ) : payments.length === 0 ? (
                    <div className="p-12 text-center">
                        <CheckCircle className="mx-auto h-12 w-12 text-success-400" />
                        <h3 className="mt-2 text-sm font-medium text-gray-900">All caught up</h3>
                        <p className="page-subtitle mt-1">There are no pending manual payments that require verification.</p>
                    </div>
                ) : (
                    <>
                        <table className="hidden md:table min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-200 rounded"
                                            checked={selectedIds.size === payments.length && payments.length > 0}
                                            onChange={toggleAll}
                                        />
                                    </th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">User</th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">Provider</th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">Amount</th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">Invoice</th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">Package</th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">Date</th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {payments.map((payment) => (
                                    <tr key={payment.id} className="hover:bg-gray-50">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <input
                                                type="checkbox"
                                                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-200 rounded"
                                                checked={selectedIds.has(payment.id)}
                                                onChange={() => toggleSelection(payment.id)}
                                            />
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex flex-col">
                                                <span className="text-sm font-medium text-gray-900">{payment.user_email}</span>
                                                <div className="flex gap-2 items-center">
                                                    <span className="text-xs text-gray-500">ID: {payment.user_id}</span>
                                                    <button onClick={() => viewUserDetails(payment.user_id)} className="text-xs text-primary-600 hover:text-primary-800 underline flex items-center gap-1"><UserIcon className="h-3 w-3" /> Details</button>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${payment.provider === 'BITCOIN' ? 'bg-warning-100 text-warning-700' : 'bg-primary-50 text-primary-700'
                                                }`}>
                                                {payment.provider}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-medium">
                                            {payment.currency} {payment.amount.toFixed(2)}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            {payment.invoice_number ? (
                                                <div className="flex flex-col">
                                                    <span className="text-sm font-medium text-gray-900">{payment.invoice_number}</span>
                                                    <span className="text-xs text-gray-500 uppercase">{payment.invoice_status}</span>
                                                </div>
                                            ) : (
                                                <span className="text-xs text-gray-400 italic">No Invoice</span>
                                            )}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                            {payment.package_name || 'Credit Package'}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                            {new Date(payment.created_at).toLocaleDateString()} {new Date(payment.created_at).toLocaleTimeString()}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <div className="flex items-center justify-end gap-2">
                                                <button
                                                    onClick={() => handleVerify(payment.id, 'approve')}
                                                    disabled={processingId === payment.id}
                                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-success-50 text-success-700 hover:bg-success-50 font-medium transition-colors disabled:opacity-50"
                                                >
                                                    {processingId === payment.id ? (
                                                        <RefreshCw className="h-4 w-4 animate-spin" />
                                                    ) : (
                                                        <CheckCircle className="h-4 w-4" />
                                                    )}
                                                    Approve
                                                </button>
                                                <button
                                                    onClick={() => handleVerify(payment.id, 'reject')}
                                                    disabled={processingId === payment.id}
                                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-error-50 text-error-700 hover:bg-error-50 font-medium transition-colors disabled:opacity-50"
                                                >
                                                    <XCircle className="h-4 w-4" />
                                                    Reject
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        {/* Mobile: card list — one card per pending payment. */}
                        <ul className="md:hidden flex flex-col gap-2 p-2">
                            {payments.map((payment) => (
                                <li
                                    key={payment.id}
                                    className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 hover:bg-gray-50 transition-colors"
                                >
                                    <div className="flex items-start justify-between gap-2 mb-2">
                                        <div className="min-w-0 flex-1 flex items-start gap-2">
                                            <input
                                                type="checkbox"
                                                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-200 rounded mt-0.5 shrink-0"
                                                checked={selectedIds.has(payment.id)}
                                                onChange={() => toggleSelection(payment.id)}
                                            />
                                            <div className="min-w-0 flex-1">
                                                <div className="text-sm font-medium text-gray-900 truncate">{payment.user_email}</div>
                                                <div className="flex gap-2 items-center mt-0.5">
                                                    <span className="text-[11px] text-gray-500">ID: {payment.user_id}</span>
                                                    <button onClick={() => viewUserDetails(payment.user_id)} className="text-[11px] text-primary-600 hover:text-primary-800 dark:text-primary-300 underline flex items-center gap-1">
                                                        <UserIcon className="h-3 w-3" /> Details
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                        <span className={`shrink-0 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${payment.provider === 'BITCOIN' ? 'bg-warning-100 text-warning-700 dark:bg-warning-500/15 dark:text-warning-300' : 'bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-300'
                                            }`}>
                                            {payment.provider}
                                        </span>
                                    </div>
                                    <div className="grid grid-cols-3 gap-2 mb-2">
                                        <div>
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Amount</div>
                                            <div className="text-sm text-gray-900 font-medium tabular-nums">
                                                {payment.currency} {payment.amount.toFixed(2)}
                                            </div>
                                        </div>
                                        <div>
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Package</div>
                                            <div className="text-xs text-gray-500 truncate">
                                                {payment.package_name || 'Credit Package'}
                                            </div>
                                        </div>
                                        <div>
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Date</div>
                                            <div className="text-xs text-gray-500 tabular-nums">
                                                {new Date(payment.created_at).toLocaleDateString()}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="mb-2">
                                        <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Invoice</div>
                                        {payment.invoice_number ? (
                                            <div className="flex items-center gap-2">
                                                <span className="text-xs font-medium text-gray-900">{payment.invoice_number}</span>
                                                <span className="text-[10px] text-gray-500 uppercase">{payment.invoice_status}</span>
                                            </div>
                                        ) : (
                                            <span className="text-xs text-gray-400 italic">No Invoice</span>
                                        )}
                                    </div>
                                    <div className="flex items-center justify-end gap-2">
                                        <button
                                            onClick={() => handleVerify(payment.id, 'approve')}
                                            disabled={processingId === payment.id}
                                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-success-50 text-success-700 dark:bg-success-500/10 dark:text-success-300 hover:bg-success-50 font-medium transition-colors disabled:opacity-50 text-xs"
                                        >
                                            {processingId === payment.id ? (
                                                <RefreshCw className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <CheckCircle className="h-4 w-4" />
                                            )}
                                            Approve
                                        </button>
                                        <button
                                            onClick={() => handleVerify(payment.id, 'reject')}
                                            disabled={processingId === payment.id}
                                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-error-50 text-error-700 dark:bg-error-500/10 dark:text-error-300 hover:bg-error-50 font-medium transition-colors disabled:opacity-50 text-xs"
                                        >
                                            <XCircle className="h-4 w-4" />
                                            Reject
                                        </button>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </>
                )}

                {/* Pagination */}
                {totalItems > pageSize && (
                    <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
                        <div className="flex-1 flex justify-between sm:hidden">
                            <button
                                onClick={() => setPage(p => Math.max(1, p - 1))}
                                disabled={page === 1}
                                className="relative inline-flex items-center px-4 py-2 border border-gray-200 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                            >
                                Previous
                            </button>
                            <button
                                onClick={() => setPage(p => p + 1)}
                                disabled={page * pageSize >= totalItems}
                                className="ml-3 relative inline-flex items-center px-4 py-2 border border-gray-200 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                            >
                                Next
                            </button>
                        </div>
                        <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                            <div>
                                <p className="text-sm text-gray-700">
                                    Showing <span className="font-medium">{(page - 1) * pageSize + 1}</span> to{' '}
                                    <span className="font-medium">{Math.min(page * pageSize, totalItems)}</span> of{' '}
                                    <span className="font-medium">{totalItems}</span> results
                                </p>
                            </div>
                            <div>
                                <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                                    <button
                                        onClick={() => setPage(p => Math.max(1, p - 1))}
                                        disabled={page === 1}
                                        className="btn-secondary rounded-l-md rounded-r-none px-2 py-2"
                                    >
                                        Previous
                                    </button>
                                    <button
                                        onClick={() => setPage(p => p + 1)}
                                        disabled={page * pageSize >= totalItems}
                                        className="btn-secondary rounded-r-md rounded-l-none px-2 py-2"
                                    >
                                        Next
                                    </button>
                                </nav>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* User Details Modal */}
            {isUserModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
                    <div className="bg-white rounded-lg shadow-xl w-full max-w-lg overflow-hidden flex flex-col">
                        <div className="p-6 border-b border-gray-200 flex justify-between items-center">
                            <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                                <UserIcon className="h-5 w-5 text-primary-600" />
                                User Details
                            </h3>
                            <button
                                onClick={() => setIsUserModalOpen(false)}
                                className="text-gray-400 hover:text-gray-600 transition-colors"
                            >
                                <XCircle className="h-5 w-5" />
                            </button>
                        </div>

                        <div className="p-6 overflow-y-auto max-h-[70vh]">
                            {loadingUser ? (
                                <div className="flex justify-center p-8">
                                    <RefreshCw className="h-8 w-8 text-primary-600 animate-spin" />
                                </div>
                            ) : selectedUser ? (
                                <div className="space-y-4">
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <p className="text-sm text-gray-500">ID</p>
                                            <p className="font-medium">{selectedUser.id}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-gray-500">Username</p>
                                            <p className="font-medium">{selectedUser.username}</p>
                                        </div>
                                        <div className="col-span-2">
                                            <p className="text-sm text-gray-500">Email</p>
                                            <p className="font-medium">{selectedUser.email}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-gray-500">Full Name</p>
                                            <p className="font-medium">{(selectedUser.firstName || '') + ' ' + (selectedUser.lastName || '')}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-gray-500">Role</p>
                                            <p className="font-medium">{selectedUser.role}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-gray-500">Status</p>
                                            <p className="font-medium">
                                                {selectedUser.isActive ? (
                                                    <span className="text-success-600 font-medium">Active</span>
                                                ) : (
                                                    <span className="text-error-600 font-medium">Inactive</span>
                                                )}
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-gray-500">Verified</p>
                                            <p className="font-medium">{selectedUser.isVerified ? 'Yes' : 'No'}</p>
                                        </div>
                                        <div className="col-span-2">
                                            <p className="text-sm text-gray-500">Registered</p>
                                            <p className="font-medium">{new Date(selectedUser.createdAt).toLocaleString()}</p>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <p className="text-center text-gray-500">User not found.</p>
                            )}
                        </div>
                        <div className="p-4 border-t border-gray-200 bg-gray-50 flex justify-end">
                            <button
                                onClick={() => setIsUserModalOpen(false)}
                                className="px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50"
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </PageShell>
    );
}
