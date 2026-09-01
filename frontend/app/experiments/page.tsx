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
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable, EmptyState } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
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
      <RunExperimentPanel onRun={refetch} />

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
            emptyMessage="Run an evaluation experiment above to see results here."
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

          {selected.length === 2 && (
            <DetailedComparisonPanel idA={selected[0]} idB={selected[1]} />
          )}
        </>
      )}
    </div>
  );
}

function RunExperimentPanel({ onRun }: { onRun: () => void }) {
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [promptId, setPromptId] = useState("");
  const [promptVersion, setPromptVersion] = useState("1");
  const [datasetId, setDatasetId] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  async function handleRun() {
    if (!name.trim() || !model.trim() || !promptId.trim() || !datasetId.trim()) return;
    setRunning(true);
    setRunError(null);
    try {
      await api.runExperiment({
        name: name.trim(),
        model: model.trim(),
        prompt_id: promptId.trim(),
        prompt_version: Number(promptVersion) || 1,
        dataset_id: datasetId.trim(),
      });
      setName("");
      onRun();
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : "Experiment run failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <Panel
      title="Run an evaluation experiment"
      action={
        <span className="text-[10px] text-base-500">
          runs the real generation + evaluation pipeline against every dataset record
        </span>
      }
    >
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. flash-vs-pro"
            className="w-36 rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 placeholder:text-base-500"
          />
        </Field>
        <Field label="Model">
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="mock:sentinel-flash"
            className="w-40 rounded border border-base-600 bg-base-800 px-2 py-1.5 font-mono text-base-200 placeholder:text-base-500"
          />
        </Field>
        <Field label="Prompt ID">
          <input
            value={promptId}
            onChange={(e) => setPromptId(e.target.value)}
            placeholder="support-answer"
            className="w-32 rounded border border-base-600 bg-base-800 px-2 py-1.5 font-mono text-base-200 placeholder:text-base-500"
          />
        </Field>
        <Field label="Version">
          <input
            value={promptVersion}
            onChange={(e) => setPromptVersion(e.target.value)}
            className="w-14 rounded border border-base-600 bg-base-800 px-2 py-1.5 font-mono text-base-200"
          />
        </Field>
        <Field label="Dataset ID">
          <input
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value)}
            placeholder="from /datasets"
            className="w-40 rounded border border-base-600 bg-base-800 px-2 py-1.5 font-mono text-base-200 placeholder:text-base-500"
          />
        </Field>
        <button
          type="button"
          onClick={handleRun}
          disabled={running || !name.trim() || !model.trim() || !promptId.trim() || !datasetId.trim()}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {running ? "Running…" : "Run"}
        </button>
      </div>
      {runError && <p className="mt-2 text-xs text-red-400">{runError}</p>}
    </Panel>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-[10px] uppercase tracking-wide text-base-500">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function DetailedComparisonPanel({ idA, idB }: { idA: string; idB: string }) {
  const { data, loading, error } = useFetch(() => api.compareExperiments(idA, idB), [idA, idB]);

  return (
    <Panel title="Metric-by-metric verdict" action={<span className="text-[10px] text-base-500">computed server-side</span>}>
      {error && <ErrorState message={error} />}
      {!error && (loading || !data) && <SkeletonTable rows={6} cols={5} />}
      {!error && data && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-base-500">
              <th className="pb-2">Metric</th>
              <th className="pb-2 text-right">{data.experiment_a.name}</th>
              <th className="pb-2 text-right">{data.experiment_b.name}</th>
              <th className="pb-2 text-right">Δ</th>
              <th className="pb-2 text-right">Winner</th>
            </tr>
          </thead>
          <tbody>
            {data.metrics.map((m) => (
              <tr key={m.metric_name} className="border-t border-base-800">
                <td className="py-1.5 font-mono text-base-300">{m.metric_name}</td>
                <td className="py-1.5 text-right font-mono">{m.value_a.toFixed(4)}</td>
                <td className="py-1.5 text-right font-mono">{m.value_b.toFixed(4)}</td>
                <td className="py-1.5 text-right font-mono text-base-400">
                  {m.delta_pct !== null ? `${m.delta_pct > 0 ? "+" : ""}${m.delta_pct.toFixed(1)}%` : "—"}
                </td>
                <td className="py-1.5 text-right">
                  <StatusBadge
                    status={m.better === "tie" ? "tie" : m.better === "a" ? data.experiment_a.name : data.experiment_b.name}
                    tone={m.better === "tie" ? "neutral" : "ok"}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
