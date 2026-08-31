"use client";

import {
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
import { Panel } from "@/components/Panel";
import { MetricCard } from "@/components/MetricCard";
import { ErrorState, Skeleton } from "@/components/StateViews";
import { formatCost } from "@/lib/format";

export default function CostPage() {
  const { timeRange } = useFilters();
  const { data, loading, error, refetch } = useFetch(
    () => api.getCostSummary(timeRange === "1h" ? "7d" : timeRange),
    [timeRange]
  );

  return (
    <div className="space-y-6">
      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MetricCard
            label="Total cost"
            value={data ? formatCost(data.total_cost) : ""}
            loading={loading || !data}
          />
          <MetricCard
            label="Models tracked"
            value={data ? String(data.by_model.length) : ""}
            loading={loading || !data}
          />
          <MetricCard
            label="Applications tracked"
            value={data ? String(data.by_application.length) : ""}
            loading={loading || !data}
          />
        </div>
      )}

      {!error && data?.insight_text && (
        <Panel className="border-accent/30 bg-accent/5">
          <p className="text-sm text-base-100">{data.insight_text}</p>
        </Panel>
      )}

      {!error && (
        <Panel title="Daily cost">
          {loading || !data ? (
            <Skeleton className="h-56 w-full" />
          ) : data.daily.length === 0 ? (
            <p className="py-8 text-center text-xs text-base-400">
              No daily cost data for this range.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" minTickGap={20} />
                <YAxis width={56} tickFormatter={(v) => `$${v}`} />
                <Tooltip formatter={(v: number) => formatCost(v)} />
                <Line
                  type="monotone"
                  dataKey="cost"
                  stroke="#22d3ee"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {!error && (
          <Panel title="Cost by model">
            {loading || !data ? (
              <Skeleton className="h-56 w-full" />
            ) : data.by_model.length === 0 ? (
              <p className="py-8 text-center text-xs text-base-400">No model cost data.</p>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(180, data.by_model.length * 32)}>
                <BarChart data={data.by_model} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tickFormatter={(v) => `$${v}`} />
                  <YAxis dataKey="model" type="category" width={120} />
                  <Tooltip formatter={(v: number) => formatCost(v)} />
                  <Bar dataKey="cost" fill="#a78bfa" radius={[0, 2, 2, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>
        )}
        {!error && (
          <Panel title="Cost by application">
            {loading || !data ? (
              <Skeleton className="h-56 w-full" />
            ) : data.by_application.length === 0 ? (
              <p className="py-8 text-center text-xs text-base-400">
                No application cost data.
              </p>
            ) : (
              <ResponsiveContainer
                width="100%"
                height={Math.max(180, data.by_application.length * 32)}
              >
                <BarChart data={data.by_application} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tickFormatter={(v) => `$${v}`} />
                  <YAxis dataKey="application_id" type="category" width={120} />
                  <Tooltip formatter={(v: number) => formatCost(v)} />
                  <Bar dataKey="cost" fill="#34d399" radius={[0, 2, 2, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}
