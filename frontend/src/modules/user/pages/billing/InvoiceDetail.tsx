import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { appConfig } from '@/config/env';
import { userBillingApi } from '../../services/billing';
import type { InvoiceDetail as InvoiceDetailType } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Loader2, ArrowLeft, Printer, Download, AlertCircle, FileText, CheckCircle, Clock, XCircle, CreditCard, Wallet } from 'lucide-react';
import toast from 'react-hot-toast';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function InvoiceDetail() {
    const { invoiceId } = useParams({ strict: false }) as { invoiceId: string };
    const navigate = useNavigate();
    const [invoice, setInvoice] = useState<InvoiceDetailType | null>(null);
    const [htmlContent, setHtmlContent] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const iframeRef = useRef<HTMLIFrameElement>(null);

    useEffect(() => {
        if (invoiceId) {
            fetchInvoiceData(invoiceId);
        }
    }, [invoiceId]);

    useEffect(() => {
        // Write HTML content to iframe when it loads
        if (htmlContent && iframeRef.current) {
            const iframe = iframeRef.current;
            const doc = iframe.contentDocument || iframe.contentWindow?.document;

            if (doc) {
                doc.open();
                doc.write(htmlContent);
                doc.close();

                // Add print styles
                const style = doc.createElement('style');
                style.textContent = `
          @media print {
            body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
            @page { margin: 1cm; }
          }
        `;
                doc.head.appendChild(style);
            }
        }
    }, [htmlContent]);

    const fetchInvoiceData = async (id: string) => {
        setIsLoading(true);
        setError(null);
        try {
            const [detailRes, htmlRes] = await Promise.all([
                userBillingApi.getInvoiceDetail(id),
                userBillingApi.getInvoiceHtml(id)
            ]);

            if (detailRes.success && detailRes.data) {
                setInvoice(detailRes.data);
            } else {
                throw new Error(detailRes.message || 'Error loading invoice details');
            }

            if (htmlRes.success && htmlRes.data) {
                setHtmlContent(htmlRes.data);
            } else {
                throw new Error(htmlRes.message || 'Error loading invoice design');
            }
        } catch (err: any) {
            console.error('Error loading invoice:', err);
            setError(err.message || 'Error loading invoice');
            toast.error(err.message || 'Error loading invoice');
        } finally {
            setIsLoading(false);
        }
    };

    const handlePrint = () => {
        if (iframeRef.current) {
            const iframe = iframeRef.current;
            const iframeWindow = iframe.contentWindow;

            if (iframeWindow) {
                iframeWindow.focus();
                iframeWindow.print();
            }
        }
    };

    const handleDownloadPDF = () => {
        // For now, we use the print dialog which allows "Save as PDF"
        // This ensures maximum fidelity with the enterprise HTML template
        handlePrint();
        toast('Please select "Save as PDF" in the print destination.', { icon: 'ℹ️' });
    };

    const handleDownloadHTML = () => {
        if (!htmlContent || !invoice) return;

        const blob = new Blob([htmlContent], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `invoice-${invoice.invoice_number}.html`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    };

    const getStatusClass = (status?: string) => {
        const s = status?.toLowerCase();
        if (s === 'paid' || s === 'completed') return 'bg-success-50 text-success-700';
        if (s === 'failed' || s === 'cancelled') return 'bg-error-50 text-error-700';
        return 'bg-warning-50 text-warning-700';
    };

    const getStatusIcon = (status?: string) => {
        const s = status?.toLowerCase();
        if (s === 'paid' || s === 'completed') return <CheckCircle className="w-4 h-4 mr-1" />;
        if (s === 'failed' || s === 'cancelled') return <XCircle className="w-4 h-4 mr-1" />;
        return <Clock className="w-4 h-4 mr-1" />;
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[400px]">
                <Loader2 className="w-10 h-10 animate-spin text-primary-600 mb-4" />
                <p className="text-gray-600 font-medium">Loading invoice details...</p>
            </div>
        );
    }

    if (error || !invoice) {
        return (
            <div className="max-w-2xl mx-auto py-12 px-4">
                <div className="bg-error-50 border border-error-200 rounded-lg p-8 text-center">
                    <AlertCircle className="w-12 h-12 text-error-600 mx-auto mb-4" />
                    <h2
                        className="text-xl font-bold text-error-900 mb-2"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                        Error Loading Invoice
                    </h2>
                    <p className="text-error-700 mb-6">{error || 'Invoice not found'}</p>
                    <Button onClick={() => navigate({ to: routes.account.billing.invoices })}>
                        <ArrowLeft className="w-4 h-4 mr-2" />
                        Back to Invoices
                    </Button>
                </div>
            </div>
        );
    }

    return (
        <PageShell className="max-w-5xl mx-auto">
            <PageHeader
                title={`Invoice ${invoice.invoice_number}`}
                description={`Issued on ${new Date(invoice.date).toLocaleDateString()}`}
                icon={<FileText className="w-5 h-5" />}
                backTo={routes.account.billing.invoices}
                backLabel="Back to Invoices"
                badge={
                    <span className={`text-xs px-2.5 py-0.5 rounded-full font-medium flex items-center ${getStatusClass(invoice.status)}`}>
                        {getStatusIcon(invoice.status)}
                        {invoice.status?.toUpperCase() || 'PAID'}
                    </span>
                }
                actions={
                    <div className="flex items-center gap-2">
                        <Button variant="secondary" onClick={handleDownloadHTML} title="Download original HTML">
                            <FileText className="w-4 h-4 mr-2" />
                            HTML
                        </Button>
                        <Button variant="secondary" onClick={handleDownloadPDF}>
                            <Download className="w-4 h-4 mr-2" />
                            Download PDF
                        </Button>
                        <Button onClick={handlePrint}>
                            <Printer className="w-4 h-4 mr-2" />
                            Print Invoice
                        </Button>
                    </div>
                }
            />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Left Column: Iframe View */}
                <div className="lg:col-span-2">
                    <div className="card p-0 overflow-hidden min-h-[800px] flex flex-col">
                        <div className="bg-gray-50 px-4 py-2 border-b border-gray-200 flex justify-between items-center">
                            <span className="auth-mono-label">Electronic Invoice Document</span>
                            <span className="auth-mono-label">{appConfig.legalEntity}</span>
                        </div>
                        <iframe
                            ref={iframeRef}
                            title={`Invoice ${invoice.invoice_number}`}
                            className="w-full flex-1 border-none"
                        />
                    </div>
                </div>

                {/* Right Column: Key Details Sidebar */}
                <div className="space-y-6">
                    <div className="card">
                        <h3
                            className="font-semibold text-gray-900 mb-4 pb-2 border-b border-gray-200"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            Payment Summary
                        </h3>
                        <div className="space-y-3 text-sm">
                            <div className="flex justify-between">
                                <span className="text-gray-500">Amount Paid:</span>
                                <span className="font-bold text-gray-900">
                                    {new Intl.NumberFormat('en-US', { style: 'currency', currency: invoice.currency }).format(invoice.total_amount)}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-gray-500">Payment Method:</span>
                                <span className="text-gray-900 flex items-center gap-1">
                                    {invoice.provider === 'STRIPE' ? <CreditCard className="w-4 h-4" /> : <Wallet className="w-4 h-4" />}
                                    {invoice.provider}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-gray-500">Transaction ID:</span>
                                <span className="text-gray-900 font-mono text-[10px] break-all max-w-[120px] text-right">
                                    {invoice.provider_transaction_id}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="card">
                        <h3
                            className="font-semibold text-gray-900 mb-4 pb-2 border-b border-gray-200"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            Billing Information
                        </h3>
                        <div className="space-y-3 text-sm">
                            <div>
                                <span className="text-gray-500 block">Name:</span>
                                <span className="text-gray-900 font-medium">{invoice.billing_name}</span>
                            </div>
                            <div>
                                <span className="text-gray-500 block">Email:</span>
                                <span className="text-gray-900">{invoice.billing_email}</span>
                            </div>
                            {invoice.billing_address && (
                                <div>
                                    <span className="text-gray-500 block">Address:</span>
                                    <address className="not-italic text-gray-900 text-xs mt-1">
                                        {invoice.billing_address.line1}<br />
                                        {invoice.billing_address.line2 && <>{invoice.billing_address.line2}<br /></>}
                                        {invoice.billing_address.city}, {invoice.billing_address.state} {invoice.billing_address.postal_code}<br />
                                        {invoice.billing_address.country}
                                    </address>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="bg-primary-50 rounded-lg p-6 border border-primary-100">
                        <h4
                            className="text-primary-900 font-semibold text-sm mb-2"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            Need Help?
                        </h4>
                        <p className="text-primary-700 text-xs mb-4">
                            If you have any questions about this invoice, please contact our billing team or open a support ticket.
                        </p>
                        <Button
                            variant="secondary"
                            className="w-full text-xs"
                            onClick={() => navigate({ to: routes.account.tickets })}
                        >
                            Contact Support
                        </Button>
                    </div>
                </div>
            </div>
        </PageShell>
    );
}
