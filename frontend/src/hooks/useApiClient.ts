import { useMemo } from 'react';
import { getApiClient, isApiClientReady } from '../services/apiClientManager';
import { useApiUrl } from '../contexts/ApiUrlContext';

export function useApiClient() {
  const { isInitialized } = useApiUrl();
  const isReady = useMemo(() => isInitialized && isApiClientReady(), [isInitialized]);

  const getClient = () => {
    if (!isReady) {
      console.warn('⚠️ API client not ready yet, returning default client');
    }
    return getApiClient();
  };

  return {
    client: getClient(),
    isReady,
    isInitialized
  };
} 