import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { liveChatApi } from '@livechat';
import { adminUserRepository } from '../services/index';
import type { ChatMessageResponse, SessionMetadataResponse } from '@/types/api';
import type { AdminUser } from '../types';
import { MessageSquare, Send, Loader2, AlertTriangle, Paperclip, Trash2, ArrowLeft, FileText, X, CheckCircle, Monitor, Globe, Info, Activity } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { resolveLivechatMediaUrl } from '@/utils/url';
import clsx from 'clsx';
import toast from 'react-hot-toast';

export function LiveChatAdminConsole() {
    const { id: sessionId } = useParams({ strict: false }) as { id: string };
    const navigate = useNavigate();

    const [session, setSession] = useState<SessionMetadataResponse | null>(null);
    const [userProfile, setUserProfile] = useState<AdminUser | null>(null);
    const [messages, setMessages] = useState<ChatMessageResponse[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [messageInput, setMessageInput] = useState('');
    const [isSending, setIsSending] = useState(false);
    const [isEnding, setIsEnding] = useState(false);
    const [selectedFile, setSelectedFile] = useState<File | null>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const scrollToBottom = useCallback(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, []);

    useEffect(() => {
        scrollToBottom();
    }, [messages, scrollToBottom]);

    const fetchSessionData = useCallback(async () => {
        if (!sessionId) return;
        try {
            const [sessionRes, messagesRes] = await Promise.all([
                liveChatApi.getSession(sessionId),
                liveChatApi.adminGetMessages(sessionId)
            ]);

            const sessionData = (sessionRes as any).data ?? sessionRes;
            const messagesData = (messagesRes as any).data ?? messagesRes;

            setSession(sessionData);
            if (Array.isArray(messagesData)) {
                setMessages(messagesData);
            }

            if (sessionData.status === 'ENDED') {
                // Keep the current view but stop polling? In a real app we might toast.
            }

        } catch (error) {
            console.error('Failed to fetch session data:', error);
            toast.error('Failed to load chat session.');
        } finally {
            setIsLoading(false);
        }
    }, [sessionId]);

    useEffect(() => {
        const fetchUserProfile = async () => {
            if (session?.is_authenticated_user && session?.user_id && !userProfile) {
                try {
                    const res = await adminUserRepository.get(session.user_id);
                    if (res.success && res.data) {
                        setUserProfile(res.data.user);
                    }
                } catch (err) {
                    console.error('Failed to fetch user profile:', err);
                }
            }
        };
        fetchUserProfile();
    }, [session?.is_authenticated_user, session?.user_id, userProfile]);

    useEffect(() => {
        fetchSessionData();
        const interval = setInterval(() => {
            if (session?.status !== 'ENDED') {
                fetchSessionData();
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [fetchSessionData, session?.status]);

    const handleSendMessage = async (e: React.FormEvent) => {
        e.preventDefault();
        if ((!messageInput.trim() && !selectedFile) || !sessionId || isSending || session?.status === 'ENDED') return;

        const tempMessage = messageInput;
        setMessageInput('');
        setIsSending(true);
        try {
            const res = await liveChatApi.adminSendMessage(sessionId, { message: tempMessage || '(Attached File)' });
            const msg = (res as any).data ?? res;

            if (selectedFile && msg.id) {
                await liveChatApi.uploadAttachment(sessionId, undefined, msg.id, selectedFile);
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
            }

            await fetchSessionData();
        } catch (error) {
            console.error('Failed to send message:', error);
            setMessageInput(tempMessage);
            toast.error('Failed to send message.');
        } finally {
            setIsSending(false);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const file = e.target.files[0];
            if (file.size > 5 * 1024 * 1024) {
                toast.error('File exceeds 5MB limit');
                return;
            }
            setSelectedFile(file);
        }
    };

    const handleEndSession = async () => {
        if (!sessionId || !confirm('Are you sure you want to end this chat?')) return;
        setIsEnding(true);
        try {
            await liveChatApi.adminEndSession(sessionId);
            toast.success('Session ended.');
            await fetchSessionData();
        } catch (error) {
            console.error('Failed to end session:', error);
            toast.error('Failed to end session.');
        } finally {
            setIsEnding(false);
        }
    };

    if (isLoading && !session) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[400px]">
                <Loader2 className="w-10 h-10 animate-spin text-primary-500 mb-4" />
                <p className="text-gray-500">Loading chat console...</p>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-[calc(100vh-64px)] bg-gray-50 ml-[-24px] mr-[-24px] mt-[-24px]">
            {/* Console Header */}
            <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shadow-sm z-10">
                <div className="flex items-center gap-4">
                    <button onClick={() => navigate({ to: `/admin/livechat` })} className="text-gray-400 hover:text-gray-600">
                        <ArrowLeft className="w-5 h-5" />
                    </button>
                    <div>
                        <div className="flex items-center gap-2">
                            <h2 className="text-lg font-bold text-gray-900" style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}>Session Console</h2>
                            <span className="text-xs font-mono text-gray-400">#{sessionId?.split('-')[0]}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                            {session?.is_authenticated_user ? (
                                <div className="flex items-center gap-2">
                                    <span className="text-sm font-semibold text-gray-800">
                                        {userProfile ? `${userProfile.firstName} ${userProfile.lastName}` : 'Authenticated User'}
                                    </span>
                                    {userProfile?.email && <span className="text-xs text-gray-400">({userProfile.email})</span>}
                                    <span className="flex items-center gap-1 text-[11px] font-bold text-primary-600 bg-primary-50 px-1.5 py-0.5 rounded border border-primary-100 shadow-sm animate-in fade-in zoom-in duration-300">
                                        <CheckCircle className="w-3 h-3" /> Verified Identity
                                    </span>
                                    {userProfile?.plan && (
                                        <span className="flex items-center gap-1 text-[11px] font-bold text-primary-600 bg-primary-50 px-1.5 py-0.5 rounded border border-primary-100">
                                            Plan: {userProfile.plan}
                                        </span>
                                    )}
                                </div>
                            ) : (
                                <span className="flex items-center gap-1 text-[11px] text-warning-600 bg-warning-50 px-1.5 py-0.5 rounded border border-warning-100">
                                    <AlertTriangle className="w-3 h-3" /> Unverified Guest
                                </span>
                            )}
                            <span className="text-gray-300 mx-1">|</span>
                            <span className={clsx(
                                "auth-mono-label px-1.5 py-0.5 rounded border",
                                session?.status === 'ACTIVE' ? "bg-success-50 text-success-700 border-success-200" : "bg-gray-100 text-gray-600 border-gray-200"
                            )}>
                                {session?.status}
                            </span>
                            {!!session?.initial_context?.source_url && (
                                <>
                                    <span className="text-gray-300 mx-1">|</span>
                                    <span className="text-[10px] text-gray-400">
                                        via {String(session.initial_context.source_url)}
                                    </span>
                                </>
                            )}
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {session?.status === 'ACTIVE' && (
                        <Button
                            onClick={handleEndSession}
                            disabled={isEnding}
                            variant="secondary"
                            className="bg-white border-gray-200 text-error-600 hover:bg-error-50 hover:border-error-200 flex items-center gap-2"
                        >
                            {isEnding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                            End Session
                        </Button>
                    )}
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex overflow-hidden">
                {/* Chat Messages and Input */}
                <div className="flex-1 flex flex-col min-w-0">
                    {/* Chat Messages */}
                    <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
                        {messages.length === 0 ? (
                            <div className="m-auto text-center opacity-40 flex flex-col items-center">
                                <MessageSquare className="w-12 h-12 mb-3" />
                                <p>No messages yet.</p>
                            </div>
                        ) : (
                            messages.map((msg) => {
                                const isFromAgent = msg.sender_type === 'AGENT';
                                const isSystem = msg.sender_type === 'SYSTEM';

                                if (isSystem) {
                                    return (
                                        <div key={msg.id} className="text-center my-2">
                                            <span className="text-xs italic text-gray-400 bg-gray-100 px-3 py-1 rounded-full border border-gray-200">
                                                {msg.message}
                                            </span>
                                        </div>
                                    );
                                }

                                return (
                                    <div key={msg.id} className={clsx(
                                        "flex flex-col max-w-[75%]",
                                        isFromAgent ? "self-end items-end" : "self-start items-start"
                                    )}>
                                        <div className="flex items-center gap-2 mb-1 px-1">
                                            <span className="auth-mono-label">
                                                {isFromAgent ? 'You (Agent)' : 'Client'}
                                            </span>
                                            <span className="text-[9px] text-gray-400">
                                                {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                            </span>
                                        </div>
                                        <div className={clsx(
                                            "p-3.5 rounded-xl shadow-sm text-sm whitespace-pre-wrap break-words border",
                                            isFromAgent
                                                ? "bg-primary-600 text-white border-primary-700 rounded-tr-none"
                                                : "bg-white text-gray-800 border-gray-200 rounded-tl-none"
                                        )}>
                                            {msg.message}
                                            {msg.attachments && msg.attachments.length > 0 && (
                                                <div className="mt-3 flex flex-col gap-2">
                                                    {msg.attachments.map(att => (
                                                        <a
                                                            key={att.id}
                                                            href={resolveLivechatMediaUrl(att.file_url)}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            className={clsx(
                                                                "flex flex-col gap-2 p-1 rounded overflow-hidden",
                                                                isFromAgent ? "hover:bg-primary-700/50" : "hover:bg-gray-50"
                                                            )}
                                                        >
                                                            {att.content_type.startsWith('image/') ? (
                                                                <img
                                                                    src={resolveLivechatMediaUrl(att.file_url)}
                                                                    alt={att.file_name}
                                                                    className="max-w-full h-auto rounded-lg max-h-64 object-contain bg-black/5"
                                                                />
                                                            ) : (
                                                                <div className={clsx(
                                                                    "flex items-center gap-2 p-2 rounded border text-xs font-medium",
                                                                    isFromAgent ? "bg-primary-700/50 border-primary-500 text-white" : "bg-gray-50 border-gray-200 text-primary-600"
                                                                )}>
                                                                    <FileText className="w-4 h-4 flex-shrink-0" />
                                                                    <span className="truncate">{att.file_name}</span>
                                                                </div>
                                                            )}
                                                        </a>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })
                        )}
                        <div ref={messagesEndRef} />
                    </div>

                    {/* Input Area */}
                    <div className="p-4 bg-white border-t border-gray-200 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)]">
                        {session?.status === 'ENDED' ? (
                            <div className="text-center py-2 text-gray-500 text-sm italic bg-gray-50 rounded-lg border border-dashed border-gray-200">
                                This session has ended. You can no longer send messages.
                            </div>
                        ) : (
                            <div className="max-w-5xl mx-auto">
                                {selectedFile && (
                                    <div className="flex items-center justify-between bg-primary-50 text-primary-700 px-4 py-2 rounded-t-xl text-xs border-x border-t border-primary-100">
                                        <div className="flex items-center gap-2 overflow-hidden">
                                            <FileText className="w-4 h-4 flex-shrink-0" />
                                            <span className="truncate font-medium">{selectedFile.name}</span>
                                            <span className="text-primary-400 text-[10px]">({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                                        </div>
                                        <button type="button" onClick={() => setSelectedFile(null)} className="p-1 hover:bg-primary-200 rounded text-primary-600 transition">
                                            <X className="w-4 h-4" />
                                        </button>
                                    </div>
                                )}
                                <form onSubmit={handleSendMessage} className={clsx(
                                    "flex items-center gap-3 bg-gray-100 p-2",
                                    selectedFile ? "rounded-b-xl border-x border-b border-primary-100" : "rounded-lg"
                                )}>
                                    <input
                                        type="file"
                                        ref={fileInputRef}
                                        onChange={handleFileChange}
                                        className="hidden"
                                        accept="image/*,application/pdf,.doc,.docx,.txt"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => fileInputRef.current?.click()}
                                        disabled={isSending}
                                        className="text-gray-400 hover:text-primary-600 transition-colors p-2"
                                    >
                                        <Paperclip className="w-5 h-5" />
                                    </button>
                                    <div className="flex-1 relative">
                                        <input
                                            placeholder="Type your response..."
                                            value={messageInput}
                                            onChange={(e) => setMessageInput(e.target.value)}
                                            className="w-full bg-transparent border-none focus:ring-0 rounded-lg py-2 px-4 text-sm outline-none pr-12"
                                            disabled={isSending}
                                        />
                                        <button
                                            type="submit"
                                            disabled={(!messageInput.trim() && !selectedFile) || isSending}
                                            className={clsx(
                                                "absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg transition-all",
                                                (messageInput.trim() || selectedFile) ? "bg-primary-600 text-white shadow-md hover:bg-primary-700" : "text-gray-300"
                                            )}
                                        >
                                            <Send className="w-4 h-4" />
                                        </button>
                                    </div>
                                </form>
                            </div>
                        )}
                    </div>
                </div>

                {/* Client Information Sidebar */}
                <div className="w-80 bg-white border-l border-gray-200 overflow-y-auto hidden lg:flex flex-col">
                    <div className="p-4 border-b border-gray-200 bg-gray-50/50">
                        <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2" style={{ fontFamily: 'var(--font-mono-display)' }}>
                            <Info className="w-4 h-4 text-primary-500" />
                            Client Information
                        </h3>
                    </div>

                    <div className="p-5 flex flex-col gap-6">
                        {/* Network Section */}
                        <div className="space-y-3">
                            <h4 className="auth-mono-label">Network Context</h4>
                            <div className="space-y-2">
                                <div className="flex flex-col gap-1">
                                    <span className="text-[10px] text-gray-500 flex items-center gap-1">
                                        <Globe className="w-3 h-3" /> IP Address
                                    </span>
                                    <span className="text-xs font-mono bg-primary-50 text-primary-700 px-2 py-1 rounded border border-primary-100">
                                        {String(session?.ip_address || session?.initial_context?.ip || 'Unknown')}
                                    </span>
                                </div>
                                <div className="flex flex-col gap-1">
                                    <span className="text-[10px] text-gray-500 flex items-center gap-1">
                                        <Activity className="w-3 h-3" /> Current URL
                                    </span>
                                    <p className="text-xs text-gray-700 break-all bg-gray-50 p-2 rounded border border-gray-200">
                                        {String(session?.current_url || session?.initial_context?.source_url || 'Unknown')}
                                    </p>
                                </div>
                            </div>
                        </div>

                        {/* Device Section */}
                        <div className="space-y-3">
                            <h4 className="auth-mono-label">Device and Browser</h4>
                            <div className="grid grid-cols-1 gap-3">
                                <div className="bg-gray-50 p-3 rounded-lg border border-gray-200">
                                    <span className="text-[10px] text-gray-500 block mb-1 flex items-center gap-1">
                                        <Monitor className="w-3 h-3" /> User Agent
                                    </span>
                                    <p className="text-[10px] leading-relaxed text-gray-600 font-mono break-words italic">
                                        {String(session?.user_agent || session?.initial_context?.user_agent || 'Not provided')}
                                    </p>
                                </div>

                                <div className="flex items-center justify-between text-xs py-1 border-b border-gray-50">
                                    <span className="text-gray-500">Platform</span>
                                    <span className="font-medium text-gray-900">{String((session?.initial_context?.custom as any)?.platform || 'Unknown')}</span>
                                </div>
                                <div className="flex items-center justify-between text-xs py-1 border-b border-gray-50">
                                    <span className="text-gray-500">Resolution</span>
                                    <span className="font-medium text-gray-900">{String((session?.initial_context?.custom as any)?.screen_resolution || 'Unknown')}</span>
                                </div>
                                <div className="flex items-center justify-between text-xs py-1 border-b border-gray-50">
                                    <span className="text-gray-500">Language</span>
                                    <span className="font-medium text-gray-900">{String((session?.initial_context?.custom as any)?.language || 'Unknown')}</span>
                                </div>
                                <div className="flex items-center justify-between text-xs py-1">
                                    <span className="text-gray-500">Timezone</span>
                                    <span className="font-medium text-gray-900 truncate max-w-[120px]" title={String((session?.initial_context?.custom as any)?.timezone || '')}>
                                        {String((session?.initial_context?.custom as any)?.timezone || 'Unknown')}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Session Section */}
                        <div className="mt-auto pt-6 border-t border-gray-200">
                            <div className="bg-primary-50/50 p-3 rounded-lg border border-primary-100">
                                <div className="flex items-center justify-between text-[10px] mb-2">
                                    <span className="text-primary-600 font-bold uppercase">Session ID</span>
                                    <span className="text-primary-400 font-mono">#{sessionId?.split('-')[0]}</span>
                                </div>
                                <div className="text-[10px] text-primary-700/70">
                                    Started: {session ? new Date(session.created_at).toLocaleString() : '...'}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
