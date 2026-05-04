import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { LogIn, Loader, AlertTriangle } from 'lucide-react';
import { useNavigate } from '@tanstack/react-router';
import toast from 'react-hot-toast';

import { useApiClient } from '@/hooks/useApiClient';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/utils/cn';

const impersonateSchema = z.object({
    email: z.string().email('Please enter a valid email address'),
});

type ImpersonateForm = z.infer<typeof impersonateSchema>;

export function AdminQuickLogin() {
    const { client: apiClient, isReady } = useApiClient();
    const { impersonate, user } = useAuth();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [isOpen, setIsOpen] = useState(false);

    const {
        register,
        handleSubmit,
        formState: { errors },
    } = useForm<ImpersonateForm>({
        resolver: zodResolver(impersonateSchema),
    });

    const onSubmit = async (data: ImpersonateForm) => {
        if (!isReady) return;

        if (data.email === user?.email) {
            toast.error('You cannot impersonate yourself');
            return;
        }

        setLoading(true);
        try {
            const impersonationData = await apiClient.loginAsUserByEmail(data.email);

            if (impersonationData && impersonationData.access_token) {
                toast.success(`Switching session to ${impersonationData.user.email}...`);

                // Wait briefly for toast
                setTimeout(() => {
                    // Map flat ImpersonationResponse to LoginResponse structure
                    const loginResponse: any = {
                        user: impersonationData.user,
                        tokens: {
                            access_token: impersonationData.access_token,
                            refresh_token: impersonationData.refresh_token,
                            token_type: impersonationData.token_type,
                            expires_in: impersonationData.expires_in
                        }
                    };

                    impersonate(loginResponse);
                    navigate({ to: '/' });
                    window.location.reload();
                }, 800);
            } else {
                toast.error('Error impersonating user');
            }
        } catch (error: any) {
            console.error('Failed to impersonate user:', error);
            if (error.response?.status === 404) {
                toast.error('User not found');
            } else if (error.response?.status === 400) {
                toast.error(error.response.data.message || 'Invalid request');
            } else {
                toast.error('Failed to impersonate user');
            }
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) {
        return (
            <button
                onClick={() => setIsOpen(true)}
                className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium text-warning-700 bg-warning-50 border border-warning-200 rounded-lg hover:bg-warning-50 transition-colors"
                title="Admin: Quick login as User"
            >
                <LogIn className="h-4 w-4" />
                <span className="hidden sm:inline">Unmask</span>
            </button>
        );
    }

    return (
        <div className="relative">
            <div className="fixed inset-0 z-40 bg-transparent" onClick={() => setIsOpen(false)} />
            <div className="absolute right-0 top-full mt-2 w-72 z-50 bg-white rounded-lg shadow-lg border border-gray-200 p-4">
                <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                        <LogIn className="h-4 w-4 text-warning-500" />
                        Quick Impersonation
                    </h3>
                    <button
                        onClick={() => setIsOpen(false)}
                        className="text-gray-400 hover:text-gray-500"
                    >
                        <span className="sr-only">Close</span>
                        <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                        </svg>
                    </button>
                </div>

                <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
                    <div className="space-y-1">
                        <input
                            {...register('email')}
                            type="email"
                            placeholder="user@example.com"
                            className={cn(
                                "input focus:ring-warning-500 focus:border-warning-500",
                                errors.email ? "border-error-300 bg-error-50" : "bg-gray-50"
                            )}
                            autoFocus
                        />
                        {errors.email && (
                            <p className="text-xs text-error-500 flex items-center gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                {errors.email.message}
                            </p>
                        )}
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="btn-warning w-full shadow-sm"
                    >
                        {loading ? (
                            <>
                                <Loader className="animate-spin -ml-1 mr-2 h-4 w-4" />
                                Switching...
                            </>
                        ) : (
                            'Login as User'
                        )}
                    </button>
                </form>

                <p className="mt-3 text-xs text-gray-500 text-center">
                    The session will switch immediately.
                </p>
            </div>
        </div>
    );
}
