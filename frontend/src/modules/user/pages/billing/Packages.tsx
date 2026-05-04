import { useState, useEffect } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { userBillingApi } from '../../services/billing';
import type { CreditPackage, PaymentMethod, PaymentProvider } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Loader2, CreditCard, Check, Sparkles, Zap, Crown, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import { PageShell } from '@/components/ui/PageShell';

export function Packages() {
  const navigate = useNavigate();
  const [packages, setPackages] = useState<CreditPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedPackage, setSelectedPackage] = useState<CreditPackage | null>(null);
  const [isCheckoutModalOpen, setIsCheckoutModalOpen] = useState(false);
  const [enabledGateways, setEnabledGateways] = useState<PaymentMethod[]>([]);
  const [isLoadingGateways, setIsLoadingGateways] = useState(true);

  useEffect(() => {
    fetchPackages();
    fetchEnabledGateways();
  }, []);

  const fetchPackages = async () => {
    setIsLoading(true);
    try {
      const response = await userBillingApi.getPackages();
      if (response.success && response.data) {
        // Filter only active packages for users
        const activePackages = response.data.filter(pkg => pkg.is_active !== false);
        setPackages(activePackages);
      } else {
        toast.error(response.message || 'Failed to load packages');
      }
    } catch (error) {
      console.error('Error fetching packages:', error);
      toast.error('Failed to load credit packages');
    } finally {
      setIsLoading(false);
    }
  };

  const fetchEnabledGateways = async () => {
    setIsLoadingGateways(true);
    try {
      const response = await userBillingApi.getPaymentMethods();
      if (response.success && response.data) {
        setEnabledGateways(response.data.payment_methods);
      } else {
        console.warn('Failed to load payment gateways:', response.message);
      }
    } catch (error) {
      console.error('Error fetching payment gateways:', error);
    } finally {
      setIsLoadingGateways(false);
    }
  };

  const handleSelectPackage = (pkg: CreditPackage) => {
    setSelectedPackage(pkg);
    setIsCheckoutModalOpen(true);
  };

  const handleProceedToCheckout = (provider: 'paypal' | 'stripe' | 'bitcoin' | 'bank_transfer') => {
    if (!selectedPackage) return;

    setIsCheckoutModalOpen(false);
    navigate({ to: routes.account.billing.checkout, state: {
        package: selectedPackage,
        provider
      } as any
    });
  };

  const isGatewayEnabled = (providerType: PaymentProvider) => {
    return enabledGateways.some(g => g.provider === providerType && g.is_enabled);
  };

  const getEnabledGatewayCount = () => {
    return enabledGateways.filter(g => g.is_enabled).length;
  };

  const getPackageIcon = (index: number, total: number) => {
    const mid = Math.floor(total / 2);
    if (index === mid) return <Zap className="w-6 h-6 text-primary-600" />;
    if (index === total - 1) return <Crown className="w-6 h-6 text-warning-500" />;
    return <Sparkles className="w-6 h-6 text-gray-500" />;
  };

  const isPopular = (index: number, total: number) => index === Math.floor(total / 2);

  const getPackageColor = (index: number, total: number) => {
    if (isPopular(index, total)) return 'ring-2 ring-primary-500 border-primary-200 hover:border-primary-300 bg-primary-50/50';
    if (index === total - 1) return 'border-warning-200 hover:border-warning-300 bg-warning-50/50';
    return 'border-gray-200 hover:border-gray-200 bg-gray-50/50';
  };

  const getManualPaymentMethod = (provider: 'BITCOIN' | 'BANK_TRANSFER') => {
    return enabledGateways.find(g => g.provider === provider && g.is_enabled);
  };

  return (
    <PageShell>
      <div className="text-center max-w-2xl mx-auto mb-8">
        <h1
          className="text-3xl font-bold text-gray-900 mb-3"
          style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
        >
          Buy Credits
        </h1>
        <p className="text-gray-600">
          Choose a credit package that fits your needs. Credits are valid for 1 month and can be used across the platform.
        </p>
      </div>

      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-primary-600 mb-4" />
          <p className="text-gray-500">Loading packages...</p>
        </div>
      ) : packages.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg">
          <CreditCard className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No packages available</h3>
          <p className="text-gray-500">Please check back later for available credit packages.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {packages.map((pkg, index) => (
            <div
              key={pkg.id}
              className={clsx(
                'relative rounded-lg border-2 p-6 transition-all duration-200 cursor-pointer',
                'hover:shadow-lg hover:-translate-y-1',
                getPackageColor(index, packages.length)
              )}
              onClick={() => handleSelectPackage(pkg)}
            >
              {isPopular(index, packages.length) && (
                <div className="auth-mono-label absolute -top-3 left-1/2 -translate-x-1/2 bg-primary-600 text-white px-3 py-1 rounded-full shadow-sm" style={{ color: '#ffffff' }}>
                  Most Popular
                </div>
              )}
              <div className="flex items-center justify-between mb-4">
                <div className="p-2 bg-white rounded-lg shadow-sm">
                  {getPackageIcon(index, packages.length)}
                </div>
                <div className="text-right">
                  <span className="text-2xl font-bold text-gray-900">
                    ${pkg.amount.toFixed(2)}
                  </span>
                  <span className="text-sm text-gray-500 block">{pkg.currency}</span>
                </div>
              </div>

              <h3
                className="text-lg font-semibold text-gray-900 mb-2"
                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
              >
                {pkg.name}
              </h3>
              <p className="text-sm text-gray-600 mb-4 min-h-[40px]">{pkg.description}</p>

              <div className="flex items-center gap-2 mb-4 p-3 bg-white rounded-lg">
                <Check className="w-5 h-5 text-success-500" />
                <span className="font-semibold text-gray-900">{pkg.credits} Credits</span>
              </div>

              <Button
                className="btn-primary auth-submit w-full"
                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: '0.02em' }}
              >
                select →
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Checkout Modal */}
      <Modal
        isOpen={isCheckoutModalOpen}
        onClose={() => setIsCheckoutModalOpen(false)}
        title="Choose Payment Method"
      >
        {selectedPackage && (
          <div className="space-y-6">
            <div className="bg-gray-50 p-4 rounded-lg">
              <h4
                className="font-semibold text-gray-900 mb-1"
                style={{ fontFamily: 'var(--font-mono-display)' }}
              >
                {selectedPackage.name}
              </h4>
              <p className="text-sm text-gray-600 mb-3">{selectedPackage.description}</p>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-600">Credits:</span>
                <span className="font-semibold text-gray-900">{selectedPackage.credits}</span>
              </div>
              <div className="flex items-center justify-between text-lg font-bold mt-2 pt-2 border-t border-gray-200">
                <span className="text-gray-900">Total:</span>
                <span className="text-primary-600">${selectedPackage.amount.toFixed(2)} {selectedPackage.currency}</span>
              </div>
            </div>

            {isLoadingGateways ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="w-5 h-5 animate-spin text-gray-400 mr-2" />
                <span className="text-sm text-gray-500">Loading payment options...</span>
              </div>
            ) : getEnabledGatewayCount() === 0 ? (
              <div className="p-4 bg-warning-50 border border-warning-200 rounded-lg flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-warning-600 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-warning-700">No payment methods available</p>
                  <p className="text-sm text-warning-700 mt-1">
                    Please try again later or contact support if the problem persists.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm font-medium text-gray-700 mb-3">Select payment method:</p>

                {isGatewayEnabled('PAYPAL') && (
                  <Button
                    onClick={() => handleProceedToCheckout('paypal')}
                    variant="secondary"
                    className="w-full justify-center py-3 bg-[#0070BA] text-white hover:bg-[#003087] border-0"
                  >
                    <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M7.076 21.337H2.47a.641.641 0 0 1-.633-.74L4.944.901C5.026.382 5.474 0 5.998 0h7.46c2.57 0 4.578.543 5.69 1.81 1.01 1.15 1.304 2.42 1.012 4.287-.023.143-.047.288-.077.437-.983 5.05-4.349 6.797-8.647 6.797h-2.19c-.524 0-.968.382-1.05.9l-1.12 7.106zm14.146-14.42a3.35 3.35 0 0 0-.607-.541c-.013.076-.026.175-.041.254-.59 3.025-2.566 6.082-8.558 6.082h-2.19c-.524 0-.968.382-1.05.9l-1.209 7.675h3.85c.464 0 .858-.334.929-.794l.04-.19.73-4.627.047-.255a.933.933 0 0 1 .928-.794h.584c3.77 0 6.726-1.528 7.594-5.62.266-1.277.123-2.37-.577-3.14z" />
                    </svg>
                    Pay with PayPal
                  </Button>
                )}

                {isGatewayEnabled('STRIPE') && (
                  <Button
                    onClick={() => handleProceedToCheckout('stripe')}
                    variant="secondary"
                    className="w-full justify-center py-3 bg-[#635BFF] text-white hover:bg-[#4b44c7] border-0"
                  >
                    <CreditCard className="w-5 h-5 mr-2" />
                    Pay with Card (Stripe)
                  </Button>
                )}

                {isGatewayEnabled('BITCOIN') && (
                  <Button
                    onClick={() => handleProceedToCheckout('bitcoin')}
                    variant="secondary"
                    className="w-full justify-center py-3 bg-warning-600 text-white hover:bg-warning-700 border-0"
                  >
                    <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v2h-2zm0 3h2v6h-2zm0 3h2v2h-2z" />
                    </svg>
                    {getManualPaymentMethod('BITCOIN')?.name || 'Pay with Bitcoin'}
                  </Button>
                )}

                {isGatewayEnabled('BANK_TRANSFER') && (
                  <Button
                    onClick={() => handleProceedToCheckout('bank_transfer')}
                    variant="secondary"
                    className="btn-success w-full justify-center py-3"
                  >
                    <CreditCard className="w-5 h-5 mr-2" />
                    {getManualPaymentMethod('BANK_TRANSFER')?.name || 'Bank Transfer'}
                  </Button>
                )}
              </div>
            )}

            <p className="text-xs text-gray-500 text-center">
              Your payment is secure and encrypted. Credits will be added immediately after successful payment.
            </p>
          </div>
        )}
      </Modal>
    </PageShell>
  );
}
