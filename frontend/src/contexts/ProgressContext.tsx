import React, { createContext, useContext, useState, useCallback } from 'react';
import type { ReactNode } from 'react';

export interface ProgressState {
  isActive: boolean;
  type: 'bulk-upload' | 'single-product' | 'batch-check' | null;
  current: number;
  total: number;
  message: string;
  currentItem?: string;
  success: number;
  failed: number;
  canCancel: boolean;
  onCancel?: () => void;
}

interface ProgressContextType {
  progress: ProgressState;
  startProgress: (config: Omit<ProgressState, 'isActive'>) => void;
  updateProgress: (updates: Partial<ProgressState>) => void;
  stopProgress: () => void;
  cancelProgress: () => void;
}

const ProgressContext = createContext<ProgressContextType | undefined>(undefined);

export function useProgress() {
  const context = useContext(ProgressContext);
  if (context === undefined) {
    throw new Error('useProgress must be used within a ProgressProvider');
  }
  return context;
}

interface ProgressProviderProps {
  children: ReactNode;
}

export function ProgressProvider({ children }: ProgressProviderProps) {
  const [progress, setProgress] = useState<ProgressState>({
    isActive: false,
    type: null,
    current: 0,
    total: 0,
    message: '',
    success: 0,
    failed: 0,
    canCancel: false,
  });

  const startProgress = useCallback((config: Omit<ProgressState, 'isActive'>) => {
    setProgress({
      ...config,
      isActive: true,
    });
  }, []);

  const updateProgress = useCallback((updates: Partial<ProgressState>) => {
    setProgress(prev => ({
      ...prev,
      ...updates,
    }));
  }, []);

  const stopProgress = useCallback(() => {
    setProgress(prev => ({
      ...prev,
      isActive: false,
      type: null,
      current: prev.current, // Keep the final current value
      total: prev.total, // Keep the final total value
      message: prev.message, // Keep the final message
      currentItem: undefined,
      success: prev.success, // Keep the final success count
      failed: prev.failed, // Keep the final failed count
      canCancel: false,
      onCancel: undefined,
    }));
  }, []);

  const cancelProgress = useCallback(() => {
    if (progress.onCancel) {
      progress.onCancel();
    }
    stopProgress();
  }, [progress, stopProgress]);

  const value: ProgressContextType = React.useMemo(() => ({
    progress,
    startProgress,
    updateProgress,
    stopProgress,
    cancelProgress,
  }), [progress, startProgress, updateProgress, stopProgress, cancelProgress]);

  return (
    <ProgressContext.Provider value={value}>
      {children}
    </ProgressContext.Provider>
  );
} 