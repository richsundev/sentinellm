export function formatNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatCompactNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(n);
}

export function formatPercent(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // Accept either 0..1 or 0..100 ranges; treat <=1.5 as a fraction.
  const pct = Math.abs(n) <= 1.5 ? n * 100 : n;
  return `${pct.toFixed(digits)}%`;
}

/**
 * A value already on a 0..100 percentage scale, shown as-is with an explicit
 * sign. Unlike `formatPercent` it never guesses the scale: `formatPercent(1)`
 * reads 1 as the fraction 100%, which is wrong for "a 1% change".
 */
export function formatSignedPercentPoints(
  n: number | null | undefined,
  digits = 1
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(digits)}%`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${formatNumber(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined || Number.isNaN(cost)) return "—";
  if (cost < 0.01 && cost > 0) return `$${cost.toFixed(5)}`;
  return `$${cost.toFixed(4)}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatRelativeShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

export function truncate(s: string, max = 80): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}
