import type { RecipientRepository, Recipient, CreateRecipientRequest, UpdateRecipientRequest } from '../types';
import type { ApiResponse, RecipientListResponse, Recipient as ApiRecipient, PaginationMeta } from '@/types/api';
import { apiRequest } from '@/api/client';

export class RecipientRepositoryImpl implements RecipientRepository {
    private baseUrl = '/user/account/recipients';

    private mapToDomain(r: ApiRecipient): Recipient {
        return {
            id: r.id,
            type: r.type,
            value: r.value,
            isVerified: r.is_verified,
            isEnabled: r.is_enabled,
            name: r.name,
            subjectTag: r.subject_tag
        };
    }

    async list(params?: { page?: number; pageSize?: number; search?: string; sortBy?: string; sortOrder?: "asc" | "desc"; type?: string; isVerified?: boolean; }): Promise<ApiResponse<{ recipients: Recipient[]; pagination: PaginationMeta; }>> {
        const queryParams: Record<string, any> = {};
        if (params?.page) queryParams.page = params.page;
        if (params?.pageSize) queryParams.page_size = params.pageSize;
        if (params?.search) queryParams.search = params.search;
        if (params?.sortBy) queryParams.sort_by = params.sortBy;
        if (params?.sortOrder) queryParams.sort_order = params.sortOrder;
        if (params?.type) queryParams.recipient_type = params.type;
        if (params?.isVerified !== undefined) queryParams.is_verified = params.isVerified;

        const response = await apiRequest<ApiResponse<RecipientListResponse>>({
            method: 'GET',
            url: this.baseUrl,
            params: queryParams
        });

        if (response.success && response.data) {
            return {
                ...response,
                data: {
                    recipients: response.data.recipients.map(this.mapToDomain),
                    pagination: {
                        page: response.data.pagination.page,
                        page_size: response.data.pagination.page_size,
                        total_items: response.data.pagination.total,
                        total_pages: response.data.pagination.total_pages,
                        has_next: response.data.pagination.page < response.data.pagination.total_pages,
                        has_previous: response.data.pagination.page > 1
                    }
                }
            };
        }
        return response as any;
    }

    async create(data: CreateRecipientRequest): Promise<ApiResponse<Recipient>> {
        const response = await apiRequest<ApiResponse<ApiRecipient>>({
            method: 'POST',
            url: this.baseUrl,
            data
        });

        if (response.success && response.data) {
            return {
                ...response,
                data: this.mapToDomain(response.data)
            };
        }
        return response as any;
    }

    async update(id: number, data: UpdateRecipientRequest): Promise<ApiResponse<Recipient>> {
        // Map domain fields to API snake_case
        const apiData: any = {};
        if (data.name !== undefined) apiData.name = data.name;
        if (data.isEnabled !== undefined) apiData.is_enabled = data.isEnabled;
        if (data.subjectTag !== undefined) apiData.subject_tag = data.subjectTag;

        const response = await apiRequest<ApiResponse<ApiRecipient>>({
            method: 'PATCH',
            url: `${this.baseUrl}/${id}`,
            data: apiData
        });

        if (response.success && response.data) {
            return {
                ...response,
                data: this.mapToDomain(response.data)
            };
        }
        return response as any;
    }

    async delete(id: number): Promise<ApiResponse> {
        return apiRequest({
            method: 'DELETE',
            url: `${this.baseUrl}/${id}`
        });
    }

    async resendVerification(id: number, captchaToken?: string): Promise<ApiResponse> {
        return apiRequest({
            method: 'POST',
            url: `${this.baseUrl}/${id}/resend-verification`,
            data: { captcha_token: captchaToken || null }
        });
    }
}
