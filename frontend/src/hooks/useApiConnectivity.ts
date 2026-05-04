import { useState, useEffect, useCallback, useRef } from 'react';
import { getApiClient } from '../services/apiClientManager';
import { apiConfig, appConfig } from '../config/env';

interface ConnectivityStatus {
  isOnline: boolean;
  lastCheck: Date | null;
  error: any | null;
  isChecking: boolean;
}

interface UseApiConnectivityOptions {
  checkInterval?: number; // milliseconds, default 60 seconds
  enabled?: boolean; // whether to enable automatic checking
  onStatusChange?: (status: ConnectivityStatus) => void;
}

export function useApiConnectivity(options: UseApiConnectivityOptions = {}) {
  const {
    checkInterval = 60000, // 60 seconds default (in milliseconds)
    enabled = true,
    onStatusChange
  } = options;

  const [status, setStatus] = useState<ConnectivityStatus>({
    isOnline: true, // Assume online initially
    lastCheck: null,
    error: null,
    isChecking: false
  });

  const intervalRef = useRef<number | null>(null);
  const isMountedRef = useRef(true);
  const isCheckingRef = useRef(false);

  // Check connectivity function
  const checkConnectivity = useCallback(async () => {
    if (!enabled || isCheckingRef.current) return;

    isCheckingRef.current = true;
    console.log('🔍 Checking API connectivity...', new Date().toISOString());
    setStatus(prev => ({ ...prev, isChecking: true }));

    try {
      // Use a simple health check endpoint with a shorter timeout for faster response
      const tempClient = getApiClient();
      const apiTimeout = apiConfig.timeout;

      await Promise.race([
        tempClient.healthCheck(),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('Health check timeout')), apiTimeout)
        )
      ]);

      const newStatus: ConnectivityStatus = {
        isOnline: true,
        lastCheck: new Date(),
        error: null,
        isChecking: false
      };

      console.log('✅ API connectivity check successful');
      setStatus(newStatus);
      onStatusChange?.(newStatus);
    } catch (error: any) {
      let errorMessage = error.message;

      // Provide more specific error messages for different failure types
      if (error.message?.includes('Health endpoint not found')) {
        errorMessage = 'This is not our API server - health endpoint missing';
      } else if (error.message?.includes('not our API')) {
        errorMessage = `Connected to wrong server - this is not our ${appConfig.name} API`;
      } else if (error.response?.status === 404) {
        errorMessage = 'API endpoint not found - wrong server or API not running';
      } else if (error.code === 'ECONNREFUSED') {
        errorMessage = 'Connection refused - server not running or wrong port';
      } else if (error.message?.includes('Network Error')) {
        errorMessage = 'Network error - cannot reach the server';
      } else if (error.message?.includes('timeout')) {
        errorMessage = 'Connection timeout - server not responding';
      }

      const newStatus: ConnectivityStatus = {
        isOnline: false,
        lastCheck: new Date(),
        error: { ...error, message: errorMessage },
        isChecking: false
      };

      console.log('❌ API connectivity check failed:', errorMessage);
      setStatus(newStatus);
      onStatusChange?.(newStatus);
    } finally {
      isCheckingRef.current = false;
    }
  }, [enabled, getApiClient]);

  // Manual check function
  const checkNow = useCallback(() => {
    checkConnectivity();
  }, [checkConnectivity]);

  // Start periodic checking
  useEffect(() => {
    if (!enabled) return;

    // Clear any existing interval first
    if (intervalRef.current) {
      console.log('🛑 Clearing existing connectivity check interval');
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    console.log('🔄 Setting up connectivity check interval:', checkInterval / 1000, 'seconds');

    // Initial check
    checkConnectivity();

    // Set up interval
    intervalRef.current = setInterval(checkConnectivity, checkInterval);

    return () => {
      if (intervalRef.current) {
        console.log('🛑 Clearing connectivity check interval');
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, checkInterval, checkConnectivity]);

  // Listen for API URL changes
  useEffect(() => {
    const handleApiUrlChange = () => {
      console.log('🔄 API URL changed, triggering connectivity check');
      checkConnectivity();
    };

    window.addEventListener('apiUrlChanged', handleApiUrlChange);
    return () => {
      window.removeEventListener('apiUrlChanged', handleApiUrlChange);
    };
  }, [checkConnectivity]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  // Pause/resume functionality
  const pause = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const resume = useCallback(() => {
    if (enabled && !intervalRef.current) {
      checkConnectivity();
      intervalRef.current = setInterval(checkConnectivity, checkInterval);
    }
  }, [enabled, checkInterval]);

  return {
    ...status,
    checkNow,
    pause,
    resume
  };
} 