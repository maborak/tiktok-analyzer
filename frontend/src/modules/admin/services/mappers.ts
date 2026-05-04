import type { AdminUser, Role, Permission } from '../types';

export const mapUserToDomain = (data: any): AdminUser => {
    return {
        id: data.id,
        username: data.username,
        email: data.email,
        firstName: data.first_name,
        lastName: data.last_name,
        fullName: data.full_name || `${data.first_name || ''} ${data.last_name || ''}`.trim() || data.username,
        role: data.role,
        roleId: data.role_id,
        isActive: data.is_active,
        isVerified: data.is_verified,
        lastLogin: data.last_login,
        createdAt: data.created_at,
        updatedAt: data.updated_at,
        apiRateLimit: data.api_rate_limit,
        failedLoginAttempts: data.failed_login_attempts,
        lockedUntil: data.locked_until,
    };
};

export const mapRoleToDomain = (data: any): Role => {
    return {
        id: data.id,
        name: data.name,
        description: data.description,
        isSystem: data.is_system,
        isActive: data.is_active,
        createdAt: data.created_at,
        updatedAt: data.updated_at,
        permissions: data.permissions ? data.permissions.map(mapPermissionToDomain) : undefined,
    };
};

export const mapPermissionToDomain = (data: any): Permission => {
    return {
        id: data.id,
        name: data.name,
        description: data.description,
        category: data.category,
        isActive: data.is_active,
        createdAt: data.created_at,
        updatedAt: data.updated_at,
    };
};
