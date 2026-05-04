import { useEffect } from 'react';
import { useLocation, useNavigate, Link } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { Button } from '@/components/ui/Button';
import { CheckCircle, CreditCard, FileText, ArrowRight, Sparkles } from 'lucide-react';
import { PageShell } from '@/components/ui/PageShell';

interface PaymentSuccessState {
  transactionId: string;
  invoiceId: string;
  creditsAdded: number;
  packageName?: string;
}

export function PaymentSuccess() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as unknown as PaymentSuccessState | null;

  useEffect(() => {
    if (!state?.transactionId) {
      // Redirect to packages if no success data
      navigate({ to: routes.account.billing.packages });
      return;
    }
  }, [state, navigate]);

  if (!state?.transactionId) {
    return null; // Will redirect
  }

  const { transactionId, invoiceId, creditsAdded, packageName } = state;

  return (
    <PageShell className="max-w-2xl mx-auto">
      <div className="card p-0 overflow-hidden">
        {/* Success Header */}
        <div className="bg-success-50 p-8 text-center border-b border-success-100">
          <div className="w-20 h-20 bg-success-50 rounded-full flex items-center justify-center mx-auto mb-4">
            <CheckCircle className="w-10 h-10 text-success-600" />
          </div>
          <h1 className="page-title mb-2">Payment Successful!</h1>
          <p className="text-gray-600">
            Thank you for your purchase. The credits have been added to your account.
          </p>
        </div>

        <div className="p-6 space-y-6">
          {/* Credits Added */}
          <div className="bg-primary-50 rounded-lg p-6 text-center">
            <div className="flex items-center justify-center gap-2 mb-2">
              <Sparkles className="w-5 h-5 text-primary-500" />
              <span
                className="text-lg font-semibold text-primary-900"
                style={{ fontFamily: 'var(--font-mono-display)' }}
              >
                Credits Added
              </span>
              <Sparkles className="w-5 h-5 text-primary-500" />
            </div>
            <div
              className="text-4xl font-bold text-primary-600 mb-1"
              style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
            >
              +{creditsAdded}
            </div>
            <p className="text-sm text-primary-700">
              Credits are valid for 1 month starting today
            </p>
          </div>

          {/* Transaction Details */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h3
              className="font-semibold text-gray-900 mb-3"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              Transaction Details
            </h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Transaction ID:</span>
                <span className="font-mono text-gray-900">{transactionId}</span>
              </div>
              {packageName && (
                <div className="flex justify-between">
                  <span className="text-gray-600">Package:</span>
                  <span className="text-gray-900">{packageName}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-gray-600">Status:</span>
                <span className="text-success-600 font-medium">Completed</span>
              </div>
            </div>
          </div>

          {/* Next Steps */}
          <div className="space-y-3">
            <h3
              className="font-semibold text-gray-900"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              What's next?
            </h3>

            {invoiceId && (
              <Link
                to={routes.account.billing.invoiceDetail(invoiceId)}
                className="flex items-center p-4 bg-white border border-gray-200 rounded-lg hover:border-primary-300 hover:shadow-sm transition-all group"
              >
                <div className="w-10 h-10 bg-primary-50 rounded-lg flex items-center justify-center mr-4 group-hover:bg-primary-200 transition-colors">
                  <FileText className="w-5 h-5 text-primary-600" />
                </div>
                <div className="flex-1">
                  <h4
                    className="font-medium text-gray-900"
                    style={{ fontFamily: 'var(--font-mono-display)' }}
                  >
                    View Invoice
                  </h4>
                  <p className="text-sm text-gray-500">Download or print your receipt</p>
                </div>
                <ArrowRight className="w-5 h-5 text-gray-400 group-hover:text-primary-500" />
              </Link>
            )}

            <Link
              to="/"
              className="flex items-center p-4 bg-white border border-gray-200 rounded-lg hover:border-primary-300 hover:shadow-sm transition-all group"
            >
              <div className="w-10 h-10 bg-success-50 rounded-lg flex items-center justify-center mr-4 group-hover:bg-success-200 transition-colors">
                <CreditCard className="w-5 h-5 text-success-600" />
              </div>
              <div className="flex-1">
                <h4
                  className="font-medium text-gray-900"
                  style={{ fontFamily: 'var(--font-mono-display)' }}
                >
                  Start Using Credits
                </h4>
                <p className="text-sm text-gray-500">Use your credits to access premium features</p>
              </div>
              <ArrowRight className="w-5 h-5 text-gray-400 group-hover:text-primary-500" />
            </Link>
          </div>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-3 pt-4 border-t border-gray-200">
            <Button
              variant="secondary"
              onClick={() => navigate({ to: routes.account.billing.invoices })}
              className="flex-1"
            >
              <FileText className="w-4 h-4 mr-2" />
              View Invoices
            </Button>
            <Button
              onClick={() => navigate({ to: routes.account.billing.packages })}
              className="btn-primary auth-submit flex-1"
              style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: '0.02em' }}
            >
              <CreditCard className="w-4 h-4 mr-2" />
              buy more credits →
            </Button>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
