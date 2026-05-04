import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { MessageSquare, UserCheck, Clock, Loader2, RefreshCw, ExternalLink, ChevronLeft, ChevronRight, Filter, CheckSquare, Square, X, ArrowUpDown, Calendar, BarChart3 } from 'lucide-react';
import { liveChatApi } from '@livechat';
import type { SessionMetadataResponse, LiveChatStatsResponse } from '@/types/api';
import { AlertTriangle, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { Button } from '@/components/ui/Button';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { formatRelativeTime } from '@/utils/dateUtils';

function StatusBadge({ status }: { status: string }) {
    const colors: Record<string, string> = {
        WAITING: 'bg-warning-50 text-warning-700 border-warning-200',
        ACTIVE: 'bg-success-50 text-success-700 border-success-200',
        ENDED: 'bg-gray-100 text-gray-600 border-gray-200',
    };
    return (
        <span className={clsx('px-2.5 py-0.5 rounded-full text-xs font-medium border', colors[status] ?? 'bg-gray-100 text-gray-600')}>
            {status}
        </span>
    );
}

export function LiveChatAdmin() {
    const navigate = useNavigate();
    const [sessions, setSessions] = useState<SessionMetadataResponse[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [claimingId, setClaimingId] = useState<string | null>(null);
    const [endingId, setEndingId] = useState<string | null>(null);
    const [apiError, setApiError] = useState<string | null>(null);

    // Pagination
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(5);
    const [totalSessions, setTotalSessions] = useState(0);

    // Filter
    const [statusFilter, setStatusFilter] = useState<string>('');

    // Sorting
    const [sortBy, setSortBy] = useState<'created_at' | 'status'>('created_at');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

    // Selection for mass actions
    const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set());
    const [isMassClosing, setIsMassClosing] = useState(false);

    // Stats state
    const [stats, setStats] = useState<LiveChatStatsResponse | null>(null);
    const [isLoadingStats, setIsLoadingStats] = useState(false);

    const fetchStats = useCallback(async () => {
        setIsLoadingStats(true);
        try {
            const response = await liveChatApi.getStats();
            const data = (response as any).data ?? response;
            if (data && typeof data === 'object' && 'waiting' in data) {
                setStats(data as LiveChatStatsResponse);
            }
        } catch (err) {
            console.error('Failed to fetch live chat stats:', err);
        } finally {
            setIsLoadingStats(false);
        }
    }, []);

    const fetchSessions = useCallback(async () => {
        setIsLoading(true);
        setApiError(null);
        try {
            // Use backend pagination and filtering
            const response = await liveChatApi.getSessions({
                status: statusFilter || undefined,
                page: currentPage,
                page_size: pageSize
            });

            console.log('API Response:', response);

            // Check if response is an error (has detail field)
            if (response && typeof response === 'object' && 'detail' in response) {
                const errorDetail = (response as any).detail;
                console.error('API Error:', errorDetail);
                setApiError(`API Error: ${errorDetail}`);
                setSessions([]);
                setTotalSessions(0);
                return;
            }

            // Handle different response formats
            let sessionsList: SessionMetadataResponse[] = [];
            let total = 0;

            if (Array.isArray(response)) {
                // Direct array response
                sessionsList = response;
                total = response.length;
            } else if (response && typeof response === 'object') {
                // Object response - check for common patterns
                const data = (response as any).data ?? response;
                if (Array.isArray(data)) {
                    sessionsList = data;
                    total = data.length;
                } else if (data?.items && Array.isArray(data.items)) {
                    sessionsList = data.items;
                    total = data.total ?? data.items.length;
                } else {
                    // Try to find array in response
                    const possibleArrays = Object.values(response).filter(v => Array.isArray(v));
                    if (possibleArrays.length > 0) {
                        sessionsList = possibleArrays[0] as SessionMetadataResponse[];
                        total = sessionsList.length;
                    }
                }
            }

            console.log('Parsed sessions:', sessionsList.length, 'Total:', total);

            setSessions(sessionsList);
            setTotalSessions(total);
        } catch (err: any) {
            console.error('Failed to fetch live sessions:', err);
            setApiError(err?.message || 'Failed to fetch sessions');
            toast.error('Failed to fetch live sessions');
        } finally {
            setIsLoading(false);
        }
    }, [currentPage, pageSize, statusFilter]);

    useEffect(() => {
        fetchSessions();
        fetchStats();
        const interval = setInterval(() => {
            fetchSessions();
            fetchStats();
        }, 5000);
        return () => clearInterval(interval);
    }, [fetchSessions, fetchStats]);

    // Reset selection when filters change
    useEffect(() => {
        setSelectedSessions(new Set());
    }, [statusFilter, currentPage, pageSize]);

    // Sort sessions
    const sortedSessions = [...sessions].sort((a, b) => {
        if (sortBy === 'created_at') {
            const dateA = new Date(a.created_at).getTime();
            const dateB = new Date(b.created_at).getTime();
            return sortOrder === 'asc' ? dateA - dateB : dateB - dateA;
        }
        if (sortBy === 'status') {
            const statusOrder = { WAITING: 0, ACTIVE: 1, ENDED: 2 };
            const orderA = statusOrder[a.status] ?? 3;
            const orderB = statusOrder[b.status] ?? 3;
            if (orderA !== orderB) {
                return sortOrder === 'asc' ? orderA - orderB : orderB - orderA;
            }
            // If same status, sort by date descending
            return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        }
        return 0;
    });

    const handleClaim = async (sessionId: string) => {
        setClaimingId(sessionId);
        try {
            await liveChatApi.joinSession(sessionId);
            toast.success('Session claimed! Joining chat...');
            navigate({ to: `/admin/livechat/${sessionId}` });
        } catch (err: any) {
            console.error('Failed to claim session:', err);
            toast.error(err?.response?.data?.detail || 'Failed to claim session.');
        } finally {
            setClaimingId(null);
        }
    };
    const handleEndSession = async (sessionId: string) => {
        if (!confirm('Are you sure you want to end this session?')) return;
        setEndingId(sessionId);
        try {
            await liveChatApi.adminEndSession(sessionId);
            toast.success('Session ended.');
            await fetchSessions();
        } catch (err: any) {
            console.error('Failed to end session:', err);
            toast.error('Failed to end session.');
        } finally {
            setEndingId(null);
        }
    };

    const handleSelectSession = (sessionId: string, checked: boolean) => {
        const newSelection = new Set(selectedSessions);
        if (checked) {
            newSelection.add(sessionId);
        } else {
            newSelection.delete(sessionId);
        }
        setSelectedSessions(newSelection);
    };

    const handleSelectAll = (checked: boolean) => {
        if (checked) {
            setSelectedSessions(new Set(sessions.map(s => s.id)));
        } else {
            setSelectedSessions(new Set());
        }
    };

    const handleMassClose = async () => {
        if (selectedSessions.size === 0) return;
        if (!confirm(`Are you sure you want to end ${selectedSessions.size} session(s)?`)) return;

        setIsMassClosing(true);
        let successCount = 0;
        let failCount = 0;

        // End sessions sequentially to avoid overwhelming the server
        for (const sessionId of selectedSessions) {
            try {
                await liveChatApi.adminEndSession(sessionId);
                successCount++;
            } catch (error) {
                failCount++;
                console.error(`Failed to end session ${sessionId}:`, error);
            }
        }

        setIsMassClosing(false);
        setSelectedSessions(new Set());

        if (successCount > 0) {
            toast.success(`Ended ${successCount} session(s)`);
        }
        if (failCount > 0) {
            toast.error(`Failed to end ${failCount} session(s)`);
        }

        fetchSessions();
    };

    const waitingSessions = sessions.filter((s: SessionMetadataResponse) => s.status === 'WAITING');
    const activeSessions = sessions.filter((s: SessionMetadataResponse) => s.status === 'ACTIVE');
    const totalPages = Math.ceil(totalSessions / pageSize);

    return (
        <PageShell>
            <PageHeader
                title="Live Chat Queue"
                description="Active sessions update every 5 seconds."
                icon={<MessageSquare className="h-5 w-5" />}
                actions={
                    <div className="flex items-center gap-2">
                        {selectedSessions.size > 0 && (
                            <Button
                                onClick={handleMassClose}
                                disabled={isMassClosing}
                                variant="secondary"
                                className="flex items-center gap-2 bg-error-50 text-error-600 border-error-200 hover:bg-error-50"
                                title="End selected sessions"
                            >
                                {isMassClosing ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                    <><X className="w-4 h-4" /> End ({selectedSessions.size})</>
                                )}
                            </Button>
                        )}
                        <Button onClick={() => { fetchSessions(); fetchStats(); }} variant="secondary" className="flex items-center gap-2">
                            <RefreshCw className={clsx('w-4 h-4', (isLoading || isLoadingStats) && 'animate-spin')} />
                            Refresh
                        </Button>
                    </div>
                }
            />

            {/* Stats Widget - Section 6.8: Admin Session Statistics */}
            <div className="grid grid-cols-4 gap-4 mb-6">
                {/* Waiting */}
                <div className="bg-warning-50 border border-warning-200 rounded-lg p-4 flex items-center gap-3 shadow-sm hover:shadow-md transition-shadow">
                    <div className="w-12 h-12 bg-warning-50 rounded-full flex items-center justify-center flex-shrink-0 shadow-inner">
                        <Clock className="w-6 h-6 text-warning-700" />
                    </div>
                    <div>
                        <div className="text-3xl font-bold text-warning-700">
                            {isLoadingStats && !stats ? (
                                <Loader2 className="w-6 h-6 animate-spin" />
                            ) : (
                                stats?.waiting ?? waitingSessions.length
                            )}
                        </div>
                        <div className="text-sm text-warning-700 font-medium">Waiting</div>
                    </div>
                </div>

                {/* Active */}
                <div className="bg-success-50 border border-success-200 rounded-lg p-4 flex items-center gap-3 shadow-sm hover:shadow-md transition-shadow">
                    <div className="w-12 h-12 bg-success-50 rounded-full flex items-center justify-center flex-shrink-0 shadow-inner">
                        <UserCheck className="w-6 h-6 text-success-700" />
                    </div>
                    <div>
                        <div className="text-3xl font-bold text-success-700">
                            {isLoadingStats && !stats ? (
                                <Loader2 className="w-6 h-6 animate-spin" />
                            ) : (
                                stats?.active ?? activeSessions.length
                            )}
                        </div>
                        <div className="text-sm text-success-700 font-medium">Active</div>
                    </div>
                </div>

                {/* Ended */}
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 flex items-center gap-3 shadow-sm hover:shadow-md transition-shadow">
                    <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center flex-shrink-0 shadow-inner">
                        <BarChart3 className="w-6 h-6 text-gray-600" />
                    </div>
                    <div>
                        <div className="text-3xl font-bold text-gray-700">
                            {isLoadingStats && !stats ? (
                                <Loader2 className="w-6 h-6 animate-spin" />
                            ) : (
                                stats?.ended ?? '-'
                            )}
                        </div>
                        <div className="text-sm text-gray-600 font-medium">Ended</div>
                    </div>
                </div>

                {/* Total */}
                <div className="bg-primary-50 border border-primary-200 rounded-lg p-4 flex items-center gap-3 shadow-sm hover:shadow-md transition-shadow">
                    <div className="w-12 h-12 bg-primary-50 rounded-full flex items-center justify-center flex-shrink-0 shadow-inner">
                        <BarChart3 className="w-6 h-6 text-primary-700" />
                    </div>
                    <div>
                        <div className="text-3xl font-bold text-primary-700">
                            {isLoadingStats && !stats ? (
                                <Loader2 className="w-6 h-6 animate-spin" />
                            ) : (
                                stats?.total ?? totalSessions
                            )}
                        </div>
                        <div className="text-sm text-primary-700 font-medium">Total</div>
                    </div>
                </div>
            </div>

            {/* API Error Display */}
            {apiError && (
                <div className="bg-error-50 border border-error-200 rounded-lg p-4 mb-4 text-error-700">
                    <p className="font-medium">API Error: {apiError}</p>
                    <p className="text-sm mt-1">Check browser console for details</p>
                </div>
            )}

            {/* Filter & Sort Bar */}
            <div className="card p-4 flex flex-wrap gap-4 items-center justify-between mb-4">
                <div className="flex flex-wrap gap-4 items-center text-sm">
                    <div className="flex items-center text-gray-600 font-medium">
                        <Filter className="w-4 h-4 mr-2" />
                        Filter:
                    </div>
                    <select
                        value={statusFilter}
                        onChange={(e) => {
                            setStatusFilter(e.target.value);
                            setCurrentPage(1);
                        }}
                        className="input rounded-lg pl-3 pr-8"
                    >
                        <option value="">All Statuses</option>
                        <option value="WAITING">Waiting</option>
                        <option value="ACTIVE">Active</option>
                        <option value="ENDED">Ended</option>
                    </select>

                    <div className="h-6 w-px bg-gray-300" />

                    <div className="flex items-center text-gray-600 font-medium">
                        <ArrowUpDown className="w-4 h-4 mr-2" />
                        Sort:
                    </div>
                    <select
                        value={sortBy}
                        onChange={(e) => setSortBy(e.target.value as 'created_at' | 'status')}
                        className="input rounded-lg pl-3 pr-8"
                    >
                        <option value="created_at">Creation Date</option>
                        <option value="status">Status</option>
                    </select>
                    <button
                        onClick={() => setSortOrder(order => order === 'asc' ? 'desc' : 'asc')}
                        className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
                        title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
                    >
                        {sortOrder === 'asc' ? '↑' : '↓'}
                    </button>

                    <div className="h-6 w-px bg-gray-300" />

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

            {/* Debug Info */}
            <div className="text-xs text-gray-400 mb-2">
                Debug: {sessions.length} sessions loaded | Page {currentPage} | Filter: {statusFilter || 'none'}
            </div>

            {/* Sessions Table */}
            {isLoading ? (
                <div className="flex justify-center items-center py-24 text-gray-400 bg-white rounded-lg border border-gray-200">
                    <Loader2 className="w-8 h-8 animate-spin" />
                </div>
            ) : sessions.length === 0 ? (
                <div className="text-center py-24 bg-gray-50 rounded-lg border border-gray-200">
                    <MessageSquare className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                    <p className="text-gray-500 font-medium">No active sessions</p>
                    <p className="text-gray-400 text-sm mt-1">The queue will update automatically.</p>
                    <p className="text-gray-400 text-xs mt-2">Check browser console for API response details</p>
                </div>
            ) : (
                <div className="card p-0 overflow-hidden">
                    <table className="min-w-full text-sm">
                        <thead className="bg-gray-50 border-b border-gray-200">
                            <tr>
                                <th className="px-4 py-3 w-10">
                                    <button
                                        onClick={() => handleSelectAll(sessions.length > 0 && selectedSessions.size !== sessions.length)}
                                        className="p-1 rounded hover:bg-gray-200 transition-colors"
                                        title={selectedSessions.size === sessions.length ? "Deselect all" : "Select all"}
                                    >
                                        {selectedSessions.size === sessions.length && sessions.length > 0 ? (
                                            <CheckSquare className="w-5 h-5 text-primary-600" />
                                        ) : (
                                            <Square className="w-5 h-5 text-gray-400" />
                                        )}
                                    </button>
                                </th>
                                <th className="px-4 py-3 text-left font-semibold text-gray-600 w-32">Session ID</th>
                                <th className="px-4 py-3 text-left font-semibold text-gray-600 w-24">Status</th>
                                <th className="px-4 py-3 text-left font-semibold text-gray-600 w-40">User</th>
                                <th className="px-4 py-3 text-left font-semibold text-gray-600 w-32">Agent</th>
                                <th className="px-4 py-3 text-left font-semibold text-gray-600">Details</th>
                                <th className="px-4 py-3 text-left font-semibold text-gray-600 w-36">Started</th>
                                <th className="px-4 py-3 text-right font-semibold text-gray-600 w-40">Action</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                            {sortedSessions.map((session: SessionMetadataResponse) => (
                                <tr
                                    key={session.id}
                                    className={clsx(
                                        "hover:bg-gray-50 transition-colors",
                                        selectedSessions.has(session.id) && "bg-primary-50 hover:bg-primary-50"
                                    )}
                                >
                                    <td className="px-4 py-4">
                                        <button
                                            onClick={() => handleSelectSession(session.id, !selectedSessions.has(session.id))}
                                            className="p-1 rounded hover:bg-gray-200 transition-colors"
                                        >
                                            {selectedSessions.has(session.id) ? (
                                                <CheckSquare className="w-5 h-5 text-primary-600" />
                                            ) : (
                                                <Square className="w-5 h-5 text-gray-400" />
                                            )}
                                        </button>
                                    </td>
                                    <td className="px-4 py-4 font-mono text-xs text-gray-600">
                                        <span className="font-semibold text-gray-700">#{session.id.split('-')[0]}</span>
                                    </td>
                                    <td className="px-4 py-4">
                                        <StatusBadge status={session.status} />
                                    </td>
                                    <td className="px-4 py-4">
                                        <div className="flex flex-col gap-1">
                                            {session.user_id ? (
                                                <span className="text-sm text-gray-700 font-medium">User #{session.user_id}</span>
                                            ) : (
                                                <span className="text-sm text-gray-500">Anonymous</span>
                                            )}
                                            {!session.is_authenticated_user && (
                                                <span className="flex items-center gap-1 text-[10px] text-warning-600 bg-warning-50 px-1.5 py-0.5 rounded border border-warning-100 w-fit">
                                                    <AlertTriangle className="w-2.5 h-2.5" /> Guest
                                                </span>
                                            )}
                                        </div>
                                    </td>
                                    <td className="px-4 py-4">
                                        {session.agent_id ? (
                                            <span className="text-sm text-success-700 font-medium">Agent #{session.agent_id}</span>
                                        ) : (
                                            <span className="text-xs text-gray-400 italic">Unassigned</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-4">
                                        <div className="flex flex-col gap-1 max-w-[200px]">
                                            {session.ip_address && (
                                                <span className="text-[11px] font-mono text-primary-600 bg-primary-50 px-1.5 py-0.5 rounded border border-primary-100 w-fit">
                                                    {String(session.ip_address)}
                                                </span>
                                            )}
                                            {session.current_url && (
                                                <span className="text-[11px] text-gray-500 truncate" title={String(session.current_url)}>
                                                    {String(session.current_url).replace(/^https?:\/\//, '').split('/')[0]}
                                                </span>
                                            )}
                                            {session.user_agent && (
                                                <span className="text-[10px] text-gray-400 truncate" title={String(session.user_agent)}>
                                                    {String(session.user_agent).includes('Mobile') ? '📱 Mobile' : '💻 Desktop'}
                                                </span>
                                            )}
                                        </div>
                                    </td>
                                    <td className="px-4 py-4 text-gray-500">
                                        <div className="flex flex-col gap-0.5">
                                            {(session.status === 'ACTIVE' || session.status === 'WAITING') ? (
                                                <>
                                                    <span className="font-medium text-gray-700" title={new Date(session.created_at).toLocaleString()}>
                                                        {formatRelativeTime(session.created_at)}
                                                    </span>
                                                    <span className="text-xs text-gray-400 flex items-center gap-1">
                                                        <Calendar className="w-3 h-3" />
                                                        {new Date(session.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                                                    </span>
                                                </>
                                            ) : (
                                                <span title={new Date(session.created_at).toLocaleString()}>
                                                    {new Date(session.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                                                </span>
                                            )}
                                        </div>
                                    </td>
                                    <td className="px-4 py-4 text-right">
                                        <div className="flex justify-end gap-2">
                                            {session.status === 'WAITING' && (
                                                <Button
                                                    onClick={() => handleClaim(session.id)}
                                                    disabled={claimingId === session.id}
                                                    className="text-xs py-1.5 px-3 bg-primary-600 hover:bg-primary-700 text-white shadow-sm"
                                                >
                                                    {claimingId === session.id
                                                        ? <><Loader2 className="w-3 h-3 mr-1 animate-spin inline" /> Claiming...</>
                                                        : 'Claim'
                                                    }
                                                </Button>
                                            )}
                                            {session.status === 'ACTIVE' && (
                                                <>
                                                    <Button
                                                        onClick={() => navigate({ to: `/admin/livechat/${session.id}` })}
                                                        className="text-xs py-1.5 px-3 bg-primary-50 text-primary-600 hover:bg-primary-50 border border-primary-200 flex items-center gap-1.5 shadow-sm"
                                                    >
                                                        <ExternalLink className="w-3.5 h-3.5" />
                                                        Open
                                                    </Button>
                                                    <Button
                                                        onClick={() => handleEndSession(session.id)}
                                                        disabled={endingId === session.id}
                                                        variant="secondary"
                                                        className="text-xs py-1.5 px-3 border-gray-200 hover:bg-error-50 hover:text-error-600 hover:border-error-200 shadow-sm"
                                                    >
                                                        {endingId === session.id
                                                            ? <Loader2 className="w-3 h-3 animate-spin" />
                                                            : <Trash2 className="w-3.5 h-3.5" />
                                                        }
                                                        <span className="ml-1.5">End</span>
                                                    </Button>
                                                </>
                                            )}
                                            {session.status === 'ENDED' && (
                                                <>
                                                    <Button
                                                        onClick={() => navigate({ to: `/admin/livechat/${session.id}` })}
                                                        className="text-xs py-1.5 px-3 bg-gray-50 text-gray-600 hover:bg-gray-100 border border-gray-200 flex items-center gap-1.5 shadow-sm"
                                                    >
                                                        <ExternalLink className="w-3.5 h-3.5" />
                                                        View
                                                    </Button>
                                                    <span className="text-xs text-gray-400 italic bg-gray-100 px-2 py-1 rounded">Closed</span>
                                                </>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div className="flex items-center justify-between px-6 py-4 bg-gray-50 border-t border-gray-200">
                            <div className="text-sm text-gray-500">
                                Showing <span className="font-medium text-gray-700">{((currentPage - 1) * pageSize) + 1}</span> to <span className="font-medium text-gray-700">{Math.min(currentPage * pageSize, totalSessions)}</span> of <span className="font-medium text-gray-700">{totalSessions}</span> sessions
                            </div>
                            <div className="flex items-center gap-2">
                                <Button
                                    onClick={() => setCurrentPage((p: number) => Math.max(1, p - 1))}
                                    disabled={currentPage === 1 || isLoading}
                                    variant="secondary"
                                    className="px-3 py-2 hover:bg-gray-200"
                                >
                                    <ChevronLeft className="w-4 h-4" />
                                </Button>
                                <span className="text-sm text-gray-600 font-medium px-2">
                                    Page {currentPage} of {totalPages}
                                </span>
                                <Button
                                    onClick={() => setCurrentPage((p: number) => Math.min(totalPages, p + 1))}
                                    disabled={currentPage === totalPages || isLoading}
                                    variant="secondary"
                                    className="px-3 py-2 hover:bg-gray-200"
                                >
                                    <ChevronRight className="w-4 h-4" />
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </PageShell>
    );
}
