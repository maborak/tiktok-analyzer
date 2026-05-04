import { GoogleOAuthProvider } from '@react-oauth/google';
import { googleConfig } from '../config/env';
import type { ReactNode } from 'react';

/**
 * Conditionally wraps children with GoogleOAuthProvider when Google OAuth is configured.
 * If VITE_GOOGLE_CLIENT_ID is not set, renders children directly without the provider.
 */
export function GoogleOAuthWrapper({ children }: { children: ReactNode }) {
  if (!googleConfig.enabled) {
    return <>{children}</>;
  }

  return (
    <GoogleOAuthProvider clientId={googleConfig.clientId}>
      {children}
    </GoogleOAuthProvider>
  );
}
