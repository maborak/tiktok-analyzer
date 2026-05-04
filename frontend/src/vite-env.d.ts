/// <reference types="vite/client" />

interface ImportMetaEnv {
  // API Configuration
  readonly VITE_API_BASE_URL?: string
  readonly VITE_API_TIMEOUT?: string
  
  // App Configuration
  readonly VITE_APP_NAME?: string
  readonly VITE_APP_VERSION?: string
  // Connectivity Configuration
  readonly VITE_CONNECTIVITY_CHECK_INTERVAL?: string
  
  // Debug Configuration
  readonly VITE_DEBUG_MODE?: string
  readonly VITE_LOG_LEVEL?: 'debug' | 'info' | 'warn' | 'error'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
