// ── Domain types (formerly domain/User.ts) ──────────────────────────

export interface User {
    id: number;
    username: string;
    email: string;
    firstName?: string;
    lastName?: string;
    fullName: string;
    isActive: boolean;
    isVerified: boolean;
    role: string;
    roleId?: number;
    lastLogin?: string | null;
    hasPassword?: boolean;
    createdAt: string;
    updatedAt: string;
}

export interface UserPreferences {
    apiRateLimit: number;
}

// ── Domain types (formerly domain/Recipient.ts) ─────────────────────

export type RecipientType = 'email' | 'slack' | 'webhook';

export interface Recipient {
    id: number;
    type: RecipientType;
    value: string;
    isVerified: boolean;
    isEnabled: boolean;
    name?: string;
    subjectTag?: string;
}

export interface CreateRecipientRequest {
    type: RecipientType;
    value: string;
    name?: string;
}

export interface UpdateRecipientRequest {
    name?: string;
    isEnabled?: boolean;
    subjectTag?: string;
}

// ── Port interfaces (formerly application/ports/UserRepository.ts) ──

import type { ApiResponse, UserAccountEditRequest, ChangePasswordRequest } from '@/types/api';

export interface UserRepository {
    getAccount(): Promise<ApiResponse<User>>;
    updateAccount(data: UserAccountEditRequest): Promise<ApiResponse<User>>;
    changePassword(data: ChangePasswordRequest): Promise<ApiResponse>;
    deleteAccount(): Promise<ApiResponse>;
    resendVerificationEmail(): Promise<ApiResponse>;
}

// ── Port interfaces (formerly application/ports/RecipientRepository.ts)

import type { PaginationMeta } from '@/types/api';

export interface RecipientRepository {
    list(params?: {
        page?: number;
        pageSize?: number;
        search?: string;
        sortBy?: string;
        sortOrder?: 'asc' | 'desc';
        type?: string;
        isVerified?: boolean;
    }): Promise<ApiResponse<{ recipients: Recipient[]; pagination: PaginationMeta }>>;

    create(data: CreateRecipientRequest): Promise<ApiResponse<Recipient>>;
    update(id: number, data: UpdateRecipientRequest): Promise<ApiResponse<Recipient>>;
    delete(id: number): Promise<ApiResponse>;
    resendVerification(id: number, captchaToken?: string): Promise<ApiResponse>;
}
