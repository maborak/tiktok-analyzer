import { useState, useEffect } from 'react';
import { userBillingApi } from '../../services/billing';
import type { CreditLedgerEntry } from '@/types/api';
import {
    TrendingUp,
    TrendingDown,
    Gift,
    ShoppingCart,
    ChevronLeft,
    ChevronRight,
    Coins,
    UserCheck,
} from 'lucide-react';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { format } from 'date-fns';
import toast from 'react-hot-toast';

const SOURCE_META: Record<CreditLedgerEntry['source'], {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    colorClass: string;
}> = {
    registration: {
        label: 'Registration bonus',
        icon: Gift,
        colorClass: 'text-primary-600 bg-primary-50',
    },
    purchase: {
        label: 'Purchase',
        icon: ShoppingCart,
        colorClass: 'text-primary-600 bg-primary-50',
    },
    admin_grant: {
        label: 'Granted by admin',
        icon: UserCheck,
        colorClass: 'text-primary-600 bg-primary-50',
    },
};

function AmountBadge({ amount }: { amount: number }) {
    const isPositive = amount > 0;
    return (
        <span
            className={`inline-flex items-center gap-1 font-semibold text-sm ${
                isPositive ? 'text-success-600' : 'text-error-600'
            }`}
        >
            {isPositive ? (
                <TrendingUp className="w-4 h-4" />
            ) : (
                <TrendingDown className="w-4 h-4" />
            )}
            {isPositive ? `+${amount}` : amount}
        </span>
    );
}

const PAGE_SIZE = 5;

export function CreditHistory() {
    const [entries, setEntries] = useState<CreditLedgerEntry[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const [totalPages, setTotalPages] = useState(1);

    useEffect(() => {
        load();
    }, [page]);

    const load = async () => {
        setIsLoading(true);
        try {
            const res = await userBillingApi.getCreditHistory(page, PAGE_SIZE);
            if (res.success && res.data) {
                setEntries(res.data.items);
                setTotal(res.data.pagination.total);
                setTotalPages(res.data.pagination.total_pages);
            } else {
                toast.error(res.message || 'Failed to load credit history');
            }
        } catch {
            toast.error('Failed to load credit history');
        } finally {
            setIsLoading(false);
        }
    };

    const formatDate = (iso: string) => {
        try {
            return format(new Date(iso), 'MMM d, yyyy · HH:mm');
        } catch {
            return iso;
        }
    };

    return (
        <PageShell>
            <PageHeader
                title="Credit History"
                description="Complete record of credit additions and deductions in your account."
                icon={<Coins className="w-5 h-5" />}
            />

            <div className="card p-0 overflow-hidden">
                {/* Header */}
                <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-700">
                        {isLoading ? 'Loading...' : `${total} records`}
                    </span>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={page <= 1 || isLoading}
                            className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            <ChevronLeft className="w-4 h-4 text-gray-600" />
                        </button>
                        <span className="text-xs text-gray-500">
                            Page {page} of {totalPages}
                        </span>
                        <button
                            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                            disabled={page >= totalPages || isLoading}
                            className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            <ChevronRight className="w-4 h-4 text-gray-600" />
                        </button>
                    </div>
                </div>

                {/* Table */}
                {isLoading ? (
                    <div className="divide-y divide-gray-50">
                        {Array.from({ length: PAGE_SIZE }).map((_, i) => (
                            <div key={i} className="flex items-center gap-4 px-6 py-4 animate-pulse">
                                <div className="w-8 h-8 rounded-full bg-gray-200 flex-shrink-0" />
                                <div className="flex-1 space-y-2">
                                    <div className="h-3 bg-gray-200 rounded w-1/3" />
                                    <div className="h-3 bg-gray-100 rounded w-1/4" />
                                </div>
                                <div className="h-4 bg-gray-200 rounded w-12" />
                            </div>
                        ))}
                    </div>
                ) : entries.length === 0 ? (
                    <div className="py-16 text-center text-gray-400 text-sm">
                        No credit history yet.
                    </div>
                ) : (
                    <div className="divide-y divide-gray-50">
                        {entries.map(entry => {
                            const meta = SOURCE_META[entry.source] ?? {
                                label: entry.source,
                                icon: Coins,
                                colorClass: 'text-gray-600 bg-gray-100',
                            };
                            const Icon = meta.icon;
                            return (
                                <div key={entry.id} className="flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors">
                                    {/* Icon */}
                                    <div className={`p-2 rounded-full flex-shrink-0 ${meta.colorClass}`}>
                                        <Icon className="w-4 h-4" />
                                    </div>

                                    {/* Description */}
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm font-medium text-gray-900">{meta.label}</p>
                                        <p className="text-xs text-gray-400 mt-0.5">{formatDate(entry.created_at)}</p>
                                    </div>

                                    {/* Amount */}
                                    <div className="flex-shrink-0 text-right">
                                        <AmountBadge amount={entry.amount} />
                                        <p className="text-xs text-gray-400 mt-0.5">
                                            exp. {formatDate(entry.expires_at).split(' · ')[0]}
                                        </p>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                {/* Footer pagination */}
                {!isLoading && totalPages > 1 && (
                    <div className="px-6 py-3 border-t border-gray-200 flex justify-center gap-2">
                        <button
                            onClick={() => setPage(p => Math.max(1, p - 1))}
                            disabled={page <= 1}
                            className="btn-secondary px-3 py-1.5 text-xs"
                        >
                            Previous
                        </button>
                        <button
                            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                            disabled={page >= totalPages}
                            className="btn-secondary px-3 py-1.5 text-xs"
                        >
                            Next
                        </button>
                    </div>
                )}
            </div>
        </PageShell>
    );
}
