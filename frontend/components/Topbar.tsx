"use client";

import { usePathname } from "next/navigation";
import clsx from "clsx";
import { ENVIRONMENTS, TIME_RANGES, useFilters } from "@/lib/filters-context";

const TIME_RANGE_ROUTES = new Set(["/overview", "/traces", "/evaluations"]);

const TITLES: Record<string, string> = {
  "/overview": "Overview",
  "/traces": "Traces",
  "/evaluations": "Evaluations",
  "/regressions": "Regressions",
  "/routing": "Routing decisions",
  "/models": "Model registry",
  "/experiments": "Experiments",
  "/prompts": "Prompt registry",
  "/datasets": "Datasets",
  "/cost": "Cost",
  "/settings": "Settings",
};

function pageTitle(pathname: string | null): string {
  if (!pathname) return "SentinelLLM";
  if (pathname.startsWith("/trace/")) return "Trace detail";
  const base = `/${pathname.split("/").filter(Boolean)[0] ?? ""}`;
  return TITLES[base] ?? "SentinelLLM";
}

export function Topbar() {
  const pathname = usePathname();
  const { timeRange, setTimeRange, environment, setEnvironment } = useFilters();
  const base = pathname ? `/${pathname.split("/").filter(Boolean)[0] ?? ""}` : "";
  const showTimeRange = TIME_RANGE_ROUTES.has(base);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-base-700 bg-base-900 px-6">
      <h1 className="text-sm font-semibold text-base-100">
        {pageTitle(pathname)}
      </h1>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5 text-xs text-base-400">
          Env
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
            className="rounded border border-base-600 bg-base-800 px-2 py-1 text-xs text-base-100 focus:border-accent focus:outline-none"
          >
            {ENVIRONMENTS.map((env) => (
              <option key={env} value={env}>
                {env}
              </option>
            ))}
          </select>
        </label>
        {showTimeRange && (
          <div className="flex rounded border border-base-600 bg-base-800 p-0.5">
            {TIME_RANGES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setTimeRange(r)}
                className={clsx(
                  "rounded px-2 py-1 text-xs font-mono transition-colors",
                  timeRange === r
                    ? "bg-accent/20 text-accent"
                    : "text-base-300 hover:text-base-100"
                )}
              >
                {r}
              </button>
            ))}
          </div>
        )}
      </div>
    </header>
  );
}
