import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { Plus, RefreshCw, MessageSquare, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Pagination } from '@/components/ui/Pagination';
import { userTicketsApi } from '../services/tickets';
import type { Ticket, TicketCategory, TicketPriority, TicketStatus, PaginationMeta } from '@/types/api';
import { cn } from '@/utils/cn';
import toast from 'react-hot-toast';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { StatusBadge, PriorityBadge } from '../components/tickets/TicketBadges';

const PAGE_SIZE = 5;

export function Tickets() {
    const navigate = useNavigate();
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [categories, setCategories] = useState<TicketCategory[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
    const [statusFilter, setStatusFilter] = useState<TicketStatus | ''>('');

    // Search & pagination state
    const [currentPage, setCurrentPage] = useState(1);
    const [searchInput, setSearchInput] = useState('');
    const [searchTerm, setSearchTerm] = useState('');
    const [paginationMeta, setPaginationMeta] = useState<PaginationMeta | null>(null);

    // Create form state
    const [subject, setSubject] = useState('');
    const [message, setMessage] = useState('');
    const [categoryId, setCategoryId] = useState('');
    const [priority, setPriority] = useState<TicketPriority>('NORMAL');
    const [isSubmitting, setIsSubmitting] = useState(false);

    const fetchTickets = useCallback(async () => {
        setIsLoading(true);
        try {
            const params: { status?: string; search?: string; page?: number; page_size?: number } = {
                page: currentPage,
                page_size: PAGE_SIZE,
            };
            if (statusFilter) params.status = statusFilter;
            if (searchTerm) params.search = searchTerm;

            const data = await userTicketsApi.listTickets(params);
            const response = (data as any).data || data;
            const ticketsList = response?.items || response;

            if (Array.isArray(ticketsList)) {
                setTickets(ticketsList);
            }

            // Build PaginationMeta from backend response
            const total = response?.total ?? ticketsList?.length ?? 0;
            const page = response?.page ?? currentPage;
            const ps = response?.page_size ?? PAGE_SIZE;
            const totalPages = ps > 0 ? Math.ceil(total / ps) || 1 : 1;
            setPaginationMeta({
                total_items: total,
                page,
                page_size: ps,
                total_pages: totalPages,
                has_next: page < totalPages,
                has_previous: page > 1,
            });
        } catch (error) {
            console.error('Failed to fetch tickets:', error);
            toast.error('Failed to load tickets');
        } finally {
            setIsLoading(false);
        }
    }, [currentPage, statusFilter, searchTerm]);

    const fetchCategories = async () => {
        try {
            const data = await userTicketsApi.getCategories();
            const cats = (data as any).data || data;
            if (Array.isArray(cats)) {
                setCategories(cats);
                if (cats.length > 0 && !categoryId) {
                    setCategoryId(cats[0].id || '');
                }
            }
        } catch (error) {
            console.error('Failed to load categories', error);
        }
    };

    useEffect(() => {
        fetchTickets();
    }, [fetchTickets]);

    useEffect(() => {
        fetchCategories();
    }, []);

    // Auto-open "New Ticket" modal with prefill from sessionStorage.
    // Used by the LiveChatWidget "Open Ticket" button to carry chat context over.
    useEffect(() => {
        const raw = sessionStorage.getItem('ticket_prefill');
        if (!raw) return;
        try {
            const prefill = JSON.parse(raw);
            if (prefill.subject) setSubject(prefill.subject);
            if (prefill.message) setMessage(prefill.message);
            if (prefill.auto_open) setIsCreateModalOpen(true);
        } catch {
            // ignore
        } finally {
            sessionStorage.removeItem('ticket_prefill');
        }
    }, []);

    const handleSearchSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        setSearchTerm(searchInput.trim());
        setCurrentPage(1);
    };

    const handleClearSearch = () => {
        setSearchInput('');
        setSearchTerm('');
        setCurrentPage(1);
    };

    const handleStatusChange = (value: TicketStatus | '') => {
        setStatusFilter(value);
        setCurrentPage(1);
    };

    const handleCreateTicket = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!subject.trim() || !message.trim() || !categoryId) {
            toast.error('Please fill in all required fields');
            return;
        }

        if (subject.trim().length < 3) {
            toast.error('Subject must be at least 3 characters');
            return;
        }

        if (message.trim().length < 10) {
            toast.error('Message must be at least 10 characters');
            return;
        }

        setIsSubmitting(true);
        try {
            await userTicketsApi.createTicket({
                subject,
                message,
                category_id: categoryId,
                priority
            });
            toast.success('Ticket created successfully');
            setIsCreateModalOpen(false);
            setSubject('');
            setMessage('');
            setCurrentPage(1);
        } catch (error) {
            console.error('Create ticket error:', error);
            toast.error('Failed to create ticket');
        } finally {
            setIsSubmitting(false);
        }
    };

    const hasActiveFilters = !!statusFilter || !!searchTerm;

    return (
        <PageShell>
            <PageHeader
                title="Support Tickets"
                description="Manage and track your support requests."
                icon={<MessageSquare className="w-5 h-5" />}
                actions={
                    <div className="flex gap-2">
                        <Button onClick={() => fetchTickets()} variant="secondary" className="px-3" title="Refresh">
                            <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
                        </Button>
                        <Button
                            onClick={() => setIsCreateModalOpen(true)}
                            className="auth-submit lowercase"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            <Plus className="w-4 h-4 mr-2" />
                            new ticket →
                        </Button>
                    </div>
                }
            />

            {/* Search + Status Filter */}
            <div className="space-y-3">
                <form onSubmit={handleSearchSubmit} className="flex gap-2">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                        <Input
                            value={searchInput}
                            onChange={(e) => setSearchInput(e.target.value)}
                            placeholder="Search by subject..."
                            className="pl-9 w-full"
                        />
                    </div>
                    {searchTerm && (
                        <Button type="button" variant="secondary" onClick={handleClearSearch} className="px-3" title="Clear search">
                            <X className="w-4 h-4" />
                        </Button>
                    )}
                    <Button type="submit" variant="secondary">Search</Button>
                </form>

                <div className="flex gap-1 overflow-x-auto pb-1">
                    {([
                        { value: '', label: 'All' },
                        { value: 'OPEN', label: 'Open' },
                        { value: 'PENDING_CUSTOMER', label: 'Awaiting Response' },
                        { value: 'IN_PROGRESS', label: 'In Progress' },
                        { value: 'RESOLVED', label: 'Resolved' },
                        { value: 'CLOSED', label: 'Closed' },
                    ] as { value: TicketStatus | ''; label: string }[]).map((tab) => (
                        <button
                            key={tab.value}
                            onClick={() => handleStatusChange(tab.value)}
                            className={cn(
                                'px-4 py-2 text-sm font-medium rounded-lg transition-colors whitespace-nowrap',
                                statusFilter === tab.value
                                    ? 'bg-primary-600 text-white shadow-sm'
                                    : 'text-gray-600 hover:bg-gray-100'
                            )}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* List */}
            <div className="card p-0 overflow-hidden">
                {isLoading && tickets.length === 0 ? (
                    <div className="p-12 text-center text-gray-500 flex flex-col items-center">
                        <RefreshCw className="w-8 h-8 animate-spin text-gray-400 mb-4" />
                        <p>Loading tickets...</p>
                    </div>
                ) : tickets.length === 0 ? (
                    <div className="p-12 text-center flex flex-col items-center">
                        <MessageSquare className="w-12 h-12 text-gray-300 mb-4" />
                        {hasActiveFilters ? (
                            <>
                                <h3
                                    className="text-lg font-medium text-gray-900"
                                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                                >
                                    No tickets found
                                </h3>
                                <p className="text-gray-500 mt-2">
                                    {searchTerm
                                        ? `No tickets match "${searchTerm}".`
                                        : 'No tickets match the selected filter.'}
                                </p>
                                <Button onClick={() => { setStatusFilter(''); handleClearSearch(); }} className="mt-6" variant="secondary">
                                    Clear filters
                                </Button>
                            </>
                        ) : (
                            <>
                                <h3
                                    className="text-lg font-medium text-gray-900"
                                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                                >
                                    No tickets found
                                </h3>
                                <p className="text-gray-500 mt-2">You haven't submitted any support requests yet.</p>
                                <Button onClick={() => setIsCreateModalOpen(true)} className="mt-6" variant="secondary">
                                    Create your first ticket
                                </Button>
                            </>
                        )}
                    </div>
                ) : (
                    <>
                        {/* Desktop: table layout. Hidden below md where the
                            column count would force horizontal scroll. */}
                        <table className="hidden md:table w-full text-sm">
                            <thead>
                                <tr className="border-b border-gray-200">
                                    <th className="auth-mono-label px-4 py-3 text-left">Ticket</th>
                                    <th className="auth-mono-label px-4 py-3 text-left">Activity</th>
                                    <th className="auth-mono-label px-4 py-3 text-left">Priority</th>
                                    <th className="auth-mono-label px-4 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {tickets.map((ticket) => (
                                    <tr
                                        key={ticket.id}
                                        className="border-b border-gray-100 hover:bg-gray-50 transition-colors cursor-pointer"
                                        onClick={() => navigate({ to: routes.account.ticketDetail(ticket.id) })}
                                    >
                                        <td className="px-4 py-3 align-top">
                                            <div className="flex items-center gap-2 mb-1">
                                                <StatusBadge status={ticket.status} className="text-[10px]" />
                                                <span className="text-xs text-gray-400 font-mono">#{ticket.id.split('-')[0]}</span>
                                                {ticket.category_name && (
                                                    <span className="text-[10px] text-gray-400">{ticket.category_name}</span>
                                                )}
                                            </div>
                                            <h4 className="font-semibold text-gray-900 truncate pr-4 text-base">{ticket.subject}</h4>
                                        </td>
                                        <td className="px-4 py-3 align-top text-xs text-gray-500">
                                            <div className="flex flex-col gap-1">
                                                <span>{ticket.reply_count ?? 0} {(ticket.reply_count ?? 0) === 1 ? 'reply' : 'replies'}</span>
                                                {ticket.last_message_at && (
                                                    <span>Last activity {new Date(ticket.last_message_at).toLocaleDateString()}</span>
                                                )}
                                                {ticket.has_agent_reply && (
                                                    <span className="text-success-600 font-medium">Agent replied</span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 align-top">
                                            <PriorityBadge priority={ticket.priority} />
                                        </td>
                                        <td className="px-4 py-3 align-top text-right">
                                            <Button variant="secondary" size="sm" onClick={(e) => { e.stopPropagation(); navigate({ to: routes.account.ticketDetail(ticket.id) }); }}>View Thread</Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        {/* Mobile: card list — one row per ticket, no
                            horizontal scroll. Only renders below md. */}
                        <ul className="md:hidden flex flex-col gap-2 p-3">
                            {tickets.map((ticket) => (
                                <li
                                    key={ticket.id}
                                    className="rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 hover:bg-gray-50 transition-colors cursor-pointer"
                                    onClick={() => navigate({ to: routes.account.ticketDetail(ticket.id) })}
                                >
                                    <div className="flex items-start justify-between gap-2 mb-1">
                                        <h4 className="min-w-0 flex-1 font-semibold text-gray-900 truncate text-sm">{ticket.subject}</h4>
                                        <StatusBadge status={ticket.status} className="text-[10px] shrink-0" />
                                    </div>
                                    <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
                                        <div className="min-w-0 flex items-center gap-2 flex-wrap">
                                            <span className="font-mono text-[10px] text-gray-400">#{ticket.id.split('-')[0]}</span>
                                            {ticket.category_name && (
                                                <span className="text-[10px] text-gray-400">{ticket.category_name}</span>
                                            )}
                                            <span>{ticket.reply_count ?? 0} {(ticket.reply_count ?? 0) === 1 ? 'reply' : 'replies'}</span>
                                            {ticket.last_message_at && (
                                                <span>· {new Date(ticket.last_message_at).toLocaleDateString()}</span>
                                            )}
                                            {ticket.has_agent_reply && (
                                                <span className="text-success-600 font-medium">Agent replied</span>
                                            )}
                                        </div>
                                        <PriorityBadge priority={ticket.priority} />
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </>
                )}
            </div>

            {/* Pagination */}
            {paginationMeta && paginationMeta.total_items > 0 && (
                <Pagination
                    pagination={paginationMeta}
                    currentPage={currentPage}
                    onPageChange={setCurrentPage}
                />
            )}

            {/* Create Modal */}
            <Modal
                isOpen={isCreateModalOpen}
                onClose={() => !isSubmitting && setIsCreateModalOpen(false)}
                title="Create Support Ticket"
            >
                <form onSubmit={handleCreateTicket} className="space-y-4">
                    <div>
                        <label className="label">Category <span className="text-error-500">*</span></label>
                        <select
                            value={categoryId}
                            onChange={(e) => setCategoryId(e.target.value)}
                            className="input"
                            required
                        >
                            {!categoryId && <option value="" disabled>Select a category</option>}
                            {categories.map(cat => (
                                <option key={cat.id} value={cat.id}>{cat.name}</option>
                            ))}
                        </select>
                    </div>

                    <div>
                        <label className="label">Priority</label>
                        <select
                            value={priority}
                            onChange={(e) => setPriority(e.target.value as TicketPriority)}
                            className="input"
                        >
                            <option value="LOW">Low</option>
                            <option value="NORMAL">Normal</option>
                            <option value="HIGH">High</option>
                            <option value="URGENT">Urgent</option>
                        </select>
                    </div>

                    <div>
                        <label className="label">Subject <span className="text-error-500">*</span> <span className="text-gray-400 text-[10px] font-normal">(min. 3 characters)</span></label>
                        <Input
                            value={subject}
                            onChange={(e) => setSubject(e.target.value)}
                            placeholder="Briefly describe the issue (min. 3 chars)"
                            required
                            className="w-full"
                        />
                    </div>

                    <div>
                        <label className="label">Message <span className="text-error-500">*</span> <span className="text-gray-400 text-[10px] font-normal">(min. 10 characters)</span></label>
                        <textarea
                            value={message}
                            onChange={(e) => setMessage(e.target.value)}
                            placeholder="Provide as much detail as possible (min. 10 chars)..."
                            required
                            rows={5}
                            className="input p-3"
                        />
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
                        <Button
                            type="submit"
                            disabled={isSubmitting || !categoryId}
                            className="auth-submit lowercase"
                            style={{ fontFamily: 'var(--font-mono-display)' }}
                        >
                            {isSubmitting ? (
                                <>
                                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                                    creating...
                                </>
                            ) : (
                                <>
                                    <Plus className="w-4 h-4 mr-2" />
                                    submit ticket →
                                </>
                            )}
                        </Button>
                    </div>
                </form>
            </Modal>
        </PageShell>
    );
}
