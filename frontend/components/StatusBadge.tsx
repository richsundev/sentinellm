import clsx from "clsx";

export type BadgeTone =
  | "ok"
  | "warn"
  | "err"
  | "crit"
  | "neutral"
  | "info";

const TONE_CLASSES: Record<BadgeTone, string> = {
  ok: "bg-ok/10 text-ok border-ok/30",
  warn: "bg-warn/10 text-warn border-warn/30",
  err: "bg-err/10 text-err border-err/30",
  crit: "bg-crit/15 text-crit border-crit/40",
  neutral: "bg-base-600/30 text-base-200 border-base-500/40",
  info: "bg-accent/10 text-accent border-accent/30",
};

// Maps well-known status/severity strings from the API contract to a tone.
function toneFor(value: string): BadgeTone {
  const v = value.toLowerCase();
  if (["ok", "healthy", "production", "supported", "passed", "true"].includes(v))
    return "ok";
  if (["degraded", "testing", "medium", "partially_supported", "draft"].includes(v))
    return "warn";
  if (["error", "down", "high", "unsupported", "false", "failed"].includes(v))
    return "err";
  if (["critical"].includes(v)) return "crit";
  if (["deprecated", "low"].includes(v)) return "neutral";
  return "info";
}

export interface StatusBadgeProps {
  status: string;
  tone?: BadgeTone;
  className?: string;
}

export function StatusBadge({ status, tone, className }: StatusBadgeProps) {
  const resolvedTone = tone ?? toneFor(status);
  return (
    <span
      data-testid="status-badge"
      className={clsx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide font-mono",
        TONE_CLASSES[resolvedTone],
        className
      )}
    >
      <span
        className={clsx("h-1.5 w-1.5 rounded-full", {
          "bg-ok": resolvedTone === "ok",
          "bg-warn": resolvedTone === "warn",
          "bg-err": resolvedTone === "err",
          "bg-crit": resolvedTone === "crit",
          "bg-base-300": resolvedTone === "neutral",
          "bg-accent": resolvedTone === "info",
        })}
      />
      {status}
    </span>
  );
}
