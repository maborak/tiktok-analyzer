import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from '@tanstack/react-router';
import { Loader2, Save, UserPlus } from 'lucide-react';
import { adminUserRepository, rbacRepository } from '../../services';
import type { Role } from '../../types';
import { toast } from 'react-hot-toast';
import { useAuth } from '@/contexts/AuthContext';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

interface FormData {
    email: string;
    password: string;
    password_confirm?: string;
    username?: string;
    first_name?: string;
    last_name?: string;
    role_id: number;
    is_active?: boolean;
    is_verified?: boolean;
    api_rate_limit?: number;
}

export function UserForm() {
    const { id } = useParams({ strict: false }) as { id: string };
    const isEdit = !!id;
    const navigate = useNavigate();
    const { isAuthenticated, user, isLoading: authLoading } = useAuth();

    const [loading, setLoading] = useState(false);
    const [loadingUser, setLoadingUser] = useState(isEdit);
    const [roles, setRoles] = useState<Role[]>([]);

    // Refs for deduplication
    const loadedIdRef = useRef<string | null>(null);
    const rolesLoadedRef = useRef(false);

    const [formData, setFormData] = useState<FormData>({
        email: '',
        password: '',
        password_confirm: '',
        username: '',
        first_name: '',
        last_name: '',
        role_id: 1, // Default to first role (usually 'user')
        is_active: true,
        is_verified: false,
        api_rate_limit: 1000,
    });

    useEffect(() => {
        if (authLoading) return;

        if (!isAuthenticated || user?.role !== 'admin') {
            toast.error('Access denied. Administrator role required.');
            navigate({ to: '/' });
            return;
        }

        if (isEdit && id) {
            // Only load if we haven't loaded this ID yet
            if (loadedIdRef.current !== id) {
                loadedIdRef.current = id;
                loadUser();
            }
        } else {
            // Only load roles if we haven't loaded them yet
            if (!rolesLoadedRef.current) {
                rolesLoadedRef.current = true;
                loadRoles();
            }
        }
    }, [authLoading, isAuthenticated, user?.role, navigate, isEdit, id]);

    const loadRoles = async () => {
        try {
            const response = await rbacRepository.listRoles({ page_size: 100, is_active: true });
            if (response.success && response.data) {
                setRoles(response.data.roles || []);
                // Set default role_id if roles are loaded and formData doesn't have a valid role_id
                if (response.data.roles && response.data.roles.length > 0 && !isEdit) {
                    const defaultRole = response.data.roles.find(r => r.name === 'user') || response.data.roles[0];
                    setFormData(prev => ({ ...prev, role_id: defaultRole.id }));
                }
            }
        } catch (error: any) {
            console.error('Failed to load roles:', error);
        }
    };

    // Listen for unauthorized events
    useEffect(() => {
        const handleUnauthorized = (event: CustomEvent) => {
            console.log('Unauthorized access detected:', event.detail);
            toast.error('Your session has expired. Please log in again.');
            navigate({ to: '/login' });
        };

        window.addEventListener('auth:unauthorized', handleUnauthorized as EventListener);
        return () => {
            window.removeEventListener('auth:unauthorized', handleUnauthorized as EventListener);
        };
    }, [navigate]);

    const loadUser = async () => {
        if (!id) return;
        try {
            setLoadingUser(true);
            const res = await adminUserRepository.get(Number(id));
            if (res.success && res.data) {
                const userData = res.data.user;
                setRoles(res.data.roles.roles || []);
                setFormData({
                    email: userData.email,
                    username: userData.username,
                    first_name: userData.firstName || '',
                    last_name: userData.lastName || '',
                    role_id: userData.roleId || 1,
                    is_active: userData.isActive,
                    is_verified: userData.isVerified,
                    api_rate_limit: userData.apiRateLimit,
                    password: '',
                    password_confirm: '',
                });
            }
        } catch (error: any) {
            console.error('Failed to load user:', error);
            toast.error(error.response?.data?.detail || 'Failed to load user');
            navigate({ to: `/admin/users` });
        } finally {
            setLoadingUser(false);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        // Validation
        if (!formData.email) {
            toast.error('Email is required');
            return;
        }

        if (!isEdit && !formData.password) {
            toast.error('Password is required');
            return;
        }

        if (formData.password && formData.password.length < 8) {
            toast.error('Password must be at least 8 characters');
            return;
        }

        if (formData.password && formData.password !== formData.password_confirm) {
            toast.error('Passwords do not match');
            return;
        }

        try {
            setLoading(true);

            if (isEdit) {
                // For update, remove password fields if empty
                const updateData: any = {
                    email: formData.email,
                    username: formData.username || undefined,
                    first_name: formData.first_name || undefined,
                    last_name: formData.last_name || undefined,
                    role_id: formData.role_id,
                    is_active: formData.is_active,
                    is_verified: formData.is_verified,
                    api_rate_limit: formData.api_rate_limit,
                };
                await adminUserRepository.update(Number(id), updateData);
                toast.success('User updated successfully');
            } else {
                // For create, password is required
                const createData: any = {
                    email: formData.email,
                    password: formData.password!,
                    username: formData.username || undefined,
                    first_name: formData.first_name || undefined,
                    last_name: formData.last_name || undefined,
                    role_id: formData.role_id,
                    is_active: formData.is_active,
                    is_verified: formData.is_verified,
                    api_rate_limit: formData.api_rate_limit,
                };
                await adminUserRepository.create(createData);
                toast.success('User created successfully');
            }

            navigate({ to: `/admin/users` });
        } catch (error: any) {
            console.error('Failed to save user:', error);
            toast.error(error.response?.data?.detail || `Failed to ${isEdit ? 'update' : 'create'} user`);
        } finally {
            setLoading(false);
        }
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value, type } = e.target;
        // Handle checkbox separately
        let checked = false;
        if (type === 'checkbox') {
            checked = (e.target as HTMLInputElement).checked;
        }

        if (type === 'checkbox') {
            setFormData((prev) => ({ ...prev, [name]: checked }));
        } else if (type === 'number' || name === 'role_id') {
            setFormData((prev) => ({ ...prev, [name]: value ? Number(value) : undefined }));
        } else {
            setFormData((prev) => ({ ...prev, [name]: value }));
        }
    };

    if (authLoading || loadingUser) {
        return (
            <div className="flex items-center justify-center min-h-96">
                <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
            </div>
        );
    }

    return (
        <PageShell>
            <PageHeader
                title={isEdit ? 'Edit User' : 'Create New User'}
                description={isEdit ? 'Update user information and settings' : 'Create a new user account'}
                icon={<UserPlus className="w-5 h-5" />}
                backTo={`/admin/users`}
                backLabel="Back to users"
            />

            <form onSubmit={handleSubmit} className="card p-0">
                <div className="px-6 py-4 border-b border-gray-200">
                    <h2
                        className="text-lg font-semibold text-gray-900"
                        style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                    >
                        User Information
                    </h2>
                </div>

                <div className="p-6 space-y-6">
                    {/* Email */}
                    <div>
                        <label htmlFor="email" className="label">
                            Email <span className="text-error-500">*</span>
                        </label>
                        <input
                            type="email"
                            id="email"
                            name="email"
                            value={formData.email}
                            onChange={handleChange}
                            required
                            className="input"
                        />
                    </div>

                    {/* Username */}
                    <div>
                        <label htmlFor="username" className="label">
                            Username
                        </label>
                        <input
                            type="text"
                            id="username"
                            name="username"
                            value={formData.username}
                            onChange={handleChange}
                            placeholder="Auto-generated from email if not provided"
                            className="input"
                        />
                    </div>

                    {/* Password (only for create) */}
                    {!isEdit && (
                        <>
                            <div>
                                <label htmlFor="password" className="label">
                                    Password <span className="text-error-500">*</span>
                                </label>
                                <input
                                    type="password"
                                    id="password"
                                    name="password"
                                    value={formData.password}
                                    onChange={handleChange}
                                    required
                                    minLength={8}
                                    placeholder="Minimum 8 characters"
                                    className="input"
                                />
                            </div>

                            <div>
                                <label htmlFor="password_confirm" className="label">
                                    Confirm Password <span className="text-error-500">*</span>
                                </label>
                                <input
                                    type="password"
                                    id="password_confirm"
                                    name="password_confirm"
                                    value={formData.password_confirm}
                                    onChange={handleChange}
                                    required
                                    minLength={8}
                                    className="input"
                                />
                            </div>
                        </>
                    )}

                    {/* Name Fields */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label htmlFor="first_name" className="label">
                                First Name
                            </label>
                            <input
                                type="text"
                                id="first_name"
                                name="first_name"
                                value={formData.first_name}
                                onChange={handleChange}
                                className="input"
                            />
                        </div>
                        <div>
                            <label htmlFor="last_name" className="label">
                                Last Name
                            </label>
                            <input
                                type="text"
                                id="last_name"
                                name="last_name"
                                value={formData.last_name}
                                onChange={handleChange}
                                className="input"
                            />
                        </div>
                    </div>

                    {/* Role */}
                    <div>
                        <label htmlFor="role_id" className="label">
                            Role
                        </label>
                        <select
                            id="role_id"
                            name="role_id"
                            value={formData.role_id}
                            onChange={handleChange}
                            className="input"
                        >
                            {roles.map((role) => (
                                <option key={role.id} value={role.id}>
                                    {role.name}{role.isSystem ? ' (system)' : ''}
                                </option>
                            ))}
                        </select>
                    </div>

                    {/* Status Checkboxes */}
                    <div className="flex items-center gap-6">
                        <label className="flex items-center">
                            <input
                                type="checkbox"
                                name="is_active"
                                checked={formData.is_active}
                                onChange={handleChange}
                                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-200 rounded"
                            />
                            <span className="ml-2 text-sm text-gray-700">Active</span>
                        </label>
                        <label className="flex items-center">
                            <input
                                type="checkbox"
                                name="is_verified"
                                checked={formData.is_verified}
                                onChange={handleChange}
                                className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-200 rounded"
                            />
                            <span className="ml-2 text-sm text-gray-700">Verified</span>
                        </label>
                    </div>

                    {/* Limits */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label htmlFor="api_rate_limit" className="label">
                                API Rate Limit (per hour)
                            </label>
                            <input
                                type="number"
                                id="api_rate_limit"
                                name="api_rate_limit"
                                value={formData.api_rate_limit}
                                onChange={handleChange}
                                min="1"
                                className="input"
                            />
                        </div>
                    </div>
                </div>

                <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 flex justify-end gap-3">
                    <button
                        type="button"
                        onClick={() => navigate({ to: `/admin/users` })}
                        className="btn-secondary auth-submit"
                        style={{ fontFamily: 'var(--font-mono-display)' }}
                    >
                        cancel
                    </button>
                    <button
                        type="submit"
                        disabled={loading}
                        className="btn-primary auth-submit flex items-center gap-2"
                        style={{ fontFamily: 'var(--font-mono-display)' }}
                    >
                        {loading ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <Save className="h-4 w-4" />
                        )}
                        {isEdit ? 'save changes →' : 'create user →'}
                    </button>
                </div>
            </form>
        </PageShell>
    );
}
