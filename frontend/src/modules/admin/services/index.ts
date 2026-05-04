import { apiRequest } from '@/api/client';
import type { ApiResponse } from '@/types/api';
import type { AdminUserRepository, RBACRepository } from '../types';
import type { AdminUserListResponse, RoleListResponse, PermissionListResponse } from '../types';
import type { AdminUser, Role, Permission } from '../types';
import { mapUserToDomain, mapRoleToDomain, mapPermissionToDomain } from './mappers';

class AdminUserRepositoryImpl implements AdminUserRepository {
    async list(params?: any): Promise<ApiResponse<AdminUserListResponse>> {
        try {
            const data = await apiRequest<any>({
                method: 'GET',
                url: '/admin/users',
                params
            });

            // The API returns a flat object (UsersListResponse)
            const pagination = data.pagination ? {
                total: data.pagination.total_items || data.pagination.total,
                page: data.pagination.page,
                pageSize: data.pagination.page_size,
                totalPages: data.pagination.total_pages,
                hasNext: data.pagination.has_next,
                hasPrevious: data.pagination.has_previous
            } : {
                total: data.total,
                page: data.page,
                pageSize: data.page_size,
                totalPages: data.total_pages
            };

            return {
                success: true,
                message: 'Users fetched successfully',
                data: {
                    users: data.users.map(mapUserToDomain),
                    pagination
                }
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to fetch users',
            };
        }
    }

    async get(id: number): Promise<ApiResponse<{ user: AdminUser, roles: RoleListResponse, permissions: PermissionListResponse, userPermissions: { permissions: Permission[] }, rolePermissions: { permissions: Permission[] } | null }>> {
        try {
            const [userData, rolesData, permissionsData, userPermissionsData] = await Promise.all([
                apiRequest<any>({ method: 'GET', url: `/admin/users/${id}` }),
                apiRequest<any>({ method: 'GET', url: '/admin/rbac/roles', params: { page: 1, page_size: 100, is_active: true } }),
                apiRequest<any>({ method: 'GET', url: '/admin/rbac/permissions', params: { page: 1, page_size: 100, is_active: true } }),
                apiRequest<any>({ method: 'GET', url: `/admin/rbac/users/${id}/permissions` })
            ]);

            const user = mapUserToDomain(userData);

            let rolePermissionsData: any = null;
            if (user.roleId) {
                rolePermissionsData = await apiRequest<any>({
                    method: 'GET',
                    url: `/admin/rbac/roles/${user.roleId}/permissions`
                });
            }

            return {
                success: true,
                message: 'User details fetched',
                data: {
                    user,
                    roles: {
                        roles: (rolesData.roles || []).map(mapRoleToDomain),
                        pagination: rolesData.pagination || {
                            total: rolesData.total,
                            page: rolesData.page,
                            pageSize: rolesData.page_size,
                            totalPages: rolesData.total_pages
                        }
                    },
                    permissions: {
                        permissions: (permissionsData.permissions || []).map(mapPermissionToDomain),
                        pagination: permissionsData.pagination || {
                            total: permissionsData.total,
                            page: permissionsData.page,
                            pageSize: permissionsData.page_size,
                            totalPages: permissionsData.total_pages
                        }
                    },
                    userPermissions: {
                        permissions: (userPermissionsData.permissions || []).map(mapPermissionToDomain)
                    },
                    rolePermissions: rolePermissionsData ? {
                        permissions: (rolePermissionsData.permissions || []).map(mapPermissionToDomain)
                    } : null
                }
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to fetch user details',
            };
        }
    }

    async create(data: any): Promise<ApiResponse<AdminUser>> {
        try {
            const userData = await apiRequest<any>({
                method: 'POST',
                url: '/admin/users',
                data
            });
            return {
                success: true,
                message: 'User created successfully',
                data: mapUserToDomain(userData)
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to create user',
            };
        }
    }

    async update(id: number, data: any): Promise<ApiResponse<AdminUser>> {
        try {
            const userData = await apiRequest<any>({
                method: 'PUT',
                url: `/admin/users/${id}`,
                data
            });
            return {
                success: true,
                message: 'User updated successfully',
                data: mapUserToDomain(userData)
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to update user',
            };
        }
    }

    async delete(id: number): Promise<ApiResponse<void>> {
        return apiRequest({
            method: 'DELETE',
            url: `/admin/users/${id}`
        });
    }

    async impersonate(id: number): Promise<ApiResponse<any>> {
        try {
            const data = await apiRequest<any>({
                method: 'POST',
                url: `/admin/users/${id}/login-as`
            });
            return {
                success: true,
                message: 'Impersonation successful',
                data
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to impersonate user',
            };
        }
    }

    async assignPermission(userId: number, permissionId: number): Promise<ApiResponse<void>> {
        return apiRequest({
            method: 'POST',
            url: `/admin/rbac/users/${userId}/permissions/${permissionId}`
        });
    }

    async removePermission(userId: number, permissionId: number): Promise<ApiResponse<void>> {
        return apiRequest({
            method: 'DELETE',
            url: `/admin/rbac/users/${userId}/permissions/${permissionId}`
        });
    }
}

class RBACRepositoryImpl implements RBACRepository {
    async listRoles(params?: any): Promise<ApiResponse<RoleListResponse>> {
        try {
            const data = await apiRequest<any>({
                method: 'GET',
                url: '/admin/rbac/roles',
                params
            });

            const pagination = data.pagination ? {
                total: data.pagination.total_items || data.pagination.total,
                page: data.pagination.page,
                pageSize: data.pagination.page_size,
                totalPages: data.pagination.total_pages,
                hasNext: data.pagination.has_next,
                hasPrevious: data.pagination.has_previous
            } : {
                total: data.total,
                page: data.page,
                pageSize: data.page_size,
                totalPages: data.total_pages
            };

            return {
                success: true,
                message: 'Roles fetched successfully',
                data: {
                    roles: data.roles.map(mapRoleToDomain),
                    pagination
                }
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to fetch roles',
            };
        }
    }

    async getRole(id: number): Promise<ApiResponse<{ role: Role, permissions: Permission[] }>> {
        try {
            const roleData = await apiRequest<any>({
                method: 'GET',
                url: `/admin/rbac/roles/${id}`
            });
            return {
                success: true,
                message: 'Role fetched successfully',
                data: {
                    role: mapRoleToDomain(roleData),
                    permissions: (roleData.permissions || []).map(mapPermissionToDomain)
                }
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to fetch role',
            };
        }
    }

    async createRole(data: any): Promise<ApiResponse<Role>> {
        try {
            const roleData = await apiRequest<any>({
                method: 'POST',
                url: '/admin/rbac/roles',
                data
            });
            return {
                success: true,
                message: 'Role created successfully',
                data: mapRoleToDomain(roleData)
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to create role',
            };
        }
    }

    async updateRole(id: number, data: any): Promise<ApiResponse<Role>> {
        try {
            const roleData = await apiRequest<any>({
                method: 'PUT',
                url: `/admin/rbac/roles/${id}`,
                data
            });
            return {
                success: true,
                message: 'Role updated successfully',
                data: mapRoleToDomain(roleData)
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to update role',
            };
        }
    }

    async deleteRole(id: number): Promise<ApiResponse<void>> {
        return apiRequest({
            method: 'DELETE',
            url: `/admin/rbac/roles/${id}`
        });
    }

    async listPermissions(params?: any): Promise<ApiResponse<PermissionListResponse>> {
        try {
            const data = await apiRequest<any>({
                method: 'GET',
                url: '/admin/rbac/permissions',
                params
            });

            const pagination = data.pagination ? {
                total: data.pagination.total_items || data.pagination.total,
                page: data.pagination.page,
                pageSize: data.pagination.page_size,
                totalPages: data.pagination.total_pages,
                hasNext: data.pagination.has_next,
                hasPrevious: data.pagination.has_previous
            } : {
                total: data.total,
                page: data.page,
                pageSize: data.page_size,
                totalPages: data.total_pages
            };

            return {
                success: true,
                message: 'Permissions fetched successfully',
                data: {
                    permissions: data.permissions.map(mapPermissionToDomain),
                    pagination
                }
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to fetch permissions',
            };
        }
    }
}

class SecurityRepositoryImpl {
    async listLockouts(params?: any): Promise<ApiResponse<any>> {
        try {
            const data = await apiRequest<any>({
                method: 'GET',
                url: '/admin/security/lockouts',
                params,
            });
            return {
                success: true,
                message: 'Lockouts fetched',
                data: {
                    users: data.users.map((u: any) => ({
                        id: u.id,
                        username: u.username,
                        email: u.email,
                        firstName: u.first_name,
                        lastName: u.last_name,
                        isActive: u.is_active,
                        isVerified: u.is_verified,
                        failedLoginAttempts: u.failed_login_attempts,
                        lockedUntil: u.locked_until,
                        lastLogin: u.last_login,
                    })),
                    pagination: {
                        total: data.total,
                        page: data.page,
                        pageSize: data.page_size,
                        totalPages: data.total_pages,
                    },
                },
            };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to fetch lockouts',
            };
        }
    }

    async unlockUser(userId: number): Promise<ApiResponse<any>> {
        try {
            const data = await apiRequest<any>({
                method: 'POST',
                url: `/admin/security/lockouts/${userId}/unlock`,
            });
            return { success: true, message: data.message, data };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to unlock user',
            };
        }
    }

    async unlockAll(): Promise<ApiResponse<any>> {
        try {
            const data = await apiRequest<any>({
                method: 'POST',
                url: '/admin/security/lockouts/unlock-all',
            });
            return { success: true, message: data.message, data };
        } catch (error: any) {
            return {
                success: false,
                message: error.response?.data?.detail || 'Failed to unlock all users',
            };
        }
    }
}

export const adminUserRepository = new AdminUserRepositoryImpl();
export const rbacRepository = new RBACRepositoryImpl();
export const securityRepository = new SecurityRepositoryImpl();
export * from './tickets';
