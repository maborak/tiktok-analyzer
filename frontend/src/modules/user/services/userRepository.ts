import type { UserRepository, User } from '../types';
import type {
    ApiResponse,
    UserAccountResponse,
    UserAccountEditRequest,
    ChangePasswordRequest,
} from '@/types/api';
import { apiRequest } from '@/api/client';

export class UserRepositoryImpl implements UserRepository {
    private baseUrl = '/user';

    private mapToDomain(apiUser: UserAccountResponse): User {
        return {
            id: 0, // Profile endpoint might not return ID? Need to check. For now 0 or hidden.
            username: apiUser.username,
            email: apiUser.email,
            firstName: apiUser.first_name,
            lastName: apiUser.last_name,
            fullName: apiUser.full_name,
            isActive: apiUser.is_active,
            isVerified: apiUser.is_verified,
            role: 'user', // Default or derived
            lastLogin: apiUser.last_login,
            hasPassword: apiUser.has_password ?? true,
            createdAt: '', // Not in response
            updatedAt: ''  // Not in response
        } as User;
    }

    async getAccount(): Promise<ApiResponse<User>> {
        const response = await apiRequest<ApiResponse<UserAccountResponse>>({
            method: 'GET',
            url: `${this.baseUrl}/account`
        });

        if (response.success && response.data) {
            return {
                ...response,
                data: this.mapToDomain(response.data)
            };
        }
        return response as any;
    }

    async updateAccount(data: UserAccountEditRequest): Promise<ApiResponse<User>> {
        const response: any = await apiRequest({
            method: 'PUT',
            url: `${this.baseUrl}/account/edit`,
            data
        });

        // The API might return the raw user object instead of a wrapped ApiResponse
        if (response && response.username && response.success === undefined) {
            return {
                success: true,
                message: 'Account updated successfully',
                data: this.mapToDomain(response as UserAccountResponse)
            };
        }

        if (response.success && response.data) {
            return {
                ...response,
                data: this.mapToDomain(response.data)
            };
        }
        return response as any;
    }

    async changePassword(data: ChangePasswordRequest): Promise<ApiResponse> {
        return apiRequest({
            method: 'POST',
            url: '/auth/change-password',
            data
        });
    }

    async deleteAccount(): Promise<ApiResponse> {
        return apiRequest({
            method: 'DELETE',
            url: `${this.baseUrl}/account/delete`
        });
    }

    async resendVerificationEmail(): Promise<ApiResponse> {
        return apiRequest({
            method: 'POST',
            url: '/auth/resend-verification'
        });
    }

    async getOAuthAccounts(): Promise<ApiResponse<{ accounts: any[]; has_password: boolean }>> {
        try {
            const data = await apiRequest<any>({
                method: 'GET',
                url: `${this.baseUrl}/account/oauth`,
            });
            return { success: true, message: 'OK', data };
        } catch {
            return { success: false, message: 'Failed to load OAuth accounts' };
        }
    }

    async linkOAuthProvider(provider: string, tokenOrCode: string, redirectUri?: string, confirmed?: boolean): Promise<ApiResponse<any>> {
        try {
            const data = await apiRequest<any>({
                method: 'POST',
                url: `${this.baseUrl}/account/oauth/link`,
                data: {
                    provider,
                    token_or_code: tokenOrCode,
                    redirect_uri: redirectUri,
                    confirmed: confirmed || false,
                },
            });
            return { success: true, message: data.message || 'Connected', data };
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            return { success: false, message: typeof detail === 'string' ? detail : 'Failed to connect account' };
        }
    }

    async unlinkOAuthAccount(provider: string): Promise<ApiResponse<void>> {
        try {
            await apiRequest<any>({
                method: 'DELETE',
                url: `${this.baseUrl}/account/oauth/${provider}`,
            });
            return { success: true, message: 'Account unlinked' };
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            return { success: false, message: typeof detail === 'string' ? detail : 'Failed to unlink account' };
        }
    }

    async setPassword(password: string, passwordConfirmation: string): Promise<ApiResponse<void>> {
        try {
            await apiRequest<any>({
                method: 'POST',
                url: `${this.baseUrl}/account/set-password`,
                data: { password, password_confirmation: passwordConfirmation },
            });
            return { success: true, message: 'Password set successfully' };
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            return { success: false, message: typeof detail === 'string' ? detail : 'Failed to set password' };
        }
    }
}
