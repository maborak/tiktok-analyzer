import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { routes } from '@/utils/appRoutes';
import { MessageSquare, ArrowLeft, Send, RefreshCw, AlertTriangle, Paperclip, X, FileText, Download, XCircle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { userTicketsApi } from '../services/tickets';
import type { Ticket, TicketMessage } from '@/types/api';
import { cn } from '@/utils/cn';
import { secureDownload } from '@/utils/url';
import toast from 'react-hot-toast';
import { StatusBadge } from '../components/tickets/TicketBadges';

const MAX_REOPENS = 3;

export function TicketDetail() {
    const { ticketId: id } = useParams({ strict: false }) as { ticketId: string };
    const navigate = useNavigate();

    const [ticket, setTicket] = useState<Ticket | null>(null);
    const [messages, setMessages] = useState<TicketMessage[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [replyText, setReplyText] = useState('');
    const [isReplying, setIsReplying] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isClosing, setIsClosing] = useState(false);
    const [isReopening, setIsReopening] = useState(false);

    const [selectedFile, setSelectedFile] = useState<File | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);

    const loadData = async () => {
        if (!id) return;
        setIsLoading(true);
        setError(null);
        try {
            const [ticketRes, messagesRes] = await Promise.all([
                userTicketsApi.getTicket(id),
                userTicketsApi.getTicketMessages(id)
            ]);

            const fetchedTicket = (ticketRes as any).data || ticketRes;
            const fetchedMessages = (messagesRes as any).data || messagesRes;

            setTicket(fetchedTicket);
            if (Array.isArray(fetchedMessages)) {
                setMessages(fetchedMessages);
            }
        } catch (err: any) {
            console.error('Failed to load ticket details:', err);
            setError(err.response?.data?.detail || 'Ticket not found or access denied');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        loadData();

        // Auto-poll for new messages every 10 seconds (skip for CLOSED/RESOLVED)
        const interval = setInterval(() => {
            if (id && ticket?.status !== 'CLOSED' && ticket?.status !== 'RESOLVED') {
                userTicketsApi.getTicketMessages(id)
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
    }, [id, ticket?.status]);

    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages]);

    const handleReply = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!id || (!replyText.trim() && !selectedFile) || isReplying) return;

        setIsReplying(true);
        try {
            const res = await userTicketsApi.replyToTicket(id, { message: replyText || "(Attached File)" });
            const msg = (res as any).data || res;

            if (selectedFile) {
                await userTicketsApi.uploadAttachment(id, msg.id, selectedFile);
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
            }

            setReplyText('');
            await loadData();
            toast.success(isTerminal ? 'Reply sent — ticket reopened' : 'Reply sent');
        } catch (err) {
            console.error('Failed to send reply:', err);
            toast.error('Error sending the reply. Please try again.');
        } finally {
            setIsReplying(false);
        }
    };

    const handleClose = async () => {
        if (!id || isClosing) return;
        setIsClosing(true);
        try {
            await userTicketsApi.closeTicket(id);
            await loadData();
            toast.success('Ticket closed');
        } catch (err: any) {
            toast.error(err.response?.data?.detail || 'Error closing the ticket');
        } finally {
            setIsClosing(false);
        }
    };

    const handleReopen = async () => {
        if (!id || isReopening) return;

        const reason = prompt('Please provide a reason for reopening this ticket:');
        if (!reason || reason.trim().length < 3) {
            if (reason !== null) toast.error('The reason must be at least 3 characters');
            return;
        }

        setIsReopening(true);
        try {
            await userTicketsApi.reopenTicket(id, reason.trim());
            await loadData();
            toast.success('Ticket reopened');
        } catch (err: any) {
            toast.error(err.response?.data?.detail || 'Error reopening the ticket');
        } finally {
            setIsReopening(false);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const file = e.target.files[0];
            if (file.size > 5 * 1024 * 1024) {
                toast.error("File exceeds the 5MB limit");
                return;
            }
            setSelectedFile(file);
        }
    };

    if (isLoading && !ticket) {
        return (
            <div className="flex justify-center items-center py-20 text-gray-500">
                <RefreshCw className="w-8 h-8 animate-spin" />
            </div>
        );
    }

    if (error || !ticket) {
        return (
            <div className="bg-error-50 text-error-700 p-6 rounded-lg flex flex-col items-center">
                <AlertTriangle className="w-12 h-12 mb-4 text-error-500" />
                <h2
                    className="text-xl font-bold"
                    style={{ fontFamily: 'var(--font-mono-display)', letterSpacing: 'var(--tracking-display-tight)' }}
                >
                    Error loading ticket
                </h2>
                <p className="mt-2">{error}</p>
                <Button onClick={() => navigate({ to: routes.account.tickets })} className="mt-6" variant="secondary">
                    <ArrowLeft className="w-4 h-4 mr-2" />
                    Back to Tickets
                </Button>
            </div>
        );
    }

    const isTerminal = ticket.status === 'CLOSED' || ticket.status === 'RESOLVED';
    const isActive = !isTerminal;
    const reopenCount = ticket.reopen_count ?? 0;
    const canReopen = isTerminal && reopenCount < MAX_REOPENS;
    return (
        <div className="max-w-4xl mx-auto flex flex-col h-[calc(100vh-140px)] card p-0 overflow-hidden animate-fadeIn">
            {/* Header */}
            <div className="p-4 sm:p-6 border-b border-gray-200 flex flex-col sm:flex-row justify-between items-start gap-4 bg-gray-50">
                <div>
                    <button
                        onClick={() => navigate({ to: routes.account.tickets })}
                        className="text-gray-500 hover:text-gray-900 flex items-center text-sm font-medium mb-3 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4 mr-1" />
                        Back to tickets
                    </button>
                    <div className="flex items-center gap-3">
                        <h1 className="page-title break-words">{ticket.subject}</h1>
                        <StatusBadge status={ticket.status} />
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-gray-500 mt-2">
                        <span>Ticket ID: <span className="font-mono text-gray-800">#{ticket.id.split('-')[0]}</span></span>
                        <span>Priority: <span className="font-medium text-gray-800">{ticket.priority}</span></span>
                        <span>Created: {new Date(ticket.created_at).toLocaleString()}</span>
                    </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                    <Button onClick={loadData} variant="secondary" title="Refresh">
                        <RefreshCw className={cn("w-4 h-4", isReplying && "animate-spin")} />
                    </Button>
                    {isActive && (
                        <Button
                            onClick={handleClose}
                            variant="secondary"
                            disabled={isClosing}
                            className="text-gray-600 hover:text-error-600"
                        >
                            {isClosing ? <RefreshCw className="w-4 h-4 animate-spin mr-1.5" /> : <XCircle className="w-4 h-4 mr-1.5" />}
                            Close Ticket
                        </Button>
                    )}
                    {canReopen && (
                        <Button
                            onClick={handleReopen}
                            variant="secondary"
                            disabled={isReopening}
                            className="text-primary-600"
                        >
                            {isReopening ? <RefreshCw className="w-4 h-4 animate-spin mr-1.5" /> : <RotateCcw className="w-4 h-4 mr-1.5" />}
                            Reopen
                        </Button>
                    )}
                </div>
            </div>

            {/* Conversation Thread */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6 bg-gray-50/50">
                {messages.length === 0 ? (
                    <div className="text-center text-gray-400 py-10 flex flex-col items-center">
                        <MessageSquare className="w-10 h-10 opacity-30 mb-3" />
                        <p>No messages yet.</p>
                    </div>
                ) : (
                    messages.map((msg) => {
                        const isAgent = msg.is_agent;
                        return (
                            <div key={msg.id} className={cn("flex flex-col max-w-[85%] sm:max-w-[75%]", isAgent ? "self-start items-start" : "self-end items-end ml-auto")}>
                                <div className="flex items-center gap-2 mb-1 px-1">
                                    <span className="text-xs font-medium text-gray-600">
                                        {isAgent ? 'Support Team' : 'You'}
                                    </span>
                                    <span className="text-[10px] text-gray-400">
                                        {new Date(msg.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                                    </span>
                                </div>
                                <div className={cn(
                                    "p-4 rounded-xl shadow-sm text-sm whitespace-pre-wrap break-words border",
                                    isAgent
                                        ? "bg-white text-gray-800 border-gray-200 rounded-tl-none"
                                        : "bg-primary-600 text-white border-primary-700 rounded-tr-none"
                                )}>
                                    {msg.message}
                                    {msg.attachments && msg.attachments.length > 0 && (
                                        <div className="mt-3 flex flex-col gap-2 border-t pt-3 border-gray-200">
                                            {msg.attachments.map(att => (
                                                <button
                                                    key={att.id}
                                                    type="button"
                                                    onClick={async () => {
                                                        try {
                                                            await secureDownload(att.file_url, att.file_name);
                                                        } catch {
                                                            toast.error('Error downloading the attachment');
                                                        }
                                                    }}
                                                    className={cn(
                                                        "flex items-center gap-2 text-xs p-2 rounded border hover:opacity-80 transition cursor-pointer text-left",
                                                        isAgent ? "bg-gray-50 border-gray-200 text-gray-700" : "bg-primary-700 border-primary-600 text-primary-50"
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

            {/* Reply Area */}
            <div className="p-4 sm:p-6 bg-white border-t border-gray-200">
                {isTerminal && !canReopen ? (
                    <div className="text-center py-4 bg-gray-50 rounded-lg border border-gray-200 text-gray-500 text-sm">
                        This ticket has reached the maximum number of reopens ({MAX_REOPENS}). Please create a new ticket if you need further assistance.
                    </div>
                ) : isTerminal && canReopen ? (
                    <div className="space-y-3">
                        <div className="flex items-start gap-2 py-3 px-4 bg-amber-50 rounded-lg border border-amber-200 text-amber-800 text-sm">
                            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                            <span>
                                This ticket is <strong>{ticket.status === 'RESOLVED' ? 'resolved' : 'closed'}</strong>.
                                Sending a reply will automatically reopen it.
                                {reopenCount > 0 && ` (${reopenCount}/${MAX_REOPENS} reopens used)`}
                            </span>
                        </div>
                        <form onSubmit={handleReply} className="relative flex flex-col gap-2">
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
                                    disabled={isReplying}
                                    className="p-3 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-colors disabled:opacity-50"
                                    title="Attach file"
                                >
                                    <Paperclip className="w-5 h-5" />
                                </button>
                                <div className="relative flex-1">
                                    <textarea
                                        value={replyText}
                                        onChange={(e) => setReplyText(e.target.value)}
                                        placeholder="Type your reply here (this will reopen the ticket)..."
                                        rows={3}
                                        disabled={isReplying}
                                        className="input rounded-lg resize-none pr-14 pl-4 pt-3 pb-3"
                                    />
                                    <button
                                        type="submit"
                                        disabled={(!replyText.trim() && !selectedFile) || isReplying}
                                        className="absolute bottom-3 right-3 bg-primary-600 text-white rounded-lg p-2 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary-700 transition"
                                    >
                                        {isReplying ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                                    </button>
                                </div>
                            </div>
                        </form>
                    </div>
                ) : (
                    <form onSubmit={handleReply} className="relative flex flex-col gap-2">
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
                                disabled={isReplying}
                                className="p-3 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-lg transition-colors disabled:opacity-50"
                                title="Attach file"
                            >
                                <Paperclip className="w-5 h-5" />
                            </button>
                            <div className="relative flex-1">
                                <textarea
                                    value={replyText}
                                    onChange={(e) => setReplyText(e.target.value)}
                                    placeholder="Type your reply here..."
                                    rows={3}
                                    disabled={isReplying}
                                    className="input rounded-lg resize-none pr-14 pl-4 pt-3 pb-3"
                                />
                                <button
                                    type="submit"
                                    disabled={(!replyText.trim() && !selectedFile) || isReplying}
                                    className="absolute bottom-3 right-3 bg-primary-600 text-white rounded-lg p-2 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary-700 transition"
                                >
                                    {isReplying ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                                </button>
                            </div>
                        </div>
                    </form>
                )}
            </div>
        </div>
    );
}
