import type { ReactNode } from "react";
import type { RolloutStage } from "@/lib/types";

export const STAGE_TONE: Record<RolloutStage, "info" | "warn" | "ok" | "err"> =
  {
    running: "info",
    paused: "warn",
    promoted: "ok",
    rolled_back: "err",
  };

export function LabeledField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-[10px] uppercase tracking-wide text-base-500">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-base-500">{label}</dt>
      <dd className="font-mono text-base-200">{value}</dd>
    </div>
  );
}

export function ActionButton({
  onClick,
  disabled,
  tone,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  tone?: "ok" | "err";
  children: ReactNode;
}) {
  const toneClass =
    tone === "ok"
      ? "border-ok/40 bg-ok/10 text-ok hover:bg-ok/20"
      : tone === "err"
        ? "border-err/40 bg-err/10 text-err hover:bg-err/20"
        : "border-base-600 bg-base-800 text-base-200 hover:bg-base-700";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded border px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-60 ${toneClass}`}
    >
      {children}
    </button>
  );
}
