export type CacheEntry<T> = {
  value: T;
  expiresAt: number;
};

const responseCache = new Map<string, CacheEntry<unknown>>();
const inFlight = new Map<string, Promise<unknown>>();

export const getCached = <T>(key: string): T | null => {
  const entry = responseCache.get(key);
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    responseCache.delete(key);
    return null;
  }
  return entry.value as T;
};

export const setCached = <T>(key: string, value: T, ttlMs: number) => {
  responseCache.set(key, {
    value,
    expiresAt: Date.now() + ttlMs,
  });
};

export const getInFlight = <T>(key: string): Promise<T> | null => {
  return (inFlight.get(key) as Promise<T> | undefined) ?? null;
};

export const setInFlight = <T>(key: string, promise: Promise<T>) => {
  inFlight.set(key, promise);
};

export const clearInFlight = (key: string) => {
  inFlight.delete(key);
};

export const clearAllCache = () => {
  responseCache.clear();
  inFlight.clear();
};

export const invalidateCacheByPrefix = (prefix: string) => {
  for (const key of responseCache.keys()) {
    if (key.includes(prefix)) {
      responseCache.delete(key);
    }
  }
};

export const createRequestKey = (method: string, url: string, params?: unknown, data?: unknown) => {
  const serializedParams = params ? JSON.stringify(params) : '';
  const serializedData = data ? JSON.stringify(data) : '';
  return `${method.toUpperCase()}::${url}::${serializedParams}::${serializedData}`;
};
