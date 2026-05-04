import type { AuthRepository } from '../types';
import type { AuthUser } from '../types';
import type { AuthTokens } from '../types';
import type { LoginRequest, RegisterRequest, PasswordResetRequest, ApiResponse, LoginResponse } from '@/types/api';
import { apiRequest } from '@/api/client';
import { apiConfig } from '@/config/env';

/** Custom error thrown when login fails, carries rate limit + CAPTCHA info from the API */
export class LoginError extends Error {
    captchaRequired: boolean;
    oauthOnly: boolean;
    providers: string[];
    retryAfter: number;
    attempt: number;
    constructor(message: string, captchaRequired: boolean = false, oauthOnly: boolean = false, providers: string[] = [], retryAfter: number = 0, attempt: number = 0) {
        super(message);
        this.name = 'LoginError';
        this.captchaRequired = captchaRequired;
        this.oauthOnly = oauthOnly;
        this.providers = providers;
        this.retryAfter = retryAfter;
        this.attempt = attempt;
    }
}

export class AuthRepositoryImpl implements AuthRepository {
    private buildAuthUrl(path: string): string {
        const base = apiConfig.baseUrl; // Using global config for now, could be injected
        if (base.endsWith('/') && path.startsWith('/')) {
            return `${base.slice(0, -1)}${path}`;
        }
        if (!base.endsWith('/') && !path.startsWith('/')) {
            return `${base}/${path}`;
        }
        return `${base}${path}`;
    }

    private mapUserToDomain(apiUser: any): AuthUser {
        return {
            id: apiUser.id,
            username: apiUser.username,
            email: apiUser.email,
            fullName: apiUser.full_name,
            role: apiUser.role,
            isVerified: apiUser.is_verified,
        };
    }

    private mapTokensToDomain(apiTokens: any): AuthTokens {
        return {
            accessToken: apiTokens.access_token,
            refreshToken: apiTokens.refresh_token,
            tokenType: apiTokens.token_type,
            expiresIn: apiTokens.expires_in,
        };
    }

    async login(credentials: LoginRequest): Promise<ApiResponse<{ user: AuthUser; tokens: AuthTokens }>> {
        try {
            const response = await apiRequest<ApiResponse<LoginResponse>>({
                method: 'POST',
                url: this.buildAuthUrl('/auth/login'),
                data: credentials,
            });

            if (response.success && response.data) {
                return {
                    ...response,
                    data: {
                        user: this.mapUserToDomain(response.data.user),
                        tokens: this.mapTokensToDomain(response.data.tokens),
                    }
                };
            }
            return response as any;
        } catch (error: any) {
            // Extract PRL fields, captcha_required, and OAUTH_ONLY_ACCOUNT from 401 response body
            const detail = error?.response?.data?.detail;
            const captchaRequired = typeof detail === 'object' && detail?.captcha_required === true;
            const oauthOnly = typeof detail === 'object' && detail?.code === 'OAUTH_ONLY_ACCOUNT';
            const providers = (typeof detail === 'object' && Array.isArray(detail?.providers)) ? detail.providers : [];
            const retryAfter = typeof detail === 'object' ? (detail?.retry_after || 0) : 0;
            const attempt = typeof detail === 'object' ? (detail?.attempt || 0) : 0;
            const message = typeof detail === 'object'
                ? detail?.message || 'Invalid email or password'
                : (typeof detail === 'string' ? detail : 'Invalid email or password');
            throw new LoginError(message, captchaRequired, oauthOnly, providers, retryAfter, attempt);
        }
    }

    async register(data: RegisterRequest): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/register'),
            data,
        });
    }

    async logout(): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/logout'),
        });
    }

    async requestPasswordReset(data: PasswordResetRequest): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/request-password-reset'),
            data,
        });
    }

    async resetPassword(token: string, newPassword: string, captchaToken?: string): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/reset-password'),
            data: {
                token,
                new_password: newPassword,
                captcha_token: captchaToken
            }
        });
    }

    async refreshToken(refreshToken: string): Promise<ApiResponse<AuthTokens>> {
        const response = await apiRequest<ApiResponse<any>>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/refresh'),
            data: { refresh_token: refreshToken }
        });

        if (response.success && response.data) {
            return {
                ...response,
                data: this.mapTokensToDomain(response.data.tokens)
            };
        }
        return response as any;
    }

    async getCurrentUser(): Promise<ApiResponse<AuthUser>> {
        const response = await apiRequest<ApiResponse<any>>({
            method: 'GET',
            url: this.buildAuthUrl('/auth/me'),
        }, { dedupe: true, cacheTtlMs: 10000 });

        if (response.success && response.data) {
            return {
                ...response,
                data: this.mapUserToDomain(response.data.user || response.data) // Handle potential nesting
            };
        }
        return response as any;
    }

    async changePassword(data: any): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/change-password'),
            data,
        });
    }

    async resendVerificationEmail(): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/resend-verification'),
        });
    }

    async verifyAccount(token: string, captchaToken?: string): Promise<ApiResponse> {
        return apiRequest<ApiResponse>({
            method: 'POST',
            url: this.buildAuthUrl('/auth/verify'),
            data: {
                token,
                captcha_token: captchaToken
            }
        });
    }

    async googleLogin(idToken: string): Promise<ApiResponse<any>> {
        try {
            const response = await apiRequest<ApiResponse<any>>({
                method: 'POST',
                url: this.buildAuthUrl('/auth/oauth/google'),
                data: { token: idToken },
            });

            if (response.success && response.data) {
                const action = response.data.action || 'logged_in';

                if (action === 'link_required') {
                    return {
                        ...response,
                        data: {
                            action: 'link_required',
                            link_data: response.data.link_data,
                        },
                    };
                }

                return {
                    ...response,
                    data: {
                        action,
                        user: this.mapUserToDomain(response.data.user),
                        tokens: this.mapTokensToDomain(response.data.tokens),
                    }
                };
            }
            return response as any;
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            const message = typeof detail === 'string' ? detail : 'Error during Google authentication';
            throw new Error(message);
        }
    }

    async githubLogin(code: string): Promise<ApiResponse<any>> {
        try {
            const response = await apiRequest<ApiResponse<any>>({
                method: 'POST',
                url: this.buildAuthUrl('/auth/oauth/github'),
                data: { code },
            });

            if (response.success && response.data) {
                const action = response.data.action || 'logged_in';

                if (action === 'link_required') {
                    return {
                        ...response,
                        data: {
                            action: 'link_required',
                            link_data: response.data.link_data,
                        },
                    };
                }

                return {
                    ...response,
                    data: {
                        action,
                        user: this.mapUserToDomain(response.data.user),
                        tokens: this.mapTokensToDomain(response.data.tokens),
                    }
                };
            }
            return response as any;
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            const message = typeof detail === 'string' ? detail : 'Error during GitHub authentication';
            throw new Error(message);
        }
    }

    async facebookLogin(code: string, redirectUri: string): Promise<ApiResponse<any>> {
        try {
            const response = await apiRequest<ApiResponse<any>>({
                method: 'POST',
                url: this.buildAuthUrl('/auth/oauth/facebook'),
                data: { code, redirect_uri: redirectUri },
            });

            if (response.success && response.data) {
                const action = response.data.action || 'logged_in';

                if (action === 'link_required') {
                    return {
                        ...response,
                        data: {
                            action: 'link_required',
                            link_data: response.data.link_data,
                        },
                    };
                }

                return {
                    ...response,
                    data: {
                        action,
                        user: this.mapUserToDomain(response.data.user),
                        tokens: this.mapTokensToDomain(response.data.tokens),
                    }
                };
            }
            return response as any;
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            const message = typeof detail === 'string' ? detail : 'Error during Facebook authentication';
            throw new Error(message);
        }
    }

    async confirmOAuthLink(data: {
        link_token: string;
        password: string;
        captcha_token?: string;
    }): Promise<ApiResponse<{ user: AuthUser; tokens: AuthTokens }>> {
        try {
            const response = await apiRequest<ApiResponse<LoginResponse>>({
                method: 'POST',
                url: this.buildAuthUrl('/auth/oauth/confirm-link'),
                data,
            });

            if (response.success && response.data) {
                return {
                    ...response,
                    data: {
                        user: this.mapUserToDomain(response.data.user),
                        tokens: this.mapTokensToDomain(response.data.tokens),
                    },
                };
            }
            return response as any;
        } catch (error: any) {
            const detail = error?.response?.data?.detail;
            const captchaRequired = typeof detail === 'object' && detail?.captcha_required === true;
            const retryAfter = typeof detail === 'object' ? (detail?.retry_after || 0) : 0;
            const attempt = typeof detail === 'object' ? (detail?.attempt || 0) : 0;
            const message = typeof detail === 'object'
                ? detail?.message || 'Incorrect password'
                : (typeof detail === 'string' ? detail : 'Error linking account');
            throw new LoginError(message, captchaRequired, false, [], retryAfter, attempt);
        }
    }
}
