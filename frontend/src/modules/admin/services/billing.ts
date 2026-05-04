import { apiRequest } from '@/api/client';
import type { ApiResponse } from '@/types/api';
import type {
  CreditPackage,
  CreatePackageRequest,
  UpdatePackageRequest,
  PackageListResponse,
  AdminPaymentGateway,
  UpdatePaymentGatewayRequest,
  PaymentGatewayToggleResponse
} from '@/types/api';

class AdminBillingRepository {
  /**
   * Get all credit packages (active and inactive)
   */
  async getPackages(): Promise<ApiResponse<PackageListResponse>> {
    try {
      const data = await apiRequest<PackageListResponse>({
        method: 'GET',
        url: '/admin/billing/packages'
      });

      // API already returns PackageListResponse format
      return {
        success: true,
        message: 'Packages fetched successfully',
        data: data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch packages'
      };
    }
  }

  /**
   * Create a new credit package
   */
  async createPackage(request: CreatePackageRequest): Promise<ApiResponse<CreditPackage>> {
    try {
      const data = await apiRequest<CreditPackage>({
        method: 'POST',
        url: '/admin/billing/packages',
        data: request
      });
      return {
        success: true,
        message: 'Package created successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to create package'
      };
    }
  }

  /**
   * Update an existing credit package
   */
  async updatePackage(id: number, request: UpdatePackageRequest): Promise<ApiResponse<CreditPackage>> {
    try {
      const data = await apiRequest<CreditPackage>({
        method: 'PUT',
        url: `/admin/billing/packages/${id}`,
        data: request
      });
      return {
        success: true,
        message: 'Package updated successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to update package'
      };
    }
  }

  /**
   * Deactivate a credit package (soft delete)
   */
  async deactivatePackage(id: number): Promise<ApiResponse<void>> {
    try {
      await apiRequest({
        method: 'DELETE',
        url: `/admin/billing/packages/${id}`
      });
      return {
        success: true,
        message: 'Package deactivated successfully'
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to deactivate package'
      };
    }
  }

  // ==================== PAYMENT GATEWAYS ====================

  /**
   * Get all payment gateway configurations (admin only)
   */
  async getPaymentGateways(): Promise<ApiResponse<AdminPaymentGateway[]>> {
    try {
      const data = await apiRequest<AdminPaymentGateway[]>({
        method: 'GET',
        url: '/admin/payment-gateways'
      });

      return {
        success: true,
        message: 'Payment gateways fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch payment gateways'
      };
    }
  }

  /**
   * Get single payment gateway configuration
   */
  async getPaymentGateway(provider: string): Promise<ApiResponse<AdminPaymentGateway>> {
    try {
      const data = await apiRequest<AdminPaymentGateway>({
        method: 'GET',
        url: `/admin/payment-gateways/${provider}`
      });

      return {
        success: true,
        message: 'Payment gateway fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch payment gateway'
      };
    }
  }

  /**
   * Create a new payment gateway configuration
   */
  async createPaymentGateway(request: UpdatePaymentGatewayRequest & { provider: string }): Promise<ApiResponse<AdminPaymentGateway>> {
    try {
      const data = await apiRequest<AdminPaymentGateway>({
        method: 'POST',
        url: '/admin/payment-gateways',
        data: request
      });

      return {
        success: true,
        message: 'Payment gateway created successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to create payment gateway'
      };
    }
  }

  /**
   * Update a payment gateway configuration
   */
  async updatePaymentGateway(provider: string, request: UpdatePaymentGatewayRequest): Promise<ApiResponse<AdminPaymentGateway>> {
    try {
      const data = await apiRequest<AdminPaymentGateway>({
        method: 'PUT',
        url: `/admin/payment-gateways/${provider}`,
        data: request
      });

      return {
        success: true,
        message: 'Payment gateway updated successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to update payment gateway'
      };
    }
  }

  /**
   * Enable a payment gateway
   */
  async enablePaymentGateway(provider: string): Promise<ApiResponse<PaymentGatewayToggleResponse>> {
    try {
      const data = await apiRequest<PaymentGatewayToggleResponse>({
        method: 'PATCH',
        url: `/admin/payment-gateways/${provider}/enable`
      });

      return {
        success: true,
        message: data.message || 'Payment gateway enabled successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to enable payment gateway'
      };
    }
  }

  /**
   * Disable a payment gateway
   */
  async disablePaymentGateway(provider: string): Promise<ApiResponse<PaymentGatewayToggleResponse>> {
    try {
      const data = await apiRequest<PaymentGatewayToggleResponse>({
        method: 'PATCH',
        url: `/admin/payment-gateways/${provider}/disable`
      });

      return {
        success: true,
        message: data.message || 'Payment gateway disabled successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to disable payment gateway'
      };
    }
  }
  /**
   * Get all pending manual payments requiring verification
   */
  async getPendingPayments(params: { page: number; page_size: number }): Promise<ApiResponse<import('@/types/api').PendingPaymentsListResponse>> {
    try {
      const data = await apiRequest<import('@/types/api').PendingPaymentsListResponse>({
        method: 'GET',
        url: '/admin/billing/pending-payments',
        params
      });
      return {
        success: true,
        message: 'Pending payments fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch pending payments'
      };
    }
  }

  /**
   * Verify (approve/reject) a manual payment
   */
  async verifyPendingPayment(transactionId: string, payload: { action: 'approve' | 'reject'; notes?: string }): Promise<ApiResponse<any>> {
    try {
      const data = await apiRequest<any>({
        method: 'POST',
        url: `/admin/billing/pending-payments/${transactionId}/verify`,
        data: payload
      });
      return {
        success: true,
        message: data.message || 'Payment verified successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to verify payment'
      };
    }
  }
}

export const adminBillingApi = new AdminBillingRepository();
