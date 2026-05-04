// API Response Types based on OpenAPI specification

export interface ApiResponse<T = any> {
  success: boolean;
  message: string;
  data?: T;
}

// Authentication Types
export interface LoginRequest {
  email: string;
  password: string;
  remember_me?: boolean;
  captcha_token?: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  captcha_token?: string;
  captcha?: string; // Some endpoints might use 'captcha'
}

export interface PasswordResetRequest {
  email: string;
  captcha_token?: string;
}

export interface LoginResponse {
  user: {
    id: number;
    username: string;
    email: string;
    full_name?: string;
    role?: string;
    is_verified?: boolean;
  };
  tokens: {
    access_token: string;
    refresh_token: string;
    token_type: string;
    expires_in: number;
  };
  session?: {
    id: number;
    expires_at: string;
  };
}

export interface ImpersonationResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: number;
    username: string;
    email: string;
    first_name?: string;
    last_name?: string;
    role: string;
    role_id?: number;
    is_active: boolean;
    is_verified: boolean;
    api_rate_limit: number;
    failed_login_attempts: number;
    locked_until?: string | null;
    last_login?: string | null;
    created_at: string;
    updated_at: string;
  };
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface RefreshTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
  captcha_token?: string;
}

export interface PublicCountry {
  id: number;
  code: string;
  name: string;
  is_enabled: boolean;
  flag_emoji: string;
}

export interface PublicCountryListResponse {
  countries: PublicCountry[];
  total_count: number;
}

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

// Validation Types
export interface HTTPValidationError {
  detail: ValidationError[];
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

// Admin API Types - Users Management
export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string;
  role_id?: number;
  is_active: boolean;
  is_verified: boolean;
  api_rate_limit: number;
  failed_login_attempts: number;
  locked_until: string | null;
  last_login: string | null;
  created_at: string;
  updated_at: string;
}

export interface UsersListResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  users: User[];
}

export interface CreateUserRequest {
  username?: string;
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  role_id: number;
  is_active?: boolean;
  is_verified?: boolean;
  api_rate_limit?: number;
}

export interface UpdateUserRequest {
  username?: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  role_id?: number;
  is_active?: boolean;
  is_verified?: boolean;
  api_rate_limit?: number;
}

// Admin API Types - RBAC (Role-Based Access Control)

// Role Types (Dynamic Roles)
export interface Role {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  permissions?: Permission[];
}

export interface RolesListResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  roles: Role[];
}

export interface CreateRoleRequest {
  name: string;
  description?: string | null;
}

export interface UpdateRoleRequest {
  name?: string;
  description?: string | null;
  is_active?: boolean;
}

// Permission Types
export interface Permission {
  id: number;
  name: string;
  description: string | null;
  category: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PermissionsListResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  permissions: Permission[];
}

export interface CreatePermissionRequest {
  name: string;
  description?: string | null;
  category?: string | null;
}

export interface UpdatePermissionRequest {
  description?: string | null;
  category?: string | null;
  is_active?: boolean;
}

export interface RolePermissionsResponse {
  role: string;
  permissions: Permission[];
}

export interface UserPermissionsResponse {
  user_id: number;
  permissions: Permission[];
}

export interface AssignPermissionRequest {
  permission_id: number;
}

export interface AssignPermissionResponse {
  message: string;
}

// User Account Types (for authenticated users - /user/account endpoints)
export interface UserAccountResponse {
  username: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  full_name: string;
  is_active: boolean;
  is_verified: boolean;
  last_login: string | null;
  credits: number;
  has_password: boolean;
}

export interface UserAccountEditRequest {
  username?: string | null;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
}

export interface MessageResponse {
  message: string;
  success?: boolean;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

// Recipient Management Types
export type RecipientType = 'email' | 'slack' | 'webhook';

export interface Recipient {
  id: number;
  type: RecipientType;
  value: string;
  is_verified: boolean;
  is_enabled: boolean;
  name?: string;
  subject_tag?: string;
}

export interface RecipientCreateRequest {
  type: RecipientType;
  value: string;
  name?: string;
}

export interface RecipientUpdateRequest {
  type?: RecipientType;
  value?: string;
  name?: string;
  is_enabled?: boolean;
  subject_tag?: string;
}

export interface RecipientVerifyRequest {
  token: string;
  captcha_token?: string;
}

export interface RecipientListResponse {
  recipients: Recipient[];
  pagination: {
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  };
}

// --- Ticket & LiveChat System Specifications ---

export type TicketStatus = 'OPEN' | 'IN_PROGRESS' | 'PENDING_CUSTOMER' | 'RESOLVED' | 'CLOSED';
export type TicketPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT';
export type TicketOrigin = 'WEB' | 'EMAIL' | 'LIVECHAT' | 'API' | 'CONTACT_FORM';

export interface TicketCategory {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
}

export interface TicketAttachment {
  id: string;
  file_name: string;
  file_url: string;
  content_type: string;
  file_size: number;
  created_at: string;
}

export interface TicketMessage {
  id: string;
  message: string;
  created_at: string;
  is_agent: boolean;
  is_internal_note?: boolean;
  attachments?: TicketAttachment[];
}

export type TicketAttachmentResponse = TicketAttachment;
export type LiveChatAttachmentResponse = TicketAttachment;

export interface CustomerInfo {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_verified: boolean;
  is_active: boolean;
  plan?: string;
  created_at: string;
}

export interface Ticket {
  id: string;
  subject: string;
  status: TicketStatus;
  priority: TicketPriority;
  category_id: string;
  category_name?: string;
  reply_count?: number;
  last_message_at?: string;
  has_agent_reply?: boolean;
  reopen_count?: number;
  origin?: TicketOrigin;
  user_id?: string;
  assigned_agent_id?: number | string | null;
  customer?: CustomerInfo;
  created_at: string;
  updated_at: string;
}

export interface CreateTicketRequest {
  subject: string;
  message: string;
  category_id: string;
  priority: TicketPriority;
}

export interface ReplyTicketRequest {
  message: string;
}

export interface AdminReplyTicketRequest {
  message: string;
  is_internal_note?: boolean;
}

export interface AdminCategoryCreateRequest {
  name: string;
  description: string;
  is_active: boolean;
}

export interface AdminCategoryUpdateRequest {
  name?: string;
  description?: string;
  is_active?: boolean;
}

export interface LiveChatSessionResponse {
  id: string;
  session_token: string;
  status: string;
  created_at: string;
}

export interface LiveChatSessionRequest {
  name?: string;
  email?: string;
  initial_message?: string | null;
  source_url?: string | null;
  client_metadata?: Record<string, unknown> | null;
  is_proactive?: boolean;
}

export interface LiveChatMessageRequest {
  message: string;
  context?: { current_url?: string } | null;
}

export interface LiveChatActivityRequest {
  current_url?: string | null;
  is_typing?: boolean;
}

export type ChatSenderType = 'USER' | 'AGENT' | 'SYSTEM';

export interface ChatMessageResponse {
  id: string;
  sender_type: ChatSenderType;
  message: string;
  created_at: string;
  sender_id: number | null;
  attachments?: LiveChatAttachmentResponse[];
}

export interface SessionResponse {
  id: string;
  session_token: string | null;
  status: string;
  created_at: string;
}

export interface SessionMetadataResponse {
  id: string;
  status: 'WAITING' | 'ACTIVE' | 'ENDED';
  created_at: string;
  ended_at: string | null;
  agent_id: number | null;
  ticket_id: string | null;
  is_authenticated_user: boolean;
  user_id: number | null;
  initial_context?: Record<string, unknown> | null;
  is_proactive?: boolean;
  ip_address?: string | null;
  user_agent?: string | null;
  current_url?: string | null;
  agent_typing?: boolean;
}

export interface LiveChatStatsResponse {
  waiting: number;
  active: number;
  ended: number;
  total: number;
}

/** Alias matching the OpenAPI `CustomerProfile` schema */
export type CustomerProfile = CustomerInfo;

/** Admin-only ticket message — includes internal notes and is_agent flag */
export interface AdminTicketMessageResponse {
  id: string;
  message: string;
  created_at: string;
  sender_id: number | null;
  is_agent: boolean;
  is_internal_note: boolean;
  attachments: TicketAttachmentResponse[];
}

export interface StaffUser {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
}

export interface ContactFormRequest {
  name: string;
  email: string;
  subject: string;
  message: string;
  category_id?: string | null;
  captcha_token?: string | null;
  _hp?: string;
}

export interface ContactFormResponse {
  ticket_id: string;
  message: string;
}

// --- Billing & Credits System Types ---

export type PaymentProvider = 'PAYPAL' | 'STRIPE' | 'BITCOIN' | 'BANK_TRANSFER';

export interface CreditPackage {
  id: number;
  name: string;
  description: string;
  amount: number;
  currency: string;
  credits: number;
  is_active?: boolean;
}

export interface CreateOrderRequest {
  package_id?: number;
  amount: number;
  currency: string;
  provider: PaymentProvider;
}

export interface OrderResponse {
  transaction_id: string;
  provider_data: any; // PayPal order ID or Stripe client secret
  package_id?: number | string;
  package_name?: string;
  description?: string;
  amount?: number;
  currency?: string;
  credits?: number;
  paypal_client_id?: string;
  stripe_publishable_key?: string;
  mode: 'sandbox' | 'live';
}

export interface CapturePaymentRequest {
  order_id: string;
  provider: PaymentProvider;
}

export interface CapturePaymentResponse {
  transaction_id: string;
  invoice_id: string;
  status: 'COMPLETED' | 'PENDING' | 'FAILED';
  credits_added: number;
  message: string;
}

export interface Invoice {
  id: string;
  invoice_number: string;
  date: string;
  invoice_date: string;
  paid_at?: string | null;
  created_at?: string;
  due_date?: string;
  total_amount: number;
  subtotal_amount?: number;
  tax_amount?: number;
  currency: string;
  billing_email: string;
  billing_name: string;
  description: string;
  status: string;
  provider: string;
  provider_transaction_id?: string;
  notes?: string;
}

export interface BillingAddress {
  line1: string;
  line2?: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
}

export interface LineItem {
  name: string;
  description: string;
  quantity: number;
  unit_price: number;
  total: number;
}

export interface InvoiceDetail extends Invoice {
  provider: 'STRIPE' | 'PAYPAL' | 'BITCOIN' | 'BANK_TRANSFER';
  provider_transaction_id: string;
  subtotal_amount: number;
  tax_amount: number;
  billing_address: BillingAddress;
  line_items: string; // JSON string of LineItem[]
  tax_rate: number;
  tax_id?: string;
  invoice_date: string;
  due_date: string;
  paid_at?: string;
  notes?: string;
}

export interface InvoicesListResponse {
  items: Invoice[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminPendingPayment {
  id: string;
  user_id: number;
  user_email: string;
  provider: string; // "BITCOIN" | "BANK_TRANSFER"
  amount: number;
  currency: string;
  status: string; // "pending"
  created_at: string;
  package_name?: string;
  invoice_number?: string;
  invoice_status?: string;
}

export interface PendingPaymentsListResponse {
  transactions: AdminPendingPayment[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserTransaction {
  id: string;
  user_id: number;
  provider: PaymentProvider;
  amount: number;
  currency: string;
  status: string;
  package_id?: number | null;
  package_name?: string | null;
  description?: string | null;
  credits?: number | null;
  invoice?: {
    id: string;
    invoice_number: string;
    status: string;
    total_amount: number;
    currency: string;
    created_at: string;
  } | null;
  created_at: string;
  updated_at: string;
}

export interface TransactionsListResponse {
  transactions?: UserTransaction[];
  items?: UserTransaction[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreditLedgerEntry {
  id: string;
  amount: number;
  source: 'registration' | 'purchase' | 'admin_grant';
  created_at: string;
  expires_at: string;
  transaction_id: string | null;
  note: string | null;
}

export interface CreditHistoryResponse {
  items: CreditLedgerEntry[];
  pagination: {
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  };
}

// Admin Billing Types
export interface CreatePackageRequest {
  name: string;
  description: string;
  amount: number;
  currency: string;
  credits: number;
  is_active?: boolean;
}

export interface UpdatePackageRequest {
  name?: string;
  description?: string;
  amount?: number;
  currency?: string;
  credits?: number;
  is_active?: boolean;
}

export interface PackageListResponse {
  packages: CreditPackage[];
  total: number;
  page: number;
  page_size: number;
}

// Payment Gateway Types (Backend API Specification)

// User-facing payment methods (GET /user/account/billing/payment-methods)
export interface PaymentMethod {
  provider: PaymentProvider;
  name: string;
  is_enabled: boolean;
  mode: 'sandbox' | 'live';
  // PayPal specific
  client_id?: string;
  // Stripe specific
  publishable_key?: string;
  // OTHER (manual) specific
  type?: 'manual';
  description?: string;
  instructions?: string;
  wallet_address?: string;
  bank_details?: string;
  contact_info?: string;
  qr_code_url?: string;
}

export interface PaymentMethodsResponse {
  payment_methods: PaymentMethod[];
  mode: 'sandbox' | 'live';
}

// Admin payment gateway management (GET /admin/payment-gateways)
export interface AdminPaymentGateway {
  id: number;
  provider: PaymentProvider;
  is_enabled: boolean;
  display_name: string;
  api_key: string | null;
  api_secret: string | null;
  webhook_secret: string | null;
  mode: 'sandbox' | 'live';
  config_json: string | null;
  created_at: string;
  updated_at: string;
}

// Request body for PUT /admin/payment-gateways/{provider}
export interface UpdatePaymentGatewayRequest {
  is_enabled?: boolean;
  display_name?: string;
  api_key?: string;
  api_secret?: string;
  webhook_secret?: string;
  mode?: 'sandbox' | 'live';
  config_json?: string | null;
}

// Response for PATCH /admin/payment-gateways/{provider}/enable|disable
export interface PaymentGatewayToggleResponse {
  provider: PaymentProvider;
  is_enabled: boolean;
  display_name: string;
  mode: 'sandbox' | 'live';
  message: string;
}

// Manual Payment Types (for Bitcoin/Bank Transfer)
export interface ManualPaymentRequest {
  package_id: number;
  amount: number;
  provider: PaymentProvider;
  currency: string;
}

export interface ManualPaymentResponse {
  transaction_id: string;
  status: 'PENDING' | 'COMPLETED' | 'FAILED';
  payment_details: {
    wallet_address?: string;
    bank_details?: string;
    instructions?: string;
    contact_info?: string;
    qr_code_url?: string;
  };
  instructions: string;
  message: string;
}

// ── Generic App Config (AW-106) ──────────────────────────────────────────────

export interface AppConfigEntry {
  id: number;
  namespace: string;
  key: string;
  value: string;
  value_type: 'int' | 'string' | 'boolean';
  scope: 'global' | 'worker';
  scope_id: string | null;
  updated_by: string | null;
  updated_at: string | null;
  created_at: string | null;
}

export interface AppConfigUpsertRequest {
  value: string;
  value_type: string;
  scope: string;
  scope_id?: string;
}

