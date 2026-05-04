import { Link } from '@tanstack/react-router';
import { Mail, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';

export function CheckEmail() {
    return (
        <div className="min-h-[80vh] flex items-center justify-center px-4">
            <div className="max-w-md w-full text-center">
                <div className="w-16 h-16 rounded-full bg-success-50 flex items-center justify-center mx-auto mb-6">
                    <Mail className="w-8 h-8 text-success-600" />
                </div>

                <h1 className="page-title mb-2">Registration Successful!</h1>
                <p className="text-gray-600 mb-6">
                    We have sent a verification link to your email. Check your inbox and click the link to activate your account.
                </p>

                <div className="bg-primary-50 border border-primary-100 rounded-lg p-4 mb-8 text-left">
                    <h3 className="text-sm font-medium text-primary-700 mb-2">Next steps:</h3>
                    <ul className="list-disc list-inside text-sm text-primary-700 space-y-1">
                        <li>Check your inbox</li>
                        <li>Click the "Verify Account" link</li>
                        <li>Sign in to your account</li>
                    </ul>
                </div>

                <div className="flex flex-col gap-3">
                    <Link to="/login">
                        <Button variant="primary" className="w-full justify-center">
                            Go to Sign In
                            <ArrowRight className="w-4 h-4 ml-2" />
                        </Button>
                    </Link>

                    <p className="text-xs text-gray-500 mt-4">
                        Didn't receive the email? Check your spam folder or{' '}
                        <a href="/contact" className="text-primary-600 hover:underline">contact support</a>.
                    </p>
                </div>
            </div>
        </div>
    );
}
