import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Headset, X, Send, Loader2, Paperclip, FileText, TicketIcon, MessageCircle, MinusIcon, PhoneOff, CheckCircle2, Download } from 'lucide-react';
import { liveChatApi } from '../services/session';
import { adminTicketsApi } from '@admin';
import type { ChatMessageResponse, TicketCategory } from '@/types/api';
import { resolveLivechatMediaUrl } from '@/utils/url';
import { useAuth } from '@/contexts/AuthContext';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { AuthModal } from '@auth';
import { LogIn } from 'lucide-react';
import { routes } from '@/utils/appRoutes';

type WidgetState = 'IDLE' | 'PRE_CHAT_FORM' | 'WAITING' | 'ACTIVE' | 'ENDED';

// Date separator helper
function formatMessageDate(dateStr: string): string {
    const date = new Date(dateStr);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const isYesterday = date.toDateString() === yesterday.toDateString();

    if (isToday) return 'Today';
    if (isYesterday) return 'Yesterday';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function LiveChatWidget() {
    const [widgetState, setWidgetState] = useState<WidgetState>('IDLE');
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [sessionToken, setSessionToken] = useState<string | null>(null);
    const [messages, setMessages] = useState<ChatMessageResponse[]>([]);
    const [isOpen, setIsOpen] = useState(false); // panel visibility separate from state

    // Form state for initialization
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [initialMessage, setInitialMessage] = useState('');
    const [isInitializing, setIsInitializing] = useState(false);

    // Chat state
    const [messageInput, setMessageInput] = useState('');
    const [isSending, setIsSending] = useState(false);
    const [isConverting, setIsConverting] = useState(false);
    const [linkedTicketId, setLinkedTicketId] = useState<string | null>(null);

    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Typing indicator state
    const [agentTyping, setAgentTyping] = useState(false);
    const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const lastTypingSentRef = useRef<number>(0);

    // Unread messages badge (when minimized)
    const [unreadCount, setUnreadCount] = useState(0);
    const lastSeenCountRef = useRef(0);

    // Restore session from sessionStorage on mount
    useEffect(() => {
        const storedSessionId = sessionStorage.getItem('livechat_session_id');
        const storedSessionToken = sessionStorage.getItem('livechat_session_token');
        if (storedSessionId && storedSessionToken) {
            setSessionId(storedSessionId);
            setSessionToken(storedSessionToken);

            liveChatApi.getSession(storedSessionId, storedSessionToken)
                .then(res => {
                    const data = (res as any).data ?? res;
                    if (data.status === 'ENDED') {
                        setWidgetState('ENDED');
                    } else if (data.status === 'ACTIVE') {
                        setWidgetState('ACTIVE');
                    } else if (data.status === 'WAITING') {
                        setWidgetState('WAITING');
                    }
                })
                .catch(() => clearSession());
        }
    }, []);

    // Scroll to bottom when messages change
    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages, widgetState]);

    // Track unread when panel is closed
    useEffect(() => {
        if (isOpen) {
            setUnreadCount(0);
            lastSeenCountRef.current = messages.length;
        } else if (messages.length > lastSeenCountRef.current) {
            const newMsgs = messages.slice(lastSeenCountRef.current);
            const agentMsgs = newMsgs.filter(m => m.sender_type === 'AGENT' || m.sender_type === 'SYSTEM');
            if (agentMsgs.length > 0) {
                setUnreadCount(prev => prev + agentMsgs.length);
            }
        }
    }, [messages, isOpen]);

    // Polling effect
    useEffect(() => {
        let intervalId: ReturnType<typeof setInterval>;

        const fetchMessages = async () => {
            if (!sessionId || !sessionToken || widgetState === 'IDLE' || widgetState === 'PRE_CHAT_FORM' || widgetState === 'ENDED') return;
            try {
                const response = await liveChatApi.getMessages(sessionId, sessionToken);
                const msgs = (response as any).data ?? response;
                if (Array.isArray(msgs)) {
                    setMessages(msgs);

                    if (widgetState === 'WAITING') {
                        const hasAgentOrSystem = msgs.some((m: ChatMessageResponse) =>
                            m.sender_type === 'AGENT' || m.sender_type === 'SYSTEM'
                        );
                        if (hasAgentOrSystem) {
                            setWidgetState('ACTIVE');
                        }
                    }
                }

                if (Math.random() > 0.5) {
                    const sessionRes = await liveChatApi.getSession(sessionId, sessionToken);
                    const sessionInfo = (sessionRes as any).data ?? sessionRes;
                    if (sessionInfo.status === 'ENDED') {
                        if (sessionInfo.ticket_id) setLinkedTicketId(sessionInfo.ticket_id);
                        setWidgetState('ENDED');
                        sessionStorage.removeItem('livechat_session_id');
                        sessionStorage.removeItem('livechat_session_token');
                    }
                    if (sessionInfo.agent_typing !== undefined) {
                        setAgentTyping(sessionInfo.agent_typing);
                    }
                }
            } catch (error: any) {
                console.error('Failed to fetch messages', error);
                if (error?.response?.status === 401 || error?.response?.status === 404) {
                    clearSession();
                }
            }
        };

        if ((widgetState === 'WAITING' || widgetState === 'ACTIVE') && sessionId && sessionToken) {
            fetchMessages();
            intervalId = setInterval(fetchMessages, 3000);
        }

        return () => {
            if (intervalId) clearInterval(intervalId);
        };
    }, [widgetState, sessionId, sessionToken]);

    const clearSession = () => {
        setSessionId(null);
        setSessionToken(null);
        setMessages([]);
        setLinkedTicketId(null);
        setUnreadCount(0);
        lastSeenCountRef.current = 0;
        sessionStorage.removeItem('livechat_session_id');
        sessionStorage.removeItem('livechat_session_token');
        setWidgetState('IDLE');
        setIsOpen(false);
    };

    const startNewChat = () => {
        setSessionId(null);
        setSessionToken(null);
        setMessages([]);
        setLinkedTicketId(null);
        setInitialMessage('');
        setUnreadCount(0);
        lastSeenCountRef.current = 0;
        sessionStorage.removeItem('livechat_session_id');
        sessionStorage.removeItem('livechat_session_token');
        setWidgetState('PRE_CHAT_FORM');
    };

    const { user, isAuthenticated, isAdmin } = useAuth();

    // Login modal state (guest pre-chat)
    const [showLoginModal, setShowLoginModal] = useState(false);

    // Convert-to-ticket modal state (admin only)
    const [showConvertModal, setShowConvertModal] = useState(false);
    const [convertSubject, setConvertSubject] = useState('Converted from Live Chat');
    const [convertCategoryId, setConvertCategoryId] = useState('');
    const [categories, setCategories] = useState<TicketCategory[]>([]);

    // Auto-update form state from auth if it changes
    useEffect(() => {
        if (isAuthenticated && user) {
            setName(user.fullName || '');
            setEmail(user.email || '');
        }
    }, [user, isAuthenticated]);

    const handleLoginSuccess = () => {
        setShowLoginModal(false);
        setWidgetState('PRE_CHAT_FORM');
    };

    const handleEndChat = async () => {
        if (!sessionId || !sessionToken) {
            setWidgetState('IDLE');
            setIsOpen(false);
            return;
        }

        try {
            await liveChatApi.endSession(sessionId, sessionToken);
        } catch (error) {
            console.error('Failed to end session via API:', error);
        } finally {
            setWidgetState('ENDED');
            sessionStorage.removeItem('livechat_session_id');
            sessionStorage.removeItem('livechat_session_token');
        }
    };

    const handleExportPDF = () => {
        if (messages.length === 0) return;

        const formatTime = (dateStr: string) =>
            new Date(dateStr).toLocaleString(undefined, {
                year: 'numeric', month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });

        const lines = messages.map(msg => {
            const sender = msg.sender_type === 'USER' ? 'You' : msg.sender_type === 'SYSTEM' ? 'System' : 'Support Agent';
            const time = formatTime(msg.created_at);
            const attachments = msg.attachments?.length
                ? `\n    📎 ${msg.attachments.map(a => a.file_name).join(', ')}`
                : '';
            return `[${time}] ${sender}:\n    ${msg.message || '(no text)'}${attachments}`;
        }).join('\n\n');

        const header = `Live Chat Transcript — Session ${sessionId || 'N/A'}\nExported: ${new Date().toLocaleString()}\n${'─'.repeat(50)}\n\n`;

        const printWindow = window.open('', '_blank');
        if (!printWindow) {
            toast.error('Pop-up blocked — please allow pop-ups to export');
            return;
        }
        printWindow.document.write(`<!DOCTYPE html><html><head><title>Chat Transcript</title><style>
            body { font-family: 'Segoe UI', system-ui, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; color: #1f2937; font-size: 14px; line-height: 1.6; }
            pre { white-space: pre-wrap; word-break: break-word; }
            h1 { font-size: 18px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }
            @media print { body { margin: 20px; } }
        </style></head><body>
            <h1>Live Chat Transcript</h1>
            <p style="color:#6b7280;font-size:12px;">Session: ${sessionId || 'N/A'} &bull; Exported: ${new Date().toLocaleString()}</p>
            <pre>${header}${lines.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
        </body></html>`);
        printWindow.document.close();
        printWindow.print();
    };

    const handleOpenTicket = () => {
        // Only authenticated users can create tickets from the widget.
        // Guests have no contact-form page in this build; the button is hidden for them.
        if (!isAuthenticated) return;

        // Pass prefill data through sessionStorage so the Tickets page can
        // auto-open its "New Ticket" modal with the chat context already filled in.
        sessionStorage.setItem('ticket_prefill', JSON.stringify({
            subject: `Live Chat #${sessionId || ''}`,
            message: messages
                .filter((m) => m.message)
                .map((m) => `[${m.sender_type}] ${m.message}`)
                .join('\n'),
            auto_open: true,
        }));
        window.location.href = routes.account.tickets;
        setIsOpen(false);
    };

    const handleStartChat = async (e: React.FormEvent) => {
        e.preventDefault();
        await initializeChat(name, email, initialMessage);
    };

    const initializeChat = async (userName: string, userEmail: string, firstMessage?: string) => {
        setIsInitializing(true);
        try {
            const response = await liveChatApi.initializeSession({
                name: userName || undefined,
                email: userEmail || undefined,
                initial_message: firstMessage?.trim() || undefined,
                source_url: window.location.href,
                client_metadata: {
                    user_agent: navigator.userAgent,
                    screen_resolution: `${window.screen.width}x${window.screen.height}`,
                    language: navigator.language,
                    platform: navigator.platform,
                    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                },
            });

            const data = (response as any).data ?? response;
            if (data.id && data.session_token) {
                setSessionId(data.id);
                setSessionToken(data.session_token);
                sessionStorage.setItem('livechat_session_id', data.id);
                sessionStorage.setItem('livechat_session_token', data.session_token);
                setWidgetState('WAITING');
            }
        } catch (error) {
            console.error('Failed to initialize session', error);
            toast.error('Failed to start chat. Please try again.');
        } finally {
            setIsInitializing(false);
        }
    };

    const lastSentUrlRef = useRef<string>(window.location.href);
    const lastUrlRef = useRef<string>(window.location.href);

    const sendTypingActivity = useCallback(async (isTyping: boolean) => {
        if (!sessionId || !sessionToken) return;
        const now = Date.now();
        if (now - lastTypingSentRef.current < 1000) return;
        lastTypingSentRef.current = now;
        try {
            await liveChatApi.updateActivity(sessionId, sessionToken, {
                is_typing: isTyping,
                current_url: window.location.href
            });
        } catch (error) {
            console.debug('Failed to send typing activity:', error);
        }
    }, [sessionId, sessionToken]);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setMessageInput(e.target.value);
        sendTypingActivity(true);
        if (typingTimeoutRef.current) {
            clearTimeout(typingTimeoutRef.current);
        }
        typingTimeoutRef.current = setTimeout(() => {
            sendTypingActivity(false);
        }, 2000);
    };

    // URL change detection
    useEffect(() => {
        if (!sessionId || !sessionToken || widgetState !== 'ACTIVE') return;
        lastUrlRef.current = window.location.href;
        const checkUrlChange = () => {
            const currentUrl = window.location.href;
            if (currentUrl !== lastUrlRef.current) {
                lastUrlRef.current = currentUrl;
                liveChatApi.updateActivity(sessionId, sessionToken, {
                    current_url: currentUrl,
                    is_typing: false
                }).catch(() => {});
            }
        };
        const urlInterval = setInterval(checkUrlChange, 2000);
        const handlePopState = () => {
            const currentUrl = window.location.href;
            lastUrlRef.current = currentUrl;
            liveChatApi.updateActivity(sessionId, sessionToken, {
                current_url: currentUrl,
                is_typing: false
            }).catch(() => {});
        };
        window.addEventListener('popstate', handlePopState);
        return () => {
            clearInterval(urlInterval);
            window.removeEventListener('popstate', handlePopState);
        };
    }, [sessionId, sessionToken, widgetState]);

    // Cleanup typing on unmount
    useEffect(() => {
        return () => {
            if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
            if (sessionId && sessionToken && lastTypingSentRef.current > 0) {
                liveChatApi.updateActivity(sessionId, sessionToken, {
                    is_typing: false,
                    current_url: window.location.href
                }).catch(() => {});
            }
        };
    }, [sessionId, sessionToken]);

    const handleSendMessage = async (e: React.FormEvent) => {
        e.preventDefault();
        if ((!messageInput.trim() && !selectedFile) || !sessionId || !sessionToken || isSending) return;

        const tempMessage = messageInput;
        setMessageInput('');
        setIsSending(true);

        const optimisticMsg: ChatMessageResponse = {
            id: `optimistic-${Date.now()}`,
            sender_type: 'USER',
            message: tempMessage || '(Attached File)',
            created_at: new Date().toISOString(),
            sender_id: null,
        };
        setMessages(prev => [...prev, optimisticMsg]);

        try {
            const currentUrl = window.location.href;
            const context = currentUrl !== lastSentUrlRef.current ? { current_url: currentUrl } : undefined;
            const res = await liveChatApi.sendMessage(sessionId, sessionToken, {
                message: tempMessage || '(Attached File)',
                context,
            });
            lastSentUrlRef.current = currentUrl;
            const msg = (res as any).data ?? res;

            if (selectedFile && msg.id) {
                await liveChatApi.uploadAttachment(sessionId, sessionToken, msg.id, selectedFile);
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
            }

            const response = await liveChatApi.getMessages(sessionId, sessionToken);
            const msgs = (response as any).data ?? response;
            if (Array.isArray(msgs)) setMessages(msgs);
        } catch (error) {
            console.error('Failed to send message', error);
            setMessageInput(tempMessage);
            setMessages(prev => prev.filter(m => m.id !== optimisticMsg.id));
        } finally {
            setIsSending(false);
        }
    };

    const handleOpenConvertModal = async () => {
        setShowConvertModal(true);
        setConvertSubject('Converted from Live Chat');
        setConvertCategoryId('');
        try {
            const cats = await adminTicketsApi.getCategories(true);
            setCategories(cats);
            if (cats.length > 0) setConvertCategoryId(cats[0].id);
        } catch {
            setCategories([]);
        }
    };

    const handleConvertToTicket = async () => {
        if (!sessionId) return;
        setIsConverting(true);
        try {
            const res = await liveChatApi.convertSessionToTicket(sessionId, convertSubject, convertCategoryId);
            const data = (res as any).data ?? res;
            if (data?.ticket_id) setLinkedTicketId(data.ticket_id);
            toast.success('Chat converted to support ticket!');
            setShowConvertModal(false);
            setWidgetState('ENDED');
            sessionStorage.removeItem('livechat_session_id');
            sessionStorage.removeItem('livechat_session_token');
        } catch (error) {
            console.error('Failed to convert session', error);
            toast.error('Failed to convert to ticket. Please try again later.');
        } finally {
            setIsConverting(false);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const file = e.target.files[0];
            if (file.size > 5 * 1024 * 1024) {
                toast.error('File exceeds the 5MB limit');
                return;
            }
            setSelectedFile(file);
        }
    };

    const handleTogglePanel = () => {
        if (!isOpen) {
            if (widgetState === 'IDLE') {
                setWidgetState('PRE_CHAT_FORM');
            }
            setIsOpen(true);
            setUnreadCount(0);
            lastSeenCountRef.current = messages.length;
        } else {
            setIsOpen(false);
        }
    };

    // Status indicator for header
    const headerSubtitle = (() => {
        switch (widgetState) {
            case 'PRE_CHAT_FORM': return 'Start a conversation';
            case 'WAITING': return 'Connecting with an agent...';
            case 'ACTIVE': return agentTyping ? 'Agent is typing...' : 'Connected';
            case 'ENDED': return 'Session ended';
            default: return 'We typically respond in minutes';
        }
    })();

    const statusColor = (() => {
        switch (widgetState) {
            case 'ACTIVE': return 'bg-success-400';
            case 'WAITING': return 'bg-warning-400 animate-pulse';
            case 'ENDED': return 'bg-gray-400';
            default: return 'bg-gray-400';
        }
    })();

    // Has active session (for bubble indicator)
    const hasActiveSession = widgetState === 'WAITING' || widgetState === 'ACTIVE';

    const renderMessage = (msg: ChatMessageResponse, index: number) => {
        if (msg.sender_type === 'SYSTEM') {
            return (
                <div key={msg.id} className="flex justify-center my-1.5">
                    <span className="text-[11px] text-gray-500 italic px-3 py-1 bg-gray-100 rounded-full">
                        {msg.message}
                    </span>
                </div>
            );
        }

        // Date separator
        const showDateSep = index === 0 || (
            formatMessageDate(msg.created_at) !== formatMessageDate(messages[index - 1].created_at)
        );

        const isUser = msg.sender_type === 'USER';
        return (
            <React.Fragment key={msg.id}>
                {showDateSep && (
                    <div className="flex justify-center my-2">
                        <span className="text-[10px] text-gray-400 font-medium px-3 py-0.5 bg-gray-100 rounded-full">
                            {formatMessageDate(msg.created_at)}
                        </span>
                    </div>
                )}
                <div
                    className={clsx('max-w-[82%] rounded-xl px-3.5 py-2.5 transition-opacity', isUser
                        ? 'text-white self-end rounded-br-sm'
                        : 'bg-white text-gray-800 self-start border border-gray-200 rounded-bl-sm shadow-sm',
                        msg.id.startsWith('optimistic-') && 'opacity-70'
                    )}
                    {...(isUser ? { style: { backgroundColor: '#171717' } } : {})}
                >
                    {!isUser && (
                        <div className="text-[10px] font-semibold text-gray-700 mb-0.5 flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-success-400 inline-block" />
                            Support Agent
                        </div>
                    )}
                    <div className="text-[13px] leading-relaxed break-words whitespace-pre-wrap">{msg.message}</div>

                    {msg.attachments && msg.attachments.length > 0 && (
                        <div className="mt-2 flex flex-col gap-1.5">
                            {msg.attachments.map(att => (
                                <a
                                    key={att.id}
                                    href={resolveLivechatMediaUrl(att.file_url, sessionToken)}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={clsx(
                                        "flex flex-col gap-1 rounded-lg overflow-hidden transition-colors",
                                        isUser ? "hover:bg-white/10" : "hover:bg-gray-50"
                                    )}
                                >
                                    {att.content_type.startsWith('image/') ? (
                                        <img
                                            src={resolveLivechatMediaUrl(att.file_url, sessionToken)}
                                            alt={att.file_name}
                                            className="max-w-full h-auto rounded-lg max-h-44 object-contain bg-black/5"
                                            loading="lazy"
                                        />
                                    ) : (
                                        <div className={clsx(
                                            "flex items-center gap-2 p-2 rounded-lg border text-xs font-medium",
                                            isUser ? "bg-white/10 border-white/20 text-white" : "bg-gray-50 border-gray-200 text-gray-700"
                                        )}>
                                            <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                                            <span className="truncate">{att.file_name}</span>
                                        </div>
                                    )}
                                </a>
                            ))}
                        </div>
                    )}

                    <div className={clsx('text-[10px] mt-1 text-right', isUser ? 'text-white/60' : 'text-gray-400')}>
                        {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                </div>
            </React.Fragment>
        );
    };

    return (
        <div className="fixed bottom-5 right-5 z-50">
            {/* Floating Action Button */}
            <button
                onClick={handleTogglePanel}
                className={clsx(
                    "w-14 h-14 rounded-full shadow-lg hover:shadow-xl transition-all flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 relative hover:opacity-90",
                    isOpen
                        ? "scale-90"
                        : "hover:scale-105"
                )}
                style={{ backgroundColor: isOpen ? '#262626' : '#171717' }}
                aria-label={isOpen ? "Minimize chat" : "Open support chat"}
            >
                {isOpen ? (
                    <MinusIcon size={22} className="text-white" />
                ) : (
                    <Headset size={24} strokeWidth={1.8} className="text-white" />
                )}

                {/* Unread badge */}
                {!isOpen && unreadCount > 0 && (
                    <span className="absolute -top-1 -right-1 w-5 h-5 bg-error-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center ring-2 ring-white animate-bounce">
                        {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                )}

                {/* Active session pulse */}
                {!isOpen && hasActiveSession && unreadCount === 0 && (
                    <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-success-400 rounded-full ring-2 ring-white">
                        <span className="absolute inset-0 bg-success-400 rounded-full animate-ping opacity-75" />
                    </span>
                )}
            </button>

            {/* Chat Panel */}
            {isOpen && (
                <div className="absolute bottom-[72px] right-0 w-[360px] sm:w-[400px] bg-white rounded-xl shadow-2xl border border-gray-200/60 flex flex-col overflow-hidden animate-in slide-in-from-bottom-2" style={{ height: 'min(calc(100vh - 120px), 580px)' }}>
                    {/* Header */}
                    <div className="text-white px-4 py-3 flex justify-between items-center gap-2 flex-shrink-0" style={{ backgroundColor: '#171717' }}>
                        <div className="min-w-0 flex items-center gap-3">
                            <div className="w-9 h-9 rounded-full bg-white/15 flex items-center justify-center flex-shrink-0">
                                <Headset size={18} strokeWidth={1.8} />
                            </div>
                            <div className="min-w-0">
                                <h3 className="font-semibold text-[15px] leading-tight">Live Support</h3>
                                <div className="flex items-center gap-1.5 mt-0.5">
                                    <span className={clsx("w-1.5 h-1.5 rounded-full flex-shrink-0", statusColor)} />
                                    <p className="text-gray-400 text-[11px] truncate">{headerSubtitle}</p>
                                </div>
                            </div>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                            {widgetState === 'ACTIVE' && isAdmin && (
                                <button
                                    onClick={handleOpenConvertModal}
                                    disabled={isConverting}
                                    className="text-[11px] bg-white/15 hover:bg-white/25 text-white px-2 py-1 rounded-md flex items-center gap-1 font-medium transition-colors disabled:opacity-50"
                                    title="Convert to Support Ticket"
                                >
                                    {isConverting ? <Loader2 className="w-3 h-3 animate-spin" /> : <TicketIcon className="w-3 h-3" />}
                                    <span className="hidden sm:inline">Ticket</span>
                                </button>
                            )}
                            {(widgetState === 'ACTIVE' || widgetState === 'WAITING') && (
                                <button
                                    onClick={handleEndChat}
                                    className="p-1.5 hover:bg-white/15 rounded-md transition-colors"
                                    aria-label="End chat"
                                    title="End session"
                                >
                                    <PhoneOff size={15} />
                                </button>
                            )}
                            <button
                                onClick={() => widgetState === 'ENDED' ? clearSession() : setIsOpen(false)}
                                className="p-1.5 hover:bg-white/15 rounded-md transition-colors"
                                aria-label="Close panel"
                            >
                                <X size={16} />
                            </button>
                        </div>
                    </div>

                    {/* PRE_CHAT_FORM */}
                    {widgetState === 'PRE_CHAT_FORM' && (
                        <div className="flex-1 flex flex-col bg-gray-50 overflow-y-auto">
                            {/* Welcome banner */}
                            <div className="bg-gray-50 px-6 pt-8 pb-4 text-center">
                                <div className="w-14 h-14 rounded-full bg-gray-100 flex items-center justify-center mx-auto mb-3">
                                    <MessageCircle className="w-7 h-7 text-gray-600" />
                                </div>
                                {isAuthenticated && user ? (
                                    <>
                                        <h4 className="text-gray-900 font-semibold text-base">Hi{user.fullName ? `, ${user.fullName.split(' ')[0]}` : ''}!</h4>
                                        <p className="page-subtitle mt-1">How can we help you today?</p>
                                    </>
                                ) : (
                                    <>
                                        <h4 className="text-gray-900 font-semibold text-base">Welcome!</h4>
                                        <p className="page-subtitle mt-1">Sign in or chat as a guest.</p>
                                    </>
                                )}
                            </div>

                            <div className="px-5 pb-6 pt-2 flex flex-col gap-4">
                                {isAuthenticated && user ? (
                                    <form onSubmit={handleStartChat} className="space-y-4">
                                        <div>
                                            <label className="block text-xs font-medium text-gray-600 mb-1.5">What do you need help with?</label>
                                            <textarea
                                                placeholder="Describe your issue or question..."
                                                value={initialMessage}
                                                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInitialMessage(e.target.value)}
                                                className="block w-full rounded-lg border border-gray-200 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-200 text-sm p-3 min-h-[110px] resize-none bg-white transition-shadow"
                                                required
                                                autoFocus
                                            />
                                        </div>
                                        <Button type="submit" className="w-full rounded-lg h-11 text-sm font-medium text-white hover:opacity-90" style={{ backgroundColor: '#171717' }} disabled={isInitializing || !initialMessage.trim()}>
                                            {isInitializing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                                            Start Chat
                                        </Button>
                                    </form>
                                ) : (
                                    <>
                                        <button
                                            onClick={() => setShowLoginModal(true)}
                                            className="w-full flex items-center justify-center gap-2 h-11 px-4 text-white rounded-lg hover:opacity-90 transition-colors text-sm font-medium shadow-sm"
                                            style={{ backgroundColor: '#171717' }}
                                        >
                                            <LogIn className="w-4 h-4" />
                                            Sign in to chat
                                        </button>

                                        <div className="flex items-center gap-3 my-0.5">
                                            <div className="flex-1 h-px bg-gray-200" />
                                            <span className="auth-mono-label">or as guest</span>
                                            <div className="flex-1 h-px bg-gray-200" />
                                        </div>

                                        <form onSubmit={handleStartChat} className="space-y-3">
                                            <div className="grid grid-cols-2 gap-2.5">
                                                <div>
                                                    <label className="block text-[11px] font-medium text-gray-500 mb-1">Name</label>
                                                    <Input
                                                        placeholder="John"
                                                        value={name}
                                                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setName(e.target.value)}
                                                        className="w-full text-sm h-9 rounded-lg"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-[11px] font-medium text-gray-500 mb-1">Email</label>
                                                    <Input
                                                        type="email"
                                                        placeholder="john@email.com"
                                                        value={email}
                                                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEmail(e.target.value)}
                                                        className="w-full text-sm h-9 rounded-lg"
                                                    />
                                                </div>
                                            </div>
                                            <div>
                                                <label className="block text-[11px] font-medium text-gray-500 mb-1">Message <span className="text-error-400">*</span></label>
                                                <textarea
                                                    placeholder="How can we help you?"
                                                    value={initialMessage}
                                                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInitialMessage(e.target.value)}
                                                    className="block w-full rounded-lg border border-gray-200 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-200 text-sm p-3 min-h-[70px] resize-none bg-white transition-shadow"
                                                    required
                                                />
                                            </div>
                                            <Button type="submit" className="w-full rounded-lg h-10 text-sm text-white hover:opacity-90" style={{ backgroundColor: '#171717' }} disabled={isInitializing || !initialMessage.trim()}>
                                                {isInitializing ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <MessageCircle className="w-4 h-4 mr-2" />}
                                                Start as Guest
                                            </Button>
                                        </form>
                                    </>
                                )}
                            </div>
                        </div>
                    )}

                    {/* WAITING */}
                    {widgetState === 'WAITING' && (
                        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-8 bg-gray-50">
                            <div className="relative">
                                <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center">
                                    <Headset className="w-7 h-7 text-gray-700" />
                                </div>
                                <span className="absolute bottom-0 right-0 w-5 h-5 bg-warning-400 rounded-full flex items-center justify-center ring-2 ring-gray-50">
                                    <Loader2 className="w-3 h-3 text-white animate-spin" />
                                </span>
                            </div>
                            <p className="text-sm text-gray-700 font-medium text-center mt-1">Finding an available agent...</p>
                            <p className="text-xs text-gray-400 text-center">Typical wait time is less than 2 minutes</p>

                            {initialMessage && (
                                <div className="w-full mt-3 p-3 bg-white rounded-lg border border-gray-200 shadow-sm">
                                    <p className="auth-mono-label mb-1">Your message</p>
                                    <p className="text-xs text-gray-600 line-clamp-3">{initialMessage}</p>
                                </div>
                            )}
                        </div>
                    )}

                    {/* ACTIVE */}
                    {widgetState === 'ACTIVE' && (
                        <div className="flex-1 flex flex-col bg-gray-50 overflow-hidden">
                            {/* Messages */}
                            <div className="flex-1 px-3 py-3 overflow-y-auto flex flex-col gap-2">
                                {messages.length === 0 ? (
                                    <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-2">
                                        <MessageCircle className="w-8 h-8 opacity-20" />
                                        <p className="text-xs text-center">Send a message to get started.</p>
                                    </div>
                                ) : (
                                    messages.map((msg, i) => renderMessage(msg, i))
                                )}

                                {agentTyping && (
                                    <div className="flex items-center gap-2 self-start bg-white rounded-xl px-3.5 py-2 rounded-bl-sm border border-gray-200 shadow-sm">
                                        <div className="flex gap-0.5">
                                            <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                            <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                            <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                                        </div>
                                        <span className="text-[11px] text-gray-400">typing</span>
                                    </div>
                                )}

                                <div ref={messagesEndRef} />
                            </div>

                            {/* Input Area */}
                            <div className="px-3 py-2.5 bg-white border-t border-gray-200">
                                {selectedFile && (
                                    <div className="flex items-center justify-between bg-gray-100 text-gray-700 px-3 py-1.5 rounded-lg text-xs mb-2 border border-gray-200">
                                        <div className="flex items-center gap-1.5 overflow-hidden">
                                            <FileText className="w-3.5 h-3.5 flex-shrink-0" />
                                            <span className="truncate max-w-[220px]">{selectedFile.name}</span>
                                        </div>
                                        <button type="button" onClick={() => { setSelectedFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; }} className="p-0.5 hover:bg-gray-200 rounded text-gray-500 transition ml-2">
                                            <X className="w-3 h-3" />
                                        </button>
                                    </div>
                                )}
                                <form onSubmit={handleSendMessage} className="flex gap-1.5 items-center">
                                    <input type="file" ref={fileInputRef} onChange={handleFileChange} className="hidden" accept="image/jpeg,image/png,application/pdf" />
                                    <button
                                        type="button"
                                        onClick={() => fileInputRef.current?.click()}
                                        disabled={isSending}
                                        className="text-gray-400 hover:text-gray-700 transition-colors disabled:opacity-50 p-1.5 rounded-full hover:bg-gray-50 flex-shrink-0"
                                        title="Attach file (JPEG, PNG, PDF — max 5MB)"
                                    >
                                        <Paperclip className="w-[18px] h-[18px]" />
                                    </button>
                                    <input
                                        type="text"
                                        value={messageInput}
                                        onChange={handleInputChange}
                                        placeholder="Type a message..."
                                        className="flex-1 rounded-full border border-gray-200 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-200 focus:border-gray-400 placeholder:text-gray-400 bg-white min-w-0 transition-shadow"
                                        disabled={isSending}
                                    />
                                    <button
                                        type="submit"
                                        disabled={(!messageInput.trim() && !selectedFile) || isSending}
                                        className="text-white rounded-full p-2 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition-colors flex-shrink-0"
                                        style={{ backgroundColor: '#171717' }}
                                    >
                                        {isSending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} className="translate-x-[1px]" />}
                                    </button>
                                </form>
                            </div>
                        </div>
                    )}

                    {/* ENDED — show chat history + actions */}
                    {widgetState === 'ENDED' && (
                        <div className="flex-1 flex flex-col overflow-hidden">
                            {/* Ended banner */}
                            <div className="flex items-center gap-2 px-4 py-2.5 bg-gray-50 border-b border-gray-200 flex-shrink-0">
                                <CheckCircle2 className="w-4 h-4 text-success-500 flex-shrink-0" />
                                <span className="text-xs font-medium text-gray-600">
                                    Chat ended {linkedTicketId ? '— a support ticket was created' : '— thank you for chatting with us!'}
                                </span>
                            </div>

                            {/* Scrollable message history (read-only) */}
                            <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-1.5 bg-gray-50">
                                {messages.length > 0 ? (
                                    messages.map((msg, i) => renderMessage(msg, i))
                                ) : (
                                    <div className="flex-1 flex items-center justify-center text-sm text-gray-400">No messages</div>
                                )}
                            </div>

                            {/* Action bar */}
                            <div className="flex-shrink-0 border-t border-gray-200 bg-white px-3 py-3 space-y-2">
                                <div className="flex gap-2">
                                    <button
                                        onClick={handleExportPDF}
                                        className="flex-1 text-xs text-gray-600 border border-gray-200 h-9 rounded-lg hover:bg-gray-50 transition-colors font-medium flex items-center justify-center gap-1.5"
                                        title="Export chat transcript"
                                    >
                                        <Download className="w-3.5 h-3.5" /> Export PDF
                                    </button>
                                    {linkedTicketId ? (
                                        <a
                                            href={routes.account.ticketDetail(linkedTicketId)}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="flex-1 text-xs text-gray-700 border border-gray-200 bg-white h-9 rounded-lg hover:bg-gray-50 transition-colors font-medium flex items-center justify-center gap-1.5"
                                        >
                                            <TicketIcon className="w-3.5 h-3.5" /> View Ticket
                                        </a>
                                    ) : isAuthenticated ? (
                                        <button
                                            onClick={handleOpenTicket}
                                            className="flex-1 text-xs text-gray-700 border border-gray-200 bg-white h-9 rounded-lg hover:bg-gray-50 transition-colors font-medium flex items-center justify-center gap-1.5"
                                        >
                                            <TicketIcon className="w-3.5 h-3.5" /> Open Ticket
                                        </button>
                                    ) : null}
                                </div>
                                <button
                                    onClick={startNewChat}
                                    className="w-full text-xs text-gray-500 h-8 rounded-lg hover:bg-gray-50 transition-colors font-medium flex items-center justify-center gap-1.5"
                                >
                                    <MessageCircle className="w-3.5 h-3.5" /> Start New Conversation
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Convert-to-Ticket Modal (admin only) */}
            <Modal
                isOpen={showConvertModal}
                title="Save as Support Ticket"
                onClose={() => setShowConvertModal(false)}
                className="max-w-md"
                footer={
                    <div className="flex justify-end gap-2">
                        <Button variant="secondary" onClick={() => setShowConvertModal(false)}>Cancel</Button>
                        <Button onClick={handleConvertToTicket} disabled={isConverting || !convertSubject.trim()}>
                            {isConverting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
                            Create Ticket
                        </Button>
                    </div>
                }
            >
                <div className="space-y-4">
                    <div>
                        <label className="label">Subject</label>
                        <Input
                            value={convertSubject}
                            onChange={(e) => setConvertSubject(e.target.value)}
                            placeholder="Ticket subject"
                        />
                    </div>
                    {categories.length > 0 && (
                        <div>
                            <label className="label">Category</label>
                            <Select
                                value={convertCategoryId}
                                onChange={(e) => setConvertCategoryId(e.target.value)}
                                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                            >
                                {categories.map(cat => (
                                    <option key={cat.id} value={cat.id}>{cat.name}</option>
                                ))}
                            </Select>
                        </div>
                    )}
                </div>
            </Modal>

            {/* Login Modal (guest pre-chat) */}
            <AuthModal
                isOpen={showLoginModal}
                onClose={() => setShowLoginModal(false)}
                initialView="login"
                onSuccess={handleLoginSuccess}
                loginOnly
            />
        </div>
    );
}
