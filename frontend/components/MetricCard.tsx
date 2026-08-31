import clsx from "clsx";
import type { ReactNode } from "react";

export interface MetricCardProps {
  label: string;
  value: string;
  sublabel?: string;
  trend?: "up" | "down" | "flat";
  trendTone?: "good" | "bad" | "neutral";
  icon?: ReactNode;
  loading?: boolean;
}

export function MetricCard({
  label,
  value,
  sublabel,
  trend,
  trendTone = "neutral",
  icon,
  loading,
}: MetricCardProps) {
  if (loading) {
    return (
      <div
        data-testid="metric-card-skeleton"
        className="rounded-lg border border-base-700 bg-base-850 p-4 shadow-panel"
      >
        <div className="h-3 w-20 animate-pulse rounded bg-base-700" />
        <div className="mt-3 h-7 w-24 animate-pulse rounded bg-base-700" />
        <div className="mt-2 h-3 w-16 animate-pulse rounded bg-base-700" />
      </div>
    );
  }

  return (
    <div
      data-testid="metric-card"
      className="rounded-lg border border-base-700 bg-base-850 p-4 shadow-panel"
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-wide text-base-300">
          {label}
        </span>
        {icon}
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="font-mono text-2xl font-semibold text-base-50">
          {value}
        </span>
        {trend && (
          <span
            className={clsx("text-xs font-mono", {
              "text-ok": trendTone === "good",
              "text-err": trendTone === "bad",
              "text-base-300": trendTone === "neutral",
            })}
          >
            {trend === "up" ? "▲" : trend === "down" ? "▼" : "▬"}
          </span>
        )}
      </div>
      {sublabel && (
        <div className="mt-1 text-xs text-base-400">{sublabel}</div>
      )}
    </div>
  );
}
