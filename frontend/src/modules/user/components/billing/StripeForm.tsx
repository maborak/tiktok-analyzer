import React, { useState, useMemo } from 'react';
import {
  CardNumberElement,
  CardExpiryElement,
  CardCvcElement,
  useStripe,
  useElements
} from '@stripe/react-stripe-js';
import type { StripeCardElementOptions } from '@stripe/stripe-js';
import { userBillingApi } from '../../services/billing';
import type { CreditPackage, PaymentProvider } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { useTheme } from '@/contexts/ThemeContext';
import toast from 'react-hot-toast';
import { Loader2, Lock } from 'lucide-react';

interface StripeFormProps {
  selectedPackage: CreditPackage;
  clientSecret: string;
  onSuccess: (transactionId: string, invoiceId: string, creditsAdded: number) => void;
  onError: (message: string) => void;
}

export function StripeForm({ selectedPackage, clientSecret, onSuccess, onError }: StripeFormProps) {
  const stripe = useStripe();
  const elements = useElements();
  const { resolved } = useTheme();
  const [isProcessing, setIsProcessing] = useState(false);
  const [cardError, setCardError] = useState<string | null>(null);
  const [cardholderName, setCardholderName] = useState('');

  const cardElementOptions: StripeCardElementOptions = useMemo(() => ({
    style: {
      base: {
        fontSize: '16px',
        color: resolved === 'dark' ? '#e5e5e5' : '#424770',
        '::placeholder': {
          color: resolved === 'dark' ? '#737373' : '#aab7c4',
        },
        fontFamily: 'system-ui, -apple-system, sans-serif',
      },
      invalid: {
        color: resolved === 'dark' ? '#f87171' : '#9e2146',
      },
    },
  }), [resolved]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!stripe || !elements) {
      toast.error('Stripe has not loaded yet. Please wait a moment.');
      return;
    }

    setIsProcessing(true);
    setCardError(null);

    try {
      // Confirm the payment with Stripe
      const { error, paymentIntent } = await stripe.confirmCardPayment(clientSecret, {
        payment_method: {
          card: elements.getElement(CardNumberElement)!,
          billing_details: {
            name: cardholderName || undefined,
          },
        },
      });

      if (error) {
        throw new Error(error.message || 'Payment failed');
      }

      if (paymentIntent.status === 'succeeded') {
        // Capture payment on our backend
        const captureResponse = await userBillingApi.capturePayment({
          order_id: paymentIntent.id,
          provider: 'STRIPE' as PaymentProvider
        });

        if (!captureResponse.success || !captureResponse.data) {
          throw new Error(captureResponse.message || 'Error al capturar el pago');
        }

        if (captureResponse.data.status?.toLowerCase() === 'completed') {
          onSuccess(captureResponse.data.transaction_id, captureResponse.data.invoice_id, captureResponse.data.credits_added);
        } else {
          throw new Error('El pago no fue completado. Por favor intenta de nuevo.');
        }
      } else {
        throw new Error(`Estado del pago: ${paymentIntent.status}. Por favor intenta de nuevo.`);
      }
    } catch (error: any) {
      console.error('Stripe payment error:', error);
      setCardError(error.message || 'Payment failed');
      toast.error(error.message || 'Payment failed');
      onError(error.message || 'Payment failed');
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Cardholder Name */}
      <div>
        <label className="label">
          Nombre del Titular
        </label>
        <Input
          type="text"
          value={cardholderName}
          onChange={(e) => setCardholderName(e.target.value)}
          placeholder="Nombre en la tarjeta"
        />
      </div>

      {/* Card Number */}
      <div>
        <label className="label">
          Card Number
        </label>
        <div className="bg-white p-3 rounded-md border border-gray-200 focus-within:border-primary-500 focus-within:ring-1 focus-within:ring-primary-500">
          <CardNumberElement options={cardElementOptions} />
        </div>
      </div>

      {/* Expiry and CVC */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">
            Vencimiento
          </label>
          <div className="bg-white p-3 rounded-md border border-gray-200 focus-within:border-primary-500 focus-within:ring-1 focus-within:ring-primary-500">
            <CardExpiryElement options={cardElementOptions} />
          </div>
        </div>
        <div>
          <label className="label">
            CVC
          </label>
          <div className="bg-white p-3 rounded-md border border-gray-200 focus-within:border-primary-500 focus-within:ring-1 focus-within:ring-primary-500">
            <CardCvcElement options={cardElementOptions} />
          </div>
        </div>
      </div>

      {/* Test Card Info */}
      <div className="bg-primary-50 p-2 rounded text-xs text-primary-700">
        <strong>Test:</strong> 4242 4242 4242 4242 | 12/25 | 123
      </div>

      {/* Error Display */}
      {cardError && (
        <div className="p-3 bg-error-50 border border-error-200 rounded-md">
          <p className="text-sm text-error-700">{cardError}</p>
        </div>
      )}

      {/* Submit Button */}
      <Button
        type="submit"
        disabled={!stripe || isProcessing}
        className="w-full"
      >
        {isProcessing ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Procesando...
          </>
        ) : (
          <>
            <Lock className="w-4 h-4 mr-2" />
            Pagar ${selectedPackage.amount.toFixed(2)}
          </>
        )}
      </Button>
    </form>
  );
}
