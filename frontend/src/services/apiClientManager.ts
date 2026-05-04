import { DynamicApiClient } from './dynamicApiClient';
import { apiConfig } from '../config/env';
import { setApiBaseUrl } from '../api/client';

let apiClient: DynamicApiClient | undefined;
let currentBaseURL: string = '';

// Simple API client manager without connection pooling
function initializeApiClient(baseURL?: string): DynamicApiClient {
  const url = baseURL || apiConfig.baseUrl;
  currentBaseURL = url;
  setApiBaseUrl(url);
  return new DynamicApiClient(url);
}

// Get the current API client instance
export function getApiClient(): DynamicApiClient {
  if (!apiClient) {
    apiClient = initializeApiClient();
  }
  return apiClient;
}

// Check if API client is ready (has been properly initialized with correct URL)
export function isApiClientReady(): boolean {
  return apiClient !== undefined && currentBaseURL !== '';
}

// Initialize API client with a specific URL (for ApiUrlContext)
export function initializeApiClientWithURL(url: string): DynamicApiClient {
  currentBaseURL = url;
  setApiBaseUrl(url);
  
  if (apiClient) {
    apiClient.updateBaseURL(url);
  } else {
    apiClient = new DynamicApiClient(url);
  }
  
  return apiClient;
}

// Update the API client base URL
export function updateApiClientBaseURL(newBaseURL: string) {
  // Only update if the URL actually changed
  if (currentBaseURL !== newBaseURL) {
    currentBaseURL = newBaseURL;
    setApiBaseUrl(newBaseURL);
    
    if (apiClient) {
      apiClient.updateBaseURL(newBaseURL);
    } else {
      apiClient = new DynamicApiClient(newBaseURL);
    }
  }
}

// Check if API client is initialized
export function isApiClientInitialized(): boolean {
  return apiClient !== undefined;
}

// Get the current base URL
export function getCurrentBaseURL(): string {
  return currentBaseURL || apiConfig.baseUrl;
}

// Legacy functions for compatibility (no-op)
export function killAllConnections() {
  // No-op
}

export function getActiveConnectionCount(): number {
  return 0;
} 