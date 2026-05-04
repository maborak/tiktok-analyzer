import { cn } from '@/utils/cn';
import type { TicketStatus, TicketPriority } from '@/types/api';

/** Display-friendly labels for ticket statuses. */
export const STATUS_LABELS: Record<TicketStatus, string> = {
    OPEN: 'Abierto',
    IN_PROGRESS: 'En Progreso',
    PENDING_CUSTOMER: 'Esperando tu Respuesta',
    RESOLVED: 'Resuelto',
    CLOSED: 'Cerrado',
};

/** Admin-facing labels (uses internal terminology). */
export const ADMIN_STATUS_LABELS: Record<TicketStatus, string> = {
    OPEN: 'Abierto',
    IN_PROGRESS: 'En Progreso',
    PENDING_CUSTOMER: 'Pendiente Cliente',
    RESOLVED: 'Resuelto',
    CLOSED: 'Cerrado',
};

export const STATUS_COLORS: Record<TicketStatus, string> = {
    OPEN: 'bg-primary-50 text-primary-700',
    IN_PROGRESS: 'bg-warning-50 text-warning-700',
    PENDING_CUSTOMER: 'bg-amber-50 text-amber-700 border border-amber-200',
    RESOLVED: 'bg-success-50 text-success-700',
    CLOSED: 'bg-gray-100 text-gray-600',
};

const PRIORITY_COLORS: Record<string, string> = {
    URGENT: 'text-error-600 bg-error-50 border border-error-100',
    HIGH: 'text-warning-600 bg-warning-50 border border-warning-100',
    NORMAL: 'text-gray-600',
    LOW: 'text-gray-500',
};

export function StatusBadge({ status, admin, className }: { status: TicketStatus; admin?: boolean; className?: string }) {
    const labels = admin ? ADMIN_STATUS_LABELS : STATUS_LABELS;
    return (
        <span className={cn(
            'px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide whitespace-nowrap',
            STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-600',
            className,
        )}>
            {labels[status] ?? status}
        </span>
    );
}

export function PriorityBadge({ priority, className }: { priority: TicketPriority | string; className?: string }) {
    const show = priority === 'URGENT' || priority === 'HIGH';
    if (!show) return null;
    return (
        <span className={cn(
            'py-0.5 px-2 rounded text-xs font-medium whitespace-nowrap',
            PRIORITY_COLORS[priority] ?? 'text-gray-600',
            className,
        )}>
            {priority}
        </span>
    );
}
