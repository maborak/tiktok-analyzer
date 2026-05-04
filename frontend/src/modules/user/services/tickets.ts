import { apiRequest } from '@/api/client';
import type {
    TicketCategory,
    Ticket,
    CreateTicketRequest,
    TicketMessage,
    ReplyTicketRequest,
    TicketAttachmentResponse
} from '@/types/api';

export const userTicketsApi = {
    getCategories: () =>
        apiRequest<TicketCategory[]>({ method: 'GET', url: '/user/account/tickets/categories' }),

    createTicket: (data: CreateTicketRequest) =>
        apiRequest<Ticket>({ method: 'POST', url: '/user/account/tickets/', data }),

    listTickets: (params?: { status?: string; search?: string; page?: number; page_size?: number }) =>
        apiRequest<{ items: Ticket[]; total: number; page: number; page_size: number }>({
            method: 'GET',
            url: '/user/account/tickets',
            params
        }),

    getTicket: (ticketId: string) =>
        apiRequest<Ticket>({ method: 'GET', url: `/user/account/tickets/${ticketId}` }),

    getTicketMessages: (ticketId: string) =>
        apiRequest<TicketMessage[]>({ method: 'GET', url: `/user/account/tickets/${ticketId}/messages` }),

    replyToTicket: (ticketId: string, data: ReplyTicketRequest) =>
        apiRequest<TicketMessage>({ method: 'POST', url: `/user/account/tickets/${ticketId}/messages`, data }),

    closeTicket: (ticketId: string) =>
        apiRequest<Ticket>({ method: 'POST', url: `/user/account/tickets/${ticketId}/close` }),

    reopenTicket: (ticketId: string, message: string) =>
        apiRequest<Ticket>({ method: 'POST', url: `/user/account/tickets/${ticketId}/reopen`, data: { message } }),

    uploadAttachment: (ticketId: string, messageId: string, file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return apiRequest<TicketAttachmentResponse>({
            method: 'POST',
            url: `/user/account/tickets/${ticketId}/attachments`,
            params: { message_id: messageId },
            data: formData,
            headers: { 'Content-Type': 'multipart/form-data' }
        });
    },
};
