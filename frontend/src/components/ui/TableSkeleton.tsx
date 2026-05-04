import { Skeleton } from './Skeleton';

export function TableSkeleton() {
    return (
        <div className="space-y-6 animate-pulse">
            <div className="flex justify-between items-center">
                <div className="space-y-2">
                    <Skeleton className="h-8 w-48" />
                    <Skeleton className="h-4 w-64" />
                </div>
                <Skeleton className="h-10 w-32" />
            </div>

            <div
                className="rounded-lg border border-gray-200 overflow-hidden"
                style={{ backgroundColor: 'var(--color-surface-primary)' }}
            >
                {/* Header */}
                <div className="border-b border-gray-200 bg-gray-50 px-6 py-4">
                    <div className="flex gap-4">
                        <Skeleton className="h-4 w-1/4" />
                        <Skeleton className="h-4 w-1/4" />
                        <Skeleton className="h-4 w-1/4" />
                        <Skeleton className="h-4 w-1/4" />
                    </div>
                </div>

                {/* Rows */}
                <div className="divide-y divide-gray-200">
                    {[...Array(5)].map((_, i) => (
                        <div key={i} className="px-6 py-4 flex gap-4">
                            <div className="w-1/4 space-y-2">
                                <Skeleton className="h-5 w-3/4" />
                            </div>
                            <div className="w-1/4 space-y-2">
                                <Skeleton className="h-5 w-full" />
                                <Skeleton className="h-3 w-1/2" />
                            </div>
                            <div className="w-1/4">
                                <div className="flex flex-wrap gap-2">
                                    <Skeleton className="h-6 w-16 rounded" />
                                    <Skeleton className="h-6 w-16 rounded" />
                                </div>
                            </div>
                            <div className="w-1/4 flex justify-end">
                                <Skeleton className="h-8 w-8 rounded p-1" />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
