import clsx from "clsx";
import type { Span } from "@/lib/types";
import { formatMs } from "@/lib/format";

export interface TimelineChartProps {
  spans: Span[];
}

const ROW_COLORS = [
  "bg-accent",
  "bg-emerald-400",
  "bg-violet-400",
  "bg-amber-400",
  "bg-pink-400",
  "bg-sky-400",
];

export function TimelineChart({ spans }: TimelineChartProps) {
  if (!spans || spans.length === 0) {
    return (
      <div
        data-testid="timeline-empty"
        className="rounded-lg border border-dashed border-base-700 p-6 text-center text-xs text-base-400"
      >
        No span data recorded for this trace.
      </div>
    );
  }

  const totalEnd = Math.max(...spans.map((s) => s.start_ms + s.duration_ms));
  const totalStart = Math.min(...spans.map((s) => s.start_ms));
  const span = Math.max(1, totalEnd - totalStart);

  return (
    <div data-testid="timeline-chart" className="space-y-2">
      {spans.map((s, i) => {
        const leftPct = ((s.start_ms - totalStart) / span) * 100;
        const widthPct = Math.max((s.duration_ms / span) * 100, 0.5);
        return (
          <div key={`${s.name}-${i}`} className="flex items-center gap-3">
            <div className="w-40 shrink-0 truncate text-xs text-base-300">
              {s.name}
            </div>
            <div className="relative h-5 flex-1 rounded bg-base-800">
              <div
                className={clsx(
                  "absolute top-0 h-5 rounded",
                  s.status === "error" ? "bg-err" : ROW_COLORS[i % ROW_COLORS.length],
                  s.status === "error" && "ring-1 ring-err"
                )}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                title={`${s.name}: ${formatMs(s.duration_ms)}`}
              />
            </div>
            <div className="w-20 shrink-0 text-right font-mono text-xs text-base-400">
              {formatMs(s.duration_ms)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
