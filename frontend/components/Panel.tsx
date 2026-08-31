import type { ReactNode } from "react";

export function Panel({
  title,
  action,
  children,
  className,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-base-700 bg-base-850 p-4 shadow-panel ${className ?? ""}`}
    >
      {title && (
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-base-300">
            {title}
          </h2>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
