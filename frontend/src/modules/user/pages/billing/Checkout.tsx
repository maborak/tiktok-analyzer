import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { loadStripe } from '@stripe/stripe-js';
import type { Stripe } from '@stripe/stripe-js';
import { Elements } from '@stripe/react-stripe-js';
import { userBillingApi } from '../../services/billing';
import type { CreditPackage, PaymentProvider, OrderResponse, PaymentMethod, ManualPaymentResponse } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { PayPalButton } from '../../components/billing/PayPalButton';
import { PayPalProvider } from '../../components/billing/PayPalProvider';
import { StripeForm } from '../../components/billing/StripeForm';
import { Loader2, CreditCard, AlertCircle, CheckCircle, Copy } from 'lucide-react';
import toast from 'react-hot-toast';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

interface CheckoutState {
  package: CreditPackage;
  provider: 'paypal' | 'stripe' | 'bitcoin' | 'bank_transfer';
  resumeOrderId?: string;
}

export function Checkout() {
  const location = useLocation();
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(true);
  const [isCreatingOrder, setIsCreatingOrder] = useState(false);
  const [orderData, setOrderData] = useState<OrderResponse | null>(null);
  const [stripePromise, setStripePromise] = useState<Promise<Stripe | null> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manualPaymentMethod, setManualPaymentMethod] = useState<PaymentMethod | null>(null);
  const [manualPaymentData, setManualPaymentData] = useState<ManualPaymentResponse | null>(null);
  const [showConfirmationModal, setShowConfirmationModal] = useState(false);
  const [isCreatingManualPayment, setIsCreatingManualPayment] = useState(false);

  const state = location.state as unknown as CheckoutState | null;
  const resumeOrderId = state?.resumeOrderId;
  const [selectedPackage, setSelectedPackage] = useState<CreditPackage | undefined>(state?.package);
  const [provider] = useState<CheckoutState['provider'] | undefined>(state?.provider);
  const initRef = useRef(false);

  useEffect(() => {
    if (!selectedPackage || !provider) {
      // Redirect back to packages if no selection
      navigate({ to: routes.account.billing.packages });
      return;
    }

    if (initRef.current) return;
    initRef.current = true;

    // Fetch payment methods for manual payment details
    fetchPaymentMethods();

    if (resumeOrderId) {
      resumeExistingOrder(resumeOrderId);
      return;
    }

    // Only create order for PayPal/Stripe, not for manual payments
    if (provider !== 'bitcoin' && provider !== 'bank_transfer') {
      createOrder();
    } else {
      // For manual payments, create the manual payment record
      createManualPayment();
    }
  }, [selectedPackage, provider, resumeOrderId]);



  const fetchPaymentMethods = async () => {
    try {
      const response = await userBillingApi.getPaymentMethods();
      if (response.success && response.data) {
        // Find the manual payment method based on provider
        const providerUpper = provider?.toUpperCase() as PaymentProvider;
        const manualMethod = response.data.payment_methods.find(m => m.provider === providerUpper);
        if (manualMethod) {
          setManualPaymentMethod(manualMethod);
        }
      }
    } catch (error) {
      console.error('Error fetching payment methods:', error);
    }
  };

  const createOrder = async () => {
    if (!selectedPackage || !provider) return;

    setIsLoading(true);
    setIsCreatingOrder(true);
    setError(null);

    try {
      const response = await userBillingApi.createOrder({
        package_id: selectedPackage.id,
        amount: selectedPackage.amount,
        currency: selectedPackage.currency,
        provider: provider.toUpperCase() as PaymentProvider
      });

      if (!response.success || !response.data) {
        throw new Error(response.message || 'Error creating order');
      }

      setOrderData(response.data);

      // Initialize Stripe if using Stripe payment
      if (provider === 'stripe' && response.data.stripe_publishable_key) {
        setStripePromise(loadStripe(response.data.stripe_publishable_key));
      }
    } catch (err: any) {
      console.error('Error creating order:', err);
      setError(err.message || 'Error initializing payment. Please try again.');
      toast.error(err.message || 'Error initializing payment');
    } finally {
      setIsLoading(false);
      setIsCreatingOrder(false);
    }
  };

  const resumeExistingOrder = async (orderId: string) => {
    setIsLoading(true);
    setIsCreatingOrder(true);
    setError(null);

    try {
      const response = await userBillingApi.resumeOrder(orderId);

      if (!response.success || !response.data) {
        throw new Error(response.message || 'Error resuming order');
      }

      const data = response.data;
      setOrderData(data);

      // Hydrate package information from the resume response to fix missing credits/name/description
      if (data.amount) {
        setSelectedPackage(prev => ({
          id: Number(data.package_id || prev?.id || 0),
          name: data.package_name || prev?.name || 'Credit Package',
          description: data.description || prev?.description || `Resume payment for ${data.package_name || 'Credit Package'}`,
          amount: data.amount,
          currency: data.currency || prev?.currency || 'USD',
          credits: data.credits !== undefined ? data.credits : prev?.credits || 0,
        } as CreditPackage));
      }

      // Initialize Stripe if using Stripe payment
      if (provider === 'stripe' && data.stripe_publishable_key) {
        setStripePromise(loadStripe(data.stripe_publishable_key));
      }
    } catch (err: any) {
      console.error('Error resuming order:', err);
      setError(err.message || 'Error resuming payment session. Please try again.');
      toast.error(err.message || 'Error resuming payment session');
    } finally {
      setIsLoading(false);
      setIsCreatingOrder(false);
    }
  };

  const createManualPayment = async () => {
    if (!selectedPackage || !provider) return;

    setIsLoading(true);
    setIsCreatingManualPayment(true);
    setError(null);

    try {
      const response = await userBillingApi.createManualPayment({
        package_id: selectedPackage.id,
        amount: selectedPackage.amount,
        currency: selectedPackage.currency,
        provider: provider.toUpperCase() as PaymentProvider
      });

      if (!response.success || !response.data) {
        throw new Error(response.message || 'Error creating manual payment');
      }

      setManualPaymentData(response.data);
    } catch (err: any) {
      console.error('Error creating manual payment:', err);
      setError(err.message || 'Error initializing manual payment. Please try again.');
      toast.error(err.message || 'Error initializing manual payment');
    } finally {
      setIsLoading(false);
      setIsCreatingManualPayment(false);
    }
  };

  const handlePaymentSuccess = (transactionId: string, invoiceId: string, creditsAdded: number) => {
    // Navigate to success page
    navigate({ to: routes.account.billing.success,
      state: {
        transactionId,
        invoiceId,
        creditsAdded,
        packageName: selectedPackage?.name
      } as any
    });
  };

  const handlePaymentError = (message: string) => {
    setError(message);
  };

  const handleRetry = () => {
    setError(null);
    if (provider !== 'bitcoin' && provider !== 'bank_transfer') {
      createOrder();
    } else {
      createManualPayment();
    }
  };

  const handleCopyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success('Copied to clipboard');
  };

  const handleManualPaymentConfirmation = () => {
    setShowConfirmationModal(true);
  };

  const handleConfirmManualPayment = async () => {
    // Create a ticket or send notification about manual payment
    toast.success('Thank you! We will verify your payment and add the credits soon.');
    navigate({ to: routes.account.billing.packages });
  };

  const isManualPayment = provider === 'bitcoin' || provider === 'bank_transfer';

  if (!selectedPackage || !provider) {
    return null; // Will redirect
  }

  return (
    <PageShell className="max-w-2xl mx-auto">
      <PageHeader
        title="Complete Your Purchase"
        description="Review your order and complete the payment securely."
        icon={<CreditCard className="w-5 h-5" />}
        backTo="/account/billing/packages"
        backLabel="Back to Packages"
      />

      <div className="card p-0 overflow-hidden">

        <div className="p-6 space-y-6">
          {/* Order Summary */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h3
              className="font-semibold text-gray-900 mb-3"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              Order Summary
            </h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-600">Package:</span>
                <span className="font-medium text-gray-900">{selectedPackage.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Description:</span>
                <span className="text-gray-900">{selectedPackage.description}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Credits:</span>
                <span className="font-medium text-gray-900">{selectedPackage.credits || '-'}</span>
              </div>
              <div className="pt-2 border-t border-gray-200 flex justify-between text-lg font-bold">
                <span className="text-gray-900">Total:</span>
                <span className="text-primary-600">
                  {selectedPackage.amount ? `$${selectedPackage.amount.toFixed(2)} ${selectedPackage.currency}` : 'Calculated at checkout'}
                </span>
              </div>
            </div>
          </div>

          {/* Payment Section */}
          <div>
            <h3
              className="font-semibold text-gray-900 mb-4 flex items-center"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              <CreditCard className="w-5 h-5 mr-2" />
              Payment Details
            </h3>

            {isLoading ? (
              <div className="flex flex-col items-center justify-center py-8">
                <Loader2 className="w-8 h-8 animate-spin text-primary-600 mb-3" />
                <p className="text-gray-600">
                  {isCreatingOrder ? 'Initializing payment...' : isCreatingManualPayment ? 'Loading payment instructions...' : 'Loading...'}
                </p>
              </div>
            ) : error ? (
              <div className="p-4 bg-error-50 border border-error-200 rounded-lg">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-error-600 mt-0.5" />
                  <div>
                    <h4 className="font-medium text-error-700">Payment Error</h4>
                    <p className="text-sm text-error-700 mt-1">{error}</p>
                    <Button
                      onClick={handleRetry}
                      variant="secondary"
                      className="mt-3"
                    >
                      Try Again
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {provider === 'paypal' && orderData?.provider_data?.id && orderData?.paypal_client_id && orderData.paypal_client_id.length > 0 ? (
                  <div className="border border-gray-200 rounded-lg p-4">
                    <PayPalProvider clientId={orderData.paypal_client_id} mode={orderData.mode}>
                      <PayPalButton
                        selectedPackage={selectedPackage}
                        orderId={orderData.provider_data.id}
                        onSuccess={handlePaymentSuccess}
                        onError={handlePaymentError}
                      />
                    </PayPalProvider>
                  </div>
                ) : provider === 'paypal' && !isLoading && (
                  <div className="p-4 bg-warning-50 border border-warning-200 rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-warning-600 mt-0.5" />
                      <div>
                        <h4 className="font-medium text-warning-700">PayPal Not Configured</h4>
                        <p className="text-sm text-warning-700 mt-1">
                          PayPal is not configured. Please contact the administrator to set up PayPal credentials, or use a different payment method.
                        </p>
                        <Button
                          onClick={() => navigate({ to: routes.account.billing.packages })}
                          variant="secondary"
                          className="mt-3"
                        >
                          Back to Packages
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                {provider === 'stripe' && orderData?.provider_data?.client_secret && orderData.provider_data.client_secret.length > 0 && stripePromise ? (
                  <div className="border border-gray-200 rounded-lg p-4">
                    <Elements stripe={stripePromise} options={{ clientSecret: orderData.provider_data.client_secret }}>
                      <StripeForm
                        selectedPackage={selectedPackage}
                        clientSecret={orderData.provider_data.client_secret}
                        onSuccess={handlePaymentSuccess}
                        onError={handlePaymentError}
                      />
                    </Elements>
                  </div>
                ) : provider === 'stripe' && !isLoading && (
                  <div className="p-4 bg-warning-50 border border-warning-200 rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-warning-600 mt-0.5" />
                      <div>
                        <h4 className="font-medium text-warning-700">Stripe Not Configured</h4>
                        <p className="text-sm text-warning-700 mt-1">
                          Stripe is not configured. Please contact the administrator to set up Stripe credentials, or use a different payment method.
                        </p>
                        <Button
                          onClick={() => navigate({ to: routes.account.billing.packages })}
                          variant="secondary"
                          className="mt-3"
                        >
                          Back to Packages
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                {isManualPayment && (manualPaymentData || manualPaymentMethod) && (
                  <div className="border border-gray-200 rounded-lg p-4 space-y-4">
                    <div className="text-center">
                      <h4
                        className="font-semibold text-gray-900 text-lg"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                      >
                        {manualPaymentData?.payment_details ?
                          (provider === 'bitcoin' ? 'Bitcoin Payment' : 'Bank Transfer')
                          : manualPaymentMethod?.name}
                      </h4>
                      {(manualPaymentData?.instructions || manualPaymentMethod?.description) && (
                        <p className="text-gray-600 mt-1">
                          {manualPaymentData?.instructions || manualPaymentMethod?.description}
                        </p>
                      )}
                    </div>

                    {/* Wallet Address for Bitcoin */}
                    {(manualPaymentData?.payment_details?.wallet_address || manualPaymentMethod?.wallet_address) && (
                      <div className="bg-gray-50 p-3 rounded-lg">
                        <label className="text-sm font-medium text-gray-700 block mb-1">Wallet Address:</label>
                        <div className="flex items-center gap-2">
                          <code className="flex-1 bg-white p-2 rounded text-sm break-all">
                            {manualPaymentData?.payment_details?.wallet_address || manualPaymentMethod?.wallet_address}
                          </code>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleCopyToClipboard(manualPaymentData?.payment_details?.wallet_address || manualPaymentMethod?.wallet_address || '')}
                          >
                            <Copy className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    )}

                    {/* Bank Details for Bank Transfer */}
                    {(manualPaymentData?.payment_details?.bank_details || manualPaymentMethod?.bank_details) && (
                      <div className="bg-gray-50 p-3 rounded-lg">
                        <label className="text-sm font-medium text-gray-700 block mb-1">Bank Transfer Details:</label>
                        <pre className="bg-white p-2 rounded text-sm whitespace-pre-wrap">
                          {manualPaymentData?.payment_details?.bank_details || manualPaymentMethod?.bank_details}
                        </pre>
                      </div>
                    )}

                    {/* QR Code */}
                    {(manualPaymentData?.payment_details?.qr_code_url || manualPaymentMethod?.qr_code_url) && (
                      <div className="text-center">
                        <img
                          src={manualPaymentData?.payment_details?.qr_code_url || manualPaymentMethod?.qr_code_url}
                          alt="Payment QR Code"
                          className="mx-auto max-w-[200px] rounded-lg"
                        />
                      </div>
                    )}

                    {/* Instructions */}
                    {(manualPaymentData?.payment_details?.instructions || manualPaymentMethod?.instructions) && (
                      <div className="bg-primary-50 p-3 rounded-lg">
                        <p className="text-sm text-primary-700">
                          {manualPaymentData?.payment_details?.instructions || manualPaymentMethod?.instructions}
                        </p>
                      </div>
                    )}

                    {/* Contact Info */}
                    {(manualPaymentData?.payment_details?.contact_info || manualPaymentMethod?.contact_info) && (
                      <div className="text-center text-sm text-gray-600">
                        Contact: <a
                          href={`mailto:${manualPaymentData?.payment_details?.contact_info || manualPaymentMethod?.contact_info}`}
                          className="text-primary-600 hover:underline"
                        >
                          {manualPaymentData?.payment_details?.contact_info || manualPaymentMethod?.contact_info}
                        </a>
                      </div>
                    )}

                    {/* Transaction ID for reference */}
                    {manualPaymentData?.transaction_id && (
                      <div className="bg-warning-50 p-3 rounded-lg">
                        <label className="text-sm font-medium text-warning-700 block mb-1">Transaction Reference:</label>
                        <div className="flex items-center gap-2">
                          <code className="flex-1 bg-white p-2 rounded text-sm break-all text-warning-900">
                            {manualPaymentData.transaction_id}
                          </code>
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleCopyToClipboard(manualPaymentData.transaction_id)}
                          >
                            <Copy className="w-4 h-4" />
                          </Button>
                        </div>
                        <p className="text-xs text-warning-700 mt-1">
                          Please include this reference when contacting support
                        </p>
                      </div>
                    )}

                    <Button
                      onClick={handleManualPaymentConfirmation}
                      className="btn-primary auth-submit w-full justify-center py-3"
                      style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: '0.02em' }}
                    >
                      <CheckCircle className="w-5 h-5 mr-2" />
                      i have completed the payment →
                    </Button>
                  </div>
                )}

                {isManualPayment && !manualPaymentMethod && !manualPaymentData && !isLoading && (
                  <div className="p-4 bg-warning-50 border border-warning-200 rounded-lg">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-warning-600 mt-0.5" />
                      <div>
                        <h4 className="font-medium text-warning-700">Payment Method Not Available</h4>
                        <p className="text-sm text-warning-700 mt-1">
                          This payment method is not configured currently. Please try another payment method.
                        </p>
                        <Button
                          onClick={() => navigate({ to: routes.account.billing.packages })}
                          variant="secondary"
                          className="mt-3"
                        >
                          Back to Packages
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Security Note */}
          <p className="text-xs text-gray-500 text-center">
            {isManualPayment
              ? 'Please follow the instructions above to complete your payment manually. Credits will be added after administrator verification.'
              : `Your payment is safely processed by ${provider === 'paypal' ? 'PayPal' : 'Stripe'}. We do not store your payment data.`
            }
          </p>
        </div>
      </div>

      {/* Manual Payment Confirmation Modal */}
      <Modal
        isOpen={showConfirmationModal}
        onClose={() => setShowConfirmationModal(false)}
        title="Confirm Payment"
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="w-6 h-6 text-success-500 mt-0.5" />
            <div>
              <p className="text-gray-700">
                Have you completed the payment for <strong>{selectedPackage?.name}</strong>?
              </p>
              <p className="text-sm text-gray-500 mt-2">
                Total amount: <strong>{selectedPackage?.amount ? `$${selectedPackage.amount.toFixed(2)} ${selectedPackage.currency}` : 'Calculated at checkout'}</strong>
              </p>
              <p className="page-subtitle mt-1">
                Credits to receive: <strong>{selectedPackage?.credits}</strong>
              </p>
              {manualPaymentData?.transaction_id && (
                <p className="page-subtitle mt-1">
                  Reference ID: <strong>{manualPaymentData.transaction_id}</strong>
                </p>
              )}
            </div>
          </div>

          <div className="bg-warning-50 p-3 rounded-lg">
            <p className="text-sm text-warning-700">
              <strong>Note:</strong> Our team will verify your payment and add the credits to your account within the next 24 hours. We may contact you for verification.
            </p>
          </div>

          <div className="pt-4 flex justify-end gap-3 border-t border-gray-200">
            <Button
              variant="secondary"
              onClick={() => setShowConfirmationModal(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirmManualPayment}
              className="btn-success"
            >
              <CheckCircle className="w-4 h-4 mr-2" />
              Yes, I Paid
            </Button>
          </div>
        </div>
      </Modal>
    </PageShell>
  );
}
