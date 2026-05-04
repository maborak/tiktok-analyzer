import { useState } from 'react';
import { PayPalButtons, usePayPalScriptReducer } from '@paypal/react-paypal-js';
import type { CreateOrderData, CreateOrderActions, OnApproveData, OnApproveActions } from '@paypal/paypal-js';
import { userBillingApi } from '../../services/billing';
import type { CreditPackage, PaymentProvider } from '@/types/api';
import toast from 'react-hot-toast';
import { Loader2 } from 'lucide-react';

interface PayPalButtonProps {
  selectedPackage: CreditPackage;
  orderId: string;
  onSuccess: (transactionId: string, invoiceId: string, creditsAdded: number) => void;
  onError: (message: string) => void;
}

export function PayPalButton({ selectedPackage: _selectedPackage, orderId, onSuccess, onError }: PayPalButtonProps) {
  const [{ isPending, isRejected }] = usePayPalScriptReducer();
  const [isProcessing, setIsProcessing] = useState(false);

  const createOrder = async (_data: CreateOrderData, _actions: CreateOrderActions) => {
    // Return the existing PayPal order ID from the backend
    // The order ID was already created when the checkout was initialized
    return Promise.resolve(orderId);
  };

  const onApprove = async (data: OnApproveData, _actions: OnApproveActions) => {
    setIsProcessing(true);
    try {
      // Capture payment on our backend immediately
      const captureResponse = await userBillingApi.capturePayment({
        order_id: data.orderID,
        provider: 'PAYPAL' as PaymentProvider
      });

      if (!captureResponse.success || !captureResponse.data) {
        throw new Error(captureResponse.message || 'Error capturing payment');
      }

      if (captureResponse.data.status?.toLowerCase() === 'completed') {
        onSuccess(captureResponse.data.transaction_id, captureResponse.data.invoice_id, captureResponse.data.credits_added);
      } else {
        throw new Error('Payment was not completed. Please try again.');
      }
    } catch (error: any) {
      console.error('Error capturing payment:', error);
      toast.error(error.message || 'Error processing payment');
      onError(error.message || 'Error capturing payment');
    } finally {
      setIsProcessing(false);
    }
  };

  const onCancel = () => {
    toast('Payment cancelled', { icon: 'ℹ️' });
  };

  const onErrorPayPal = (err: Record<string, unknown>) => {
    console.error('PayPal error:', err);
    toast.error('PayPal encountered an error. Please try again.');
    onError('An error occurred with PayPal');
  };

  if (isPending) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-6 h-6 animate-spin text-primary-600" />
        <span className="ml-2 text-gray-600">Loading PayPal...</span>
      </div>
    );
  }

  if (isRejected) {
    return (
      <div className="p-4 bg-error-50 border border-error-200 rounded-lg">
        <p className="text-error-700 text-sm">
          Error loading PayPal. Please refresh the page or try another payment method.
        </p>
      </div>
    );
  }

  return (
    <div className="relative">
      {isProcessing && (
        <div className="absolute inset-0 bg-white/80 flex items-center justify-center z-10 rounded-lg">
          <div className="flex items-center">
            <Loader2 className="w-6 h-6 animate-spin text-primary-600" />
            <span className="ml-2 text-gray-700 font-medium">Processing payment...</span>
          </div>
        </div>
      )}
      <PayPalButtons
        createOrder={createOrder}
        onApprove={onApprove}
        onCancel={onCancel}
        onError={onErrorPayPal}
        style={{
          layout: 'vertical',
          color: 'blue',
          shape: 'rect',
          label: 'paypal'
        }}
        disabled={isProcessing}
      />
    </div>
  );
}
