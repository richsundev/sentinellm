"use client";

import { useState } from "react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, Skeleton, SkeletonTable } from "@/components/StateViews";
import type { ModelInfo, ModelStatus } from "@/lib/types";
import { formatMs, formatPercent } from "@/lib/format";

const STATUS_OPTIONS: ModelStatus[] = ["healthy", "degraded", "down"];

export default function ModelsPage() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listModels({ limit: 200 }),
    []
  );
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  async function handleStatusChange(modelId: string, status: ModelStatus) {
    setUpdatingId(modelId);
    try {
      await api.updateModel(modelId, { status });
      await refetch();
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleResetToAuto(modelId: string) {
    setUpdatingId(modelId);
    try {
      await api.updateModel(modelId, { status_auto: true });
      await refetch();
    } finally {
      setUpdatingId(null);
    }
  }

  const columns: Column<ModelInfo>[] = [
    {
      key: "name",
      header: "Model",
      render: (m) => <span className="font-medium text-base-100">{m.name}</span>,
      sortValue: (m) => m.name,
    },
    {
      key: "provider",
      header: "Provider",
      render: (m) => m.provider,
      sortValue: (m) => m.provider,
    },
    {
      key: "input_price_per_1k",
      header: "In $/1K",
      align: "right",
      render: (m) => `$${m.input_price_per_1k.toFixed(4)}`,
      sortValue: (m) => m.input_price_per_1k,
    },
    {
      key: "output_price_per_1k",
      header: "Out $/1K",
      align: "right",
      render: (m) => `$${m.output_price_per_1k.toFixed(4)}`,
      sortValue: (m) => m.output_price_per_1k,
    },
    {
      key: "context_window",
      header: "Context",
      align: "right",
      render: (m) => m.context_window.toLocaleString(),
      sortValue: (m) => m.context_window,
    },
    {
      key: "avg_quality",
      header: "Avg quality",
      align: "right",
      render: (m) => (m.avg_quality !== null ? formatPercent(m.avg_quality) : "—"),
      sortValue: (m) => m.avg_quality ?? -1,
    },
    {
      key: "avg_latency_ms",
      header: "Avg latency",
      align: "right",
      render: (m) => formatMs(m.avg_latency_ms),
      sortValue: (m) => m.avg_latency_ms ?? -1,
    },
    {
      key: "status",
      header: "Status",
      render: (m) => (
        <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <select
            value={m.status}
            disabled={updatingId === m.id}
            onChange={(e) => handleStatusChange(m.id, e.target.value as ModelStatus)}
            title={m.status_reason ?? undefined}
            className="rounded border border-base-600 bg-base-800 px-1.5 py-0.5 text-[11px] text-base-200 disabled:cursor-not-allowed"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {m.status_auto ? (
            <span className="text-[10px] text-base-500" title={m.status_reason ?? "auto-managed"}>
              auto
            </span>
          ) : (
            <button
              type="button"
              onClick={() => handleResetToAuto(m.id)}
              disabled={updatingId === m.id}
              title="Manually pinned — click to let the health checker manage this again"
              className="text-[10px] text-accent underline decoration-dotted hover:text-accent/80 disabled:cursor-not-allowed"
            >
              manual
            </button>
          )}
        </div>
      ),
      sortValue: (m) => m.status,
    },
  ];

  const scatterData = (data?.items ?? [])
    .filter((m) => m.avg_quality !== null)
    .map((m) => ({
      name: m.name,
      cost: m.input_price_per_1k + m.output_price_per_1k,
      quality: (m.avg_quality ?? 0) * (Math.abs(m.avg_quality ?? 0) <= 1.5 ? 100 : 1),
      latency: m.avg_latency_ms ?? 0,
    }));

  return (
    <div className="space-y-4">
      <RegisterModelPanel onCreated={refetch} />

      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (
        <Panel title="Quality vs cost">
          {loading || !data ? (
            <Skeleton className="h-64 w-full" />
          ) : scatterData.length === 0 ? (
            <p className="py-8 text-center text-xs text-base-400">
              No models with quality data yet.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="cost"
                  name="Combined $/1K tokens"
                  tickFormatter={(v) => `$${v.toFixed(3)}`}
                />
                <YAxis
                  type="number"
                  dataKey="quality"
                  name="Avg quality"
                  unit="%"
                  width={44}
                />
                <ZAxis type="number" dataKey="latency" range={[60, 300]} name="Avg latency" unit="ms" />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<ScatterTooltip />} />
                <Scatter data={scatterData} fill="#22d3ee" />
              </ScatterChart>
            </ResponsiveContainer>
          )}
        </Panel>
      )}

      {!error && (loading || !data) && <SkeletonTable rows={6} cols={8} />}
      {!error && data && (
        <DataTable<ModelInfo>
          columns={columns}
          rows={data.items}
          rowKey={(m) => m.id}
          emptyTitle="No models registered"
          emptyMessage="No models are registered in the model registry yet."
          defaultSortKey="name"
          defaultSortDir="asc"
        />
      )}
    </div>
  );
}

function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: { name: string; cost: number; quality: number; latency: number } }[];
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded border border-base-600 bg-base-900 px-2.5 py-1.5 text-xs shadow-lg">
      <div className="mb-1 font-mono text-base-100">{p.name}</div>
      <div className="text-base-400">cost: ${p.cost.toFixed(4)}/1K</div>
      <div className="text-base-400">quality: {p.quality.toFixed(1)}%</div>
      <div className="text-base-400">latency: {p.latency.toFixed(0)}ms</div>
    </div>
  );
}

function RegisterModelPanel({ onCreated }: { onCreated: () => void }) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [inputPrice, setInputPrice] = useState("");
  const [outputPrice, setOutputPrice] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const canSubmit = id.trim() && name.trim() && provider.trim() && inputPrice !== "" && outputPrice !== "";

  async function handleCreate() {
    if (!canSubmit) return;
    setCreating(true);
    setCreateError(null);
    try {
      await api.createModel({
        id: id.trim(),
        name: name.trim(),
        provider: provider.trim(),
        input_price_per_1k: Number(inputPrice),
        output_price_per_1k: Number(outputPrice),
      });
      setId("");
      setName("");
      setProvider("");
      setInputPrice("");
      setOutputPrice("");
      onCreated();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to register model");
    } finally {
      setCreating(false);
    }
  }

  return (
    <Panel
      title="Register a model"
      action={<span className="text-[10px] text-base-500">adds it to the router&apos;s candidate pool + pricing catalog</span>}
    >
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <LabeledInput label="ID" value={id} onChange={setId} placeholder="openai:gpt-4o-mini" mono />
        <LabeledInput label="Name" value={name} onChange={setName} placeholder="gpt-4o-mini" />
        <LabeledInput label="Provider" value={provider} onChange={setProvider} placeholder="openai" />
        <LabeledInput label="In $/1K" value={inputPrice} onChange={setInputPrice} placeholder="0.00015" width="w-24" />
        <LabeledInput label="Out $/1K" value={outputPrice} onChange={setOutputPrice} placeholder="0.0006" width="w-24" />
        <button
          type="button"
          onClick={handleCreate}
          disabled={!canSubmit || creating}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {creating ? "Registering…" : "Register"}
        </button>
      </div>
      {createError && <p className="mt-2 text-xs text-red-400">{createError}</p>}
    </Panel>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  placeholder,
  mono,
  width = "w-36",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  width?: string;
}) {
  return (
    <label className="block text-[10px] uppercase tracking-wide text-base-500">
      {label}
      <div className="mt-1">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={`${width} rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 placeholder:text-base-500 ${mono ? "font-mono" : ""}`}
        />
      </div>
    </label>
  );
}
