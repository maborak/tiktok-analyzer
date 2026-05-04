import { Link } from '@tanstack/react-router';
import { CheckCircle, Mail, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';

export function RegistrationSuccess() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="max-w-md w-full bg-white rounded-xl shadow-lg border border-gray-200 p-8 text-center">
        {/* Success Icon */}
        <div className="mx-auto w-16 h-16 bg-success-50 rounded-full flex items-center justify-center mb-6">
          <CheckCircle className="w-8 h-8 text-success-600" />
        </div>

        {/* Title */}
        <h1 className="page-title mb-2">
          Almost Done!
        </h1>

        {/* Verification Message */}
        <div className="bg-primary-50 border border-primary-100 rounded-lg p-4 mb-6">
          <div className="flex items-start gap-3">
            <Mail className="w-5 h-5 text-primary-600 mt-0.5 shrink-0" />
            <div className="text-left">
              <p className="text-sm text-primary-900 font-medium mb-1">
                Check your email
              </p>
              <p className="text-xs text-primary-700 leading-relaxed">
                We have sent a verification link to your email.
                Click the link to activate your account and start using the platform.
              </p>
            </div>
          </div>
        </div>

        {/* Next Steps */}
        <div className="bg-gray-50 border border-gray-100 rounded-lg p-4 mb-6 text-left">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Next steps:</h3>
          <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
            <li>Check your inbox (and spam folder)</li>
            <li>Click the "Verify Account" link</li>
            <li>Sign in to start using the platform</li>
          </ul>
        </div>

        {/* Login Button */}
        <Link to="/login">
          <Button className="w-full justify-center">
            Go to Sign In
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </Link>

        {/* Help link */}
        <p className="mt-4 text-xs text-gray-500">
          Didn't receive the email? Check your spam folder or{' '}
          <Link to="/account/tickets" className="text-primary-600 hover:text-primary-700 font-medium">
            contact support
          </Link>
        </p>
      </div>
    </div>
  );
}
