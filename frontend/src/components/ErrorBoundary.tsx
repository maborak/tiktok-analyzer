import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
  errorInfo?: ErrorInfo;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    // Update state so the next render will show the fallback UI
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Log the error to console for debugging
    console.error('Error Boundary caught an error:', error, errorInfo);
    
    this.setState({
      error,
      errorInfo,
    });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: undefined, errorInfo: undefined });
  };

  render() {
    if (this.state.hasError) {
      // Render custom fallback UI
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="max-w-md w-full bg-white shadow-lg rounded-lg p-6">
            <div className="flex items-center justify-center w-12 h-12 mx-auto bg-error-50 rounded-full">
              <AlertTriangle className="w-6 h-6 text-error-600" />
            </div>
            
            <div className="mt-4 text-center">
              <h1 className="text-lg font-medium text-gray-900">Something went wrong</h1>
              <p className="mt-2 text-sm text-gray-500">
                An error occurred while displaying this page. Please try refreshing or contact support if the problem persists.
              </p>
              
              {import.meta.env.DEV && this.state.error && (
                <details className="mt-4 text-left">
                  <summary className="text-sm text-gray-700 cursor-pointer hover:text-gray-900">
                    Error Details (Development)
                  </summary>
                  <div className="mt-2 p-3 bg-gray-100 rounded text-xs font-mono text-error-600 overflow-auto max-h-40">
                    <div className="font-bold">{this.state.error.name}: {this.state.error.message}</div>
                    <div className="mt-2 whitespace-pre-wrap">{this.state.error.stack}</div>
                    {this.state.errorInfo && (
                      <div className="mt-2 whitespace-pre-wrap">{this.state.errorInfo.componentStack}</div>
                    )}
                  </div>
                </details>
              )}
            </div>
            
            <div className="mt-6 flex space-x-3">
              <button
                onClick={this.handleReset}
                className="btn-primary flex-1"
              >
                <RefreshCw className="w-4 h-4 mr-2" />
                Try Again
              </button>
              
              <button
                onClick={() => window.location.reload()}
                className="btn-secondary flex-1"
              >
                Reload Page
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
} 