"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, Pagination, type Column } from "@/components/DataTable";
import { ErrorState, Skeleton, SkeletonTable } from "@/components/StateViews";
import type { RoutingDecision } from "@/lib/types";
import { formatDate, truncate } from "@/lib/format";

const LIMIT = 25;

export default function RoutingPage() {
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const { data, loading, error, refetch } = useFetch(
    () => api.listRoutingDecisions({ limit: LIMIT, offset }),
    [offset]
  );

  const modelCounts = useMemo(() => {
    if (!data) return [];
    const map = new Map<string, number>();
    for (const d of data.items) {
      map.set(d.selected_model, (map.get(d.selected_model) ?? 0) + 1);
    }
    return Array.from(map.entries())
      .map(([model, count]) => ({ model, count }))
      .sort((a, b) => b.count - a.count);
  }, [data]);

  const columns: Column<RoutingDecision>[] = [
    {
      key: "created_at",
      header: "Time",
      render: (d) => <span className="font-mono text-xs">{formatDate(d.created_at)}</span>,
      sortValue: (d) => d.created_at,
    },
    {
      key: "trace_id",
      header: "Trace ID",
      render: (d) => (
        <span className="font-mono text-xs text-accent">{truncate(d.trace_id, 18)}</span>
      ),
      sortValue: (d) => d.trace_id,
    },
    {
      key: "selected_model",
      header: "Selected model",
      render: (d) => <span className="font-mono text-xs">{d.selected_model}</span>,
      sortValue: (d) => d.selected_model,
    },
    {
      key: "reason",
      header: "Reason",
      render: (d) => <span className="text-xs text-base-300">{d.reason}</span>,
    },
    {
      key: "candidates",
      header: "Candidates",
      align: "right",
      render: (d) => d.candidates.length,
      sortValue: (d) => d.candidates.length,
    },
  ];

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (
        <Panel title="Model selection breakdown">
          {loading || !data ? (
            <Skeleton className="h-48 w-full" />
          ) : modelCounts.length === 0 ? (
            <p className="py-8 text-center text-xs text-base-400">
              No routing decisions in this page yet.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(160, modelCounts.length * 34)}>
              <BarChart data={modelCounts} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" allowDecimals={false} />
                <YAxis dataKey="model" type="category" width={130} />
                <Tooltip />
                <Bar dataKey="count" fill="#22d3ee" radius={[0, 2, 2, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Panel>
      )}

      {!error && (loading || !data) && <SkeletonTable rows={8} cols={5} />}

      {!error && data && (
        <>
          <DataTable<RoutingDecision>
            columns={columns}
            rows={data.items}
            rowKey={(d) => `${d.trace_id}-${d.created_at}`}
            onRowClick={(d) => router.push(`/trace/${encodeURIComponent(d.trace_id)}`)}
            emptyTitle="No routing decisions"
            emptyMessage="No routing decisions have been recorded yet."
            defaultSortKey="created_at"
          />
          <Pagination
            offset={data.offset}
            limit={data.limit}
            total={data.total}
            onPageChange={setOffset}
          />
        </>
      )}
    </div>
  );
}
