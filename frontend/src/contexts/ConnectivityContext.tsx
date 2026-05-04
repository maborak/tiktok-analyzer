import React, { createContext, useContext } from 'react';
import { useApiConnectivity } from '../hooks/useApiConnectivity';
import { connectivityConfig } from '../config/env';

interface ConnectivityContextType {
  isOnline: boolean;
  lastCheck: Date | null;
  error: any | null;
  isChecking: boolean;
  checkNow: () => void;
  pause: () => void;
  resume: () => void;
}

const ConnectivityContext = createContext<ConnectivityContextType | undefined>(undefined);

interface ConnectivityProviderProps {
  children: React.ReactNode;
  checkInterval?: number;
  enabled?: boolean;
}

export function ConnectivityProvider({ 
  children, 
  checkInterval = connectivityConfig.checkInterval,
  enabled = true 
}: ConnectivityProviderProps) {
  const connectivity = useApiConnectivity({
    checkInterval,
    enabled,
    onStatusChange: (status) => {
      // You can add global side effects here, like showing toasts
      // when the API comes back online or goes offline
      console.log('API Connectivity changed:', status);
    }
  });

  return (
    <ConnectivityContext.Provider value={connectivity}>
      {children}
    </ConnectivityContext.Provider>
  );
}

export function useConnectivity() {
  const context = useContext(ConnectivityContext);
  if (context === undefined) {
    throw new Error('useConnectivity must be used within a ConnectivityProvider');
  }
  return context;
} 