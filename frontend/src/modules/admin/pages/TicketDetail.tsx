import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { MessageSquare, ArrowLeft, Send, RefreshCw, ShieldAlert, Paperclip, X, FileText, Download, UserCheck, UserX, User, Globe, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';

import { adminTicketsApi } from '../services/tickets';
import type { Ticket, AdminTicketMessageResponse, TicketStatus, TicketPriority, StaffUser } from '@/types/api';
import { secureDownload } from '@/utils/url';
import { cn } from '@/utils/cn';
import toast from 'react-hot-toast';

export function TicketDetail() {
    const { id } = useParams({ strict: false }) as { id: string };
    const navigate = useNavigate();

    // Core state
    const [ticket, setTicket] = useState<Ticket | null>(null);
    const [messages, setMessages] = useState<AdminTicketMessageResponse[]>([]);
    const [agents, setAgents] = useState<StaffUser[]>([]);

    // UI state
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [replyText, setReplyText] = useState('');
    const [isInternalNote, setIsInternalNote] = useState(false);
    const [isReplying, setIsReplying] = useState(false);

    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const ticketStatusRef = useRef<string | null>(null);

    // Keep ref in sync with ticket status
    useEffect(() => {
        ticketStatusRef.current = ticket?.status || null;
    }, [ticket?.status]);

    const loadData = async () => {
        if (!id) return;
        setIsLoading(true);
        setError(null);
        try {
            // Using Promise.all to fetch metadata + msgs simultaneously
            // Note: In admin, getTicket is not definitively listed separate from tickets queue,
            // so we might filter it from the queue, OR use a direct GET if available. Let's assume queue has it or API handles `GET /admin/tickets/tickets` but it's not documented for ID GET?
            // Actually, API usually allows GET collection + filtering. Let's fetch the thread which is critical.

            const [ticketRes, messagesRes, agentsRes] = await Promise.all([
                adminTicketsApi.getTicket(id),
                adminTicketsApi.getTicketMessages(id),
                adminTicketsApi.getAgents()
            ]);

            const fetchedTicket = (ticketRes as any).data || ticketRes;
            const fetchedMessages = (messagesRes as any).data || messagesRes;

            setAgents((agentsRes as any).data || agentsRes);

            if (fetchedTicket?.id) setTicket(fetchedTicket);
            if (Array.isArray(fetchedMessages)) setMessages(fetchedMessages);
        } catch (err: any) {
            console.error('Failed to load admin ticket details:', err);
            setError(err.response?.data?.detail || 'Failed to load ticket workspace.');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadData();

        // Auto-poll for new messages every 10 seconds
        const interval = setInterval(() => {
            if (id && ticketStatusRef.current !== 'CLOSED') {
                adminTicketsApi.getTicketMessages(id)
                    .then((messagesRes: any) => {
                        const fetchedMessages = messagesRes.data || messagesRes;
                        if (Array.isArray(fetchedMessages)) {
                            setMessages(fetchedMessages);
                        }
                    })
                    .catch(() => { }); // Silently fail on polling errors
            }
        }, 10000);

        return () => clearInterval(interval);
    }, [id]);

    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages]);

    const handleStatusChange = async (newStatus: TicketStatus) => {
        if (!ticket) return;
        try {
            await adminTicketsApi.changeStatus(ticket.id, newStatus);
            toast.success('Status updated');
            loadData();
        } catch {
            toast.error('Failed to update status');
        }
    };

    const handlePriorityChange = async (newPriority: TicketPriority) => {
        if (!ticket) return;
        try {
            await adminTicketsApi.changePriority(ticket.id, newPriority);
            toast.success('Priority updated');
            loadData();
        } catch {
            toast.error('Failed to update priority');
        }
    };

    const handleAgentChange = async (agentIdStr: string) => {
        if (!ticket) return;
        const agentId = agentIdStr === "" ? 0 : parseInt(agentIdStr, 10);
        try {
            await adminTicketsApi.assignAgent(ticket.id, agentId);
            toast.success('Assignment updated');
            loadData();
        } catch {
            toast.error('Failed to update assignment');
        }
    };

    const handleReply = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!id || (!replyText.trim() && !selectedFile) || isReplying) return;

        setIsReplying(true);
        try {
            const res = await adminTicketsApi.replyToTicket(id, {
                message: replyText || "(Attached File)",
                is_internal_note: isInternalNote
            });
            // The API might return the message as { data: TicketMessage } or directly as TicketMessage
            const msg = (res as any)?.data ?? res;
            const msgId: string | undefined = msg?.id;

            console.debug('[Admin Reply] Created message id:', msgId, '| full response:', msg);

            if (selectedFile && msgId) {
                await adminTicketsApi.uploadAttachment(id, msgId, selectedFile);
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
            } else if (selectedFile && !msgId) {
                console.error('[Admin Reply] Could not extract message id from reply response; skipping attachment upload.', res);
                toast.error('Failed to attach file: could not identify message. The reply was sent.');
            }

            setReplyText('');
            setIsInternalNote(false);
            // Small delay so the backend finishes associating the attachment before we reload
            await new Promise(resolve => setTimeout(resolve, 500));
            await loadData();
            toast.success(isInternalNote ? 'Internal note added' : 'Reply sent to client');
        } catch (err) {
            console.error('Failed to send reply from admin:', err);
            toast.error('Error processing the request.');
        } finally {
            setIsReplying(false);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const file = e.target.files[0];
            if (file.size > 5 * 1024 * 1024) {
                toast.error("File exceeds 5MB limit");
                return;
            }
            setSelectedFile(file);
        }
    };

    if (isLoading && !ticket) {
        return (
            <div className="flex justify-center items-center py-32 text-gray-500">
                <RefreshCw className="w-8 h-8 animate-spin" />
            </div>
        );
    }

    if (error || !ticket) {
        return (
            <div className="bg-error-50 text-error-700 p-8 rounded-lg flex flex-col items-center max-w-2xl mx-auto mt-10 shadow-sm border border-error-100">
                <ShieldAlert className="w-16 h-16 mb-4 text-error-500" />
                <h2 className="text-2xl font-bold">Workspace Unavailable</h2>
                <p className="mt-2 text-center">{error || "Could not locate this ticket metadata."}</p>
                <Button onClick={() => navigate({ to: `/admin/tickets` })} className="mt-8" variant="secondary">
                    <ArrowLeft className="w-4 h-4 mr-2" />
                    Back to Queue
                </Button>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-[calc(100vh-120px)] bg-white rounded-xl shadow-xl border border-gray-200 overflow-hidden">
            {/* Top Bar Navigation & Metadata */}
            <div className="text-white p-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4" style={{ backgroundColor: '#171717' }}>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => navigate({ to: `/admin/tickets` })}
                        className="text-gray-400 hover:text-white p-1 rounded transition-colors"
                        title="Back to queue"
                    >
                        <ArrowLeft className="w-5 h-5" />
                    </button>
                    <div>
                        <div className="flex items-center gap-3">
                            <h1 className="page-title truncate max-w-[400px]">{ticket.subject}</h1>
                            <select
                                value={ticket.status}
                                onChange={(e) => handleStatusChange(e.target.value as TicketStatus)}
                                className={cn(
                                    "auth-mono-label px-2 py-0.5 rounded border-0 focus:ring-2 focus:ring-offset-1 focus:ring-primary-500 cursor-pointer text-center",
                                    ticket.status === 'OPEN' ? "bg-primary-500 text-white" :
                                        ticket.status === 'IN_PROGRESS' ? "bg-warning-500 text-white" :
                                            ticket.status === 'PENDING_CUSTOMER' ? "bg-warning-500 text-white" :
                                                ticket.status === 'RESOLVED' ? "bg-success-500 text-white" :
                                                    ""
                                )}
                                style={{
                                    WebkitAppearance: 'none',
                                    MozAppearance: 'none',
                                    ...(ticket.status !== 'OPEN' && ticket.status !== 'IN_PROGRESS' && ticket.status !== 'PENDING_CUSTOMER' && ticket.status !== 'RESOLVED'
                                        ? { backgroundColor: '#374151', color: '#d1d5db' }
                                        : {}),
                                }}
                            >
                                <option value="OPEN">OPEN</option>
                                <option value="IN_PROGRESS">IN PROGRESS</option>
                                <option value="PENDING_CUSTOMER">PENDING</option>
                                <option value="RESOLVED">RESOLVED</option>
                                <option value="CLOSED">CLOSED</option>
                            </select>
                        </div>
                        <div className="text-xs text-gray-400 mt-2 flex flex-wrap items-center gap-3">
                            <span>ID: {ticket.id}</span>
                            <span>| Origin: {ticket.origin || 'WEB'}</span>
                            <span>| Priority:
                                <select
                                    value={ticket.priority}
                                    onChange={(e) => handlePriorityChange(e.target.value as TicketPriority)}
                                    className={cn(
                                        "ml-1 bg-transparent border-b border-dashed border-gray-500 cursor-pointer focus:outline-none focus:border-white",
                                        ticket.priority === 'URGENT' ? "text-error-400 font-bold" : "text-gray-300"
                                    )}
                                >
                                    <option value="LOW" className="text-gray-900">LOW</option>
                                    <option value="NORMAL" className="text-gray-900">NORMAL</option>
                                    <option value="HIGH" className="text-gray-900">HIGH</option>
                                    <option value="URGENT" className="text-error-600 font-bold">URGENT</option>
                                </select>
                            </span>
                            <span>| Assignment:
                                <select
                                    value={ticket.assigned_agent_id?.toString() || ""}
                                    onChange={(e) => handleAgentChange(e.target.value)}
                                    className="ml-1 bg-transparent border-b border-dashed border-gray-500 cursor-pointer focus:outline-none focus:border-white text-gray-300"
                                >
                                    <option value="" className="text-gray-900">Unassigned</option>
                                    {agents.map(agent => (
                                        <option key={agent.id} value={agent.id.toString()} className="text-gray-900">
                                            {agent.first_name} {agent.last_name} ({agent.role})
                                        </option>
                                    ))}
                                </select>
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {!ticket.customer?.id && (
                        <span className="text-xs text-warning-400 font-medium bg-warning-900/30 px-2 py-1 rounded border border-warning-700/50">
                            ATTACHMENTS DISABLED WITH GUESTS
                        </span>
                    )}
                    <Button onClick={loadData} variant="secondary" className="h-8 px-3 py-0 hover:opacity-90 hover:text-white" style={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#d1d5db' }}>
                        <RefreshCw className={cn("w-4 h-4", isReplying && "animate-spin")} />
                    </Button>
                </div>

            </div>

            {/* Customer Identity Panel */}
            {(() => {
                const c = ticket.customer;
                const origin = ticket.origin || 'WEB';
                if (c) {
                    return (
                        <div className={cn(
                            "px-5 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 border-b text-sm",
                            c.is_verified
                                ? "bg-primary-50 border-primary-100"
                                : "bg-warning-50 border-warning-100"
                        )}>
                            {c.is_verified ? (
                                <span className="flex items-center gap-1.5 font-semibold text-primary-700">
                                    <UserCheck className="w-4 h-4" />
                                    Verified User
                                </span>
                            ) : (
                                <span className="flex items-center gap-1.5 font-semibold text-warning-700">
                                    <UserX className="w-4 h-4" />
                                    Unverified Account
                                </span>
                            )}
                            <span className="text-gray-600">
                                {[c.first_name, c.last_name].filter(Boolean).join(' ') || <em className="text-gray-400">No name</em>}
                            </span>
                            <span className="font-mono text-gray-500 text-xs">{c.email}</span>
                            <span className="flex items-center gap-1 text-xs bg-white border border-gray-200 rounded px-2 py-0.5 text-gray-600 shadow-sm">
                                Plan: <strong className="text-primary-600 ml-1">{c.plan || 'FREE'}</strong>
                            </span>
                            {!c.is_active && (
                                <span className="flex items-center gap-1 text-xs font-semibold text-error-600 bg-error-50 border border-error-100 rounded px-2 py-0.5">
                                    <XCircle className="w-3.5 h-3.5" /> Deactivated Account
                                </span>
                            )}
                            <span className="flex items-center gap-1 text-xs text-gray-400 ml-auto">
                                <Globe className="w-3.5 h-3.5" /> via {origin}
                            </span>
                        </div>
                    );
                }
                // No customer object = came from an anonymous/guest session
                return (
                    <div className="px-5 py-2.5 flex items-center gap-3 border-b bg-gray-50 border-gray-200 text-sm">
                        <span className="flex items-center gap-1.5 font-semibold text-gray-500">
                            <User className="w-4 h-4" /> Anonymous Guest
                        </span>
                        <span className="text-xs text-gray-400 italic">No account — ticket sent without logging in</span>
                        <span className="flex items-center gap-1 text-xs text-gray-400 ml-auto">
                            <Globe className="w-3.5 h-3.5" /> via {origin}
                        </span>
                    </div>
                );
            })()}

            <div className="flex-1 overflow-y-auto p-6 bg-gray-50 flex flex-col gap-6">
                {messages.length === 0 ? (
                    <div className="m-auto text-center opacity-40">
                        <MessageSquare className="w-12 h-12 mx-auto mb-3" />
                        <p>The thread starts here.</p>
                    </div>
                ) : (
                    messages.map((msg) => {
                        const isAgent = msg.is_agent;
                        const isInternal = msg.is_internal_note;

                        return (
                            <div key={msg.id} className={cn(
                                "flex flex-col max-w-[85%]",
                                isAgent ? "self-end items-end" : "self-start items-start"
                            )}>
                                <div className="flex items-center gap-2 mb-1.5 px-1">
                                    <span className={cn(
                                        "text-xs font-semibold",
                                        isInternal ? "text-warning-700" : isAgent ? "text-primary-700" : "text-gray-600"
                                    )}>
                                        {isInternal ? 'Admin (Internal Context)' : isAgent ? 'Agent Reply' : 'Client'}
                                    </span>
                                    <span className="text-[10px] text-gray-400">
                                        {new Date(msg.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'medium' })}
                                    </span>
                                </div>
                                <div className={cn(
                                    "p-4 rounded-xl shadow-sm text-sm whitespace-pre-wrap break-words border relative",
                                    isInternal
                                        ? "bg-warning-50 text-warning-900 border-warning-200"
                                        : isAgent
                                            ? "bg-primary-50 text-primary-900 border-primary-200 rounded-tr-none"
                                            : "bg-white text-gray-800 border-gray-200 rounded-tl-none"
                                )}>
                                    {msg.message}
                                    {msg.attachments && msg.attachments.length > 0 && (
                                        <div className="mt-3 flex flex-col gap-2 border-t pt-3 border-gray-200 border-opacity-30">
                                            {msg.attachments.map(att => (
                                                <button
                                                    key={att.id}
                                                    type="button"
                                                    onClick={async () => {
                                                        try {
                                                            await secureDownload(att.file_url, att.file_name);
                                                        } catch {
                                                            toast.error('Failed to download attachment');
                                                        }
                                                    }}
                                                    className={cn(
                                                        "flex items-center gap-2 text-xs p-2 rounded border hover:opacity-80 transition cursor-pointer text-left",
                                                        isInternal
                                                            ? "bg-warning-50 border-warning-300 text-warning-900"
                                                            : isAgent
                                                                ? "bg-primary-50 border-primary-300 text-primary-900"
                                                                : "bg-gray-50 border-gray-200 text-gray-700"
                                                    )}
                                                >
                                                    <Download className="w-4 h-4 flex-shrink-0" />
                                                    <span className="truncate max-w-[200px]">{att.file_name}</span>
                                                </button>
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

            {/* Admin Compose Area */}
            <div className="bg-white border-t border-gray-200 p-4">
                <form onSubmit={handleReply} className="flex flex-col gap-3">
                    <div className="flex items-center gap-4 bg-gray-50 p-2 rounded-lg border border-gray-200">
                        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-gray-700 font-medium px-2">
                            <input
                                type="radio"
                                checked={!isInternalNote}
                                onChange={() => setIsInternalNote(false)}
                                className="w-4 h-4 text-primary-600 focus:ring-primary-500 border-gray-200"
                            />
                            Public Reply
                        </label>
                        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-warning-700 font-medium px-2 rounded hover:bg-warning-50 transition-colors">
                            <input
                                type="radio"
                                checked={isInternalNote}
                                onChange={() => setIsInternalNote(true)}
                                className="w-4 h-4 text-warning-600 focus:ring-warning-500 border-warning-300"
                            />
                            Internal Note (Hidden)
                        </label>
                    </div>

                    {selectedFile && (
                        <div className="flex items-center gap-2 bg-primary-50 text-primary-700 px-3 py-2 rounded-lg text-sm border border-primary-100 self-start">
                            <FileText className="w-4 h-4" />
                            <span className="truncate max-w-[200px]">{selectedFile.name}</span>
                            <button
                                type="button"
                                onClick={() => setSelectedFile(null)}
                                className="p-1 hover:bg-primary-50 rounded-full text-primary-600 transition"
                            >
                                <X className="w-3 h-3" />
                            </button>
                        </div>
                    )}
                    <div className="relative flex items-end gap-2">
                        <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handleFileChange}
                            className="hidden"
                            accept="image/jpeg,image/png,application/pdf"
                        />
                        <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={isReplying || !ticket.customer?.id}
                            className={cn(
                                "p-3 rounded-lg transition-colors",
                                ticket.customer?.id
                                    ? "text-gray-500 hover:text-primary-600 hover:bg-gray-100"
                                    : "text-gray-400 cursor-not-allowed"
                            )}
                            title={ticket.customer?.id ? "Attach file" : "ATTACHMENT DISABLED WITH GUESTS"}
                        >
                            <Paperclip className="w-5 h-5" />
                        </button>

                        <div className="relative flex-1">
                            <textarea
                                value={replyText}
                                onChange={(e) => setReplyText(e.target.value)}
                                placeholder={isInternalNote ? "Leave a private note for other agents..." : "Type your response to the client..."}
                                rows={4}
                                disabled={isReplying}
                                className={cn(
                                    "w-full rounded-lg border-gray-200 focus:ring-2 resize-none pr-16 pl-4 pt-4 pb-4 text-sm transition-all",
                                    isInternalNote
                                        ? "bg-warning-50 focus:border-warning-400 focus:ring-warning-400/20 placeholder:text-warning-700/50 text-warning-900"
                                        : "bg-white focus:border-primary-500 focus:ring-primary-500/20 shadow-inner"
                                )}
                            />
                            <button
                                type="submit"
                                disabled={(!replyText.trim() && !selectedFile) || isReplying}
                                className={cn(
                                    "absolute bottom-4 right-4 text-white rounded-lg p-2.5 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md",
                                    isInternalNote ? "bg-warning-600 hover:bg-warning-700" : "bg-primary-600 hover:bg-primary-700"
                                )}
                                title={isInternalNote ? "Save Internal Note" : "Send Reply to Client"}
                            >
                                {isReplying ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5 relative -left-[1px] -top-[1px]" />}
                            </button>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    );
}
