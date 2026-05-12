import { useState, useEffect } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Filter, RefreshCw, MessageSquare, CheckCircle, ChevronLeft, ChevronRight, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { adminTicketsApi } from '../services/tickets';
import type { Ticket, TicketStatus, TicketPriority, StaffUser } from '@/types/api';
import { cn } from '@/utils/cn';
import toast from 'react-hot-toast';
import { STATUS_COLORS } from '@user';

export function Tickets() {
    const navigate = useNavigate();
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [totalTickets, setTotalTickets] = useState(0);

    // Pagination
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(5);

    // Filters
    const [statusFilter, setStatusFilter] = useState<TicketStatus | ''>('');
    const [unassignedFilter, setUnassignedFilter] = useState<boolean>(false);
    const [agentIdFilter, setAgentIdFilter] = useState<string>('');

    // Selection for mass actions
    const [selectedTickets, setSelectedTickets] = useState<Set<string>>(new Set());
    const [isMassClosing, setIsMassClosing] = useState(false);

    const loadTickets = async () => {
        setIsLoading(true);
        try {
            // Use backend pagination
            const data = await adminTicketsApi.listTickets({
                status: statusFilter || undefined,
                unassigned: unassignedFilter ? true : undefined,
                agent_id: agentIdFilter || undefined,
                page: currentPage,
                page_size: pageSize
            });
            // Handle paginated response: { items: [...], total, page, page_size }
            const responseData = (data as any).data || data;
            const ticketsList = responseData?.items || responseData;
            if (Array.isArray(ticketsList)) {
                setTickets(ticketsList);
                setTotalTickets(responseData?.total || ticketsList.length);
            }
        } catch (error) {
            console.error('Failed to load admin tickets:', error);
            toast.error('Failed to load tickets');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadTickets();
    }, [statusFilter, unassignedFilter, agentIdFilter, currentPage, pageSize]);

    // Reset selection when filters change
    useEffect(() => {
        setSelectedTickets(new Set());
    }, [statusFilter, unassignedFilter, agentIdFilter, currentPage]);

    const handleStatusChange = async (ticketId: string, newStatus: TicketStatus) => {
        try {
            await adminTicketsApi.changeStatus(ticketId, newStatus);
            toast.success('Status updated');
            loadTickets(); // Refresh list to reflect changes visually consistently
        } catch {
            toast.error('Failed to update status');
        }
    };

    const handlePriorityChange = async (ticketId: string, newPriority: TicketPriority) => {
        try {
            await adminTicketsApi.changePriority(ticketId, newPriority);
            toast.success('Priority updated');
            loadTickets();
        } catch {
            toast.error('Failed to update priority');
        }
    };

    const handleSelectTicket = (ticketId: string, checked: boolean) => {
        const newSelection = new Set(selectedTickets);
        if (checked) {
            newSelection.add(ticketId);
        } else {
            newSelection.delete(ticketId);
        }
        setSelectedTickets(newSelection);
    };

    const handleSelectAll = (checked: boolean) => {
        if (checked) {
            setSelectedTickets(new Set(tickets.map(t => t.id)));
        } else {
            setSelectedTickets(new Set());
        }
    };

    const handleMassClose = async () => {
        if (selectedTickets.size === 0) return;
        if (!confirm(`Are you sure you want to close ${selectedTickets.size} ticket(s)?`)) return;

        setIsMassClosing(true);
        let successCount = 0;
        let failCount = 0;

        // Close tickets sequentially to avoid overwhelming the server
        for (const ticketId of selectedTickets) {
            try {
                await adminTicketsApi.changeStatus(ticketId, 'CLOSED');
                successCount++;
            } catch (error) {
                failCount++;
                console.error(`Failed to close ticket ${ticketId}:`, error);
            }
        }

        setIsMassClosing(false);
        setSelectedTickets(new Set());

        if (successCount > 0) {
            toast.success(`Closed ${successCount} ticket(s)`);
        }
        if (failCount > 0) {
            toast.error(`Failed to close ${failCount} ticket(s)`);
        }

        loadTickets();
    };

    const totalPages = Math.ceil(totalTickets / pageSize);

    // Agent assignment
    const [agents, setAgents] = useState<StaffUser[]>([]);
    const [assigningTicketId, setAssigningTicketId] = useState<string | null>(null);

    const loadAgents = async () => {
        try {
            const data = await adminTicketsApi.getAgents();
            const agentsList = (data as any).data || data;
            if (Array.isArray(agentsList)) {
                setAgents(agentsList);
            }
        } catch (error) {
            console.error('Failed to load agents:', error);
        }
    };

    useEffect(() => {
        loadAgents();
    }, []);

    const handleAssignAgent = async (ticketId: string, agentId: number | null) => {
        setAssigningTicketId(ticketId);
        try {
            if (agentId === null) {
                await adminTicketsApi.assignAgent(ticketId, 0);
            } else {
                await adminTicketsApi.assignAgent(ticketId, agentId);
            }
            toast.success('Agent assigned');
            loadTickets();
        } catch {
            toast.error('Failed to assign agent');
        } finally {
            setAssigningTicketId(null);
        }
    };

    return (
        <PageShell>
            <PageHeader
                title="Support Queue"
                description="Manage, classify, and resolve customer support tickets."
                icon={<MessageSquare className="h-5 w-5" />}
                actions={
                    <div className="flex gap-2 w-full md:w-auto">
                        {selectedTickets.size > 0 && (
                            <Button
                                onClick={handleMassClose}
                                disabled={isMassClosing}
                                variant="secondary"
                                className="px-3 bg-error-50 text-error-600 border-error-200 hover:bg-error-50"
                                title="Close selected tickets"
                            >
                                {isMassClosing ? (
                                    <RefreshCw className="w-4 h-4 animate-spin" />
                                ) : (
                                    <><Trash2 className="w-4 h-4 mr-1" /> Close ({selectedTickets.size})</>
                                )}
                            </Button>
                        )}
                        <Button onClick={loadTickets} variant="secondary" className="px-3" title="Refresh queue">
                            <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
                        </Button>
                    </div>
                }
            />

            {/* Filters Bar */}
            <div className="card p-4 flex flex-wrap gap-4 items-center justify-between">
                <div className="flex flex-wrap gap-4 items-center text-sm">
                    <div className="flex items-center text-gray-600 font-medium">
                        <Filter className="w-4 h-4 mr-2" />
                        Filters:
                    </div>

                    <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value as TicketStatus | '')}
                        className="input rounded-lg pl-3 pr-8"
                    >
                        <option value="">All Statuses</option>
                        <option value="OPEN">Open</option>
                        <option value="IN_PROGRESS">In Progress</option>
                        <option value="PENDING_CUSTOMER">Pending Customer</option>
                        <option value="RESOLVED">Resolved</option>
                        <option value="CLOSED">Closed</option>
                    </select>

                    <label className="flex items-center gap-2 cursor-pointer select-none">
                        <input
                            type="checkbox"
                            checked={unassignedFilter}
                            onChange={(e) => setUnassignedFilter(e.target.checked)}
                            className="rounded border-gray-200 text-primary-600 focus:ring-primary-500 w-4 h-4"
                        />
                        <span className="text-gray-700">Unassigned Only</span>
                    </label>

                    <Input
                        placeholder="Agent ID..."
                        value={agentIdFilter}
                        onChange={(e) => setAgentIdFilter(e.target.value)}
                        className="w-32 h-9 text-sm"
                    />

                    <div className="h-6 w-px bg-gray-300 mx-2" />

                    <select
                        value={pageSize}
                        onChange={(e) => {
                            setPageSize(Number(e.target.value));
                            setCurrentPage(1);
                        }}
                        className="input rounded-lg pl-3 pr-8"
                    >
                        <option value={5}>5 per page</option>
                        <option value={10}>10 per page</option>
                        <option value={20}>20 per page</option>
                        <option value={50}>50 per page</option>
                    </select>
                </div>
            </div>

            {/* Queue Data Grid */}
            <div className="card p-0 overflow-hidden">
                {isLoading && tickets.length === 0 ? (
                    <div className="py-20 text-center flex flex-col items-center text-gray-500">
                        <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-gray-400" />
                        Loading queue...
                    </div>
                ) : tickets.length === 0 ? (
                    <div className="py-20 text-center flex flex-col items-center">
                        <MessageSquare className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                        <h3 className="text-lg font-medium text-gray-900">Empty Inbox! 🎉</h3>
                        <p className="page-subtitle mt-1">No tickets match your current filters.</p>
                    </div>
                ) : (
                    <>
                        <table className="hidden md:table min-w-full divide-y divide-gray-200 text-sm text-left">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="auth-mono-label px-4 py-3 text-left w-10">
                                        <input
                                            type="checkbox"
                                            checked={tickets.length > 0 && selectedTickets.size === tickets.length}
                                            onChange={(e) => handleSelectAll(e.target.checked)}
                                            className="rounded border-gray-200 text-primary-600 focus:ring-primary-500 w-4 h-4"
                                        />
                                    </th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Ticket</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Client</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Status</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Priority</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Assignment</th>
                                    <th className="auth-mono-label px-6 py-3 text-left">Origin / Date</th>
                                    <th className="auth-mono-label px-6 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {tickets.map(ticket => (
                                    <tr key={ticket.id} className={cn("hover:bg-gray-50 transition-colors", selectedTickets.has(ticket.id) && "bg-primary-50")}>
                                        <td className="px-4 py-4">
                                            <input
                                                type="checkbox"
                                                checked={selectedTickets.has(ticket.id)}
                                                onChange={(e) => handleSelectTicket(ticket.id, e.target.checked)}
                                                className="rounded border-gray-200 text-primary-600 focus:ring-primary-500 w-4 h-4"
                                            />
                                        </td>
                                        <td className="px-6 py-4 max-w-[200px]">
                                            <div className="flex flex-col gap-1 w-full overflow-hidden">
                                                <span className="font-semibold text-gray-900 truncate" title={ticket.subject}>
                                                    {ticket.subject}
                                                </span>
                                                <span className="text-xs text-gray-400 font-mono">#{ticket.id.split('-')[0]}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            {ticket.customer ? (
                                                <div className="flex flex-col gap-0.5">
                                                    <div className="flex items-center gap-1.5 min-w-0">
                                                        <span className="text-sm text-gray-700 truncate font-medium">
                                                            {ticket.customer.email}
                                                        </span>
                                                        {ticket.customer.is_verified && (
                                                            <CheckCircle className="w-3.5 h-3.5 text-success-500 flex-shrink-0" />
                                                        )}
                                                    </div>
                                                    <span className="text-[10px] text-gray-400 flex items-center gap-1">
                                                        Plan: <span className="text-primary-600 font-medium">{ticket.customer.plan || 'FREE'}</span>
                                                    </span>
                                                </div>
                                            ) : (
                                                <span className="text-xs text-gray-400 italic">User #{ticket.user_id || '???'}</span>
                                            )}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <select
                                                value={ticket.status}
                                                onChange={(e) => handleStatusChange(ticket.id, e.target.value as TicketStatus)}
                                                className={cn(
                                                    "text-xs font-semibold rounded-full border-0 focus:ring-2 focus:ring-offset-1 focus:ring-primary-500 cursor-pointer text-center px-1.5 py-1",
                                                    STATUS_COLORS[ticket.status as keyof typeof STATUS_COLORS] ?? 'bg-gray-100 text-gray-600'
                                                )}
                                                style={{ WebkitAppearance: 'none', MozAppearance: 'none' }}
                                            >
                                                <option value="OPEN">OPEN</option>
                                                <option value="IN_PROGRESS">IN PROGRESS</option>
                                                <option value="PENDING_CUSTOMER">PENDING</option>
                                                <option value="RESOLVED">RESOLVED</option>
                                                <option value="CLOSED">CLOSED</option>
                                            </select>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <select
                                                value={ticket.priority}
                                                onChange={(e) => handlePriorityChange(ticket.id, e.target.value as TicketPriority)}
                                                className={cn(
                                                    "input text-xs py-1 pl-2 pr-6 cursor-pointer",
                                                    ticket.priority === 'URGENT' && "text-error-700 font-bold border-error-200 bg-error-50"
                                                )}
                                            >
                                                <option value="LOW">LOW</option>
                                                <option value="NORMAL">NORMAL</option>
                                                <option value="HIGH">HIGH</option>
                                                <option value="URGENT">URGENT</option>
                                            </select>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <select
                                                value={ticket.assigned_agent_id || ''}
                                                onChange={(e) => {
                                                    const value = e.target.value;
                                                    const agentId = value === '' ? null : Number(value);
                                                    handleAssignAgent(ticket.id, agentId);
                                                }}
                                                disabled={assigningTicketId === ticket.id}
                                                className="input text-xs py-1 pl-2 pr-6 cursor-pointer min-w-[120px]"
                                            >
                                                <option value="">Unassigned</option>
                                                {agents.map((agent) => (
                                                    <option key={agent.id} value={agent.id}>
                                                        {agent.first_name} {agent.last_name} ({agent.email})
                                                    </option>
                                                ))}
                                            </select>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-gray-500">
                                            <div className="flex flex-col gap-1">
                                                <span className="auth-mono-label bg-gray-100 text-gray-600 px-2 py-0.5 rounded w-max">
                                                    {ticket.origin || 'WEB'}
                                                </span>
                                                <span className="text-[11px]">{new Date(ticket.created_at).toLocaleDateString()}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                            <Button
                                                variant="secondary"
                                                onClick={() => navigate({ to: `/admin/tickets/${ticket.id}` })}
                                                className="h-8 py-0 px-3 text-xs"
                                            >
                                                Open
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        {/* Mobile: card list — one card per ticket. */}
                        <ul className="md:hidden flex flex-col gap-2 p-2">
                            {tickets.map(ticket => (
                                <li
                                    key={ticket.id}
                                    className={cn(
                                        "rounded-md border border-gray-200 bg-white dark:bg-white/[0.03] px-3 py-2.5 hover:bg-gray-50 transition-colors",
                                        selectedTickets.has(ticket.id) && "bg-primary-50 dark:bg-primary-500/10"
                                    )}
                                >
                                    <div className="flex items-start justify-between gap-2 mb-2">
                                        <div className="min-w-0 flex-1 flex items-start gap-2">
                                            <input
                                                type="checkbox"
                                                checked={selectedTickets.has(ticket.id)}
                                                onChange={(e) => handleSelectTicket(ticket.id, e.target.checked)}
                                                className="rounded border-gray-200 text-primary-600 focus:ring-primary-500 w-4 h-4 mt-0.5 shrink-0"
                                            />
                                            <div className="min-w-0 flex-1">
                                                <div className="text-sm font-semibold text-gray-900 truncate" title={ticket.subject}>
                                                    {ticket.subject}
                                                </div>
                                                <div className="text-[11px] text-gray-400 font-mono">#{ticket.id.split('-')[0]}</div>
                                            </div>
                                        </div>
                                        <Button
                                            variant="secondary"
                                            onClick={() => navigate({ to: `/admin/tickets/${ticket.id}` })}
                                            className="h-8 py-0 px-3 text-xs shrink-0"
                                        >
                                            Open
                                        </Button>
                                    </div>
                                    <div className="mb-2">
                                        <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Client</div>
                                        {ticket.customer ? (
                                            <div className="flex flex-col gap-0.5">
                                                <div className="flex items-center gap-1.5 min-w-0">
                                                    <span className="text-sm text-gray-700 truncate font-medium">
                                                        {ticket.customer.email}
                                                    </span>
                                                    {ticket.customer.is_verified && (
                                                        <CheckCircle className="w-3.5 h-3.5 text-success-500 dark:text-success-400 flex-shrink-0" />
                                                    )}
                                                </div>
                                                <span className="text-[10px] text-gray-400 flex items-center gap-1">
                                                    Plan: <span className="text-primary-600 dark:text-primary-300 font-medium">{ticket.customer.plan || 'FREE'}</span>
                                                </span>
                                            </div>
                                        ) : (
                                            <span className="text-xs text-gray-400 italic">User #{ticket.user_id || '???'}</span>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-3 gap-2 mb-2">
                                        <div>
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Status</div>
                                            <select
                                                value={ticket.status}
                                                onChange={(e) => handleStatusChange(ticket.id, e.target.value as TicketStatus)}
                                                className={cn(
                                                    "w-full text-xs font-semibold rounded-full border-0 focus:ring-2 focus:ring-offset-1 focus:ring-primary-500 cursor-pointer text-center px-1.5 py-1",
                                                    STATUS_COLORS[ticket.status as keyof typeof STATUS_COLORS] ?? 'bg-gray-100 text-gray-600'
                                                )}
                                                style={{ WebkitAppearance: 'none', MozAppearance: 'none' }}
                                            >
                                                <option value="OPEN">OPEN</option>
                                                <option value="IN_PROGRESS">IN PROGRESS</option>
                                                <option value="PENDING_CUSTOMER">PENDING</option>
                                                <option value="RESOLVED">RESOLVED</option>
                                                <option value="CLOSED">CLOSED</option>
                                            </select>
                                        </div>
                                        <div>
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Priority</div>
                                            <select
                                                value={ticket.priority}
                                                onChange={(e) => handlePriorityChange(ticket.id, e.target.value as TicketPriority)}
                                                className={cn(
                                                    "input w-full text-xs py-1 pl-2 pr-6 cursor-pointer",
                                                    ticket.priority === 'URGENT' && "text-error-700 dark:text-error-300 font-bold border-error-200 bg-error-50 dark:bg-error-500/10"
                                                )}
                                            >
                                                <option value="LOW">LOW</option>
                                                <option value="NORMAL">NORMAL</option>
                                                <option value="HIGH">HIGH</option>
                                                <option value="URGENT">URGENT</option>
                                            </select>
                                        </div>
                                        <div>
                                            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Origin</div>
                                            <span className="auth-mono-label bg-gray-100 text-gray-600 px-2 py-0.5 rounded inline-block">
                                                {ticket.origin || 'WEB'}
                                            </span>
                                            <div className="text-[10px] text-gray-500 tabular-nums mt-0.5">
                                                {new Date(ticket.created_at).toLocaleDateString()}
                                            </div>
                                        </div>
                                    </div>
                                    <div>
                                        <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Assignment</div>
                                        <select
                                            value={ticket.assigned_agent_id || ''}
                                            onChange={(e) => {
                                                const value = e.target.value;
                                                const agentId = value === '' ? null : Number(value);
                                                handleAssignAgent(ticket.id, agentId);
                                            }}
                                            disabled={assigningTicketId === ticket.id}
                                            className="input w-full text-xs py-1 pl-2 pr-6 cursor-pointer"
                                        >
                                            <option value="">Unassigned</option>
                                            {agents.map((agent) => (
                                                <option key={agent.id} value={agent.id}>
                                                    {agent.first_name} {agent.last_name} ({agent.email})
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </>
                )}

                {/* Pagination */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-between px-6 py-4 bg-gray-50 border-t border-gray-200">
                        <div className="text-sm text-gray-500">
                            Showing {((currentPage - 1) * pageSize) + 1} to {Math.min(currentPage * pageSize, totalTickets)} of {totalTickets} tickets
                        </div>
                        <div className="flex items-center gap-2">
                            <Button
                                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                disabled={currentPage === 1 || isLoading}
                                variant="secondary"
                                className="px-2 py-1"
                            >
                                <ChevronLeft className="w-4 h-4" />
                            </Button>
                            <span className="text-sm text-gray-600">
                                Page {currentPage} of {totalPages}
                            </span>
                            <Button
                                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                disabled={currentPage === totalPages || isLoading}
                                variant="secondary"
                                className="px-2 py-1"
                            >
                                <ChevronRight className="w-4 h-4" />
                            </Button>
                        </div>
                    </div>
                )}
            </div>
        </PageShell>
    );
}
