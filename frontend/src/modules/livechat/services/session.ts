import { apiRequest } from '@/api/client';
import type {
    LiveChatSessionResponse,
    LiveChatSessionRequest,
    LiveChatMessageRequest,
    LiveChatActivityRequest,
    ChatMessageResponse,
    SessionMetadataResponse,
    Ticket,
    LiveChatAttachmentResponse
} from '@/types/api';

export const liveChatApi = {
    initializeSession: (data: LiveChatSessionRequest = {}) =>
        apiRequest<LiveChatSessionResponse>({ method: 'POST', url: '/livechat/session', data }),

    getSession: (sessionId: string, sessionToken?: string) =>
        apiRequest<SessionMetadataResponse>({
            method: 'GET',
            url: `/livechat/session/${sessionId}`,
            headers: sessionToken ? { 'x-session-token': sessionToken } : undefined
        }),

    getMessages: (sessionId: string, sessionToken?: string) =>
        apiRequest<ChatMessageResponse[]>({
            method: 'GET',
            url: `/livechat/session/${sessionId}/messages`,
            headers: sessionToken ? { 'x-session-token': sessionToken } : undefined
        }),

    sendMessage: (sessionId: string, sessionToken: string | undefined, data: LiveChatMessageRequest) =>
        apiRequest<ChatMessageResponse>({
            method: 'POST',
            url: `/livechat/session/${sessionId}/message`,
            data,
            headers: sessionToken ? { 'x-session-token': sessionToken } : undefined
        }),

    convertSessionToTicket: (sessionId: string, subject: string, categoryId: string) =>
        apiRequest<Ticket>({ method: 'POST', url: `/livechat/session/${sessionId}/convert`, data: { subject, category_id: categoryId } }),

    uploadAttachment: (sessionId: string, sessionToken: string | undefined, messageId: string, file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return apiRequest<LiveChatAttachmentResponse>({
            method: 'POST',
            url: `/livechat/session/${sessionId}/attachments`,
            params: { message_id: messageId },
            data: formData,
            headers: {
                ...(sessionToken ? { 'x-session-token': sessionToken } : {}),
                'Content-Type': 'multipart/form-data'
            }
        });
    },

    // Agent admin endpoints
    getSessions: (params?: { status?: string; page?: number; page_size?: number }) =>
        apiRequest<SessionMetadataResponse[]>({ method: 'GET', url: '/livechat/admin/sessions', params }),

    joinSession: (sessionId: string) =>
        apiRequest<void>({ method: 'POST', url: `/livechat/admin/session/${sessionId}/join` }),

    adminGetMessages: (sessionId: string) =>
        apiRequest<ChatMessageResponse[]>({ method: 'GET', url: `/livechat/admin/session/${sessionId}/messages` }),

    adminSendMessage: (sessionId: string, data: LiveChatMessageRequest) =>
        apiRequest<ChatMessageResponse>({ method: 'POST', url: `/livechat/admin/session/${sessionId}/message`, data }),

    endSession: (sessionId: string, sessionToken?: string) =>
        apiRequest<void>({
            method: 'POST',
            url: `/livechat/session/${sessionId}/end`,
            headers: sessionToken ? { 'x-session-token': sessionToken } : undefined
        }),

    adminEndSession: (sessionId: string) =>
        apiRequest<void>({ method: 'POST', url: `/livechat/admin/session/${sessionId}/end` }),

    getStats: () =>
        apiRequest<{ waiting: number; active: number; ended: number; total: number }>({ method: 'GET', url: '/livechat/admin/stats' }),

    updateActivity: (sessionId: string, sessionToken: string | undefined, data: LiveChatActivityRequest) =>
        apiRequest<void>({
            method: 'POST',
            url: `/livechat/session/${sessionId}/activity`,
            data,
            headers: sessionToken ? { 'x-session-token': sessionToken } : undefined
        }),
};
