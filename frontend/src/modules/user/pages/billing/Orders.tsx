import { useState, useEffect } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { userBillingApi } from '../../services/billing';
import type { UserTransaction, CreditPackage } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Loader2, RefreshCw, Clock, CheckCircle, XCircle, FileText, ChevronLeft, ChevronRight, CreditCard, Wallet, Bitcoin, Building } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import { format } from 'date-fns';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function Orders() {
    const navigate = useNavigate();
    const [orders, setOrders] = useState<UserTransaction[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(5);
    const [totalOrders, setTotalOrders] = useState(0);
    const [packageMap, setPackageMap] = useState<Record<number, CreditPackage>>({});

    useEffect(() => {
        // Fetch packages once on mount to build the resolution map
        const initializeMap = async () => {
            try {
                const res = await userBillingApi.getPackages();
                if (res.success && res.data) {
                    const map: Record<number, CreditPackage> = {};
                    res.data.forEach(pkg => {
                        map[pkg.id] = pkg;
                    });
                    setPackageMap(map);
                }
            } catch (e) {
                console.error('Failed to load package names', e);
            }
        };
        initializeMap();
    }, []);

    useEffect(() => {
        fetchOrders();
    }, [currentPage, pageSize]);

    const fetchOrders = async () => {
        setIsLoading(true);
        try {
            const response = await userBillingApi.getOrders(currentPage, pageSize);
            if (response.success && response.data) {
                // Safely handle both standard 'items' and documented 'transactions' properties
                const arr = response.data.items || response.data.transactions || [];
                setOrders(arr);
                setTotalOrders(response.data.total || 0);
            } else {
                toast.error(response.message || 'Failed to load orders');
            }
        } catch (error) {
            console.error('Error fetching orders:', error);
            toast.error('Failed to load orders');
        } finally {
            setIsLoading(false);
        }
    };

    const getStatusConfig = (status: string) => {
        switch (status.toLowerCase()) {
            case 'completed':
                return { icon: CheckCircle, color: 'text-success-600', bg: 'bg-success-50', border: 'border-success-200', text: 'Completed' };
            case 'pending':
                return { icon: Clock, color: 'text-warning-600', bg: 'bg-warning-50', border: 'border-warning-200', text: 'Pending Verification' };
            case 'awaiting_payment':
                return { icon: Clock, color: 'text-primary-600', bg: 'bg-primary-50', border: 'border-primary-200', text: 'Awaiting Payment' };
            case 'failed':
            case 'rejected':
                return { icon: XCircle, color: 'text-error-600', bg: 'bg-error-50', border: 'border-error-200', text: 'Failed / Rejected' };
            default:
                return { icon: Clock, color: 'text-gray-600', bg: 'bg-gray-50', border: 'border-gray-200', text: status };
        }
    };

    const getProviderIcon = (provider: string) => {
        switch (provider) {
            case 'STRIPE':
                return <CreditCard className="w-4 h-4 text-primary-500" />;
            case 'PAYPAL':
                return <Wallet className="w-4 h-4 text-primary-500" />;
            case 'BITCOIN':
                return <Bitcoin className="w-4 h-4 text-warning-500" />;
            case 'BANK_TRANSFER':
                return <Building className="w-4 h-4 text-gray-500" />;
            default:
                return <CreditCard className="w-4 h-4 text-gray-400" />;
        }
    };

    const totalPages = Math.ceil(totalOrders / pageSize);

    const formatDate = (dateString: string) => {
        try {
            const date = new Date(dateString);
            if (isNaN(date.getTime())) return 'Invalid Date';
            return format(date, 'MMM d, yyyy h:mm a');
        } catch {
            return dateString;
        }
    };

    return (
        <PageShell>
            <PageHeader
                title="Purchase & Order History"
                description="View your past transactions and track pending manual payments."
                icon={<FileText className="w-5 h-5" />}
                actions={
                    <Button onClick={fetchOrders} variant="secondary" className="px-3" title="Refresh">
                        <RefreshCw className={clsx("w-4 h-4", isLoading && "animate-spin")} />
                    </Button>
                }
            />

            <div className="card p-0 overflow-hidden">
                {isLoading ? (
                    <div className="p-12 text-center text-gray-500 flex flex-col items-center">
                        <Loader2 className="w-8 h-8 animate-spin text-gray-400 mb-4" />
                        <p>Loading your orders...</p>
                    </div>
                ) : orders.length === 0 ? (
                    <div className="p-12 text-center flex flex-col items-center">
                        <FileText className="w-12 h-12 text-gray-300 mb-4" />
                        <h3
                            className="text-lg font-medium text-gray-900"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            No orders found
                        </h3>
                        <p className="text-gray-500 mt-2">You haven't made any purchases or payment requests yet.</p>
                    </div>
                ) : (
                    <div>
                        {/* Desktop: dense table. Hidden below md where the
                            column count would force horizontal scroll. */}
                        <table className="hidden md:table min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">
                                        Date
                                    </th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">
                                        Amount
                                    </th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">
                                        Package
                                    </th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">
                                        Method
                                    </th>
                                    <th scope="col" className="auth-mono-label px-6 py-3 text-left">
                                        Status
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {orders.map((order) => {
                                    const statusConfig = getStatusConfig(order.status);
                                    const StatusIcon = statusConfig.icon;

                                    return (
                                        <tr key={order.id} className="hover:bg-gray-50 transition-colors">
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                                {formatDate(order.created_at)}
                                                <div className="text-xs text-gray-500 mt-1 font-mono tracking-tight">ID: {order.id}</div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-success-600">
                                                ${order.amount.toFixed(2)} {order.currency}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                                {order.package_name || (order.package_id && packageMap[order.package_id]?.name) || 'Custom Package'}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                                <div className="flex items-center">
                                                    {getProviderIcon(order.provider)}
                                                    <span className="ml-2 capitalize">{order.provider.replace('_', ' ').toLowerCase()}</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div className="flex flex-col items-start gap-2">
                                                    <span className={clsx(
                                                        'inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border',
                                                        statusConfig.bg,
                                                        statusConfig.color,
                                                        statusConfig.border
                                                    )}>
                                                        <StatusIcon className="w-3.5 h-3.5 mr-1" />
                                                        {statusConfig.text}
                                                    </span>
                                                    {['completed', 'paid'].includes(order.status.toLowerCase()) && order.invoice?.id && (
                                                        <Button
                                                            variant="secondary"
                                                            size="sm"
                                                            className="flex items-center text-xs py-1 h-7"
                                                            onClick={() => navigate({ to: routes.account.billing.invoiceDetail(order.invoice?.id ?? '') })}
                                                        >
                                                            <FileText className="w-3.5 h-3.5 mr-1" />
                                                            View Invoice
                                                        </Button>
                                                    )}
                                                    {order.status === 'AWAITING_PAYMENT' && ['STRIPE', 'PAYPAL'].includes(order.provider) && (
                                                        <Button
                                                            variant="primary"
                                                            size="sm"
                                                            className="btn-success text-xs py-1 h-7"
                                                            onClick={() => navigate({ to: routes.account.billing.checkout,
                                                                state: {
                                                                    resumeOrderId: order.id,
                                                                    provider: order.provider.toLowerCase(),
                                                                    package: {
                                                                        id: order.package_id || '',
                                                                        name: order.package_name || (order.package_id ? packageMap[order.package_id]?.name : 'Package') || 'Package',
                                                                        amount: typeof order.amount === 'string' ? parseFloat(order.amount) : order.amount,
                                                                        currency: order.currency,
                                                                        credits: order.package_id ? packageMap[order.package_id]?.credits : 0,
                                                                        description: `Resume payment for ${order.package_name || 'Credit Package'}`
                                                                    }
                                                                } as any
                                                            })}
                                                        >
                                                            Resume Payment
                                                        </Button>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>

                        {/* Mobile: card list — one row per order, no
                            horizontal scroll. Only renders below md. */}
                        <ul className="md:hidden flex flex-col gap-2 p-3">
                            {orders.map((order) => {
                                const statusConfig = getStatusConfig(order.status);
                                const StatusIcon = statusConfig.icon;
                                const packageLabel = order.package_name || (order.package_id && packageMap[order.package_id]?.name) || 'Custom Package';

                                return (
                                    <li
                                        key={order.id}
                                        className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 hover:bg-gray-50 transition-colors"
                                    >
                                        <div className="flex items-baseline justify-between gap-2 mb-1">
                                            <div className="min-w-0 flex-1 font-mono text-[11px] text-gray-500 truncate" title={`ID: ${order.id}`}>
                                                ID: {order.id}
                                            </div>
                                            <div className="shrink-0 font-medium text-success-600 tabular-nums text-sm">
                                                ${order.amount.toFixed(2)} {order.currency}
                                            </div>
                                        </div>
                                        <div className="flex items-center justify-between gap-2 mb-1.5">
                                            <div className="min-w-0 text-xs text-gray-500 flex items-center gap-2 flex-wrap">
                                                <span>{formatDate(order.created_at)}</span>
                                                <span className="inline-flex items-center gap-1 capitalize">
                                                    {getProviderIcon(order.provider)}
                                                    {order.provider.replace('_', ' ').toLowerCase()}
                                                </span>
                                            </div>
                                            <span className={clsx(
                                                'shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border',
                                                statusConfig.bg,
                                                statusConfig.color,
                                                statusConfig.border
                                            )}>
                                                <StatusIcon className="w-3 h-3 mr-1" />
                                                {statusConfig.text}
                                            </span>
                                        </div>
                                        <div className="text-xs text-gray-700 truncate mb-1">
                                            {packageLabel}
                                        </div>
                                        {((['completed', 'paid'].includes(order.status.toLowerCase()) && order.invoice?.id) ||
                                          (order.status === 'AWAITING_PAYMENT' && ['STRIPE', 'PAYPAL'].includes(order.provider))) && (
                                            <div className="flex flex-wrap gap-2 mt-1.5">
                                                {['completed', 'paid'].includes(order.status.toLowerCase()) && order.invoice?.id && (
                                                    <Button
                                                        variant="secondary"
                                                        size="sm"
                                                        className="flex items-center text-xs py-1 h-7"
                                                        onClick={() => navigate({ to: routes.account.billing.invoiceDetail(order.invoice?.id ?? '') })}
                                                    >
                                                        <FileText className="w-3.5 h-3.5 mr-1" />
                                                        View Invoice
                                                    </Button>
                                                )}
                                                {order.status === 'AWAITING_PAYMENT' && ['STRIPE', 'PAYPAL'].includes(order.provider) && (
                                                    <Button
                                                        variant="primary"
                                                        size="sm"
                                                        className="btn-success text-xs py-1 h-7"
                                                        onClick={() => navigate({ to: routes.account.billing.checkout,
                                                            state: {
                                                                resumeOrderId: order.id,
                                                                provider: order.provider.toLowerCase(),
                                                                package: {
                                                                    id: order.package_id || '',
                                                                    name: order.package_name || (order.package_id ? packageMap[order.package_id]?.name : 'Package') || 'Package',
                                                                    amount: typeof order.amount === 'string' ? parseFloat(order.amount) : order.amount,
                                                                    currency: order.currency,
                                                                    credits: order.package_id ? packageMap[order.package_id]?.credits : 0,
                                                                    description: `Resume payment for ${order.package_name || 'Credit Package'}`
                                                                }
                                                            } as any
                                                        })}
                                                    >
                                                        Resume Payment
                                                    </Button>
                                                )}
                                            </div>
                                        )}
                                    </li>
                                );
                            })}
                        </ul>

                        {/* Pagination */}
                        {totalOrders > 0 && (
                            <div className="px-6 py-4 border-t border-gray-200 flex flex-col sm:flex-row items-center justify-between bg-gray-50 gap-4">
                                <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 w-full sm:w-auto text-sm text-gray-500">
                                    <div>
                                        Showing <span className="font-medium">{(currentPage - 1) * pageSize + 1}</span> to{' '}
                                        <span className="font-medium">{Math.min(currentPage * pageSize, totalOrders)}</span> of{' '}
                                        <span className="font-medium">{totalOrders}</span> orders
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <label htmlFor="pageSize">Per page:</label>
                                        <select
                                            id="pageSize"
                                            value={pageSize}
                                            onChange={(e) => {
                                                setPageSize(Number(e.target.value));
                                                setCurrentPage(1);
                                            }}
                                            className="input rounded-md py-1 pl-2 pr-8"
                                        >
                                            <option value={5}>5</option>
                                            <option value={10}>10</option>
                                            <option value={20}>20</option>
                                            <option value={50}>50</option>
                                        </select>
                                    </div>
                                </div>
                                <div className="flex items-center space-x-2 w-full sm:w-auto justify-end">
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                        disabled={currentPage === 1}
                                    >
                                        <ChevronLeft className="w-4 h-4 mr-1" />
                                        Previous
                                    </Button>
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                        disabled={currentPage === totalPages || totalPages === 0}
                                    >
                                        Next
                                        <ChevronRight className="w-4 h-4 ml-1" />
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </PageShell>
    );
}
