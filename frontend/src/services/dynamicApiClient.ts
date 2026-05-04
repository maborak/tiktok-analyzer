import type { AxiosRequestConfig } from 'axios';
import { apiConfig } from '../config/env';
import { apiRequest, setApiBaseUrl } from '../api/client';
import type { RequestOptions } from '../api/client';
import type {
  ApiResponse,
  LoginRequest,
  RegisterRequest,
  PasswordResetRequest,
  UsersListResponse,
  User,
  CreateUserRequest,
  UpdateUserRequest,
  Permission,
  PermissionsListResponse,
  CreatePermissionRequest,
  UpdatePermissionRequest,
  RolePermissionsResponse,
  UserPermissionsResponse,
  AssignPermissionResponse,
  Role,
  RolesListResponse,
  CreateRoleRequest,
  UpdateRoleRequest,
  UserAccountResponse,
  UserAccountEditRequest,
  MessageResponse,
  ChangePasswordRequest,
  Recipient,
  RecipientCreateRequest,
  RecipientVerifyRequest,
  RecipientListResponse,
  RecipientUpdateRequest,
  ImpersonationResponse,
} from '../types/api';

export class DynamicApiClient {
  private _baseURL: string;

  constructor(baseURL?: string) {
    this._baseURL = baseURL || apiConfig.baseUrl;
    console.log('🔍 DynamicApiClient constructor called with baseURL:', this._baseURL);
  }

  private buildAuthUrl(path: string): string {
    // Use the instance base URL for all endpoints (including auth)
    const base = this._baseURL || apiConfig.baseUrl;
    if (base.endsWith('/') && path.startsWith('/')) {
      return `${base.slice(0, -1)}${path}`;
    }
    if (!base.endsWith('/') && !path.startsWith('/')) {
      return `${base}/${path}`;
    }
    return `${base}${path}`;
  }

  private request<T>(config: AxiosRequestConfig, options: RequestOptions = {}): Promise<T> {
    return apiRequest<T>({
      ...config,
      baseURL: this._baseURL,
    }, options);
  }

  private get<T>(url: string, config: AxiosRequestConfig = {}, options: RequestOptions = {}): Promise<T> {
    return this.request<T>({ ...config, method: 'GET', url }, options);
  }

  private post<T>(url: string, data?: unknown, config: AxiosRequestConfig = {}, options: RequestOptions = {}): Promise<T> {
    return this.request<T>({ ...config, method: 'POST', url, data }, options);
  }

  private put<T>(url: string, data?: unknown, config: AxiosRequestConfig = {}, options: RequestOptions = {}): Promise<T> {
    return this.request<T>({ ...config, method: 'PUT', url, data }, options);
  }

  private delete<T>(url: string, config: AxiosRequestConfig = {}, options: RequestOptions = {}): Promise<T> {
    return this.request<T>({ ...config, method: 'DELETE', url }, options);
  }

  // Method to update the base URL
  updateBaseURL(newBaseURL: string) {
    this._baseURL = newBaseURL;
    setApiBaseUrl(newBaseURL);
    console.log(`API Base URL updated to: ${newBaseURL}`);
  }

  // General Endpoints
  async getRoot(): Promise<any> {
    return this.get<any>('/', {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async healthCheck(): Promise<any> {
    try {
      const response = await this.get<any>('/health', {}, { dedupe: true, cacheTtlMs: 5000 });

      // Validate that this is our API by checking for expected response structure
      // Our API should return a health check response with specific fields
      if (!response || typeof response !== 'object') {
        throw new Error('Invalid health check response - not our API');
      }

      // Check if the response has expected fields that indicate it's our API
      // This could be a specific field, status, or structure that only our API returns
      const data = response;

      // If it's a simple string response, it might not be our API
      if (typeof data === 'string' && !data.includes('legal') && !data.includes('api')) {
        throw new Error('Health check response does not match our API format');
      }

      // If it's an object, check for expected fields (adjust based on your API's actual response)
      if (typeof data === 'object') {
        // Add specific checks for your API's health response structure
        // For example, if your API returns { status: "healthy", version: "1.0" }
        if (data.status === 'healthy' || data.message?.includes('healthy') || data.health === 'ok') {
          return response;
        }

        // If it's a generic success response without our specific structure, it might not be our API
        if (data.success === true && !data.message?.includes('healthy')) {
          // Allow generic success responses
        }
      }

      return response;
    } catch (error: any) {
      // If it's a 404, it definitely doesn't have our health endpoint
      if (error.response?.status === 404) {
        throw new Error('Health endpoint not found - this is not our API server');
      }

      // Re-throw other errors
      throw error;
    }
  }

  // Utility Methods
  formatTimestamp(timestamp?: string): string {
    if (!timestamp) return 'N/A';

    const date = new Date(timestamp);
    const now = new Date();

    // Check if the date is valid
    if (isNaN(date.getTime())) {
      return 'Invalid date';
    }

    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    // Handle future dates and invalid timestamps
    if (diffInSeconds < 0) {
      return 'Just now';
    }

    if (diffInSeconds < 60) {
      return `${diffInSeconds} seconds ago`;
    } else if (diffInSeconds < 3600) {
      const minutes = Math.floor(diffInSeconds / 60);
      return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
    } else if (diffInSeconds < 86400) {
      const hours = Math.floor(diffInSeconds / 3600);
      return `${hours} hour${hours > 1 ? 's' : ''} ago`;
    } else {
      const days = Math.floor(diffInSeconds / 86400);
      return `${days} day${days > 1 ? 's' : ''} ago`;
    }
  }

  // Authentication Endpoints
  async login(credentials: LoginRequest): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/login'), credentials);
  }

  async register(data: RegisterRequest): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/register'), data);
  }

  async logout(): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/logout'));
  }

  async requestPasswordReset(data: PasswordResetRequest): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/request-password-reset'), data);
  }

  async resetPassword(token: string, newPassword: string, captchaToken?: string): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/reset-password'), {
      token,
      new_password: newPassword,
      captcha_token: captchaToken
    });
  }

  async refreshToken(refreshToken: string): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/refresh'), {
      refresh_token: refreshToken
    });
  }

  async getCurrentUser(): Promise<ApiResponse> {
    return this.get<ApiResponse>(this.buildAuthUrl('/auth/me'), {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  // Admin API Endpoints - Users Management
  async listUsers(params?: {
    page?: number;
    page_size?: number;
    role_id?: number;
    is_active?: boolean;
    is_verified?: boolean;
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }): Promise<UsersListResponse> {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.page_size) queryParams.append('page_size', params.page_size.toString());
    if (params?.role_id) queryParams.append('role_id', params.role_id.toString());
    if (params?.is_active !== undefined) queryParams.append('is_active', params.is_active.toString());
    if (params?.is_verified !== undefined) queryParams.append('is_verified', params.is_verified.toString());
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort_by) queryParams.append('sort_by', params.sort_by);
    if (params?.sort_order) queryParams.append('sort_order', params.sort_order);

    const queryString = queryParams.toString();
    const url = `/admin/users${queryString ? `?${queryString}` : ''}`;
    return this.get<UsersListResponse>(url, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async getUser(userId: number): Promise<User> {
    return this.get<User>(`/admin/users/${userId}`, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async createUser(userData: CreateUserRequest): Promise<User> {
    return this.post<User>('/admin/users', userData);
  }

  async updateUser(userId: number, userData: UpdateUserRequest): Promise<User> {
    return this.put<User>(`/admin/users/${userId}`, userData);
  }

  async deleteUser(userId: number): Promise<void> {
    await this.delete<void>(`/admin/users/${userId}`);
  }

  // Admin API Endpoints - RBAC (Role-Based Access Control) Management
  async listPermissions(params?: {
    page?: number;
    page_size?: number;
    category?: string;
    is_active?: boolean;
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }): Promise<PermissionsListResponse> {
    const queryParams = new URLSearchParams();
    if (params?.page !== undefined && params.page > 0) {
      queryParams.append('page', params.page.toString());
    }
    if (params?.page_size !== undefined && params.page_size > 0) {
      queryParams.append('page_size', params.page_size.toString());
    }
    if (params?.category) {
      queryParams.append('category', params.category);
    }
    if (params?.is_active !== undefined) {
      queryParams.append('is_active', params.is_active.toString());
    }
    if (params?.search) {
      queryParams.append('search', params.search);
    }
    if (params?.sort_by) {
      queryParams.append('sort_by', params.sort_by);
    }
    if (params?.sort_order) {
      queryParams.append('sort_order', params.sort_order);
    }

    const queryString = queryParams.toString();
    const url = `/admin/rbac/permissions${queryString ? `?${queryString}` : ''}`;
    return this.get<PermissionsListResponse>(url, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async getPermission(permissionId: number): Promise<Permission> {
    return this.get<Permission>(`/admin/rbac/permissions/${permissionId}`, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async createPermission(permissionData: CreatePermissionRequest): Promise<Permission> {
    return this.post<Permission>('/admin/rbac/permissions', permissionData);
  }

  async updatePermission(permissionId: number, permissionData: UpdatePermissionRequest): Promise<Permission> {
    return this.put<Permission>(`/admin/rbac/permissions/${permissionId}`, permissionData);
  }

  async deletePermission(permissionId: number): Promise<void> {
    await this.delete<void>(`/admin/rbac/permissions/${permissionId}`);
  }

  // Admin API Endpoints - Roles CRUD (Dynamic Roles)
  async listRoles(params?: {
    page?: number;
    page_size?: number;
    is_active?: boolean;
    is_system?: boolean;
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
    include_inactive?: boolean; // Legacy support
  }): Promise<RolesListResponse> {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.page_size) queryParams.append('page_size', params.page_size.toString());
    if (params?.is_active !== undefined) queryParams.append('is_active', params.is_active.toString());
    if (params?.is_system !== undefined) queryParams.append('is_system', params.is_system.toString());
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort_by) queryParams.append('sort_by', params.sort_by);
    if (params?.sort_order) queryParams.append('sort_order', params.sort_order);
    // Legacy support for include_inactive
    if (params?.include_inactive && params?.is_active === undefined) {
      queryParams.append('is_active', 'false');
    }
    const queryString = queryParams.toString();
    const url = `/admin/rbac/roles${queryString ? `?${queryString}` : ''}`;
    return this.get<RolesListResponse>(url, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  // Admin User Impersonation
  async loginAsUser(userId: number): Promise<ImpersonationResponse> {
    return this.post<ImpersonationResponse>(`/admin/users/${userId}/login-as`);
  }

  async loginAsUserByEmail(email: string): Promise<ImpersonationResponse> {
    return this.post<ImpersonationResponse>('/admin/users/login-as', { email });
  }

  async getRole(roleId: number): Promise<Role> {
    return this.get<Role>(`/admin/rbac/roles/${roleId}`, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async createRole(roleData: CreateRoleRequest): Promise<Role> {
    return this.post<Role>('/admin/rbac/roles', roleData);
  }

  async updateRole(roleId: number, roleData: UpdateRoleRequest): Promise<Role> {
    return this.put<Role>(`/admin/rbac/roles/${roleId}`, roleData);
  }

  async deleteRole(roleId: number): Promise<void> {
    await this.delete<void>(`/admin/rbac/roles/${roleId}`);
  }

  // Role-Permission Management
  async getRolePermissions(roleId: number): Promise<RolePermissionsResponse> {
    return this.get<RolePermissionsResponse>(`/admin/rbac/roles/${roleId}/permissions`, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async assignPermissionToRole(roleId: number, permissionId: number): Promise<AssignPermissionResponse> {
    return this.post<AssignPermissionResponse>(`/admin/rbac/roles/${roleId}/permissions`, {
      permission_id: permissionId
    });
  }

  async removePermissionFromRole(roleId: number, permissionId: number): Promise<void> {
    await this.delete<void>(`/admin/rbac/roles/${roleId}/permissions/${permissionId}`);
  }

  // User-Permission Management
  async getUserPermissions(userId: number): Promise<UserPermissionsResponse> {
    return this.get<UserPermissionsResponse>(`/admin/rbac/users/${userId}/permissions`, {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async assignPermissionToUser(userId: number, permissionId: number): Promise<AssignPermissionResponse> {
    return this.post<AssignPermissionResponse>(`/admin/rbac/users/${userId}/permissions`, {
      permission_id: permissionId
    });
  }

  async removePermissionFromUser(userId: number, permissionId: number): Promise<void> {
    await this.delete<void>(`/admin/rbac/users/${userId}/permissions/${permissionId}`);
  }

  // Recipient Management Endpoints
  async listRecipients(params?: {
    page?: number;
    page_size?: number;
    search?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
    recipient_type?: string;
    is_verified?: boolean;
  }): Promise<ApiResponse<RecipientListResponse>> {
    return this.get<ApiResponse<RecipientListResponse>>('/user/account/recipients', { params }, { dedupe: true, cacheTtlMs: 5000 });
  }

  async createRecipient(data: RecipientCreateRequest): Promise<ApiResponse<Recipient>> {
    return this.post<ApiResponse<Recipient>>('/user/account/recipients', data);
  }

  async updateRecipient(id: number, data: RecipientUpdateRequest): Promise<ApiResponse<Recipient>> {
    return this.request<ApiResponse<Recipient>>({ method: 'PATCH', url: `/user/account/recipients/${id}`, data });
  }

  async verifyRecipient(data: RecipientVerifyRequest): Promise<ApiResponse<null>> {
    return this.post<ApiResponse<null>>('/user/account/recipients/verify', data);
  }

  async resendRecipientVerification(id: number, captchaToken?: string): Promise<ApiResponse<null>> {
    return this.post<ApiResponse<null>>(`/user/account/recipients/${id}/resend-verification`, {
      captcha_token: captchaToken
    });
  }

  async deleteRecipient(id: number): Promise<ApiResponse<null>> {
    return this.delete<ApiResponse<null>>(`/user/account/recipients/${id}`);
  }

  // User Account Endpoints (for authenticated users - /user/account)
  async getAccount(): Promise<ApiResponse<UserAccountResponse>> {
    return this.get<ApiResponse<UserAccountResponse>>('/user/account', {}, { dedupe: true, cacheTtlMs: 10000 });
  }

  async editAccount(data: UserAccountEditRequest): Promise<ApiResponse<UserAccountResponse>> {
    return this.put<ApiResponse<UserAccountResponse>>('/user/account/edit', data);
  }

  async deleteAccount(): Promise<ApiResponse<MessageResponse>> {
    return this.delete<ApiResponse<MessageResponse>>('/user/account/delete');
  }

  async changePassword(data: ChangePasswordRequest): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/change-password'), data);
  }

  async resendVerificationEmail(): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/resend-verification'));
  }

  async verifyAccount(token: string, captchaToken?: string): Promise<ApiResponse> {
    return this.post<ApiResponse>(this.buildAuthUrl('/auth/verify'), {
      token,
      captcha_token: captchaToken
    });
  }

}