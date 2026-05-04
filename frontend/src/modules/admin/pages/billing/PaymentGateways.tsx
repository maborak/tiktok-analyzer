import React, { useState, useEffect } from 'react';
import { adminBillingApi } from '../../services/billing';
import type { AdminPaymentGateway, UpdatePaymentGatewayRequest, PaymentProvider } from '@/types/api';
import { appConfig } from '@/config/env';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Input } from '@/components/ui/Input';
import { Switch } from '@/components/ui/Switch';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Loader2, RefreshCw, CreditCard, Check, X, AlertCircle, Lock, Unlock, Settings } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';

export function PaymentGateways() {
  const [gateways, setGateways] = useState<AdminPaymentGateway[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedGateway, setSelectedGateway] = useState<AdminPaymentGateway | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Form state
  const [formData, setFormData] = useState<UpdatePaymentGatewayRequest>({
    display_name: '',
    is_enabled: false,
    api_key: '',
    api_secret: '',
    webhook_secret: '',
    mode: 'sandbox',
    config_json: null
  });

  // Config JSON field states for manual payment methods
  const [configFields, setConfigFields] = useState({
    description: '',
    instructions: '',
    contact_info: '',
    qr_code_url: '',
    bank_details: ''
  });

  useEffect(() => {
    fetchGateways();
  }, []);

  const fetchGateways = async () => {
    setIsLoading(true);
    try {
      const response = await adminBillingApi.getPaymentGateways();
      if (response.success && response.data) {
        setGateways(response.data);
      } else {
        toast.error(response.message || 'Failed to load payment gateways');
      }
    } catch (error) {
      console.error('Error fetching payment gateways:', error);
      toast.error('Failed to load payment gateways');
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleEnabled = async (gateway: AdminPaymentGateway) => {
    setIsSubmitting(true);
    try {
      const response = gateway.is_enabled
        ? await adminBillingApi.disablePaymentGateway(gateway.provider)
        : await adminBillingApi.enablePaymentGateway(gateway.provider);
      
      if (response.success) {
        toast.success(response.data?.message || `${gateway.display_name} ${!gateway.is_enabled ? 'enabled' : 'disabled'} successfully`);
        fetchGateways();
      } else {
        toast.error(response.message || 'Failed to update payment gateway');
      }
    } catch (error) {
      console.error('Error updating payment gateway:', error);
      toast.error('Failed to update payment gateway');
    } finally {
      setIsSubmitting(false);
    }
  };

  const buildConfigJson = (): string | null => {
    const config: Record<string, string> = {};
    
    if (configFields.description) config.description = configFields.description;
    if (configFields.instructions) config.instructions = configFields.instructions;
    if (configFields.contact_info) config.contact_info = configFields.contact_info;
    if (configFields.qr_code_url) config.qr_code_url = configFields.qr_code_url;
    if (configFields.bank_details) config.bank_details = configFields.bank_details;
    
    return Object.keys(config).length > 0 ? JSON.stringify(config) : null;
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!selectedGateway) return;

    // Build config_json from individual fields for manual payment methods
    const updatedFormData = { ...formData };
    if (selectedGateway.provider === 'BITCOIN' || selectedGateway.provider === 'BANK_TRANSFER') {
      updatedFormData.config_json = buildConfigJson();
    }

    setIsSubmitting(true);
    try {
      const response = await adminBillingApi.updatePaymentGateway(selectedGateway.provider, updatedFormData);
      if (response.success) {
        toast.success('Payment gateway updated successfully');
        setIsEditModalOpen(false);
        setSelectedGateway(null);
        resetForm();
        fetchGateways();
      } else {
        toast.error(response.message || 'Failed to update payment gateway');
      }
    } catch (error) {
      console.error('Error updating payment gateway:', error);
      toast.error('Failed to update payment gateway');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openEditModal = (gateway: AdminPaymentGateway) => {
    setSelectedGateway(gateway);
    setFormData({
      display_name: gateway.display_name,
      is_enabled: gateway.is_enabled,
      api_key: gateway.api_key || '',
      api_secret: gateway.api_secret || '',
      webhook_secret: gateway.webhook_secret || '',
      mode: gateway.mode,
      config_json: gateway.config_json
    });

    // Parse config_json into individual fields
    const config = parseConfigJson(gateway.config_json);
    setConfigFields({
      description: config.description || '',
      instructions: config.instructions || '',
      contact_info: config.contact_info || '',
      qr_code_url: config.qr_code_url || '',
      bank_details: config.bank_details || ''
    });

    setIsEditModalOpen(true);
  };

  const resetForm = () => {
    setFormData({
      display_name: '',
      is_enabled: false,
      api_key: '',
      api_secret: '',
      webhook_secret: '',
      mode: 'sandbox',
      config_json: null
    });
    setConfigFields({
      description: '',
      instructions: '',
      contact_info: '',
      qr_code_url: '',
      bank_details: ''
    });
  };

  const handleInputChange = (field: keyof UpdatePaymentGatewayRequest, value: any) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const getProviderIcon = (provider: PaymentProvider) => {
    switch (provider) {
      case 'PAYPAL':
        return (
          <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
            <path d="M7.076 21.337H2.47a.641.641 0 0 1-.633-.74L4.944.901C5.026.382 5.474 0 5.998 0h7.46c2.57 0 4.578.543 5.69 1.81 1.01 1.15 1.304 2.42 1.012 4.287-.023.143-.047.288-.077.437-.983 5.05-4.349 6.797-8.647 6.797h-2.19c-.524 0-.968.382-1.05.9l-1.12 7.106zm14.146-14.42a3.35 3.35 0 0 0-.607-.541c-.013.076-.026.175-.041.254-.59 3.025-2.566 6.082-8.558 6.082h-2.19c-.524 0-.968.382-1.05.9l-1.209 7.675h3.85c.464 0 .858-.334.929-.794l.04-.19.73-4.627.047-.255a.933.933 0 0 1 .928-.794h.584c3.77 0 6.726-1.528 7.594-5.62.266-1.277.123-2.37-.577-3.14z"/>
          </svg>
        );
      case 'STRIPE':
        return (
          <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
            <path d="M13.976 9.15c-2.172-.806-3.356-1.426-3.356-2.409 0-.831.683-1.305 1.901-1.305 2.227 0 4.515.858 6.09 1.631l.89-5.494C18.252.975 15.697 0 12.165 0 9.667 0 7.589.654 6.104 1.872 4.56 3.147 3.757 4.992 3.757 7.218c0 4.039 2.467 5.76 6.476 7.219 2.585.92 3.445 1.574 3.445 2.583 0 .98-.84 1.545-2.354 1.545-1.875 0-4.965-.921-6.99-2.109l-.9 5.555C5.175 22.99 8.385 24 11.714 24c2.641 0 4.843-.624 6.328-1.813 1.664-1.305 2.525-3.236 2.525-5.732 0-4.128-2.524-5.851-6.591-7.305z"/>
          </svg>
        );
      case 'BITCOIN':
        return (
          <svg className="w-6 h-6" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v2h-2zm0 3h2v6h-2zm0 3h2v2h-2z"/>
          </svg>
        );
      case 'BANK_TRANSFER':
        return <CreditCard className="w-6 h-6" />;
      default:
        return <CreditCard className="w-6 h-6" />;
    }
  };

  const getProviderColor = (provider: PaymentProvider) => {
    switch (provider) {
      case 'PAYPAL':
        return 'text-[#003087] bg-[#003087]/10 border-[#003087]/20';
      case 'STRIPE':
        return 'text-[#635BFF] bg-[#635BFF]/10 border-[#635BFF]/20';
      case 'BITCOIN':
        return 'text-warning-600 bg-warning-100 border-warning-200';
      case 'BANK_TRANSFER':
        return 'text-success-600 bg-success-50 border-success-200';
      default:
        return 'text-gray-600 bg-gray-100 border-gray-200';
    }
  };

  const maskSecret = (value: string | null): string => {
    if (!value) return 'Not set';
    if (value.length <= 8) return '****';
    return `${value.slice(0, 4)}****${value.slice(-4)}`;
  };

  const parseConfigJson = (configJson: string | null): { description?: string; instructions?: string; [key: string]: any } => {
    if (!configJson) return {};
    try {
      return JSON.parse(configJson);
    } catch {
      return {};
    }
  };

  const renderConfigFields = (provider: PaymentProvider) => {
    const commonFields = (
      <>
        <div>
          <label className="label">
            Display Name
          </label>
          <Input
            value={formData.display_name || ''}
            onChange={(e) => handleInputChange('display_name', e.target.value)}
            placeholder="e.g., PayPal"
          />
        </div>
        <div className="flex items-center gap-2">
          <Switch
            checked={formData.is_enabled || false}
            onCheckedChange={(checked: boolean) => handleInputChange('is_enabled', checked)}
          />
          <label className="text-sm text-gray-700">
            Enabled
          </label>
        </div>
        <div>
          <label className="label">
            Mode
          </label>
          <select
            value={formData.mode || 'sandbox'}
            onChange={(e) => handleInputChange('mode', e.target.value as 'sandbox' | 'live')}
            className="input"
          >
            <option value="sandbox">Sandbox</option>
            <option value="live">Live</option>
          </select>
        </div>
      </>
    );

    switch (provider) {
      case 'PAYPAL':
        return (
          <div className="space-y-4">
            {commonFields}
            <div className="pt-4 border-t border-gray-200">
              <h4 className="font-medium text-gray-900 mb-3">PayPal Configuration</h4>
              <div className="space-y-3">
                <div>
                  <label className="label">
                    Client ID (API Key)
                  </label>
                  <Input
                    type="password"
                    value={formData.api_key || ''}
                    onChange={(e) => handleInputChange('api_key', e.target.value)}
                    placeholder="PayPal Client ID"
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_key || null)}</p>
                </div>
                <div>
                  <label className="label">
                    Client Secret (API Secret)
                  </label>
                  <Input
                    type="password"
                    value={formData.api_secret || ''}
                    onChange={(e) => handleInputChange('api_secret', e.target.value)}
                    placeholder="PayPal Client Secret"
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_secret || null)}</p>
                </div>
              </div>
            </div>
          </div>
        );
      case 'STRIPE':
        return (
          <div className="space-y-4">
            {commonFields}
            <div className="pt-4 border-t border-gray-200">
              <h4 className="font-medium text-gray-900 mb-3">Stripe Configuration</h4>
              <div className="space-y-3">
                <div>
                  <label className="label">
                    Publishable Key (API Key)
                  </label>
                  <Input
                    type="password"
                    value={formData.api_key || ''}
                    onChange={(e) => handleInputChange('api_key', e.target.value)}
                    placeholder="pk_live_..."
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_key || null)}</p>
                </div>
                <div>
                  <label className="label">
                    Secret Key (API Secret)
                  </label>
                  <Input
                    type="password"
                    value={formData.api_secret || ''}
                    onChange={(e) => handleInputChange('api_secret', e.target.value)}
                    placeholder="sk_live_..."
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_secret || null)}</p>
                </div>
                <div>
                  <label className="label">
                    Webhook Secret
                  </label>
                  <Input
                    type="password"
                    value={formData.webhook_secret || ''}
                    onChange={(e) => handleInputChange('webhook_secret', e.target.value)}
                    placeholder="whsec_..."
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.webhook_secret || null)}</p>
                </div>
              </div>
            </div>
          </div>
        );
      case 'BITCOIN':
        return (
          <div className="space-y-4">
            {commonFields}
            <div className="pt-4 border-t border-gray-200">
              <h4 className="font-medium text-gray-900 mb-3">Bitcoin Configuration</h4>
              <div className="space-y-3">
                <div>
                  <label className="label">
                    Wallet Address
                  </label>
                  <Input
                    value={formData.api_key || ''}
                    onChange={(e) => handleInputChange('api_key', e.target.value)}
                    placeholder="bc1q..."
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_key || null)}</p>
                </div>
                <div>
                  <label className="label">
                    Description
                  </label>
                  <Input
                    value={configFields.description}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, description: e.target.value }))}
                    placeholder="e.g., Pay with Bitcoin (BTC)"
                  />
                </div>
                <div>
                  <label className="label">
                    Instructions
                  </label>
                  <textarea
                    value={configFields.instructions}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, instructions: e.target.value }))}
                    placeholder="Send BTC to the wallet address and contact support with your transaction ID"
                    className="input"
                    rows={3}
                  />
                </div>
                <div>
                  <label className="label">
                    QR Code URL (Optional)
                  </label>
                  <Input
                    value={configFields.qr_code_url}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, qr_code_url: e.target.value }))}
                    placeholder="https://example.com/qr/btc.png"
                  />
                </div>
                <div>
                  <label className="label">
                    Contact Info
                  </label>
                  <Input
                    value={configFields.contact_info}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, contact_info: e.target.value }))}
                    placeholder="support@example.com"
                  />
                </div>
              </div>
            </div>
          </div>
        );
      case 'BANK_TRANSFER':
        return (
          <div className="space-y-4">
            {commonFields}
            <div className="pt-4 border-t border-gray-200">
              <h4 className="font-medium text-gray-900 mb-3">Bank Transfer Configuration</h4>
              <div className="space-y-3">
                <div>
                  <label className="label">
                    Description
                  </label>
                  <Input
                    value={configFields.description}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, description: e.target.value }))}
                    placeholder="e.g., Bank Transfer"
                  />
                </div>
                <div>
                  <label className="label">
                    Instructions
                  </label>
                  <textarea
                    value={configFields.instructions}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, instructions: e.target.value }))}
                    placeholder="Transfer the amount to our bank account and upload the receipt"
                    className="input"
                    rows={3}
                  />
                </div>
                <div>
                  <label className="label">
                    Bank Details
                  </label>
                  <textarea
                    value={configFields.bank_details}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, bank_details: e.target.value }))}
                    placeholder={`Bank: Chase\nAccount: 1234567890\nRouting: 021000021\nAccount Name: ${appConfig.legalEntity}`}
                    className="input"
                    rows={4}
                  />
                </div>
                <div>
                  <label className="label">
                    Contact Info
                  </label>
                  <Input
                    value={configFields.contact_info}
                    onChange={(e) => setConfigFields(prev => ({ ...prev, contact_info: e.target.value }))}
                    placeholder="billing@example.com"
                  />
                </div>
              </div>
            </div>
          </div>
        );
      default:
        return (
          <div className="space-y-4">
            {commonFields}
            <div className="pt-4 border-t border-gray-200">
              <h4 className="font-medium text-gray-900 mb-3">Payment Gateway Configuration</h4>
              <div className="space-y-3">
                <div>
                  <label className="label">
                    API Key
                  </label>
                  <Input
                    type="password"
                    value={formData.api_key || ''}
                    onChange={(e) => handleInputChange('api_key', e.target.value)}
                    placeholder="API Key"
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_key || null)}</p>
                </div>
                <div>
                  <label className="label">
                    API Secret
                  </label>
                  <Input
                    type="password"
                    value={formData.api_secret || ''}
                    onChange={(e) => handleInputChange('api_secret', e.target.value)}
                    placeholder="API Secret"
                  />
                  <p className="text-xs text-gray-500 mt-1">Current: {maskSecret(selectedGateway?.api_secret || null)}</p>
                </div>
                <div>
                  <label className="label">
                    Config JSON (Optional)
                  </label>
                  <textarea
                    value={formData.config_json || ''}
                    onChange={(e) => handleInputChange('config_json', e.target.value || null)}
                    placeholder='{"endpoint": "https://api.example.com/v1"}'
                    className="input"
                    rows={3}
                  />
                </div>
              </div>
            </div>
          </div>
        );
    }
  };

  return (
    <PageShell>
      <PageHeader
        title="Payment Gateways"
        description="Manage and configure payment gateways for credit purchases."
        icon={<CreditCard className="h-5 w-5" />}
        actions={
          <div className="flex gap-2">
            <Button onClick={fetchGateways} variant="secondary" className="px-3" title="Refresh">
              <RefreshCw className={clsx("w-4 h-4", isLoading && "animate-spin")} />
            </Button>
          </div>
        }
      />

      {/* Gateways Grid */}
      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-gray-500 flex flex-col items-center">
            <Loader2 className="w-8 h-8 animate-spin text-gray-400 mb-4" />
            <p>Loading payment gateways...</p>
          </div>
        ) : gateways.length === 0 ? (
          <div className="p-12 text-center flex flex-col items-center">
            <CreditCard className="w-12 h-12 text-gray-300 mb-4" />
            <h3 className="text-lg font-medium text-gray-900">No payment gateways found</h3>
            <p className="text-gray-500 mt-2">Payment gateways must be configured in the database.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 p-6">
            {gateways.map((gateway) => (
              <div
                key={gateway.provider}
                className={clsx(
                  'relative rounded-lg border-2 p-5 transition-all duration-200',
                  gateway.is_enabled
                    ? 'border-success-200 bg-success-50/30 hover:border-success-300 hover:shadow-md'
                    : 'border-gray-200 bg-gray-50 opacity-75'
                )}
              >
                {/* Status Badge */}
                <div className="absolute top-3 right-3">
                  {gateway.is_enabled ? (
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-success-50 text-success-700">
                      <Unlock className="w-3 h-3 mr-1" />
                      Enabled
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                      <Lock className="w-3 h-3 mr-1" />
                      Disabled
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3 mb-4">
                  <div className={clsx(
                    'p-2 rounded-lg',
                    getProviderColor(gateway.provider)
                  )}>
                    {getProviderIcon(gateway.provider)}
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">{gateway.display_name}</h3>
                    <p className="auth-mono-label">{gateway.provider}</p>
                  </div>
                </div>

                <div className="space-y-2 mb-4 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Mode:</span>
                    <span className={clsx(
                      'font-medium',
                      gateway.mode === 'live' ? 'text-success-600' : 'text-warning-600'
                    )}>
                      {gateway.mode === 'live' ? 'Live' : 'Sandbox'}
                    </span>
                  </div>
                  {(gateway.provider === 'BITCOIN' || gateway.provider === 'BANK_TRANSFER') && (
                    <>
                      {parseConfigJson(gateway.config_json).description && (
                        <div className="flex justify-between">
                          <span className="text-gray-600">Description:</span>
                          <span className="font-medium text-gray-900 truncate max-w-[150px]">
                            {parseConfigJson(gateway.config_json).description}
                          </span>
                        </div>
                      )}
                      {parseConfigJson(gateway.config_json).instructions && (
                        <div className="pt-2">
                          <span className="text-gray-600 block mb-1">Instructions:</span>
                          <p className="text-xs text-gray-700 bg-gray-100 p-2 rounded max-h-20 overflow-y-auto">
                            {parseConfigJson(gateway.config_json).instructions}
                          </p>
                        </div>
                      )}
                    </>
                  )}
                  {gateway.provider !== 'BITCOIN' && gateway.provider !== 'BANK_TRANSFER' && (
                    <div className="flex justify-between">
                      <span className="text-gray-600">API Key:</span>
                      <span className="font-medium text-gray-900">{maskSecret(gateway.api_key)}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-600">Last Updated:</span>
                    <span className="font-medium text-gray-900">
                      {new Date(gateway.updated_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                <div className="flex gap-2 pt-4 border-t border-gray-200">
                  <Button
                    variant="secondary"
                    onClick={() => openEditModal(gateway)}
                    className="flex-1 h-9 text-xs"
                  >
                    <Settings className="w-3.5 h-3.5 mr-1.5" />
                    Configure
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => handleToggleEnabled(gateway)}
                    disabled={isSubmitting}
                    className={clsx(
                      'h-9 px-3 text-xs',
                      gateway.is_enabled
                        ? 'bg-error-50 text-error-600 border-error-200 hover:bg-error-50'
                        : 'bg-success-50 text-success-600 border-success-200 hover:bg-success-50'
                    )}
                  >
                    {gateway.is_enabled ? (
                      <X className="w-3.5 h-3.5" />
                    ) : (
                      <Check className="w-3.5 h-3.5" />
                    )}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-primary-50 border border-primary-200 rounded-lg p-4 flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-primary-600 mt-0.5 flex-shrink-0" />
        <div className="text-sm text-primary-700">
          <p className="font-medium mb-1">Payment Gateway Management</p>
          <p className="text-primary-700">
            Enable or disable payment gateways to control which options are available to users during checkout. 
            Configure API keys and credentials for each gateway. Changes take effect immediately.
          </p>
        </div>
      </div>

      {/* Edit Modal */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => !isSubmitting && setIsEditModalOpen(false)}
        title={`Configure ${selectedGateway?.display_name}`}
      >
        <form onSubmit={handleUpdate} className="space-y-4">
          {selectedGateway && renderConfigFields(selectedGateway.provider)}

          <div className="pt-4 flex justify-end gap-3 border-t border-gray-200">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsEditModalOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Saving...
                </>
              ) : (
                'Save Changes'
              )}
            </Button>
          </div>
        </form>
      </Modal>
    </PageShell>
  );
}
