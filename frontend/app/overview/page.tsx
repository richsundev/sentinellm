"use client";

import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useFilters } from "@/lib/filters-context";
import { MetricCard } from "@/components/MetricCard";
import { Panel } from "@/components/Panel";
import { FilterBar } from "@/components/FilterBar";
import { ErrorState, Skeleton } from "@/components/StateViews";
import { DataTable, type Column } from "@/components/DataTable";
import {
  formatCompactNumber,
  formatCost,
  formatMs,
  formatPercent,
} from "@/lib/format";

const CHART_COLOR = "#22d3ee";

interface ProviderReliability {
  provider: string;
  success_rate: number;
}

export default function OverviewPage() {
  const { timeRange } = useFilters();
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("");
  const [applicationId, setApplicationId] = useState("");

  const { data, loading, error, refetch } = useFetch(
    () => api.getOverviewMetrics(timeRange),
    [timeRange, model, provider, applicationId]
  );

  const kpis: { label: string; value: string; sublabel?: string }[] = data
    ? [
        { label: "Request volume", value: formatCompactNumber(data.request_volume) },
        { label: "Error rate", value: formatPercent(data.error_rate) },
        { label: "P50 latency", value: formatMs(data.p50_latency_ms) },
        { label: "P95 latency", value: formatMs(data.p95_latency_ms) },
        { label: "P99 latency", value: formatMs(data.p99_latency_ms) },
        { label: "Avg cost / req", value: formatCost(data.avg_cost_per_request) },
        {
          label: "Avg tokens / req",
          value: formatCompactNumber(data.avg_tokens_per_request),
        },
        { label: "Hallucination rate", value: formatPercent(data.hallucination_rate) },
        { label: "Avg faithfulness", value: formatPercent(data.avg_faithfulness) },
        { label: "Avg relevance", value: formatPercent(data.avg_relevance) },
      ]
    : [];

  const providerColumns: Column<ProviderReliability>[] = [
    {
      key: "provider",
      header: "Provider",
      render: (r) => <span className="font-mono">{r.provider}</span>,
      sortValue: (r) => r.provider,
    },
    {
      key: "success_rate",
      header: "Success rate",
      align: "right",
      render: (r) => formatPercent(r.success_rate),
      sortValue: (r) => r.success_rate,
    },
  ];

  return (
    <div className="space-y-6">
      <FilterBar
        model={model}
        onModelChange={setModel}
        provider={provider}
        onProviderChange={setProvider}
        applicationId={applicationId}
        onApplicationIdChange={setApplicationId}
      />

      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {loading || !data
            ? Array.from({ length: 10 }).map((_, i) => (
                <MetricCard key={i} label="" value="" loading />
              ))
            : kpis.map((k) => (
                <MetricCard key={k.label} label={k.label} value={k.value} />
              ))}
        </div>
      )}

      {!error && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Panel title="Request volume">
            {loading || !data ? (
              <Skeleton className="h-52 w-full" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={data.timeseries}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="timestamp" tickFormatter={shortTime} minTickGap={30} />
                  <YAxis width={36} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="volume"
                    stroke={CHART_COLOR}
                    fill={CHART_COLOR}
                    fillOpacity={0.15}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Panel>
          <Panel title="P95 latency">
            {loading || !data ? (
              <Skeleton className="h-52 w-full" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={data.timeseries}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="timestamp" tickFormatter={shortTime} minTickGap={30} />
                  <YAxis width={44} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line
                    type="monotone"
                    dataKey="p95_latency_ms"
                    stroke="#fbbf24"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Panel>
          <Panel title="Cost">
            {loading || !data ? (
              <Skeleton className="h-52 w-full" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.timeseries}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="timestamp" tickFormatter={shortTime} minTickGap={30} />
                  <YAxis width={44} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="cost" fill="#a78bfa" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>
        </div>
      )}

      {!error && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Model usage breakdown">
            {loading || !data ? (
              <Skeleton className="h-48 w-full" />
            ) : data.model_usage.length === 0 ? (
              <p className="py-8 text-center text-xs text-base-400">
                No model usage data.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(180, data.model_usage.length * 32)}>
                <BarChart data={data.model_usage} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" />
                  <YAxis dataKey="model" type="category" width={120} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="count" fill={CHART_COLOR} radius={[0, 2, 2, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>
          <Panel title="Provider reliability">
            {loading || !data ? (
              <Skeleton className="h-48 w-full" />
            ) : (
              <DataTable<ProviderReliability>
                columns={providerColumns}
                rows={data.provider_reliability as ProviderReliability[]}
                rowKey={(r) => r.provider}
                emptyTitle="No providers"
                emptyMessage="No provider reliability data for this range."
                defaultSortKey="success_rate"
              />
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

function shortTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color?: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-base-600 bg-base-900 px-2.5 py-1.5 text-xs shadow-lg">
      <div className="mb-1 text-base-400">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-1.5 font-mono text-base-100">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: p.color }} />
          {p.name}: {typeof p.value === "number" ? p.value.toLocaleString() : p.value}
        </div>
      ))}
    </div>
  );
}
