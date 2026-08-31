export function EmptyState({
  title = "No data",
  message = "There's nothing to show here yet.",
}: {
  title?: string;
  message?: string;
}) {
  return (
    <div
      data-testid="empty-state"
      className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-base-700 bg-base-850/50 px-6 py-14 text-center"
    >
      <div className="text-2xl">▢</div>
      <div className="text-sm font-medium text-base-200">{title}</div>
      <div className="max-w-sm text-xs text-base-400">{message}</div>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      data-testid="error-state"
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-err/30 bg-err/5 px-6 py-14 text-center"
    >
      <div className="text-2xl text-err">✕</div>
      <div className="text-sm font-medium text-err">
        Couldn&apos;t load data
      </div>
      <div className="max-w-md text-xs text-base-400 font-mono">
        {message}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-200 hover:bg-base-700"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return (
    <div
      data-testid="skeleton"
      className={`animate-pulse rounded bg-base-700 ${className}`}
    />
  );
}

export function SkeletonTable({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="rounded-lg border border-base-700 bg-base-850 p-4">
      <div className="space-y-2.5">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-3">
            {Array.from({ length: cols }).map((_, c) => (
              <Skeleton key={c} className="h-3.5 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
