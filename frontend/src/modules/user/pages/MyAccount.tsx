import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  User as UserIcon,
  Loader2,
  Save,
  Key,
  Trash2,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Shield,
  Eye,
  EyeOff,
  Mail,
  AtSign,
} from 'lucide-react';
import type { User } from '../types';
import { userRepository } from '../index';
import { toast } from 'react-hot-toast';
import { useAuth } from '@/contexts/AuthContext';
import { formatRelativeTime } from '@/utils/dateUtils';
import { cn } from '@/utils/cn';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { FormField } from '@/components/ui/FormField';
import { Modal } from '@/components/ui/Modal';
import { LoadingState } from '@/components/ui/LoadingState';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { Skeleton } from '@/components/ui/Skeleton';
import { PageShell } from '@/components/ui/PageShell';
import { googleConfig, githubConfig, facebookConfig } from '@/config/env';
import { useGoogleLogin } from '@react-oauth/google';

// =============================================================================
// VALIDATION SCHEMAS
// =============================================================================

const profileSchema = z.object({
  username: z
    .string()
    .min(3, 'Username must be at least 3 characters')
    .max(50, 'Username must be at most 50 characters')
    .optional()
    .nullable(),
  email: z.string().email('Invalid email address').optional().nullable(),
  first_name: z.string().max(100, 'First name must be at most 100 characters').optional().nullable(),
  last_name: z.string().max(100, 'Last name must be at most 100 characters').optional().nullable(),
});

const passwordSchema = z
  .object({
    current_password: z.string().min(1, 'Current password is required'),
    new_password: z.string().min(8, 'New password must be at least 8 characters'),
    confirm_password: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "Passwords do not match",
    path: ['confirm_password'],
  });

type ProfileFormData = z.infer<typeof profileSchema>;
type PasswordFormData = z.infer<typeof passwordSchema>;

// =============================================================================
// STATUS BADGE COMPONENT
// =============================================================================

interface StatusBadgeProps {
  variant: 'success' | 'error' | 'warning' | 'info';
  icon: typeof CheckCircle;
  label: string;
}

function StatusBadge({ variant, icon: Icon, label }: StatusBadgeProps) {
  const variants = {
    success: 'border-success-200 bg-success-50 text-success-700',
    error: 'border-error-200 bg-error-50 text-error-700',
    warning: 'border-warning-200 bg-warning-50 text-warning-700',
    info: 'border-primary-200 bg-primary-50 text-primary-700',
  };

  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium', variants[variant])}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

// =============================================================================
// SECTION CARD COMPONENT
// =============================================================================

interface SectionCardProps {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

function SectionCard({ title, description, children, className }: SectionCardProps) {
  return (
    <section className={cn('card', className)}>
      <div className="mb-6 border-b border-gray-200 pb-4">
        <h2
          className="text-lg font-semibold text-gray-900"
          style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
        >
          {title}
        </h2>
        {description && <p className="page-subtitle mt-1">{description}</p>}
      </div>
      {children}
    </section>
  );
}

// =============================================================================
// PASSWORD INPUT COMPONENT
// =============================================================================

interface PasswordInputProps {
  id: string;
  label: string;
  placeholder: string;
  error?: string;
  hint?: string;
  register: ReturnType<typeof useForm<PasswordFormData>>['register'];
  fieldName: keyof PasswordFormData;
}

function PasswordInput({ id, label, placeholder, error, hint, register, fieldName }: PasswordInputProps) {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <FormField id={id} label={label} error={error} hint={hint}>
      <div className="relative">
        <Input
          {...register(fieldName)}
          type={showPassword ? 'text' : 'password'}
          id={id}
          placeholder={placeholder}
          className={cn(error && 'border-error-300 focus:border-error-400')}
        />
        <button
          type="button"
          onClick={() => setShowPassword(!showPassword)}
          className="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
        >
          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </FormField>
  );
}

// =============================================================================
// DELETE CONFIRMATION MODAL
// =============================================================================

interface DeleteModalProps {
  isOpen: boolean;
  account: User;
  isDeleting: boolean;
  deletionProgress: number;
  onClose: () => void;
  onConfirm: () => void;
}

function DeleteAccountModal({ isOpen, account, isDeleting, deletionProgress, onClose, onConfirm }: DeleteModalProps) {
  return (
    <Modal isOpen={isOpen} onClose={!isDeleting ? onClose : undefined} className="max-w-md">
      <div className="text-center sm:text-left">
        <div className="flex items-start gap-4 mb-6">
          <div className="flex-shrink-0 w-12 h-12 rounded-full bg-error-50 flex items-center justify-center">
            <AlertTriangle className="h-6 w-6 text-error-600" />
          </div>
          <div>
            <h3
              className="text-lg font-semibold text-gray-900"
              style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
            >
              Delete Account
            </h3>
            <p className="page-subtitle mt-1">This action is permanent and cannot be undone.</p>
          </div>
        </div>

        <div className="bg-gray-50 rounded-lg p-4 mb-6 border border-gray-200">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center">
              <UserIcon className="h-5 w-5 text-gray-500" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 truncate">{account.fullName || account.username}</p>
              <p className="text-sm text-gray-500 truncate">{account.email}</p>
            </div>
          </div>
        </div>

        <div className="bg-error-50 rounded-lg p-4 mb-6 border border-error-100">
          <p className="text-sm text-error-700">
            All your data, including tickets, recipients, and preferences will be permanently deleted.
          </p>
        </div>

        {isDeleting && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">Deleting account...</span>
              <span className="text-sm text-gray-500">{deletionProgress}%</span>
            </div>
            <ProgressBar value={deletionProgress} className="h-2" barClassName="bg-error-600 h-2" />
          </div>
        )}

        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-3 pt-4 border-t border-gray-200">
          <Button variant="secondary" onClick={onClose} disabled={isDeleting}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={isDeleting}>
            {isDeleting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Trash2 className="h-4 w-4 mr-2" />}
            Delete My Account
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================


function AccountSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      {/* Header Skeleton */}
      <section className="card">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <Skeleton className="h-16 w-16 rounded-full" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-32" />
            </div>
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-6 w-20 rounded-full" />
            <Skeleton className="h-6 w-20 rounded-full" />
          </div>
        </div>
      </section>

      {/* Profile Form Skeleton */}
      <section className="card">
        <div className="mb-6 pb-4 border-b border-gray-200 space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div className="space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-10 w-full" />
            </div>
            <div className="space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-10 w-full" />
            </div>
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-10 w-full" />
          </div>
        </div>
      </section>

      {/* Security Form Skeleton */}
      <section className="card">
        <div className="mb-6 pb-4 border-b border-gray-200 space-y-2">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-4 w-64" />
        </div>
        <div className="space-y-6">
          <div className="space-y-2">
            <Skeleton className="h-4 w-36" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div className="space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-10 w-full" />
            </div>
            <div className="space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-10 w-full" />
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

export function MyAccount() {
  const navigate = useNavigate();
  const { isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const rawLoaderData = undefined as User | undefined;
  // Loader returns raw API data (snake_case) — normalize has_password → hasPassword
  const loaderData = rawLoaderData ? { ...rawLoaderData, hasPassword: (rawLoaderData as any).hasPassword ?? (rawLoaderData as any).has_password ?? true } as User : undefined;

  // State
  const [account, setAccount] = useState<User | null>(loaderData ?? null);
  const [loading, setLoading] = useState(!loaderData);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deletionProgress, setDeletionProgress] = useState(0);

  // OAuth connected accounts
  const [oauthAccounts, setOauthAccounts] = useState<any[]>([]);
  const [oauthHasPassword, setOauthHasPassword] = useState(true);
  const [unlinkingProvider, setUnlinkingProvider] = useState<string | null>(null);
  const [unlinkConfirmProvider, setUnlinkConfirmProvider] = useState<string | null>(null);
  const [setPasswordModal, setSetPasswordModal] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  const [settingPassword, setSettingPassword] = useState(false);

  // Ref to prevent multiple loadAccount calls
  const hasLoadedRef = useRef(false);

  // Profile form
  const {
    register: registerProfile,
    handleSubmit: handleProfileSubmit,
    reset: resetProfile,
    formState: { errors: profileErrors, isDirty: profileIsDirty },
  } = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
  });

  // Password form
  const {
    register: registerPassword,
    handleSubmit: handlePasswordSubmit,
    reset: resetPassword,
    formState: { errors: passwordErrors },
  } = useForm<PasswordFormData>({
    resolver: zodResolver(passwordSchema),
  });

  // =============================================================================
  // API HANDLERS
  // =============================================================================

  const loadAccount = useCallback(async () => {
    if (hasLoadedRef.current) return;
    hasLoadedRef.current = true;

    try {
      setLoading(true);
      const response = await userRepository.getAccount();
      if (response.success && response.data) {
        const data = response.data;
        setAccount(data);
        resetProfile({
          username: data.username,
          email: data.email,
          first_name: data.firstName || '',
          last_name: data.lastName || '',
        });
      } else {
        toast.error(response.message || 'Failed to load account information');
      }
    } catch (error: unknown) {
      hasLoadedRef.current = false; // Allow retry on error
      const err = error as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 401) {
        toast.error('Your session has expired. Please log in again.');
        navigate({ to: '/login' });
      } else {
        toast.error(err.response?.data?.detail || 'Failed to load account information');
      }
    } finally {
      setLoading(false);
    }
  }, [navigate, resetProfile]);

  // Initialize form with loader data
  useEffect(() => {
    if (!loaderData) return;
    hasLoadedRef.current = true;
    setAccount(loaderData);
    resetProfile({
      username: loaderData.username,
      email: loaderData.email,
      first_name: loaderData.firstName || '',
      last_name: loaderData.lastName || '',
    });
    setLoading(false);
  }, [loaderData, resetProfile]);

  // Auth check and fallback data load
  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated) {
      navigate({ to: '/login' });
      return;
    }

    if (!loaderData && !hasLoadedRef.current) {
      loadAccount();
    }
  }, [authLoading, isAuthenticated, navigate, loaderData, loadAccount]);

  // Skip the OAuth fetch entirely when no provider is configured client-side,
  // so we don't spam the backend with 503s on a framework install without OAuth.
  const anyOAuthEnabled = googleConfig.enabled || githubConfig.enabled || facebookConfig.enabled;

  // Load OAuth connected accounts
  const loadOAuthAccounts = useCallback(async () => {
    if (!anyOAuthEnabled) return;
    try {
      const response = await userRepository.getOAuthAccounts();
      if (response.success && response.data) {
        setOauthAccounts(response.data.accounts || []);
        setOauthHasPassword(response.data.has_password ?? true);
      }
    } catch {
      // Silently fail — OAuth might not be configured
    }
  }, [anyOAuthEnabled]);

  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      loadOAuthAccounts();
    }
  }, [isAuthenticated, authLoading, loadOAuthAccounts]);

  const handleUnlinkOAuth = async (provider: string) => {
    setUnlinkingProvider(provider);
    try {
      const response = await userRepository.unlinkOAuthAccount(provider);
      if (response.success) {
        toast.success(`${provider.charAt(0).toUpperCase() + provider.slice(1)} account unlinked`);
        loadOAuthAccounts();
      } else {
        toast.error(response.message || 'Failed to unlink account');
      }
    } catch (err: any) {
      toast.error(err.message || 'Failed to unlink account');
    } finally {
      setUnlinkingProvider(null);
    }
  };

  const handleSetPassword = async () => {
    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }
    if (newPassword !== newPasswordConfirm) {
      toast.error('Passwords do not match');
      return;
    }
    setSettingPassword(true);
    try {
      const response = await userRepository.setPassword(newPassword, newPasswordConfirm);
      if (response.success) {
        toast.success('Password set successfully');
        setSetPasswordModal(false);
        setNewPassword('');
        setNewPasswordConfirm('');
        loadOAuthAccounts();
        // Reload account to update hasPassword
        hasLoadedRef.current = false;
        loadAccount();
      } else {
        toast.error(response.message || 'Failed to set password');
      }
    } catch (err: any) {
      toast.error(err.message || 'Failed to set password');
    } finally {
      setSettingPassword(false);
    }
  };

  const [linkingProvider, setLinkingProvider] = useState<string | null>(null);

  const handleLinkGoogle = async (tokenResponse: { access_token: string }) => {
    setLinkingProvider('google');
    try {
      const res = await userRepository.linkOAuthProvider('google', tokenResponse.access_token);
      if (res.success) {
        toast.success(res.message || 'Google account connected');
      } else {
        toast.error(res.message || 'Failed to connect Google');
      }
      loadOAuthAccounts();
    } catch (err: any) {
      toast.error(err.message || 'Failed to connect Google');
    } finally {
      setLinkingProvider(null);
    }
  };

  const handleLinkRedirectProvider = (provider: 'github' | 'facebook') => {
    sessionStorage.setItem('oauth_link_intent', 'true');
    if (provider === 'github') {
      const redirectUri = `${window.location.origin}/auth/github/callback`;
      const params = new URLSearchParams({
        client_id: githubConfig.clientId,
        redirect_uri: redirectUri,
        scope: 'user:email',
        prompt: 'select_account',
      });
      window.location.href = `https://github.com/login/oauth/authorize?${params.toString()}`;
    } else if (provider === 'facebook') {
      const redirectUri = `${window.location.origin}/auth/facebook/callback`;
      const params = new URLSearchParams({
        client_id: facebookConfig.appId,
        redirect_uri: redirectUri,
        scope: 'email,public_profile',
        response_type: 'code',
        auth_type: 'rerequest',
      });
      window.location.href = `https://www.facebook.com/v21.0/dialog/oauth?${params.toString()}`;
    }
  };

  // Refresh OAuth accounts when returning from a link redirect
  useEffect(() => {
    if (window.location.hash === '#sign-in-methods') {
      loadOAuthAccounts();
    }
  }, [loadOAuthAccounts]);

  const onProfileSubmit = async (data: ProfileFormData) => {
    if (!account) return;

    try {
      setSavingProfile(true);

      // Only send changed fields
      const updateData: any = {};
      if (data.username !== account.username) updateData.username = data.username;
      if (data.email !== account.email) updateData.email = data.email;
      if (data.first_name !== (account.firstName || '')) updateData.first_name = data.first_name;
      if (data.last_name !== (account.lastName || '')) updateData.last_name = data.last_name;

      if (Object.keys(updateData).length === 0) {
        toast('No changes to save');
        return;
      }

      const response = await userRepository.updateAccount(updateData);
      if (response.success && response.data) {
        const updatedAccount = response.data;
        setAccount(updatedAccount);
        resetProfile({
          username: updatedAccount.username,
          email: updatedAccount.email,
          first_name: updatedAccount.firstName || '',
          last_name: updatedAccount.lastName || '',
        });
        toast.success(response.message || 'Profile updated successfully');
      } else {
        toast.error(response.message || 'Failed to update profile');
      }
    } catch (error: unknown) {
      const err = error as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 409) {
        toast.error('Email or username already exists');
      } else {
        toast.error(err.response?.data?.detail || 'Failed to update profile');
      }
    } finally {
      setSavingProfile(false);
    }
  };

  const onPasswordSubmit = async (data: PasswordFormData) => {
    try {
      setSavingPassword(true);

      const passwordData = {
        current_password: data.current_password,
        new_password: data.new_password,
      };

      const response = await userRepository.changePassword(passwordData);
      if (response.success) {
        resetPassword();
        toast.success(response.message || 'Password changed successfully');
      } else {
        toast.error(response.message || 'Failed to change password');
      }
    } catch (error: unknown) {
      const err = error as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 400) {
        toast.error('Current password is incorrect');
      } else {
        toast.error(err.response?.data?.detail || 'Failed to change password');
      }
    } finally {
      setSavingPassword(false);
    }
  };

  const handleDeleteAccount = async () => {
    try {
      setIsDeleting(true);
      setDeletionProgress(0);

      // Simulate progress
      const progressInterval = setInterval(() => {
        setDeletionProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval);
            return 90;
          }
          return prev + 10;
        });
      }, 100);

      const response = await userRepository.deleteAccount();
      clearInterval(progressInterval);
      setDeletionProgress(100);

      await new Promise((resolve) => setTimeout(resolve, 300));

      if (response.success) {
        await logout();
        toast.success(response.message || 'Your account has been deleted');
        navigate({ to: '/login' });
      } else {
        setIsDeleting(false);
        setDeletionProgress(0);
        toast.error(response.message || 'Failed to delete account');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      setIsDeleting(false);
      setDeletionProgress(0);
      toast.error(err.response?.data?.detail || 'Failed to delete account');
    }
  };

  // =============================================================================
  // LOADING & ERROR STATES
  // =============================================================================

  if (authLoading || loading) {
    return <AccountSkeleton />;
  }

  if (!isAuthenticated) {
    return <LoadingState message="Redirecting to login..." />;
  }

  if (!account) {
    return (
      <div className="flex flex-col items-center justify-center min-h-96 text-center">
        <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
          <UserIcon className="w-8 h-8 text-gray-400" />
        </div>
        <h3
          className="text-lg font-medium text-gray-900 mb-2"
          style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
        >
          Account not found
        </h3>
        <p className="text-sm text-gray-500 mb-4">Could not load your account information.</p>
        <Button variant="secondary" onClick={() => navigate({ to: '/login' })}>
          Go to login
        </Button>
      </div>
    );
  }

  // =============================================================================
  // RENDER
  // =============================================================================

  return (
    <PageShell>
      {/* Profile Header */}
      <section className="card">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary-100">
              <UserIcon className="h-8 w-8 text-primary-600" />
            </div>
            <div className="min-w-0">
              <p className="auth-mono-label">profile</p>
              <h1 className="page-title truncate">{account.fullName || account.username}</h1>
              <p className="truncate text-sm text-gray-500">{account.email}</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {account.isActive ? (
              <StatusBadge variant="success" icon={CheckCircle} label="Active" />
            ) : (
              <StatusBadge variant="error" icon={XCircle} label="Inactive" />
            )}
            {account.isVerified ? (
              <StatusBadge variant="info" icon={Shield} label="Verified" />
            ) : (
              <StatusBadge variant="warning" icon={AlertTriangle} label="Unverified" />
            )}
            {account.lastLogin && (
              <span className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-sm text-gray-600">
                <Clock className="h-3.5 w-3.5" />
                Last login {formatRelativeTime(account.lastLogin)}
              </span>
            )}
          </div>
        </div>
      </section>

      {/* Verification Warning */}
      {!account.isVerified && (
        <div className="rounded-lg border border-warning-200 bg-warning-50 p-4">
          <div className="flex items-start gap-3">
            <div className="flex-shrink-0">
              <AlertTriangle className="h-5 w-5 text-warning-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h3
                className="text-sm font-semibold text-warning-700"
                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
              >
                Verify your email address
              </h3>
              <p className="mt-1 text-sm text-warning-700">
                Your account is not verified. Please check your inbox for the verification link to complete your account setup.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    try {
                      const response = await userRepository.resendVerificationEmail();
                      if (response.success) {
                        toast.success(response.message || 'Verification email sent! Please check your inbox.');
                      } else {
                        toast.error(response.message);
                      }
                    } catch {
                      toast.error('Failed to send verification email. Please try again.');
                    }
                  }}
                  className="border-warning-300 bg-white text-warning-700 hover:bg-warning-50"
                >
                  <Mail className="h-4 w-4 mr-1.5" />
                  Resend verification email
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Profile Information */}
      <SectionCard title="Profile Information" description="Update your personal details and email address.">
        <form onSubmit={handleProfileSubmit(onProfileSubmit)} className="space-y-6">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <FormField id="first_name" label="First Name" error={profileErrors.first_name?.message}>
              <Input {...registerProfile('first_name')} id="first_name" placeholder="Enter your first name" />
            </FormField>

            <FormField id="last_name" label="Last Name" error={profileErrors.last_name?.message}>
              <Input {...registerProfile('last_name')} id="last_name" placeholder="Enter your last name" />
            </FormField>
          </div>

          <FormField id="email" label="Email" error={profileErrors.email?.message}>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input
                {...registerProfile('email')}
                type="email"
                id="email"
                placeholder="Enter your email address"
                className="pl-10"
              />
            </div>
          </FormField>

          <FormField id="username" label="Username" error={profileErrors.username?.message}>
            <div className="relative">
              <AtSign className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <Input {...registerProfile('username')} id="username" placeholder="Enter your username" className="pl-10" />
            </div>
          </FormField>

          <div className="flex justify-end pt-4 border-t border-gray-200">
            <Button
              type="submit"
              disabled={savingProfile || !profileIsDirty}
              className="auth-submit lowercase"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              {savingProfile ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              save changes →
            </Button>
          </div>
        </form>
      </SectionCard>


      {/* Security — hidden for OAuth-only users who have no password */}
      {account?.hasPassword !== false && <SectionCard title="Security" description="Manage your password and account security.">
        <form onSubmit={handlePasswordSubmit(onPasswordSubmit)} className="space-y-6">
          <PasswordInput
            id="current_password"
            label="Current Password"
            placeholder="Enter your current password"
            error={passwordErrors.current_password?.message}
            register={registerPassword}
            fieldName="current_password"
          />

          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <PasswordInput
              id="new_password"
              label="New Password"
              placeholder="Enter your new password"
              error={passwordErrors.new_password?.message}
              hint="Must be at least 8 characters"
              register={registerPassword}
              fieldName="new_password"
            />

            <PasswordInput
              id="confirm_password"
              label="Confirm New Password"
              placeholder="Confirm your new password"
              error={passwordErrors.confirm_password?.message}
              register={registerPassword}
              fieldName="confirm_password"
            />
          </div>

          <div className="flex justify-start pt-4 border-t border-gray-200">
            <Button
              type="submit"
              disabled={savingPassword}
              className="auth-submit lowercase"
              style={{ fontFamily: 'var(--font-mono-display)' }}
            >
              {savingPassword ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Key className="w-4 h-4 mr-2" />}
              change password →
            </Button>
          </div>
        </form>
      </SectionCard>}

      {/* Sign-In Methods */}
      <SectionCard title="Sign-In Methods" description="Manage how you sign in to your account.">
        <div className="space-y-3">
          {/* Password row */}
          <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-primary)' }}>
            <div className="flex items-center gap-3">
              <Key className="h-5 w-5" style={{ color: 'var(--color-text-secondary)' }} />
              <div>
                <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>Password</p>
                <p className="page-subtitle">{oauthHasPassword ? 'Password set' : 'No password'}</p>
              </div>
            </div>
            {oauthHasPassword ? (
              <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full" style={{ backgroundColor: 'var(--color-success-50)', color: 'var(--color-success-700)' }}>
                <CheckCircle className="h-3 w-3" /> Active
              </span>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => setSetPasswordModal(true)}>
                Set Password
              </Button>
            )}
          </div>

          {/* Connected OAuth providers */}
          {oauthAccounts.map((acct) => (
            <div key={acct.provider} className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-primary)' }}>
              <div className="flex items-center gap-3">
                {acct.provider === 'google' && (
                  <svg className="h-5 w-5 flex-shrink-0" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
                )}
                {acct.provider === 'github' && (
                  <svg className="h-5 w-5 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor"><path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2Z"/></svg>
                )}
                {acct.provider === 'facebook' && (
                  <svg className="h-5 w-5 flex-shrink-0" viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" fill="#1877F2"/></svg>
                )}
                {!['google', 'github', 'facebook'].includes(acct.provider) && (
                  <Shield className="h-5 w-5 flex-shrink-0" style={{ color: 'var(--color-text-secondary)' }} />
                )}
                <div>
                  <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    {acct.provider.charAt(0).toUpperCase() + acct.provider.slice(1)}
                  </p>
                  <p className="page-subtitle">{acct.email || 'Connected'}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full" style={{ backgroundColor: 'var(--color-success-50)', color: 'var(--color-success-700)' }}>
                  <CheckCircle className="h-3 w-3" /> Connected
                </span>
                {(!oauthHasPassword && oauthAccounts.length <= 1) ? (
                  <p className="page-subtitle text-xs max-w-44 text-right">Set a password first to unlink</p>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setUnlinkConfirmProvider(acct.provider)}
                    disabled={unlinkingProvider === acct.provider}
                  >
                    {unlinkingProvider === acct.provider ? 'Disconnecting...' : 'Disconnect'}
                  </Button>
                )}
              </div>
            </div>
          ))}

          {/* Unconnected providers — show Connect buttons */}
          {googleConfig.enabled && !oauthAccounts.some(a => a.provider === 'google') && (
            <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-primary)' }}>
              <div className="flex items-center gap-3">
                <svg className="h-5 w-5 flex-shrink-0 opacity-50" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Google</p>
              </div>
              <GoogleLinkButton
                linkingProvider={linkingProvider}
                setLinkingProvider={setLinkingProvider}
                onSuccess={handleLinkGoogle}
              />
            </div>
          )}
          {githubConfig.enabled && !oauthAccounts.some(a => a.provider === 'github') && (
            <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-primary)' }}>
              <div className="flex items-center gap-3">
                <svg className="h-5 w-5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="currentColor"><path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2Z"/></svg>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>GitHub</p>
              </div>
              <Button size="sm" onClick={() => handleLinkRedirectProvider('github')} aria-label="Connect GitHub account">
                Connect
              </Button>
            </div>
          )}
          {facebookConfig.enabled && !oauthAccounts.some(a => a.provider === 'facebook') && (
            <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-primary)' }}>
              <div className="flex items-center gap-3">
                <svg className="h-5 w-5 flex-shrink-0 opacity-50" viewBox="0 0 24 24"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" fill="#1877F2"/></svg>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Facebook</p>
              </div>
              <Button size="sm" onClick={() => handleLinkRedirectProvider('facebook')} aria-label="Connect Facebook account">
                Connect
              </Button>
            </div>
          )}
        </div>
      </SectionCard>

      {/* Disconnect OAuth Confirmation Modal */}
      <Modal
        isOpen={!!unlinkConfirmProvider}
        title={`Disconnect ${unlinkConfirmProvider ? unlinkConfirmProvider.charAt(0).toUpperCase() + unlinkConfirmProvider.slice(1) : ''}?`}
        onClose={() => setUnlinkConfirmProvider(null)}
      >
        <div className="space-y-4">
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            You will no longer be able to sign in with {unlinkConfirmProvider ? unlinkConfirmProvider.charAt(0).toUpperCase() + unlinkConfirmProvider.slice(1) : 'this provider'}.
            {oauthHasPassword
              ? ' You can still sign in with your email and password.'
              : oauthAccounts.length > 1
                ? ' You can still sign in with your other connected accounts.'
                : ''}
          </p>
          <div className="flex justify-end gap-3">
            <Button variant="secondary" onClick={() => setUnlinkConfirmProvider(null)} disabled={!!unlinkingProvider}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={async () => {
                if (!unlinkConfirmProvider) return;
                await handleUnlinkOAuth(unlinkConfirmProvider);
                setUnlinkConfirmProvider(null);
              }}
              disabled={!!unlinkingProvider}
            >
              {unlinkingProvider ? 'Disconnecting...' : 'Disconnect'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Set Password Modal (for OAuth-only users) */}
      <Modal isOpen={setPasswordModal} title="Set Account Password" onClose={() => { setSetPasswordModal(false); setNewPassword(''); setNewPasswordConfirm(''); }}>
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Set a password so you can also sign in with email and password.
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">New Password</label>
              <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="Min. 8 characters" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Confirm Password</label>
              <Input type="password" value={newPasswordConfirm} onChange={(e) => setNewPasswordConfirm(e.target.value)} placeholder="Confirm password" />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="secondary" onClick={() => { setSetPasswordModal(false); setNewPassword(''); setNewPasswordConfirm(''); }} disabled={settingPassword}>Cancel</Button>
              <Button onClick={handleSetPassword} disabled={settingPassword || newPassword.length < 8}>{settingPassword ? 'Setting...' : 'Set Password'}</Button>
            </div>
          </div>
        </Modal>

      {/* Danger Zone */}
      <SectionCard title="Danger Zone" description="Irreversible and destructive actions.">
        <div className="p-4 bg-error-50 rounded-lg border border-error-100">
          <div className="flex items-start gap-4">
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-error-50">
              <AlertTriangle className="h-5 w-5 text-error-600" />
            </div>
            <div className="flex-1">
              <h3
                className="text-sm font-medium text-error-900"
                style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
              >
                Delete Account
              </h3>
              <p className="mt-1 text-sm text-error-700">
                Once you delete your account, there is no going back. All your data will be permanently deleted.
              </p>
              <Button variant="danger" size="sm" onClick={() => setDeleteModalOpen(true)} className="mt-4">
                <Trash2 className="w-4 h-4 mr-2" />
                Delete Account
              </Button>
            </div>
          </div>
        </div>
      </SectionCard>

      {/* Delete Account Modal */}
      <DeleteAccountModal
        isOpen={deleteModalOpen}
        account={account}
        isDeleting={isDeleting}
        deletionProgress={deletionProgress}
        onClose={() => setDeleteModalOpen(false)}
        onConfirm={handleDeleteAccount}
      />
    </PageShell>
  );
}

// =============================================================================
// GOOGLE LINK BUTTON
// =============================================================================
// Extracted to a child component so useGoogleLogin() is only called when the
// GoogleOAuthProvider is mounted (i.e. when googleConfig.enabled is true).
// Parent MyAccountPage guards this render with `googleConfig.enabled && ...`.

interface GoogleLinkButtonProps {
  linkingProvider: string | null;
  setLinkingProvider: (p: string | null) => void;
  onSuccess: (tokenResponse: { access_token: string }) => Promise<void>;
}

function GoogleLinkButton({ linkingProvider, setLinkingProvider, onSuccess }: GoogleLinkButtonProps) {
  const googleLink = useGoogleLogin({
    onSuccess,
    onError: () => { toast.error('Google sign-in was cancelled or failed'); setLinkingProvider(null); },
    flow: 'implicit',
  });

  return (
    <Button
      size="sm"
      onClick={() => { setLinkingProvider('google'); googleLink(); }}
      disabled={linkingProvider === 'google'}
      aria-label="Connect Google account"
    >
      {linkingProvider === 'google' ? 'Connecting...' : 'Connect'}
    </Button>
  );
}
