import { RouterProvider, createRouter } from '@tanstack/react-router'
import { HelmetProvider } from 'react-helmet-async';
import { Toaster } from 'react-hot-toast';

import { ErrorBoundary } from './components/ErrorBoundary';
import { ThemeProvider } from './contexts/ThemeContext';
import { ProgressProvider } from './contexts/ProgressContext';
import { ConnectivityProvider } from './contexts/ConnectivityContext';
import { ApiUrlProvider } from './contexts/ApiUrlContext';
import { AuthProvider } from './contexts/AuthContext';
import { GoogleOAuthWrapper } from './components/GoogleOAuthWrapper';
import { connectivityConfig } from './config/env';
import { routeTree } from './routeTree.gen';
import { LiveChatWidget } from '@livechat';
import { DebugOverlay, DebugToggle } from '@admin/components/DebugLabel';

const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

function App() {
  return (
    <HelmetProvider>
    <ThemeProvider>
      <ProgressProvider>
        <ConnectivityProvider checkInterval={connectivityConfig.checkInterval} enabled={true}>
          <ApiUrlProvider>
            <GoogleOAuthWrapper>
            <AuthProvider>
                <ErrorBoundary>
                  <div className="App relative">
                    <RouterProvider router={router} />
                    <LiveChatWidget />
                    {/* Admin-only debug labels: a top-center toggle
                        pill + a DOM overlay that decorates every
                        element carrying `data-debug` with a unique
                        4-character code so the operator can refer to
                        it by name. Toggle persists in localStorage. */}
                    <DebugOverlay />
                    <DebugToggle />
                    <Toaster
                      position="bottom-center"
                      containerClassName="toaster-container"
                      toastOptions={{
                        duration: 3000,
                        className: 'toast-base',
                        success: {
                          iconTheme: {
                            primary: '#10b981',
                            secondary: '#fff',
                          },
                        },
                        error: {
                          iconTheme: {
                            primary: '#ef4444',
                            secondary: '#fff',
                          },
                        },
                      }}
                    />
                  </div>
                </ErrorBoundary>
            </AuthProvider>
            </GoogleOAuthWrapper>
          </ApiUrlProvider>
        </ConnectivityProvider>
      </ProgressProvider>
    </ThemeProvider>
    </HelmetProvider>
  );
}

export default App;
