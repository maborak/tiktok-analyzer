import axios from 'axios';
import type { AxiosRequestConfig, AxiosResponse } from 'axios';
import { apiConfig } from '../config/env';
import { clearInFlight, createRequestKey, getCached, getInFlight, setCached, setInFlight } from './cache';

// Module augmentation for custom retry fields on request config
declare module 'axios' {
  interface AxiosRequestConfig {
    __retryCount?: number;
    maxRetries?: number;
  }
  interface InternalAxiosRequestConfig {
    __retryCount?: number;
    maxRetries?: number;
  }
}

export type RequestOptions = {
  signal?: AbortSignal;
  cacheTtlMs?: number;
  dedupe?: boolean;
  cacheKey?: string;
  maxRetries?: number;  // Override default retry count (use 0 to disable)
};

const httpClient = axios.create({
  baseURL: apiConfig.baseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: apiConfig.timeout,
  withCredentials: false,
});

// Helper to check if a request should be retried
const shouldRetry = (error: any) => {
  const { config, response } = error;

  // Don't retry if we don't have a config or if we've reached max retries
  if (!config || config.__retryCount >= (config.maxRetries ?? apiConfig.maxRetries)) {
    return false;
  }

  // Only retry on idempotent methods
  const idempotentMethods = ['get', 'put', 'delete', 'head', 'options'];
  if (!idempotentMethods.includes(config.method?.toLowerCase() || '')) {
    return false;
  }

  // Retry on network errors (no response)
  if (!response) {
    return true;
  }

  // Retry on 5xx server errors (except 501 Not Implemented)
  if (response.status >= 500 && response.status !== 501) {
    return true;
  }

  // Retry on 429 Too Many Requests
  if (response.status === 429) {
    return true;
  }

  return false;
};

httpClient.interceptors.request.use(
  (config) => {
    // Initialize retry count if not present
    if ((config as any).__retryCount === undefined) {
      (config as any).__retryCount = 0;
    }

    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    } else {
      delete config.headers.Authorization;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Token refresh queue — prevents parallel refresh races
let isRefreshing = false;
let refreshSubscribers: Array<(token: string) => void> = [];
let refreshRejectSubscribers: Array<(reason: any) => void> = [];

// Session-expired re-login queue — waits for user to log in via modal
let isWaitingForReLogin = false;
let reLoginSubscribers: Array<(token: string) => void> = [];
let reLoginRejectSubscribers: Array<(reason: any) => void> = [];

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach(cb => cb(token));
  refreshSubscribers = [];
  refreshRejectSubscribers = [];
}

function onTokenRefreshFailed(reason: any) {
  refreshRejectSubscribers.forEach(cb => cb(reason));
  refreshSubscribers = [];
  refreshRejectSubscribers = [];
}

function subscribeTokenRefresh(resolve: (token: string) => void, reject: (reason: any) => void) {
  refreshSubscribers.push(resolve);
  refreshRejectSubscribers.push(reject);
}

/**
 * Called by AuthContext after the user successfully re-logs in via the session-expired modal.
 * Replays all queued requests with the new token.
 */
export function onReLoginSuccess(token: string) {
  isWaitingForReLogin = false;
  reLoginSubscribers.forEach(cb => cb(token));
  reLoginSubscribers = [];
  reLoginRejectSubscribers = [];
}

/**
 * Called if the user dismisses the session-expired modal without logging in (e.g. navigates away).
 */
export function onReLoginDismissed() {
  isWaitingForReLogin = false;
  reLoginRejectSubscribers.forEach(cb => cb(new Error('Session expired — user did not re-login')));
  reLoginSubscribers = [];
  reLoginRejectSubscribers = [];
}

function waitForReLogin(config: any): Promise<any> {
  if (!isWaitingForReLogin) {
    isWaitingForReLogin = true;
    console.log('[API Interceptor] Session expired — showing re-login modal');
    window.dispatchEvent(new CustomEvent('auth:session-expired'));
  }

  return new Promise((resolve, reject) => {
    reLoginSubscribers.push(token => {
      config.headers['Authorization'] = `Bearer ${token}`;
      resolve(httpClient(config));
    });
    reLoginRejectSubscribers.push(reject);
  });
}

httpClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config } = error;

    // Handle retry logic
    if (shouldRetry(error)) {
      config.__retryCount += 1;

      // For 429s, prefer the server's retry_after value over fixed backoff
      let delay: number;
      const serverRetryAfter = error.response?.status === 429
        ? (error.response?.data?.retry_after ?? error.response?.headers?.['retry-after'])
        : null;

      if (serverRetryAfter && Number(serverRetryAfter) > 0) {
        delay = Number(serverRetryAfter) * 1000;
      } else {
        const retryDelay = config.retryDelay ?? apiConfig.retryDelay;
        delay = retryDelay * Math.pow(2, config.__retryCount - 1);
      }

      console.log(`[API Client] Retrying request (${config.__retryCount}/${config.maxRetries ?? apiConfig.maxRetries}) in ${delay}ms: ${config.url}`);

      await new Promise(resolve => setTimeout(resolve, delay));
      return httpClient(config);
    }
    // Handle 401 Unauthorized - token expired or invalid
    if (error.response?.status === 401) {
      const url = error.response.config?.url || '';

      // Don't handle 401 on auth endpoints (expected for invalid credentials / expired refresh)
      const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/register') ||
        url.includes('/auth/token') || url.includes('/auth/refresh') || url.includes('/auth/logout');

      console.log(`[API Interceptor] 401 Unauthorized for ${url}. Current path: ${window.location.pathname}`);

      if (!isAuthEndpoint && window.location.pathname !== '/login') {
        const storedRefreshToken = localStorage.getItem('refresh_token');

        if (!storedRefreshToken) {
          return waitForReLogin(config);
        }

        // If a refresh is already in-flight, queue this request and wait
        if (isRefreshing) {
          return new Promise((resolve, reject) => {
            subscribeTokenRefresh(
              token => {
                config.headers['Authorization'] = `Bearer ${token}`;
                resolve(httpClient(config));
              },
              reject
            );
          });
        }

        isRefreshing = true;
        try {
          const res = await httpClient.post('/auth/refresh', { refresh_token: storedRefreshToken });
          const tokens = res.data?.data?.tokens;
          const newAccessToken: string = tokens?.access_token;
          const newRefreshToken: string = tokens?.refresh_token;

          localStorage.setItem('auth_token', newAccessToken);
          if (newRefreshToken) localStorage.setItem('refresh_token', newRefreshToken);
          httpClient.defaults.headers.common['Authorization'] = `Bearer ${newAccessToken}`;

          onTokenRefreshed(newAccessToken);
          config.headers['Authorization'] = `Bearer ${newAccessToken}`;
          return httpClient(config);
        } catch {
          onTokenRefreshFailed(new Error('Token refresh failed'));
          return waitForReLogin(config);
        } finally {
          isRefreshing = false;
        }
      }
    }

    // Handle 403 Forbidden - no permission
    if (error.response?.status === 403) {
      const url = error.response.config?.url || '';
      window.dispatchEvent(new CustomEvent('auth:forbidden', {
        detail: {
          status: error.response.status,
          message: error.response.data?.detail || 'Access denied',
          url,
        },
      }));
    }

    return Promise.reject(error);
  }
);

export const setApiBaseUrl = (baseURL: string) => {
  httpClient.defaults.baseURL = baseURL;
};

export const apiRequest = async <T>(
  config: AxiosRequestConfig,
  options: RequestOptions = {}
): Promise<T> => {
  const method = config.method || 'GET';
  const url = config.url || '';
  const key = options.cacheKey || createRequestKey(method, url, config.params, config.data);

  if (options.cacheTtlMs) {
    const cached = getCached<T>(key);
    if (cached) {
      return cached;
    }
  }

  if (options.dedupe) {
    const existing = getInFlight<T>(key);
    if (existing) {
      return existing;
    }
  }

  const requestPromise = httpClient.request<T>({
    ...config,
    maxRetries: options.maxRetries,
    signal: options.signal,
  }).then((response: AxiosResponse<T>) => {
    if (options.cacheTtlMs) {
      setCached(key, response.data, options.cacheTtlMs);
    }
    return response.data;
  }).finally(() => {
    if (options.dedupe) {
      clearInFlight(key);
    }
  });

  if (options.dedupe) {
    setInFlight(key, requestPromise);
  }

  return requestPromise;
};
