/**
 * Application Configuration
 *
 * Centralized configuration for the entire application including API endpoints,
 * organized by URI groups with method and endpoint definitions.
 */

/**
 * HTTP Methods enum for type safety
 */
export const HTTP_METHODS = {
  GET: 'GET',
  POST: 'POST',
  PUT: 'PUT',
  DELETE: 'DELETE',
  PATCH: 'PATCH',
} as const;

export type HttpMethod = typeof HTTP_METHODS[keyof typeof HTTP_METHODS];

/**
 * API Endpoint structure
 */
export interface ApiEndpoint {
  method: HttpMethod;
  endpoint: string | ((...args: any[]) => string);
  description?: string;
}

/**
 * Main Application Configuration
 */
export const APP_CONFIG = {
  /**
   * API Configuration grouped by URI patterns
   */
  api: {
    /**
     * General API endpoints (/)
     */
    general: {
      root: {
        method: HTTP_METHODS.GET,
        endpoint: '/',
        description: 'API root endpoint'
      },
      healthCheck: {
        method: HTTP_METHODS.GET,
        endpoint: '/health',
        description: 'Health check endpoint'
      }
    },
  },

  /**
   * Application settings
   */
  app: {
    name: import.meta.env.VITE_APP_NAME || 'Phoveus',
    version: import.meta.env.VITE_APP_VERSION || '1.0.0',

    // Theme configuration
    themes: {
      default: 'default',
      storageKey: 'selected-theme'
    },

    // UI Configuration
    ui: {
      itemsPerPage: 20,

      // Toast notifications
      toast: {
        position: 'top-right',
        duration: 4000
      },

      // Pagination settings
      pagination: {
        defaultPageSize: 20,
        pageSizeOptions: [10, 20, 50, 100]
      }
    },

  }
} as const;

/**
 * Helper function to get an API endpoint
 */
export const getApiEndpoint = (group: keyof typeof APP_CONFIG.api, endpoint: string): ApiEndpoint | undefined => {
  const apiGroup = APP_CONFIG.api[group] as Record<string, ApiEndpoint>;
  return apiGroup?.[endpoint];
};

/**
 * Helper function to build complete endpoint URL
 */
export const buildEndpointUrl = (baseUrl: string, endpoint: string | ((...args: any[]) => string), ...args: any[]): string => {
  const endpointPath = typeof endpoint === 'function' ? endpoint(...args) : endpoint;
  return `${baseUrl.replace(/\/$/, '')}${endpointPath}`;
};

/**
 * Type definitions for better TypeScript support
 */
export type ApiGroups = keyof typeof APP_CONFIG.api;
export type GeneralEndpoints = keyof typeof APP_CONFIG.api.general;
