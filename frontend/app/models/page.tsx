"use client";

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
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, Skeleton, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { ModelInfo } from "@/lib/types";
import { formatMs, formatPercent } from "@/lib/format";

export default function ModelsPage() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listModels({ limit: 200 }),
    []
  );

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
      render: (m) => <StatusBadge status={m.status} />,
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
