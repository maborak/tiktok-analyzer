import { useState, useEffect, useRef } from 'react';
import { Mail, Plus, CheckCircle, AlertCircle, Send, Trash2, Edit, Save, RefreshCw, Clock, Loader } from 'lucide-react';
import type { Recipient, RecipientType } from '../types';
import { recipientRepository } from '../index';
import { toast } from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { FormField } from '@/components/ui/FormField';
import { Modal } from '@/components/ui/Modal';
import { LoadingState } from '@/components/ui/LoadingState';
import { DataTable } from '@/components/DataTable';
import type { Column, FilterConfig, RowAction } from '@/components/DataTable';
import { PageShell } from '@/components/ui/PageShell';
import { RecipientWizard } from '../components/RecipientWizard';

export function Recipients() {
    // const loaderData = useLoaderData(); // Unused

    const [recipients, setRecipients] = useState<Recipient[]>([]);
    const [loading, setLoading] = useState(true);
    const [operationLoading, setOperationLoading] = useState(false);

    // Search state
    const [searchTerm, setSearchTerm] = useState('');
    const [activeSearchTerm, setActiveSearchTerm] = useState('');

    // Filter & Sort State
    const [statusFilter, setStatusFilter] = useState<string>('all');
    const [sortBy, setSortBy] = useState<keyof Recipient>('name');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

    // Modal state
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [currentRecipient, setCurrentRecipient] = useState<Recipient | null>(null);
    const [showAddWizard, setShowAddWizard] = useState(false);

    // Bulk Actions State
    const [selectedIds, setSelectedIds] = useState<Set<number | string>>(new Set());
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [recipientToDelete, setRecipientToDelete] = useState<Recipient | null>(null);
    const [deleteProgress, setDeleteProgress] = useState(0);
    const [isDeleting, setIsDeleting] = useState(false);
    const abortControllerRef = useRef<AbortController | null>(null);

    // Resend verification modal state
    const [resendRecipient, setResendRecipient] = useState<Recipient | null>(null);
    const [resendLoading, setResendLoading] = useState(false);
    const [resendPolling, setResendPolling] = useState(false);
    const [resendCountdown, setResendCountdown] = useState(0);
    const [resendRateLimit, setResendRateLimit] = useState<{
        retryAfter: number;
        requiresCaptcha: boolean;
        captchaProvider: string | null;
        attempt: number;
        totalTiers: number;
    } | null>(null);
    const resendPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Form state
    const [formData, setFormData] = useState<{
        name: string;
        value: string;
        type: RecipientType;
    }>({
        name: '',
        value: '',
        type: 'email'
    });

    // Removed unused isInitialMount ref

    const loadRecipients = async (showLoading = true) => {
        try {
            if (showLoading) setLoading(true);
            const response = await recipientRepository.list();
            if (response.success && response.data) {
                setRecipients(response.data.recipients);
            } else {
                toast.error(response.message || 'Error loading recipients');
            }
        } catch (error) {
            console.error('Failed to load recipients:', error);
            toast.error('Error loading recipients');
        } finally {
            if (showLoading) setLoading(false);
        }
    };

    useEffect(() => {
        loadRecipients();
    }, []);

    const handleCreateOpen = () => {
        setShowAddWizard(true);
    };

    const handleEditOpen = (recipient: Recipient) => {
        setFormData({ name: recipient.name || '', value: recipient.value, type: recipient.type });
        setIsEdit(true);
        setCurrentRecipient(recipient);
        setIsModalOpen(true);
    };

    const handleClose = () => {
        setIsModalOpen(false);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!formData.name.trim() || !formData.value.trim()) {
            toast.error('Name and email are required');
            return;
        }

        setOperationLoading(true);
        try {
            if (isEdit && currentRecipient) {
                // Update
                const response = await recipientRepository.update(currentRecipient.id, {
                    name: formData.name,
                    // We don't update value/type in this simple form usually, but if we do:
                    // value: formData.value  -- Assuming API supports it? 
                    // Let's assume update supports checking the updated type?
                    // But actually Recipient interface in Domain doesn't show update method signature here.
                    // Checking UpdateRecipientRequest in Domain... lines 19-23. No value???
                    // Step 776: UpdateRecipientRequest: name, isEnabled, subjectTag. NO VALUE.
                    // So we cannot update email/value?
                    // I'll stick to updating name only or check Repo impl.
                });

                if (response.success) {
                    toast.success('Recipient updated successfully');
                    loadRecipients(false);
                    handleClose();
                } else {
                    toast.error(response.message || 'Error updating recipient');
                }
            } else {
                // Create
                const response = await recipientRepository.create({
                    name: formData.name,
                    value: formData.value,
                    type: 'email'
                });

                if (response.success) {
                    toast.success('Recipient created successfully');
                    loadRecipients(false);
                    handleClose();
                } else {
                    toast.error(response.message || 'Error creating recipient');
                }
            }
        } catch (error) {
            console.error('Operation failed:', error);
            toast.error(isEdit ? 'Error updating recipient' : 'Error creating recipient');
        } finally {
            setOperationLoading(false);
        }
    };

    const confirmDelete = async () => {
        if (!recipientToDelete) return;

        setIsDeleting(true);
        try {
            const response = await recipientRepository.delete(recipientToDelete.id);
            if (response.success) {
                toast.success('Recipient deleted successfully');
                loadRecipients(false);
                setShowDeleteModal(false);
                setRecipientToDelete(null);
            } else {
                toast.error(response.message || 'Error deleting recipient');
            }
        } catch (error) {
            console.error('Delete failed:', error);
            toast.error('Error deleting recipient');
        } finally {
            setIsDeleting(false);
        }
    };

    const handleDeleteClick = (recipient: Recipient) => {
        setRecipientToDelete(recipient);
        setShowDeleteModal(true);
    };

    const handleBulkDelete = async () => {
        setIsDeleting(true);
        setDeleteProgress(0);
        abortControllerRef.current = new AbortController();

        const idsToDelete = Array.from(selectedIds);
        let successCount = 0;
        let failCount = 0;

        for (let i = 0; i < idsToDelete.length; i++) {
            if (abortControllerRef.current?.signal.aborted) {
                break;
            }

            const id = Number(idsToDelete[i]);
            try {
                const response = await recipientRepository.delete(id);
                if (response.success) {
                    successCount++;
                } else {
                    failCount++;
                    console.error(`Failed to delete recipient ${id}:`, response.message);
                }
            } catch (error) {
                failCount++;
                console.error(`Failed to delete recipient ${id}:`, error);
            }

            setDeleteProgress(Math.round(((i + 1) / idsToDelete.length) * 100));
        }

        setIsDeleting(false);
        setShowDeleteModal(false);
        setSelectedIds(new Set());
        loadRecipients(false);

        if (successCount > 0) {
            toast.success(`${successCount} recipients deleted successfully`);
        }
        if (failCount > 0) {
            toast.error(`Error deleting ${failCount} recipients`);
        }
    };

    const cancelDelete = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        setShowDeleteModal(false);
        setIsDeleting(false);
        setDeleteProgress(0);
        setRecipientToDelete(null);
    };

    // Countdown timer for resend rate limit
    useEffect(() => {
        if (resendCountdown <= 0) return;
        const timer = setInterval(() => setResendCountdown(c => c - 1), 1000);
        return () => clearInterval(timer);
    }, [resendCountdown]);

    // Cleanup polling on unmount
    useEffect(() => {
        return () => { if (resendPollRef.current) clearInterval(resendPollRef.current); };
    }, []);

    const handleOpenResendModal = (recipient: Recipient) => {
        setResendRecipient(recipient);
        setResendPolling(false);
        setResendRateLimit(null);
        setResendCountdown(0);
    };

    const handleCloseResendModal = () => {
        if (resendPollRef.current) clearInterval(resendPollRef.current);
        setResendRecipient(null);
        setResendPolling(false);
        setResendRateLimit(null);
        setResendCountdown(0);
    };

    const handleResendVerification = async () => {
        if (!resendRecipient) return;
        setResendLoading(true);
        try {
            const response = await recipientRepository.resendVerification(resendRecipient.id);
            if (response.success) {
                toast.success('Verification email sent');
                setResendPolling(true);
                // Start polling for verification
                if (resendPollRef.current) clearInterval(resendPollRef.current);
                resendPollRef.current = setInterval(async () => {
                    try {
                        const res = await recipientRepository.list();
                        if (res.success && res.data) {
                            const found = res.data.recipients.find(r => r.id === resendRecipient.id);
                            if (found?.isVerified) {
                                if (resendPollRef.current) clearInterval(resendPollRef.current);
                                toast.success('Correo verificado correctamente');
                                setRecipients(res.data.recipients);
                                handleCloseResendModal();
                            }
                        }
                    } catch { /* continue */ }
                }, 5000);
            }
        } catch (err: any) {
            const status = err?.response?.status;
            const data = err?.response?.data;
            const prl = status === 429 ? (data?.detail?.detail === 'progressive_rate_limited' ? data.detail : null) : null;
            if (prl) {
                setResendRateLimit({
                    retryAfter: prl.retry_after,
                    requiresCaptcha: prl.requires_captcha,
                    captchaProvider: prl.captcha_provider,
                    attempt: prl.attempt,
                    totalTiers: prl.total_tiers,
                });
                setResendCountdown(prl.retry_after);
            } else {
                toast.error('Error sending verification email');
            }
        } finally {
            setResendLoading(false);
        }
    };

    // Pagination state
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);

    const handleSearchSubmit = (term: string) => {
        setSearchTerm(term);
        setActiveSearchTerm(term);
        setPage(1);
    };

    const filteredRecipients = recipients
        .filter(r => {
            const searchMatch = (r.name && r.name.toLowerCase().includes(activeSearchTerm.toLowerCase())) ||
                r.value.toLowerCase().includes(activeSearchTerm.toLowerCase());

            if (!searchMatch) return false;

            if (statusFilter === 'verified') return r.isVerified === true;
            if (statusFilter === 'pending') return r.isVerified === false;
            return true;
        })
        .sort((a, b) => {
            const valA = a[sortBy];
            const valB = b[sortBy];

            if (typeof valA === 'string' && typeof valB === 'string') {
                return sortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
            }
            if (typeof valA === 'boolean' && typeof valB === 'boolean') {
                return sortOrder === 'asc' ? (valA === valB ? 0 : valA ? 1 : -1) : (valA === valB ? 0 : valA ? -1 : 1);
            }
            return 0; // fallback
        });

    const filterConfigs: FilterConfig[] = [
        {
            key: 'status',
            label: 'Status',
            options: [
                { value: 'all', label: 'All Statuses' },
                { value: 'verified', label: 'Verified' },
                { value: 'pending', label: 'Pending' }
            ],
            value: statusFilter,
            onChange: (val) => {
                setStatusFilter(val);
                setPage(1);
            }
        }
    ];

    const rowActions = (row: Recipient): RowAction[] => [
        {
            label: 'Edit',
            icon: Edit,
            onClick: () => handleEditOpen(row)
        },
        {
            label: 'Delete',
            icon: Trash2,
            onClick: () => handleDeleteClick(row),
            variant: 'danger'
        }
    ];

    const total = filteredRecipients.length;
    const totalPages = Math.ceil(total / pageSize);
    const paginatedRecipients = filteredRecipients.slice((page - 1) * pageSize, page * pageSize);

    const columns: Column<Recipient>[] = [
        {
            key: 'name',
            label: 'Name',
            sortable: true,
            render: (r) => (
                <div className="font-medium text-gray-900">{r.name}</div>
            )
        },
        {
            key: 'value',
            label: 'Email Address',
            sortable: true,
            render: (r) => (
                <div className="flex items-center gap-2">
                    <Mail className="w-4 h-4 text-gray-400" />
                    <span className="text-gray-600">{r.value}</span>
                </div>
            )
        },
        {
            key: 'isVerified',
            label: 'Status',
            sortable: true,
            render: (r) => {
                if (r.isVerified) {
                    return (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-success-50 text-success-700">
                            <CheckCircle className="w-3 h-3 mr-1" />
                            Verified
                        </span>
                    );
                } else {
                    return (
                        <div className="flex items-center gap-2">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-warning-50 text-warning-700">
                                <AlertCircle className="w-3 h-3 mr-1" />
                                Pending
                            </span>
                            <button
                                onClick={() => handleOpenResendModal(r)}
                                className="text-xs text-primary-600 hover:underline flex items-center gap-1"
                                title="Resend verification email"
                            >
                                <Send className="w-3 h-3" />
                                Resend
                            </button>
                        </div>
                    );
                }
            }
        }
    ];

    if (loading) {
        return <LoadingState message="Loading recipients..." />;
    }

    return (
        <PageShell>
            <DataTable<Recipient>
                data={paginatedRecipients}
                loading={loading}
                columns={columns}
                getRowId={(r) => r.id}
                title="Recipients"
                subtitle="Manage who receives notifications"
                headerAction={
                    <Button
                        onClick={handleCreateOpen}
                        className="auth-submit lowercase"
                        style={{ fontFamily: 'var(--font-mono-display)' }}
                    >
                        <Plus className="w-4 h-4 mr-2" />
                        add recipient →
                    </Button>
                }
                searchEnabled={true}
                searchTerm={searchTerm}
                onSearchChange={setSearchTerm}
                onSearchSubmit={handleSearchSubmit}
                filters={filterConfigs}
                rowActions={rowActions}
                sortBy={sortBy}
                sortOrder={sortOrder}
                onSort={(key) => {
                    const typedKey = key as keyof Recipient;
                    if (sortBy === typedKey) {
                        setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
                    } else {
                        setSortBy(typedKey);
                        setSortOrder('asc');
                    }
                }}
                emptyTitle="No recipients found"
                emptyDescription={searchTerm ? "Try adjusting your search" : "Add your first recipient to start sending alerts."}
                page={page}
                pageSize={pageSize}
                total={total}
                totalPages={totalPages || 1}
                onPageChange={setPage}
                onPageSizeChange={setPageSize}
                selectable={true}
                selectedIds={selectedIds}
                onSelectionChange={setSelectedIds}
                bulkActions={[
                    {
                        label: 'Delete Selected',
                        icon: Trash2,
                        onClick: () => setShowDeleteModal(true),
                        variant: 'danger'
                    }
                ]}
                deleteModal={{
                    show: showDeleteModal,
                    title: recipientToDelete ? `Delete Recipient` : `Delete ${selectedIds.size} Recipients`,
                    message: recipientToDelete
                        ? `Are you sure you want to delete ${recipientToDelete.name}? This action cannot be undone.`
                        : `Are you sure you want to delete ${selectedIds.size} selected recipients? This action cannot be undone and may affect alerts.`,
                    onConfirm: recipientToDelete ? confirmDelete : handleBulkDelete,
                    onCancel: cancelDelete,
                    loading: isDeleting,
                    showProgress: isDeleting && !recipientToDelete,
                    progress: deleteProgress,
                    onCancelProgress: cancelDelete,
                    confirmLabel: recipientToDelete ? 'Delete' : 'Delete All',
                    confirmVariant: 'danger'
                }}
            />

            {/* Create/Edit Recipient Modal */}
            <Modal
                isOpen={isModalOpen}
                onClose={handleClose}
                title={isEdit ? "Edit Recipient" : "Add Recipient"}
            >
                <form onSubmit={handleSubmit} className="space-y-4">
                    <FormField id="name" label="Name">
                        <Input
                            id="name"
                            value={formData.name}
                            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                            placeholder="Ex. John Doe"
                            required
                        />
                    </FormField>
                    <FormField id="email" label="Email Address">
                        <Input
                            id="email"
                            type="email"
                            value={formData.value}
                            onChange={(e) => setFormData({ ...formData, value: e.target.value })}
                            placeholder="Ex. john@example.com"
                            required
                            disabled={isEdit}
                        />
                    </FormField>

                    <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                        <Button type="button" variant="secondary" onClick={handleClose} disabled={operationLoading}>
                            Cancel
                        </Button>
                        <Button type="submit" disabled={operationLoading}>
                            {operationLoading ? (
                                <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                            ) : (
                                <Save className="w-4 h-4 mr-2" />
                            )}
                            {isEdit ? 'Save Changes' : 'Add'}
                        </Button>
                    </div>
                </form>
            </Modal>

            {/* Add Recipient Wizard */}
            <Modal
                isOpen={showAddWizard}
                onClose={() => setShowAddWizard(false)}
                title="Agregar Destinatario"
                className="max-w-lg"
            >
                <RecipientWizard
                    onRecipientReady={(_recipientIds, updatedRecipients) => {
                        setRecipients(updatedRecipients);
                        setShowAddWizard(false);
                        toast.success('Recipient added and verified!');
                    }}
                    onSkipVerification={(_recipientId) => {
                        loadRecipients(false);
                        setShowAddWizard(false);
                        toast.success('Recipient added. Verification pending.');
                    }}
                />
            </Modal>

            {/* Resend Verification Modal */}
            <Modal
                isOpen={!!resendRecipient}
                onClose={handleCloseResendModal}
                title="Resend Verification Email"
                className="max-w-md"
            >
                {resendRecipient && (
                    <div className="space-y-4">
                        {resendPolling ? (
                            <div className="text-center py-6">
                                <div className="w-16 h-16 rounded-full bg-primary-100 flex items-center justify-center mx-auto mb-4">
                                    <Loader className="w-8 h-8 animate-spin text-primary-600" />
                                </div>
                                <h3
                                    className="text-lg font-semibold text-gray-900"
                                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                                >
                                    Awaiting verification
                                </h3>
                                <p className="text-sm text-gray-500 mt-1">
                                    We sent a verification link to <span className="font-medium text-gray-700">{resendRecipient.value}</span>.
                                    Click the link in your email to verify.
                                </p>
                                <div className="flex flex-col gap-2 mt-4">
                                    <button
                                        onClick={() => { setResendPolling(false); }}
                                        disabled={resendCountdown > 0}
                                        className="text-sm text-primary-600 hover:text-primary-700 font-medium flex items-center justify-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <RefreshCw className="w-3.5 h-3.5" />
                                        {resendCountdown > 0 ? `Reenviar en ${resendCountdown}s` : 'Enviar de nuevo'}
                                    </button>
                                    <button
                                        onClick={handleCloseResendModal}
                                        className="text-sm text-gray-500 hover:text-gray-700"
                                    >
                                        Cerrar
                                    </button>
                                </div>
                            </div>
                        ) : resendCountdown > 0 ? (
                            <div className="text-center py-6">
                                <Clock className="w-10 h-10 text-amber-500 mx-auto mb-3" />
                                <p className="text-sm text-gray-700">Por favor espera antes de reenviar</p>
                                <p className="text-2xl font-bold text-gray-900 mt-2">{resendCountdown}s</p>
                                {resendRateLimit && (
                                    <p className="text-xs text-gray-400 mt-2">
                                        Intento {resendRateLimit.attempt} de {resendRateLimit.totalTiers}
                                    </p>
                                )}
                                <div className="flex justify-end gap-3 mt-4">
                                    <Button type="button" variant="secondary" onClick={handleCloseResendModal}>
                                        Cancelar
                                    </Button>
                                </div>
                            </div>
                        ) : (
                            <div>
                                <p className="text-sm text-gray-600">
                                    Send a new verification link to <span className="font-medium text-gray-900">{resendRecipient.value}</span>?
                                </p>
                                {resendRateLimit?.requiresCaptcha && (
                                    <div className="border rounded-lg p-4 bg-gray-50 mt-3">
                                        <p className="text-xs text-gray-500 mb-2">Por favor verifica que eres humano</p>
                                        <p className="text-xs text-gray-400 italic">CAPTCHA: {resendRateLimit.captchaProvider || 'none'}</p>
                                    </div>
                                )}
                                {resendRateLimit && (
                                    <p className="text-xs text-gray-400 text-center mt-2">
                                        Intento {resendRateLimit.attempt} de {resendRateLimit.totalTiers}
                                    </p>
                                )}
                                <div className="flex justify-end gap-3 mt-4">
                                    <Button type="button" variant="secondary" onClick={handleCloseResendModal}>
                                        Cancelar
                                    </Button>
                                    <Button
                                        type="button"
                                        onClick={handleResendVerification}
                                        disabled={resendLoading}
                                    >
                                        {resendLoading ? <Loader className="w-4 h-4 animate-spin mr-2" /> : <Send className="w-4 h-4 mr-2" />}
                                        Reenviar
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </Modal>
        </PageShell>
    );
}
