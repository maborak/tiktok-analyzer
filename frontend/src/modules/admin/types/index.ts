import type { ApiResponse } from '@/types/api';

// ── Domain types (previously domain/types.ts) ──

export interface AdminUser {
    id: number;
    username: string;
    email: string;
    firstName: string | null;
    lastName: string | null;
    fullName: string;
    role: string;
    roleId?: number;
    isActive: boolean;
    isVerified: boolean;
    lastLogin: string | null;
    createdAt: string;
    updatedAt: string;
    apiRateLimit: number;
    failedLoginAttempts: number;
    lockedUntil: string | null;
    plan?: string | null;
}

export interface Role {
    id: number;
    name: string;
    description: string | null;
    isSystem: boolean;
    isActive: boolean;
    createdAt: string;
    updatedAt: string;
    permissions?: Permission[];
}

export interface Permission {
    id: number;
    name: string;
    description: string | null;
    category: string | null;
    isActive: boolean;
    createdAt: string;
    updatedAt: string;
}

export interface PaginationMeta {
    total: number;
    page: number;
    pageSize: number;
    totalPages: number;
}

export interface AdminUserListResponse {
    users: AdminUser[];
    pagination: PaginationMeta;
}

export interface RoleListResponse {
    roles: Role[];
    pagination: PaginationMeta;
}

export interface PermissionListResponse {
    permissions: Permission[];
    pagination: PaginationMeta;
}

// ── Port interfaces (previously application/ports/index.ts) ──

export interface AdminUserRepository {
    list(params?: any): Promise<ApiResponse<AdminUserListResponse>>;
    get(id: number): Promise<ApiResponse<{ user: AdminUser, roles: RoleListResponse, permissions: PermissionListResponse, userPermissions: { permissions: Permission[] }, rolePermissions: { permissions: Permission[] } | null }>>;
    create(data: any): Promise<ApiResponse<AdminUser>>;
    update(id: number, data: any): Promise<ApiResponse<AdminUser>>;
    delete(id: number): Promise<ApiResponse<void>>;
    impersonate(id: number): Promise<ApiResponse<any>>;
    assignPermission(userId: number, permissionId: number): Promise<ApiResponse<void>>;
    removePermission(userId: number, permissionId: number): Promise<ApiResponse<void>>;
}

export interface RBACRepository {
    listRoles(params?: any): Promise<ApiResponse<RoleListResponse>>;
    getRole(id: number): Promise<ApiResponse<{ role: Role, permissions: Permission[] }>>;
    createRole(data: any): Promise<ApiResponse<Role>>;
    updateRole(id: number, data: any): Promise<ApiResponse<Role>>;
    deleteRole(id: number): Promise<ApiResponse<void>>;

    listPermissions(params?: any): Promise<ApiResponse<PermissionListResponse>>;
}
