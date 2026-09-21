"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { API_BASE_URL } from "@/lib/api";

const NAV_ITEMS: { href: string; label: string; icon: string; alsoActiveOn?: string }[] = [
  { href: "/overview", label: "Overview", icon: "◈" },
  // The detail page lives at /trace/[id] (singular), so it needs its own match.
  { href: "/traces", label: "Traces", icon: "≡", alsoActiveOn: "/trace" },
  { href: "/evaluations", label: "Evaluations", icon: "✓" },
  { href: "/regressions", label: "Regressions", icon: "!" },
  { href: "/routing", label: "Routing", icon: "⇄" },
  { href: "/rollouts", label: "Rollouts", icon: "⇉" },
  { href: "/models", label: "Models", icon: "◆" },
  { href: "/experiments", label: "Experiments", icon: "⚗" },
  { href: "/prompts", label: "Prompts", icon: "¶" },
  { href: "/datasets", label: "Datasets", icon: "▤" },
  { href: "/cost", label: "Cost", icon: "$" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-base-700 bg-base-900">
      <div className="flex items-center gap-2 border-b border-base-700 px-4 py-4">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-accent/15 font-mono text-sm font-bold text-accent">
          S
        </div>
        <div>
          <div className="text-sm font-semibold tracking-tight text-base-50">
            SentinelLLM
          </div>
          <div className="text-[10px] uppercase tracking-wider text-base-400">
            Observability
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_ITEMS.map((item) => {
          const prefixes = [item.href, item.alsoActiveOn].filter((p): p is string => !!p);
          const active = prefixes.some(
            (prefix) => pathname === prefix || pathname?.startsWith(`${prefix}/`)
          );
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-2.5 px-4 py-2 text-sm transition-colors",
                active
                  ? "border-r-2 border-accent bg-accent/10 text-accent"
                  : "text-base-300 hover:bg-base-800 hover:text-base-100"
              )}
            >
              <span className="w-4 text-center font-mono text-xs">
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-base-700 px-4 py-3">
        <div className="flex items-center gap-2 text-[11px] text-base-400">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" />
          <span className="truncate font-mono">{API_BASE_URL}</span>
        </div>
      </div>
    </aside>
  );
}
