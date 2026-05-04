import { apiRequest } from '@/api/client';
import type {
  ApiResponse,
  CreditPackage,
  CreateOrderRequest,
  OrderResponse,
  CapturePaymentRequest,
  CapturePaymentResponse,
  InvoicesListResponse,
  InvoiceDetail,
  PaymentMethodsResponse,
  ManualPaymentRequest,
  ManualPaymentResponse,
  TransactionsListResponse,
  CreditHistoryResponse
} from '@/types/api';

class UserBillingApi {
  /**
   * Get available credit packages
   */
  async getPackages(): Promise<ApiResponse<CreditPackage[]>> {
    try {
      const data = await apiRequest<CreditPackage[]>({
        method: 'GET',
        url: '/user/account/billing/packages'
      });

      return {
        success: true,
        message: 'Packages fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch packages'
      };
    }
  }

  /**
   * Get enabled payment methods for checkout
   */
  async getPaymentMethods(): Promise<ApiResponse<PaymentMethodsResponse>> {
    try {
      const data = await apiRequest<PaymentMethodsResponse>({
        method: 'GET',
        url: '/user/account/billing/payment-methods'
      });

      return {
        success: true,
        message: 'Payment methods fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch payment methods'
      };
    }
  }

  /**
   * Create a payment order
   */
  async createOrder(request: CreateOrderRequest): Promise<ApiResponse<OrderResponse>> {
    try {
      const data = await apiRequest<OrderResponse>({
        method: 'POST',
        url: '/user/account/billing/orders',
        data: request
      });

      return {
        success: true,
        message: 'Order created successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to create order'
      };
    }
  }

  /**
   * Resume an existing pending order (PayPal/Stripe)
   */
  async resumeOrder(orderId: string): Promise<ApiResponse<OrderResponse>> {
    try {
      const data = await apiRequest<OrderResponse>({
        method: 'POST',
        url: `/user/account/billing/orders/${orderId}/resume`,
      });

      return {
        success: true,
        message: 'Order resumed successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to resume order'
      };
    }
  }

  /**
   * Capture a payment after user approval
   */
  async capturePayment(request: CapturePaymentRequest): Promise<ApiResponse<CapturePaymentResponse>> {
    try {
      const data = await apiRequest<CapturePaymentResponse>({
        method: 'POST',
        url: '/user/account/billing/capture',
        data: request
      });

      return {
        success: true,
        message: 'Payment captured successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to capture payment'
      };
    }
  }

  /**
   * Get user's invoices with pagination
   */
  async getInvoices(page: number = 1, pageSize: number = 20): Promise<ApiResponse<InvoicesListResponse>> {
    try {
      const data = await apiRequest<InvoicesListResponse>({
        method: 'GET',
        url: '/user/account/billing/invoices',
        params: { page, page_size: pageSize }
      });

      return {
        success: true,
        message: 'Invoices fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch invoices'
      };
    }
  }

  /**
   * Get detailed invoice information (Enterprise JSON)
   */
  async getInvoiceDetail(invoiceId: string): Promise<ApiResponse<InvoiceDetail>> {
    try {
      const data = await apiRequest<InvoiceDetail>({
        method: 'GET',
        url: `/user/account/billing/invoices/${invoiceId}`
      });

      return {
        success: true,
        message: 'Invoice details fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch invoice details'
      };
    }
  }

  /**
   * Get invoice HTML for printing/PDF
   */
  async getInvoiceHtml(invoiceId: string): Promise<ApiResponse<string>> {
    try {
      const data = await apiRequest<string>({
        method: 'GET',
        url: `/user/account/billing/invoices/${invoiceId}/html`,
        headers: {
          'Accept': 'text/html'
        }
      });

      return {
        success: true,
        message: 'Invoice HTML fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch invoice HTML'
      };
    }
  }

  /**
   * Create a manual payment (for Bitcoin/Bank Transfer)
   */
  async createManualPayment(request: ManualPaymentRequest): Promise<ApiResponse<ManualPaymentResponse>> {
    try {
      const data = await apiRequest<ManualPaymentResponse>({
        method: 'POST',
        url: '/user/account/billing/manual-payment',
        data: request
      });

      return {
        success: true,
        message: 'Manual payment created successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to create manual payment'
      };
    }
  }

  /**
   * Get user's orders (transactions) with pagination
   */
  async getOrders(page: number = 1, pageSize: number = 20): Promise<ApiResponse<TransactionsListResponse>> {
    try {
      const data = await apiRequest<TransactionsListResponse>({
        method: 'GET',
        url: '/user/account/billing/orders',
        params: { page, page_size: pageSize }
      });

      return {
        success: true,
        message: 'Orders fetched successfully',
        data
      };
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to fetch orders'
      };
    }
  }

  /**
   * Get user's credit ledger history (all debits and credits)
   */
  async getCreditHistory(page: number = 1, pageSize: number = 20): Promise<ApiResponse<CreditHistoryResponse>> {
    try {
      // Backend wraps in { success, data: CreditHistoryResponse }
      const raw = await apiRequest<{ success: boolean; data: CreditHistoryResponse }>({
        method: 'GET',
        url: '/user/account/billing/history',
        params: { page, page_size: pageSize }
      });
      return { success: true, message: 'Credit history fetched', data: raw.data };
    } catch (error: any) {
      return { success: false, message: error.response?.data?.detail || 'Failed to fetch credit history' };
    }
  }
}

export const userBillingApi = new UserBillingApi();
