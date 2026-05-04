// Auth domain types (merged from domain/ + application/ports/)

export interface AuthTokens {
    accessToken: string;
    refreshToken: string;
    tokenType: string;
    expiresIn: number;
}

export interface AuthUser {
    id: number;
    username: string;
    email: string;
    fullName?: string;
    role?: string;
    isVerified?: boolean;
}

export interface OAuthLinkData {
    user_id: number;
    email: string;
    provider: string;
    provider_user_id: string;
    name: string;
    picture: string;
}

export interface OAuthResponse {
    action: 'logged_in' | 'account_created' | 'link_required';
    user?: AuthUser;
    tokens?: AuthTokens;
    link_data?: OAuthLinkData;
}

import type { LoginRequest, RegisterRequest, PasswordResetRequest, ApiResponse } from '@/types/api';

export interface AuthRepository {
    login(credentials: LoginRequest): Promise<ApiResponse<{ user: AuthUser; tokens: AuthTokens }>>;
    register(data: RegisterRequest): Promise<ApiResponse>;
    logout(): Promise<ApiResponse>;
    requestPasswordReset(data: PasswordResetRequest): Promise<ApiResponse>;
    resetPassword(token: string, newPassword: string, captchaToken?: string): Promise<ApiResponse>;
    refreshToken(refreshToken: string): Promise<ApiResponse<AuthTokens>>;
    getCurrentUser(): Promise<ApiResponse<AuthUser>>;
    changePassword(data: any): Promise<ApiResponse>;
    resendVerificationEmail(): Promise<ApiResponse>;
    verifyAccount(token: string, captchaToken?: string): Promise<ApiResponse>;
    googleLogin(idToken: string): Promise<ApiResponse<OAuthResponse>>;
    githubLogin(code: string): Promise<ApiResponse<OAuthResponse>>;
    facebookLogin(code: string, redirectUri: string): Promise<ApiResponse<OAuthResponse>>;
    confirmOAuthLink(data: { link_token: string; password: string; captcha_token?: string }): Promise<ApiResponse<{ user: AuthUser; tokens: AuthTokens }>>;
}
