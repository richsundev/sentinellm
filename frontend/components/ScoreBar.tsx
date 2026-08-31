import clsx from "clsx";

export interface ScoreBarProps {
  label: string;
  score: number; // 0..1
  threshold?: number | null;
  passed?: boolean | null;
}

export function ScoreBar({ label, score, threshold, passed }: ScoreBarProps) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const tone =
    passed === false ? "bg-err" : passed === true ? "bg-ok" : "bg-accent";

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-base-300">{label}</span>
        <span className="font-mono text-base-100">{score.toFixed(2)}</span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-base-700">
        <div
          className={clsx("h-2 rounded-full transition-all", tone)}
          style={{ width: `${pct}%` }}
        />
        {threshold !== null && threshold !== undefined && (
          <div
            className="absolute top-0 h-2 w-px bg-base-100/70"
            style={{ left: `${Math.max(0, Math.min(1, threshold)) * 100}%` }}
            title={`threshold ${threshold}`}
          />
        )}
      </div>
    </div>
  );
}
