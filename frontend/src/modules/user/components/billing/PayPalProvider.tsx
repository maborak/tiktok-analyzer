import React from 'react';
import { PayPalScriptProvider } from '@paypal/react-paypal-js';

interface PayPalProviderProps {
  children: React.ReactNode;
  clientId: string;
  mode: 'sandbox' | 'live';
}

export function PayPalProvider({ children, clientId, mode }: PayPalProviderProps) {
  // If no client ID is provided, show a message
  if (!clientId) {
    return (
      <div className="p-4 bg-warning-50 border border-warning-200 rounded-lg">
        <p className="text-sm text-warning-700">
          PayPal configuration is missing. Please try again.
        </p>
      </div>
    );
  }

  const initialOptions = {
    clientId: clientId,
    'client-id': clientId,
    currency: 'USD',
    intent: 'capture',
    ...(mode === 'sandbox' && {
      'enable-funding': 'card',
      'disable-funding': 'paylater,venmo',
    }),
  };

  return (
    <PayPalScriptProvider options={initialOptions}>
      {children}
    </PayPalScriptProvider>
  );
}
