import { useState, useRef, useEffect } from 'react';
import { useProgress } from '../contexts/ProgressContext';
import { Upload, CheckCircle, XCircle, Loader, X, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '../utils/cn';
import { ProgressBar } from './ui/ProgressBar';

export function ProgressIndicator() {
  const { progress, stopProgress, cancelProgress } = useProgress();
  const [isExpanded, setIsExpanded] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (progress.isActive) {
      const timer = setTimeout(() => setIsVisible(true), 0);
      return () => clearTimeout(timer);
    }
    const timer = setTimeout(() => setIsVisible(false), 2000);
    return () => clearTimeout(timer);
  }, [progress.isActive]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const getProgressIcon = () => {
    if (progress.failed > 0 && progress.success === 0) {
      return <XCircle className="w-5 h-5" />;
    }
    if (progress.success > 0 && progress.failed === 0) {
      return <CheckCircle className="w-5 h-5" />;
    }
    return <Upload className="w-5 h-5" />;
  };

  const getProgressColor = () => {
    if (progress.failed > 0 && progress.success === 0) {
      return 'text-error-600 bg-error-50 border-error-200';
    }
    if (progress.success > 0 && progress.failed === 0) {
      return 'text-success-600 bg-success-50 border-success-200';
    }
    return 'text-primary-600 bg-primary-50 border-primary-200';
  };

  const getProgressText = () => {
    if (progress.type === 'bulk-upload') {
      return 'Uploading items';
    } else if (progress.type === 'single-product') {
      return 'Verifying item';
    } else if (progress.type === 'batch-check') {
      return 'Verifying items';
    }
    return 'Processing...';
  };

  const handleClick = () => {
    if (progress.isActive) {
      setIsExpanded(!isExpanded);
    }
  };

  if (!isVisible) return null;

  const percentage = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;

  return (
    <div className="relative mx-2 sm:mx-4 min-h-10 flex items-center" ref={dropdownRef}>
      {/* Main Progress Button */}
      <button
        onClick={handleClick}
        className={cn(
          'flex items-center space-x-2 sm:space-x-3 px-2 sm:px-3 py-2 rounded-lg border-2 transition-all duration-200 hover:shadow-md',
          getProgressColor(),
          progress.isActive && 'animate-pulse',
          !isVisible && 'opacity-0 pointer-events-none'
        )}
      >
        <div className="flex items-center space-x-2">
          {progress.isActive ? (
            <Loader className="w-4 h-4 animate-spin" />
          ) : (
            getProgressIcon()
          )}
          <div className="text-left min-w-0">
            <div className="font-medium text-xs truncate">{getProgressText()}</div>
            <div className="text-xs opacity-75 truncate">
              {progress.isActive 
                ? `${progress.current} / ${progress.total} (${percentage}%)`
                : progress.total > 0 
                  ? 'COMPLETED'
                  : 'Done'
              }
            </div>
          </div>
        </div>
        
        <div className="flex items-center space-x-1 sm:space-x-2">
          {progress.success > 0 && (
            <div className="flex items-center space-x-1 text-success-600">
              <CheckCircle className="w-3 h-3 sm:w-4 sm:h-4" />
              <span className="text-xs font-medium hidden sm:inline">{progress.success}</span>
            </div>
          )}
          {progress.failed > 0 && (
            <div className="flex items-center space-x-1 text-error-600">
              <XCircle className="w-3 h-3 sm:w-4 sm:h-4" />
              <span className="text-xs font-medium hidden sm:inline">{progress.failed}</span>
            </div>
          )}
          {isExpanded ? (
            <ChevronUp className="w-3 h-3 sm:w-4 sm:h-4" />
          ) : (
            <ChevronDown className="w-3 h-3 sm:w-4 sm:h-4" />
          )}
        </div>
      </button>

      {/* Expanded Details */}
      {isExpanded && (
        <div className="absolute top-full right-0 mt-2 w-80 bg-white rounded-lg shadow-lg border border-gray-200 p-4 z-50">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-gray-900">Progress details</h3>
            <button
              onClick={() => setIsExpanded(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Progress Bar */}
          <div className="mb-4">
            <div className="flex justify-between text-xs text-gray-600 mb-1">
              <span>Progress</span>
              <span>{percentage}%</span>
            </div>
            <ProgressBar
              value={percentage}
              className="h-3 bg-gray-200"
              barClassName="bg-primary-500 h-3"
            />
          </div>

          {/* Status */}
          <div className="mb-4">
            <p className="text-sm text-gray-700 mb-2">{progress.message}</p>
            {progress.currentItem && (
              <div className="bg-gray-50 rounded p-2">
                <p className="text-xs text-gray-600 mb-1">Currently processing:</p>
                <p className="text-xs text-gray-800 font-mono truncate">
                  {progress.currentItem}
                </p>
              </div>
            )}
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-success-50 rounded p-2">
              <div className="flex items-center space-x-1">
                <CheckCircle className="w-3 h-3 text-success-600" />
                <span className="text-xs text-success-700">Successful</span>
              </div>
              <div className="text-lg font-bold text-success-600">{progress.success}</div>
            </div>
            <div className="bg-error-50 rounded p-2">
              <div className="flex items-center space-x-1">
                <XCircle className="w-3 h-3 text-error-600" />
                <span className="text-xs text-error-700">Failed</span>
              </div>
              <div className="text-lg font-bold text-error-600">{progress.failed}</div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex space-x-2">
            {progress.canCancel && progress.isActive && (
              <button
                onClick={cancelProgress}
                className="flex-1 bg-error-50 hover:bg-error-50 text-error-700 text-xs font-medium py-2 px-3 rounded transition-colors"
              >
                Cancel
              </button>
            )}
            {!progress.isActive && (
              <button
                onClick={stopProgress}
                className="flex-1 bg-gray-50 hover:bg-gray-100 text-gray-700 text-xs font-medium py-2 px-3 rounded transition-colors"
              >
                Close
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
} 