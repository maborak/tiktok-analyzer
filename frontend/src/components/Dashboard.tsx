import { useNavigate } from '@tanstack/react-router';
import { Scale } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { appConfig } from '../config/env';

export function Dashboard() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  if (isAuthenticated) {
    return (
      <div className="space-y-8 pb-12">
        <div className="text-center py-12">
          <div className="flex justify-center mb-6">
            <div className="p-3 bg-primary-100 rounded-xl">
              <Scale className="w-10 h-10 text-primary-600" />
            </div>
          </div>
          <h1 className="text-3xl font-semibold text-gray-900 mb-3">
            Welcome to {appConfig.name}
          </h1>
          <p className="text-lg text-gray-500 max-w-xl mx-auto">
            Your workspace is ready. Use the sidebar to navigate.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 pb-12">
      <div className="text-center py-12">
        <div className="flex justify-center mb-6">
          <div className="p-3 bg-primary-100 rounded-xl">
            <Scale className="w-10 h-10 text-primary-600" />
          </div>
        </div>
        <h1 className="text-3xl font-semibold text-gray-900 mb-3">
          {appConfig.name}
        </h1>
        <p className="text-lg text-gray-500 max-w-xl mx-auto mb-8">
          Production SaaS framework. Auth, billing, tickets, and live chat — out of the box.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <button
            onClick={() => navigate({ to: '/register' })}
            className="btn-primary auth-submit py-3 px-8"
            style={{ fontFamily: 'var(--font-mono-display)' }}
          >
            Create Free Account
          </button>
          <button
            onClick={() => navigate({ to: '/login' })}
            className="w-full sm:w-auto px-8 py-3 bg-transparent text-gray-700 font-bold rounded-lg border hover:opacity-80 transition-colors"
            style={{ borderColor: 'var(--color-border-primary)' }}
          >
            Sign In
          </button>
        </div>
      </div>
    </div>
  );
}
