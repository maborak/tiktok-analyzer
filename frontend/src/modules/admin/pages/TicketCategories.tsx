import { useState, useEffect } from 'react';
import { Plus, RefreshCw, Edit, Tag } from 'lucide-react';
import { adminTicketsApi } from '../services/tickets';
import type { TicketCategory } from '@/types/api';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';

export function TicketCategories() {
    const [categories, setCategories] = useState<TicketCategory[]>([]);
    const [isLoading, setIsLoading] = useState(true);

    // Modal
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isEditing, setIsEditing] = useState(false);

    // Form State
    const [editingId, setEditingId] = useState('');
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [isActive, setIsActive] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);

    const loadCategories = async () => {
        setIsLoading(true);
        try {
            const data = await adminTicketsApi.getCategories();
            const cats = (data as any).data || data;
            if (Array.isArray(cats)) {
                setCategories(cats);
            }
        } catch (error) {
            console.error('Failed to load categories', error);
            toast.error('Failed to load categories');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadCategories();
    }, []);

    const openCreateModal = () => {
        setIsEditing(false);
        setName('');
        setDescription('');
        setIsActive(true);
        setIsModalOpen(true);
    };

    const openEditModal = (category: TicketCategory) => {
        setIsEditing(true);
        setEditingId(category.id);
        setName(category.name);
        setDescription(category.description || '');
        setIsActive(category.is_active);
        setIsModalOpen(true);
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!name.trim()) {
            toast.error('Name is required');
            return;
        }

        setIsSubmitting(true);
        try {
            if (isEditing) {
                await adminTicketsApi.updateCategory(editingId, {
                    name,
                    description,
                    is_active: isActive
                });
                toast.success('Category updated');
            } else {
                await adminTicketsApi.createCategory({
                    name,
                    description,
                    is_active: isActive
                });
                toast.success('Category created');
            }
            setIsModalOpen(false);
            loadCategories();
        } catch (error) {
            console.error('Submit error:', error);
            toast.error('Failed to save category');
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleToggleStatus = async (category: TicketCategory) => {
        try {
            await adminTicketsApi.updateCategory(category.id, {
                is_active: !category.is_active
            });
            toast.success(`Category ${!category.is_active ? 'Activated' : 'Archived'}`);
            loadCategories();
        } catch {
            toast.error('Failed to toggle category status');
        }
    };

    return (
        <PageShell>
            <PageHeader
                title="Ticket Categories"
                description="Manage system categories for support routing."
                icon={<Tag className="h-5 w-5" />}
                actions={
                    <div className="flex gap-2 w-full md:w-auto">
                        <Button onClick={loadCategories} variant="secondary" className="px-3" title="Refresh">
                            <RefreshCw className={clsx("w-4 h-4", isLoading && "animate-spin")} />
                        </Button>
                        <Button onClick={openCreateModal} className="w-full sm:w-auto">
                            <Plus className="w-4 h-4 mr-2" />
                            Create Category
                        </Button>
                    </div>
                }
            />

            <div className="card p-0 overflow-hidden">
                {isLoading && categories.length === 0 ? (
                    <div className="py-20 text-center flex flex-col items-center justify-center text-gray-500">
                        <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-gray-400" />
                        Loading categories...
                    </div>
                ) : (
                    <>
                        <table className="hidden md:table min-w-full divide-y divide-gray-200 text-sm text-left">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="auth-mono-label px-6 py-3 text-left">Name</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Description</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Status</th>
                                    <th className="auth-mono-label px-6 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {categories.map(category => (
                                    <tr key={category.id} className={clsx("hover:bg-gray-50 transition-colors", !category.is_active && "opacity-60")}>
                                        <td className="px-6 py-4 whitespace-nowrap font-medium text-gray-900">
                                            {category.name}
                                        </td>
                                        <td className="px-6 py-4 text-gray-500 max-w-xs truncate">
                                            {category.description || '-'}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={clsx(
                                                "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
                                                category.is_active ? "bg-success-50 text-success-700" : "bg-gray-100 text-gray-800"
                                            )}>
                                                {category.is_active ? 'Active' : 'Archived'}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <div className="flex justify-end gap-2">
                                                <Button
                                                    variant="secondary"
                                                    onClick={() => handleToggleStatus(category)}
                                                    className="h-8 py-0 px-3 text-xs"
                                                >
                                                    {category.is_active ? 'Archive' : 'Activate'}
                                                </Button>
                                                <Button
                                                    variant="secondary"
                                                    onClick={() => openEditModal(category)}
                                                    className="h-8 py-0 px-3 text-xs"
                                                >
                                                    <Edit className="w-4 h-4" />
                                                </Button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {categories.length === 0 && (
                                    <tr>
                                        <td colSpan={4} className="px-6 py-10 text-center text-gray-500">
                                            No categories found. Create one.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>

                        {/* Mobile: card list — one card per category. */}
                        {categories.length === 0 ? (
                            <div className="md:hidden px-6 py-10 text-center text-gray-500">
                                No categories found. Create one.
                            </div>
                        ) : (
                            <ul className="md:hidden flex flex-col gap-2 p-2">
                                {categories.map(category => (
                                    <li
                                        key={category.id}
                                        className={clsx(
                                            "rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 hover:bg-gray-50 transition-colors",
                                            !category.is_active && "opacity-60"
                                        )}
                                    >
                                        <div className="flex items-start justify-between gap-2 mb-1">
                                            <div className="min-w-0 flex-1 text-sm font-medium text-gray-900 truncate">
                                                {category.name}
                                            </div>
                                            <span className={clsx(
                                                "shrink-0 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
                                                category.is_active
                                                    ? "bg-success-50 text-success-700 dark:bg-success-500/10 dark:text-success-300"
                                                    : "bg-gray-100 text-gray-800"
                                            )}>
                                                {category.is_active ? 'Active' : 'Archived'}
                                            </span>
                                        </div>
                                        {category.description && (
                                            <div className="text-xs text-gray-500 mb-2">
                                                {category.description}
                                            </div>
                                        )}
                                        <div className="flex justify-end gap-2">
                                            <Button
                                                variant="secondary"
                                                onClick={() => handleToggleStatus(category)}
                                                className="h-8 py-0 px-3 text-xs"
                                            >
                                                {category.is_active ? 'Archive' : 'Activate'}
                                            </Button>
                                            <Button
                                                variant="secondary"
                                                onClick={() => openEditModal(category)}
                                                className="h-8 py-0 px-3 text-xs"
                                            >
                                                <Edit className="w-4 h-4" />
                                            </Button>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </>
                )}
            </div>

            <Modal
                isOpen={isModalOpen}
                onClose={() => !isSubmitting && setIsModalOpen(false)}
                title={isEditing ? 'Edit Category' : 'Create Category'}
            >
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="label">Name <span className="text-error-500">*</span></label>
                        <Input
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            placeholder="e.g. Technical Support"
                            required
                        />
                    </div>
                    <div>
                        <label className="label">Description</label>
                        <textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            placeholder="Optional explanation of this category"
                            rows={3}
                            className="input p-3"
                        />
                    </div>
                    <div className="flex items-center gap-2 mt-4">
                        <input
                            type="checkbox"
                            id="categoryActive"
                            checked={isActive}
                            onChange={(e) => setIsActive(e.target.checked)}
                            className="rounded border-gray-200 text-primary-600 focus:ring-primary-500"
                        />
                        <label htmlFor="categoryActive" className="text-sm text-gray-700 cursor-pointer">
                            Category is active and selectable by users
                        </label>
                    </div>

                    <div className="pt-4 flex justify-end gap-3 border-t border-gray-200">
                        <Button
                            type="button"
                            variant="secondary"
                            onClick={() => setIsModalOpen(false)}
                            disabled={isSubmitting}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={isSubmitting || !name.trim()}>
                            {isSubmitting ? (
                                <>
                                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                                    Saving...
                                </>
                            ) : 'Save Category'}
                        </Button>
                    </div>
                </form>
            </Modal>
        </PageShell>
    );
}
