import { apiRequest } from '@/api/client';
import type {
    Ticket,
    AdminTicketMessageResponse,
    AdminReplyTicketRequest,
    TicketStatus,
    TicketPriority,
    TicketCategory,
    AdminCategoryCreateRequest,
    AdminCategoryUpdateRequest,
    TicketAttachmentResponse,
    StaffUser
} from '@/types/api';

export const adminTicketsApi = {
    listTickets: (params?: { status?: TicketStatus; agent_id?: string; unassigned?: boolean; page?: number; page_size?: number }) =>
        apiRequest<{ items: Ticket[]; total: number; page: number; page_size: number }>({ 
            method: 'GET', 
            url: '/admin/tickets/tickets', 
            params 
        }),

    getAgents: () =>
        apiRequest<StaffUser[]>({ method: 'GET', url: '/admin/tickets/agents' }),

    getTicket: (ticketId: string) =>
        apiRequest<Ticket>({ method: 'GET', url: `/admin/tickets/tickets/${ticketId}` }),

    getTicketMessages: (ticketId: string) =>
        apiRequest<AdminTicketMessageResponse[]>({ method: 'GET', url: `/admin/tickets/tickets/${ticketId}/messages` }),

    replyToTicket: (ticketId: string, data: AdminReplyTicketRequest) =>
        apiRequest<AdminTicketMessageResponse>({ method: 'POST', url: `/admin/tickets/tickets/${ticketId}/messages`, data }),

    uploadAttachment: (ticketId: string, messageId: string, file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return apiRequest<TicketAttachmentResponse>({
            method: 'POST',
            url: `/admin/tickets/tickets/${ticketId}/attachments`,
            params: { message_id: messageId },
            data: formData,
            headers: { 'Content-Type': 'multipart/form-data' }
        });
    },

    changeStatus: (ticketId: string, status: TicketStatus) =>
        apiRequest<void>({ method: 'PATCH', url: `/admin/tickets/tickets/${ticketId}/status`, data: { status } }),

    changePriority: (ticketId: string, priority: TicketPriority) =>
        apiRequest<void>({ method: 'PATCH', url: `/admin/tickets/tickets/${ticketId}/priority`, data: { priority } }),

    assignAgent: (ticketId: string, assignedTo: number) =>
        apiRequest<void>({ method: 'POST', url: `/admin/tickets/tickets/${ticketId}/assign`, data: { assigned_to: assignedTo } }),

    getCategories: (activeOnly: boolean = false) =>
        apiRequest<TicketCategory[]>({ method: 'GET', url: '/admin/tickets/categories', params: { active_only: activeOnly } }),

    createCategory: (data: AdminCategoryCreateRequest) =>
        apiRequest<TicketCategory>({ method: 'POST', url: '/admin/tickets/categories', data }),

    updateCategory: (categoryId: string, data: AdminCategoryUpdateRequest) =>
        apiRequest<void>({ method: 'PATCH', url: `/admin/tickets/categories/${categoryId}`, data })
};

