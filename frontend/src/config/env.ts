/**
 * Environment Configuration
 * 
 * This file centralizes all environment variable access and provides
 * type-safe configuration with sensible defaults.
 */

export interface AppConfig {
  api: {
    baseUrl: string;
    timeout: number; // in milliseconds
    maxRetries: number;
    retryDelay: number; // in milliseconds
    defaultCacheTtl: number; // in milliseconds
  };
  connectivity: {
    checkInterval: number; // in milliseconds
  };
  app: {
    name: string;
    legalEntity: string;
    domain: string;
    supportEmail: string;
    version: string;
    /** Deployment mode -- controls which route groups are registered. */
    mode: 'full' | 'client' | 'admin';
    /**
     * Prefix segment for all admin/management routes.
     * Defaults to 'management' for local dev.
     * Set VITE_ADMIN_ROUTE_PREFIX to a random string in production to obfuscate paths.
     */
    adminRoutePrefix: string;
    /**
     * Prefix segment for all user account routes.
     * Defaults to 'account' for local dev.
     * Set VITE_USER_ROUTE_PREFIX to a random string in production to obfuscate paths.
     */
    userRoutePrefix: string;
    pageSizeOptions: number[];
    pageSizeDefault: number;
  };
  debug: {
    enabled: boolean;
    logLevel: 'debug' | 'info' | 'warn' | 'error';
  };
  ui: {
    loaderType: 'simple' | 'progress_bar' | 'skeleton' | 'shimmer';
  };
}

/**
 * Validate configuration values
 */
function validateConfig(config: AppConfig): void {
  // Validate API URL
  try {
    new URL(config.api.baseUrl);
  } catch {
    console.warn(`⚠️  Invalid API URL: ${config.api.baseUrl}. Using default.`);
  }

  // Validate timeout (convert from seconds to milliseconds for validation)
  const timeoutSeconds = config.api.timeout / 1000;
  if (timeoutSeconds < 1) {
    console.warn(`⚠️  API timeout too low: ${timeoutSeconds}s. Recommend at least 1s.`);
  }

  // Validate connectivity check interval (convert from seconds to milliseconds for validation)
  const intervalSeconds = config.connectivity.checkInterval / 1000;
  if (intervalSeconds < 5) {
    console.warn(`⚠️  Connectivity check interval too low: ${intervalSeconds}s. Recommend at least 5s.`);
  }

  // Validate log level
  const validLogLevels = ['debug', 'info', 'warn', 'error'];
  if (!validLogLevels.includes(config.debug.logLevel)) {
    console.warn(`⚠️  Invalid log level: ${config.debug.logLevel}. Using 'info'.`);
  }
}

/**
 * Get configuration from environment variables with fallbacks
 */
function createConfig(): AppConfig {
  // Try to get API URL from environment, with multiple fallback options
  let apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

  // If no environment variable, try to detect ngrok or local development
  if (!apiBaseUrl) {
    // Check if we're running on ngrok
    if (window.location.hostname.includes('ngrok')) {
      // For ngrok, we need to use the ngrok URL for the API
      const ngrokUrl = window.location.origin.replace('https://', 'http://');
      apiBaseUrl = ngrokUrl.replace(window.location.port, '8000');
      console.log('🔧 Detected ngrok deployment, using API URL:', apiBaseUrl);
    } else {
      // Default to localhost for development
      apiBaseUrl = 'http://localhost:8000';
    }
  }

  const config: AppConfig = {
    api: {
      baseUrl: apiBaseUrl,
      // Convert seconds to milliseconds with robust fallback
      timeout: (() => {
        const envValue = import.meta.env.VITE_API_TIMEOUT;
        if (!envValue) return 30000;
        const parsed = parseInt(envValue, 10);
        return isNaN(parsed) ? 30000 : parsed * 1000;
      })(),
      maxRetries: parseInt(import.meta.env.VITE_API_MAX_RETRIES || '3', 10),
      retryDelay: parseInt(import.meta.env.VITE_API_RETRY_DELAY || '1000', 10),
      defaultCacheTtl: parseInt(import.meta.env.VITE_API_CACHE_TTL || '0', 10),
    },
    connectivity: {
      // Convert seconds to milliseconds
      checkInterval: parseInt(import.meta.env.VITE_CONNECTIVITY_CHECK_INTERVAL || '60', 10) * 1000,
    },
    app: {
      name: import.meta.env.VITE_APP_NAME || 'Phoveus',
      legalEntity: import.meta.env.VITE_APP_LEGAL_ENTITY || 'Phoveus',
      domain: import.meta.env.VITE_APP_DOMAIN || 'legalai.com',
      supportEmail: import.meta.env.VITE_SUPPORT_EMAIL || 'support@legalai.com',
      version: import.meta.env.VITE_APP_VERSION || '1.0.0',
      pageSizeOptions: (import.meta.env.VITE_PAGE_SIZE_OPTIONS || '10,20,50').split(',').map(Number),
      pageSizeDefault: parseInt(import.meta.env.VITE_PAGE_SIZE_DEFAULT || '20', 10),
      mode: (import.meta.env.VITE_APP_MODE || 'full') as AppConfig['app']['mode'],
      adminRoutePrefix: import.meta.env.VITE_ADMIN_ROUTE_PREFIX || 'management',
      userRoutePrefix: import.meta.env.VITE_USER_ROUTE_PREFIX || 'account',
    },
    debug: {
      enabled: import.meta.env.VITE_DEBUG_MODE === 'true' || import.meta.env.DEV === true,
      logLevel: (import.meta.env.VITE_LOG_LEVEL || 'info') as AppConfig['debug']['logLevel'],
    },
    ui: {
      loaderType: (import.meta.env.VITE_LOADER_TYPE || 'progress_bar') as AppConfig['ui']['loaderType'],
    },
  };

  // Validate configuration in development
  if (config.debug.enabled) {
    validateConfig(config);
  }

  return config;
}

// Export the configuration instance
export const config = createConfig();

// Export individual config sections for convenience
export const apiConfig = config.api;
export const connectivityConfig = config.connectivity;
export const appConfig = config.app;
export const debugConfig = config.debug;
export const uiConfig = config.ui;

// Google OAuth Configuration
export const googleConfig = {
  clientId: import.meta.env.VITE_GOOGLE_CLIENT_ID || '',
  enabled: !!import.meta.env.VITE_GOOGLE_CLIENT_ID,
};

// GitHub OAuth Configuration
export const githubConfig = {
  clientId: import.meta.env.VITE_GITHUB_CLIENT_ID || '',
  enabled: !!import.meta.env.VITE_GITHUB_CLIENT_ID,
};

// Facebook OAuth Configuration
export const facebookConfig = {
  appId: import.meta.env.VITE_FACEBOOK_APP_ID || '',
  enabled: !!import.meta.env.VITE_FACEBOOK_APP_ID,
};

export const captchaConfig = {
  provider: (import.meta.env.VITE_CAPTCHA_PROVIDER || 'none') as 'none' | 'recaptcha_v3' | 'turnstile',
  recaptchaSiteKey: import.meta.env.VITE_RECAPTCHA_SITE_KEY || '',
  turnstileSiteKey: import.meta.env.VITE_TURNSTILE_SITE_KEY || '',
};

// Payment Provider Configuration
export const paymentConfig = {
  paypal: {
    clientId: import.meta.env.VITE_PAYPAL_CLIENT_ID || '',
    sandbox: import.meta.env.VITE_PAYPAL_SANDBOX !== 'false', // Default to sandbox mode
  },
  stripe: {
    publishableKey: import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || '',
  }
};

// Utility functions
export const isProduction = () => import.meta.env.PROD;
export const isDevelopment = () => import.meta.env.DEV;
export const getEnvironment = () => import.meta.env.MODE;

// Configuration info function for debugging
export const logConfigInfo = () => {
  if (debugConfig.enabled) {
    console.group('🔧 App Configuration');
    console.log('Environment:', getEnvironment());
    console.log('API Base URL:', apiConfig.baseUrl);

    // Add timeout debugging
    const timeoutEnvValue = import.meta.env.VITE_API_TIMEOUT;
    console.log('⏱️  API Timeout:');
    console.log('  - Environment Variable:', timeoutEnvValue);
    console.log('  - Interpreted as seconds:', (apiConfig.timeout / 1000) + 's');
    console.log('  - Converted to milliseconds:', apiConfig.timeout + 'ms');
    console.log('  - Max Retries:', apiConfig.maxRetries);
    console.log('  - Retry Delay:', apiConfig.retryDelay + 'ms');

    console.log('App Name:', appConfig.name);
    console.log('App Version:', appConfig.version);
    console.log('Debug Mode:', debugConfig.enabled);
    console.log('Log Level:', debugConfig.logLevel);
    console.log('Current Hostname:', window.location.hostname);
    console.log('Current Origin:', window.location.origin);

    // Add connectivity debugging
    const envValue = import.meta.env.VITE_CONNECTIVITY_CHECK_INTERVAL;
    console.log('🔗 Connectivity Check Interval:');
    console.log('  - Environment Variable:', envValue);
    console.log('  - Interpreted as seconds:', envValue + 's');
    console.log('  - Converted to milliseconds:', connectivityConfig.checkInterval + 'ms');
    console.log('  - Actual interval:', (connectivityConfig.checkInterval / 1000) + 's');

    console.groupEnd();
  }
};

// Log configuration on import in development
logConfigInfo();
