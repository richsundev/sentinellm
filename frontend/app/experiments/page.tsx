"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable, EmptyState } from "@/components/StateViews";
import type { Experiment } from "@/lib/types";
import { formatCost, formatDate, formatMs, formatPercent } from "@/lib/format";

export default function ExperimentsPage() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listExperiments({ limit: 200 }),
    []
  );
  const [selected, setSelected] = useState<string[]>([]);

  function toggleSelect(id: string) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  }

  const comparison = useMemo(() => {
    if (!data) return null;
    const chosen = data.items.filter((e) => selected.includes(e.id));
    if (chosen.length !== 2) return null;
    const metrics: { key: keyof Experiment; label: string; pct?: boolean }[] = [
      { key: "faithfulness", label: "Faithfulness", pct: true },
      { key: "relevance", label: "Relevance", pct: true },
      { key: "hallucination_rate", label: "Hallucination rate", pct: true },
      { key: "pass_rate", label: "Pass rate", pct: true },
    ];
    return metrics.map((m) => ({
      metric: m.label,
      [chosen[0].name]: chosen[0][m.key] as number,
      [chosen[1].name]: chosen[1][m.key] as number,
    }));
  }, [data, selected]);

  const chosenExperiments = data?.items.filter((e) => selected.includes(e.id)) ?? [];

  const columns: Column<Experiment>[] = [
    {
      key: "select",
      header: "",
      render: (e) => (
        <input
          type="checkbox"
          checked={selected.includes(e.id)}
          onChange={() => toggleSelect(e.id)}
          onClick={(evt) => evt.stopPropagation()}
          className="h-3.5 w-3.5 accent-cyan-400"
        />
      ),
    },
    {
      key: "name",
      header: "Name",
      render: (e) => <span className="font-medium text-base-100">{e.name}</span>,
      sortValue: (e) => e.name,
    },
    {
      key: "model",
      header: "Model",
      render: (e) => <span className="font-mono text-xs">{e.model}</span>,
      sortValue: (e) => e.model,
    },
    {
      key: "prompt",
      header: "Prompt",
      render: (e) => (
        <span className="font-mono text-xs">
          {e.prompt_id} v{e.prompt_version}
        </span>
      ),
      sortValue: (e) => `${e.prompt_id}-${e.prompt_version}`,
    },
    {
      key: "dataset_id",
      header: "Dataset",
      render: (e) => <span className="font-mono text-xs">{e.dataset_id}</span>,
    },
    {
      key: "faithfulness",
      header: "Faithfulness",
      align: "right",
      render: (e) => formatPercent(e.faithfulness),
      sortValue: (e) => e.faithfulness,
    },
    {
      key: "relevance",
      header: "Relevance",
      align: "right",
      render: (e) => formatPercent(e.relevance),
      sortValue: (e) => e.relevance,
    },
    {
      key: "hallucination_rate",
      header: "Hallucination",
      align: "right",
      render: (e) => formatPercent(e.hallucination_rate),
      sortValue: (e) => e.hallucination_rate,
    },
    {
      key: "p95_latency_ms",
      header: "P95 latency",
      align: "right",
      render: (e) => formatMs(e.p95_latency_ms),
      sortValue: (e) => e.p95_latency_ms,
    },
    {
      key: "cost_per_request",
      header: "Cost / req",
      align: "right",
      render: (e) => formatCost(e.cost_per_request),
      sortValue: (e) => e.cost_per_request,
    },
    {
      key: "git_commit",
      header: "Commit",
      render: (e) => (
        <span className="font-mono text-[10px] text-base-400">
          {e.git_commit.slice(0, 8)}
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Created",
      render: (e) => <span className="font-mono text-xs">{formatDate(e.created_at)}</span>,
      sortValue: (e) => e.created_at,
    },
  ];

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} onRetry={refetch} />}
      {!error && (loading || !data) && <SkeletonTable rows={8} cols={10} />}

      {!error && data && (
        <>
          <p className="text-xs text-base-400">
            Select up to two experiments (checkbox) to compare metrics side-by-side.
          </p>
          <DataTable<Experiment>
            columns={columns}
            rows={data.items}
            rowKey={(e) => e.id}
            emptyTitle="No experiments"
            emptyMessage="Run an evaluation experiment to see results here."
            defaultSortKey="created_at"
          />

          <Panel title="Comparison">
            {selected.length !== 2 ? (
              <EmptyState
                title="Select two experiments"
                message="Check two rows above to compare their metrics."
              />
            ) : (
              comparison && (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={comparison}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="metric" />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar
                      dataKey={chosenExperiments[0]?.name}
                      fill="#22d3ee"
                      radius={[2, 2, 0, 0]}
                    />
                    <Bar
                      dataKey={chosenExperiments[1]?.name}
                      fill="#a78bfa"
                      radius={[2, 2, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
