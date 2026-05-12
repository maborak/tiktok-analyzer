import { useState, useEffect } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { userBillingApi } from '../../services/billing';
import type { Invoice } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Loader2, FileText, ChevronLeft, ChevronRight, RefreshCw, Receipt, CheckCircle, XCircle, Clock, Eye, CreditCard, Wallet, Bitcoin, Building } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import { format } from 'date-fns';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function Invoices() {
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);
  const [totalInvoices, setTotalInvoices] = useState(0);

  useEffect(() => {
    fetchInvoices();
  }, [currentPage, pageSize]);

  const fetchInvoices = async () => {
    setIsLoading(true);
    try {
      const response = await userBillingApi.getInvoices(currentPage, pageSize);
      if (response.success && response.data) {
        setInvoices(response.data.items);
        setTotalInvoices(response.data.total || 0);
      } else {
        toast.error(response.message || 'Error loading invoices');
      }
    } catch (error) {
      console.error('Error fetching invoices:', error);
      toast.error('Error loading invoices');
    } finally {
      setIsLoading(false);
    }
  };

  const handleViewInvoice = (invoiceId: string) => {
    navigate({ to: `/account/billing/invoices/${invoiceId}` });
  };

  const totalPages = Math.ceil(totalInvoices / pageSize);

  const formatDate = (dateString: string | undefined) => {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) return 'Invalid Date';
      return format(date, 'MMM d, yyyy');
    } catch {
      return 'Invalid Date';
    }
  };

  const formatCurrency = (amount: number, currency: string) => {
    if (typeof amount !== 'number') return 'N/A';
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD'
      }).format(amount);
    } catch {
      return `$${amount}`;
    }
  };

  const getStatusIcon = (status?: string) => {
    const normalizedStatus = status?.toLowerCase();
    switch (normalizedStatus) {
      case 'completed':
      case 'paid':
        return <CheckCircle className="w-4 h-4 text-success-500" />;
      case 'failed':
      case 'cancelled':
      case 'rejected':
        return <XCircle className="w-4 h-4 text-error-500" />;
      case 'pending':
      case 'processing':
      case 'awaiting_payment':
        return <Clock className="w-4 h-4 text-warning-500" />;
      default:
        return <CheckCircle className="w-4 h-4 text-success-500" />;
    }
  };

  const getStatusText = (status?: string) => {
    const normalizedStatus = status?.toLowerCase();
    switch (normalizedStatus) {
      case 'completed':
      case 'paid':
        return 'Paid';
      case 'failed':
        return 'Failed';
      case 'cancelled':
        return 'Cancelled';
      case 'rejected':
        return 'Rejected';
      case 'pending':
        return 'Pending';
      case 'processing':
        return 'Processing';
      case 'awaiting_payment':
        return 'Awaiting Payment';
      default:
        return status || 'Paid';
    }
  };

  const getStatusClass = (status?: string) => {
    const normalizedStatus = status?.toLowerCase();
    switch (normalizedStatus) {
      case 'completed':
      case 'paid':
        return 'bg-success-50 text-success-700';
      case 'failed':
      case 'cancelled':
      case 'rejected':
        return 'bg-error-50 text-error-700';
      case 'pending':
      case 'processing':
      case 'awaiting_payment':
        return 'bg-warning-50 text-warning-700';
      default:
        return 'bg-success-50 text-success-700';
    }
  };

  const getProviderIcon = (provider: string) => {
    switch (provider?.toUpperCase()) {
      case 'STRIPE':
        return <CreditCard className="w-4 h-4 text-primary-500" />;
      case 'PAYPAL':
        return <Wallet className="w-4 h-4 text-primary-500" />;
      case 'BITCOIN':
        return <Bitcoin className="w-4 h-4 text-warning-500" />;
      case 'BANK_TRANSFER':
        return <Building className="w-4 h-4 text-gray-500" />;
      default:
        return <FileText className="w-4 h-4 text-gray-400" />;
    }
  };

  return (
    <PageShell>
      <PageHeader
        title="Billing History"
        description="View and download your invoices and receipts."
        icon={<Receipt className="w-5 h-5" />}
        actions={
          <Button onClick={fetchInvoices} variant="secondary" className="px-3" title="Refresh">
            <RefreshCw className={clsx("w-4 h-4", isLoading && "animate-spin")} />
          </Button>
        }
      />

      <div className="card p-0 overflow-hidden">
        {isLoading && invoices.length === 0 ? (
          <div className="p-12 text-center text-gray-500 flex flex-col items-center">
            <Loader2 className="w-8 h-8 animate-spin text-gray-400 mb-4" />
            <p>Loading invoices...</p>
          </div>
        ) : invoices.length === 0 ? (
          <div className="p-12 text-center flex flex-col items-center">
            <Receipt className="w-12 h-12 text-gray-300 mb-4" />
            <h3
              className="text-lg font-medium text-gray-900"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              No invoices yet
            </h3>
            <p className="text-gray-500 mt-2">You haven't made any purchases yet.</p>
            <Button
              onClick={() => navigate({ to: routes.account.billing.packages })}
              className="mt-6"
              variant="secondary"
            >
              View Packages
            </Button>
          </div>
        ) : (
          <>
            {/* Desktop: dense table. Hidden below md where the column
                count would force horizontal scroll. */}
            <table className="hidden md:table min-w-full divide-y divide-gray-200 text-sm text-left">
              <thead className="bg-gray-50">
                <tr>
                  <th className="auth-mono-label px-6 py-3 text-left">Invoice #</th>
                  <th className="auth-mono-label px-6 py-3 text-left">Date</th>
                  <th className="auth-mono-label px-6 py-3 text-left">Method</th>
                  <th className="auth-mono-label px-6 py-3 text-left">Item</th>
                  <th className="auth-mono-label px-6 py-3 text-left">Amount</th>
                  <th className="auth-mono-label px-6 py-3 text-left">Status</th>
                  <th className="auth-mono-label px-6 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {invoices.map((invoice) => (
                  <tr key={invoice.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400" />
                        <span className="font-mono text-gray-900">{invoice.invoice_number || 'N/A'}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-500">
                      {formatDate(invoice.invoice_date || invoice.date)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-gray-700">
                        {getProviderIcon(invoice.provider)}
                        <span className="capitalize">{invoice.provider?.toLowerCase().replace('_', ' ')}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-gray-900 font-medium">
                        {invoice.description || 'Credit Purchase'}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {invoice.billing_email}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap font-medium text-gray-900">
                      {formatCurrency(invoice.total_amount, invoice.currency)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={clsx(
                        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                        getStatusClass(invoice.status)
                      )}>
                        {getStatusIcon(invoice.status)}
                        <span className="ml-1">{getStatusText(invoice.status)}</span>
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleViewInvoice(invoice.id)}
                        className="flex items-center ml-auto"
                      >
                        <Eye className="w-4 h-4 mr-1" />
                        View
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Mobile: card list — one row per invoice, no horizontal
                scroll. Only renders below md. */}
            <ul className="md:hidden flex flex-col gap-2 p-3">
              {invoices.map((invoice) => (
                <li
                  key={invoice.id}
                  className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 hover:bg-gray-50 transition-colors cursor-pointer"
                  onClick={() => handleViewInvoice(invoice.id)}
                >
                  <div className="flex items-baseline justify-between gap-2 mb-1">
                    <div className="min-w-0 flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      <span className="font-mono text-sm text-gray-900 truncate">
                        {invoice.invoice_number || 'N/A'}
                      </span>
                    </div>
                    <div className="shrink-0 font-medium text-gray-900 tabular-nums">
                      {formatCurrency(invoice.total_amount, invoice.currency)}
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <div className="min-w-0 text-xs text-gray-500 flex items-center gap-2">
                      <span>{formatDate(invoice.invoice_date || invoice.date)}</span>
                      <span className="inline-flex items-center gap-1 capitalize">
                        {getProviderIcon(invoice.provider)}
                        {invoice.provider?.toLowerCase().replace('_', ' ')}
                      </span>
                    </div>
                    <span className={clsx(
                      'shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium',
                      getStatusClass(invoice.status)
                    )}>
                      {getStatusIcon(invoice.status)}
                      <span className="ml-1">{getStatusText(invoice.status)}</span>
                    </span>
                  </div>
                  <div className="text-xs text-gray-700">
                    <div className="font-medium truncate">{invoice.description || 'Credit Purchase'}</div>
                    {invoice.billing_email && (
                      <div className="text-[11px] text-gray-500 truncate">{invoice.billing_email}</div>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            <div className="flex flex-col sm:flex-row items-center justify-between px-6 py-4 bg-gray-50 border-t border-gray-200 gap-4">
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 w-full sm:w-auto text-sm text-gray-500">
                <div>
                  Showing <span className="font-medium">{totalInvoices > 0 ? ((currentPage - 1) * pageSize) + 1 : 0}</span> to{' '}
                  <span className="font-medium">{Math.min(currentPage * pageSize, totalInvoices)}</span> of{' '}
                  <span className="font-medium">{totalInvoices}</span> invoices
                </div>
                <div className="flex items-center gap-2">
                  <label htmlFor="pageSize" className="whitespace-nowrap">Per page:</label>
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
              <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                <Button
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={currentPage === 1 || isLoading}
                  variant="secondary"
                  size="sm"
                >
                  <ChevronLeft className="w-4 h-4 mr-1" />
                  Previous
                </Button>
                <span className="text-sm font-medium text-gray-700 px-2">
                  {currentPage} / {totalPages || 1}
                </span>
                <Button
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  disabled={currentPage >= totalPages || isLoading}
                  variant="secondary"
                  size="sm"
                >
                  Next
                  <ChevronRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </PageShell>
  );
}
