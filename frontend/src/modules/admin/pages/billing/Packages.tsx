import React, { useState, useEffect } from 'react';
import { adminBillingApi } from '../../services/billing';
import type { CreditPackage, CreatePackageRequest, UpdatePackageRequest } from '@/types/api';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { Loader2, Plus, Edit2, Trash2, RefreshCw, Package, Check, X, AlertCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';

export function Packages() {
  const [packages, setPackages] = useState<CreditPackage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedPackage, setSelectedPackage] = useState<CreditPackage | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Form state
  const [formData, setFormData] = useState<CreatePackageRequest>({
    name: '',
    description: '',
    amount: 0,
    currency: 'USD',
    credits: 0,
    is_active: true
  });

  useEffect(() => {
    fetchPackages();
  }, []);

  const fetchPackages = async () => {
    setIsLoading(true);
    try {
      const response = await adminBillingApi.getPackages();
      if (response.success && response.data) {
        // API returns PackageListResponse with packages array
        const packagesData = response.data.packages || [];
        setPackages(packagesData);
      } else {
        toast.error(response.message || 'Failed to load packages');
        setPackages([]);
      }
    } catch (error) {
      console.error('Error fetching packages:', error);
      toast.error('Failed to load packages');
      setPackages([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!formData.name.trim() || formData.amount <= 0 || formData.credits <= 0) {
      toast.error('Please fill in all required fields with valid values');
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await adminBillingApi.createPackage(formData);
      if (response.success) {
        toast.success('Package created successfully');
        setIsCreateModalOpen(false);
        resetForm();
        fetchPackages();
      } else {
        toast.error(response.message || 'Failed to create package');
      }
    } catch (error) {
      console.error('Error creating package:', error);
      toast.error('Failed to create package');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!selectedPackage) return;

    setIsSubmitting(true);
    try {
      const updateData: UpdatePackageRequest = {};
      if (formData.name !== selectedPackage.name) updateData.name = formData.name;
      if (formData.description !== selectedPackage.description) updateData.description = formData.description;
      if (formData.amount !== selectedPackage.amount) updateData.amount = formData.amount;
      if (formData.currency !== selectedPackage.currency) updateData.currency = formData.currency;
      if (formData.credits !== selectedPackage.credits) updateData.credits = formData.credits;
      if (formData.is_active !== selectedPackage.is_active) updateData.is_active = formData.is_active;

      // Only call API if there are changes
      if (Object.keys(updateData).length === 0) {
        toast('No changes to save');
        setIsEditModalOpen(false);
        return;
      }

      const response = await adminBillingApi.updatePackage(selectedPackage.id, updateData);
      if (response.success) {
        toast.success('Package updated successfully');
        setIsEditModalOpen(false);
        setSelectedPackage(null);
        resetForm();
        fetchPackages();
      } else {
        toast.error(response.message || 'Failed to update package');
      }
    } catch (error) {
      console.error('Error updating package:', error);
      toast.error('Failed to update package');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeactivate = async () => {
    if (!selectedPackage) return;

    setIsSubmitting(true);
    try {
      const response = await adminBillingApi.deactivatePackage(selectedPackage.id);
      if (response.success) {
        toast.success('Package deactivated successfully');
        setIsDeleteModalOpen(false);
        setSelectedPackage(null);
        fetchPackages();
      } else {
        toast.error(response.message || 'Failed to deactivate package');
      }
    } catch (error) {
      console.error('Error deactivating package:', error);
      toast.error('Failed to deactivate package');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openCreateModal = () => {
    resetForm();
    setIsCreateModalOpen(true);
  };

  const openEditModal = (pkg: CreditPackage) => {
    setSelectedPackage(pkg);
    setFormData({
      name: pkg.name,
      description: pkg.description,
      amount: pkg.amount,
      currency: pkg.currency,
      credits: pkg.credits,
      is_active: pkg.is_active !== false
    });
    setIsEditModalOpen(true);
  };

  const openDeleteModal = (pkg: CreditPackage) => {
    setSelectedPackage(pkg);
    setIsDeleteModalOpen(true);
  };

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      amount: 0,
      currency: 'USD',
      credits: 0,
      is_active: true
    });
  };

  const handleInputChange = (field: keyof CreatePackageRequest, value: string | number | boolean) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  return (
    <PageShell>
      <PageHeader
        title="Credit Packages"
        description="Manage credit packages available for purchase."
        icon={<Package className="h-5 w-5" />}
        actions={
          <div className="flex gap-2">
            <Button onClick={fetchPackages} variant="secondary" className="px-3" title="Refresh">
              <RefreshCw className={clsx("w-4 h-4", isLoading && "animate-spin")} />
            </Button>
            <Button onClick={openCreateModal}>
              <Plus className="w-4 h-4 mr-2" />
              New Package
            </Button>
          </div>
        }
      />

      {/* Packages Grid */}
      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center text-gray-500 flex flex-col items-center">
            <Loader2 className="w-8 h-8 animate-spin text-gray-400 mb-4" />
            <p>Loading packages...</p>
          </div>
        ) : packages.length === 0 ? (
          <div className="p-12 text-center flex flex-col items-center">
            <Package className="w-12 h-12 text-gray-300 mb-4" />
            <h3 className="text-lg font-medium text-gray-900">No packages found</h3>
            <p className="text-gray-500 mt-2">Create your first credit package to get started.</p>
            <Button onClick={openCreateModal} className="mt-6">
              <Plus className="w-4 h-4 mr-2" />
              Create Package
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 p-6">
            {packages.map((pkg) => (
              <div
                key={pkg.id}
                className={clsx(
                  'relative rounded-lg border-2 p-5 transition-all duration-200',
                  pkg.is_active === false
                    ? 'border-gray-200 bg-gray-50 opacity-75'
                    : 'border-primary-200 bg-primary-50/30 hover:border-primary-300 hover:shadow-md'
                )}
              >
                {/* Status Badge */}
                <div className="absolute top-3 right-3">
                  {pkg.is_active === false ? (
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                      <X className="w-3 h-3 mr-1" />
                      Inactive
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-success-50 text-success-700">
                      <Check className="w-3 h-3 mr-1" />
                      Active
                    </span>
                  )}
                </div>

                <div className="mb-4">
                  <h3 className="text-lg font-semibold text-gray-900 pr-20">{pkg.name}</h3>
                  <p className="text-sm text-gray-600 mt-1">{pkg.description}</p>
                </div>

                <div className="space-y-2 mb-4">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Price:</span>
                    <span className="font-semibold text-gray-900">
                      ${pkg.amount.toFixed(2)} {pkg.currency}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Credits:</span>
                    <span className="font-semibold text-gray-900">{pkg.credits}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Cost per credit:</span>
                    <span className="font-medium text-gray-700">
                      ${(pkg.amount / pkg.credits).toFixed(3)}
                    </span>
                  </div>
                </div>

                <div className="flex gap-2 pt-4 border-t border-gray-200">
                  <Button
                    variant="secondary"
                    onClick={() => openEditModal(pkg)}
                    className="flex-1 h-9 text-xs"
                  >
                    <Edit2 className="w-3.5 h-3.5 mr-1.5" />
                    Edit
                  </Button>
                  {pkg.is_active !== false && (
                    <Button
                      variant="secondary"
                      onClick={() => openDeleteModal(pkg)}
                      className="h-9 px-3 text-xs bg-error-50 text-error-600 border-error-200 hover:bg-error-50"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Modal */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => !isSubmitting && setIsCreateModalOpen(false)}
        title="Create New Package"
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label className="label">
              Name <span className="text-error-500">*</span>
            </label>
            <Input
              value={formData.name}
              onChange={(e) => handleInputChange('name', e.target.value)}
              placeholder="e.g., Starter Pack"
              required
            />
          </div>

          <div>
            <label className="label">
              Description <span className="text-error-500">*</span>
            </label>
            <Input
              value={formData.description}
              onChange={(e) => handleInputChange('description', e.target.value)}
              placeholder="e.g., 100 credits for beginners"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">
                Amount ($) <span className="text-error-500">*</span>
              </label>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={formData.amount || ''}
                onChange={(e) => handleInputChange('amount', parseFloat(e.target.value) || 0)}
                placeholder="9.99"
                required
              />
            </div>
            <div>
              <label className="label">
                Moneda
              </label>
              <select
                value={formData.currency}
                onChange={(e) => handleInputChange('currency', e.target.value)}
                className="input"
              >
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
                <option value="GBP">GBP</option>
              </select>
            </div>
          </div>

          <div>
            <label className="label">
              Credits <span className="text-error-500">*</span>
            </label>
            <Input
              type="number"
              min="1"
              value={formData.credits || ''}
              onChange={(e) => handleInputChange('credits', parseInt(e.target.value) || 0)}
              placeholder="100"
              required
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_active"
              checked={formData.is_active}
              onChange={(e) => handleInputChange('is_active', e.target.checked)}
              className="rounded border-gray-200 text-primary-600 focus:ring-primary-500"
            />
            <label htmlFor="is_active" className="text-sm text-gray-700">
              Active (visible to users)
            </label>
          </div>

          <div className="pt-4 flex justify-end gap-3 border-t border-gray-200">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsCreateModalOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Creating...
                </>
              ) : (
                'Create Package'
              )}
            </Button>
          </div>
        </form>
      </Modal>

      {/* Edit Modal */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => !isSubmitting && setIsEditModalOpen(false)}
        title="Edit Package"
      >
        <form onSubmit={handleUpdate} className="space-y-4">
          <div>
            <label className="label">
              Name
            </label>
            <Input
              value={formData.name}
              onChange={(e) => handleInputChange('name', e.target.value)}
              placeholder="e.g., Starter Pack"
            />
          </div>

          <div>
            <label className="label">
              Description
            </label>
            <Input
              value={formData.description}
              onChange={(e) => handleInputChange('description', e.target.value)}
              placeholder="e.g., 100 credits for beginners"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">
                Amount ($)
              </label>
              <Input
                type="number"
                step="0.01"
                min="0.01"
                value={formData.amount || ''}
                onChange={(e) => handleInputChange('amount', parseFloat(e.target.value) || 0)}
                placeholder="9.99"
              />
            </div>
            <div>
              <label className="label">
                Moneda
              </label>
              <select
                value={formData.currency}
                onChange={(e) => handleInputChange('currency', e.target.value)}
                className="input"
              >
                <option value="USD">USD</option>
                <option value="EUR">EUR</option>
                <option value="GBP">GBP</option>
              </select>
            </div>
          </div>

          <div>
            <label className="label">
              Credits
            </label>
            <Input
              type="number"
              min="1"
              value={formData.credits || ''}
              onChange={(e) => handleInputChange('credits', parseInt(e.target.value) || 0)}
              placeholder="100"
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="edit_is_active"
              checked={formData.is_active}
              onChange={(e) => handleInputChange('is_active', e.target.checked)}
              className="rounded border-gray-200 text-primary-600 focus:ring-primary-500"
            />
            <label htmlFor="edit_is_active" className="text-sm text-gray-700">
              Active (visible to users)
            </label>
          </div>

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

      {/* Deactivate Confirmation Modal */}
      <Modal
        isOpen={isDeleteModalOpen}
        onClose={() => !isSubmitting && setIsDeleteModalOpen(false)}
        title="Deactivate Package"
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-6 h-6 text-warning-500 mt-0.5" />
            <div>
              <p className="text-gray-700">
                Are you sure you want to deactivate <strong>{selectedPackage?.name}</strong>?
              </p>
              <p className="text-sm text-gray-500 mt-2">
                This package will no longer be visible to users for purchase. This action can be reversed by editing the package.
              </p>
            </div>
          </div>

          <div className="pt-4 flex justify-end gap-3 border-t border-gray-200">
            <Button
              variant="secondary"
              onClick={() => setIsDeleteModalOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              onClick={handleDeactivate}
              disabled={isSubmitting}
              className="bg-error-600 hover:bg-error-700 text-white"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Deactivating...
                </>
              ) : (
                <>
                  <Trash2 className="w-4 h-4 mr-2" />
                  Deactivate
                </>
              )}
            </Button>
          </div>
        </div>
      </Modal>
    </PageShell>
  );
}
