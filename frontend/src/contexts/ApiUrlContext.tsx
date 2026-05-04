import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';
import { apiConfig } from '../config/env';
import { initializeApiClientWithURL } from '../services/apiClientManager';

// Create a custom event for API URL changes
const API_URL_CHANGE_EVENT = 'apiUrlChanged';

export const triggerApiUrlChange = () => {
  window.dispatchEvent(new CustomEvent(API_URL_CHANGE_EVENT));
};

interface ApiUrlContextType {
  apiUrl: string;
  isInitialized: boolean;
}

const ApiUrlContext = createContext<ApiUrlContextType | undefined>(undefined);

interface ApiUrlProviderProps {
  children: ReactNode;
}

export function ApiUrlProvider({ children }: ApiUrlProviderProps) {
  const apiUrl = apiConfig.baseUrl;
  // Lazy init runs once on mount without a cascading render.
  const [isInitialized] = useState(() => {
    console.log('🚀 Initializing API client with environment URL:', apiConfig.baseUrl);
    initializeApiClientWithURL(apiConfig.baseUrl);
    return true;
  });

  return (
    <ApiUrlContext.Provider value={{
      apiUrl,
      isInitialized,
    }}>
      {children}
    </ApiUrlContext.Provider>
  );
}

export function useApiUrl() {
  const context = useContext(ApiUrlContext);
  if (context === undefined) {
    throw new Error('useApiUrl must be used within an ApiUrlProvider');
  }
  return context;
}
