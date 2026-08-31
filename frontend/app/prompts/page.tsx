"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, SkeletonTable, EmptyState } from "@/components/StateViews";
import type { PromptVersion } from "@/lib/types";
import { formatDate } from "@/lib/format";

export default function PromptsPage() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listPrompts({ limit: 500 }),
    []
  );
  const [selected, setSelected] = useState<PromptVersion | null>(null);

  const groups = useMemo(() => {
    if (!data) return [];
    const map = new Map<string, PromptVersion[]>();
    for (const p of data.items) {
      const list = map.get(p.prompt_id) ?? [];
      list.push(p);
      map.set(p.prompt_id, list);
    }
    return Array.from(map.entries()).map(([promptId, versions]) => ({
      promptId,
      versions: versions.sort((a, b) => b.version - a.version),
    }));
  }, [data]);

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        {error && <ErrorState message={error} onRetry={refetch} />}
        {!error && (loading || !data) && <SkeletonTable rows={6} cols={4} />}
        {!error && data && groups.length === 0 && (
          <EmptyState title="No prompts" message="No prompt versions have been registered yet." />
        )}
        {!error &&
          groups.map((g) => (
            <Panel key={g.promptId} title={g.promptId}>
              <div className="space-y-1.5">
                {g.versions.map((v) => (
                  <button
                    key={v.version}
                    type="button"
                    onClick={() => setSelected(v)}
                    className="flex w-full items-center justify-between rounded border border-base-700 bg-base-900 px-3 py-2 text-left text-xs hover:border-accent/50"
                  >
                    <span className="font-mono text-base-200">v{v.version}</span>
                    <span className="text-base-400">{v.author}</span>
                    <span className="font-mono text-base-500">{formatDate(v.created_at)}</span>
                    <StatusBadge status={v.status} />
                  </button>
                ))}
              </div>
            </Panel>
          ))}
      </div>

      <div className="lg:sticky lg:top-0 lg:h-fit">
        <Panel title="Version detail">
          {!selected ? (
            <p className="text-xs text-base-400">
              Select a version from the list to inspect its template and variables.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-base-100">
                  {selected.prompt_id} · v{selected.version}
                </span>
                <StatusBadge status={selected.status} />
              </div>
              <div className="text-xs text-base-400">
                by {selected.author} · {formatDate(selected.created_at)}
              </div>
              <div>
                <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                  Variables
                </div>
                <div className="flex flex-wrap gap-1">
                  {selected.variables.length === 0 ? (
                    <span className="text-xs text-base-500">none</span>
                  ) : (
                    selected.variables.map((v) => (
                      <span
                        key={v}
                        className="rounded border border-base-600 bg-base-800 px-1.5 py-0.5 font-mono text-[10px] text-base-200"
                      >
                        {`{{${v}}}`}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div>
                <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                  Template
                </div>
                <pre className="whitespace-pre-wrap rounded bg-base-900 p-3 text-xs text-base-300">
                  {selected.template}
                </pre>
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
