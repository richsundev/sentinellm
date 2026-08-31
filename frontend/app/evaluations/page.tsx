"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, Pagination, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { Evaluation } from "@/lib/types";
import { formatDate, formatPercent, truncate } from "@/lib/format";

const LIMIT = 25;

export default function EvaluationsPage() {
  const router = useRouter();
  const [offset, setOffset] = useState(0);

  const { data, loading, error, refetch } = useFetch(
    () => api.listEvaluations({ limit: LIMIT, offset }),
    [offset]
  );

  const passRates = useMemo(() => {
    if (!data) return [];
    const byMetric = new Map<string, { pass: number; total: number }>();
    for (const ev of data.items) {
      for (const m of ev.metrics) {
        const bucket = byMetric.get(m.metric_name) ?? { pass: 0, total: 0 };
        bucket.total += 1;
        if (m.passed) bucket.pass += 1;
        byMetric.set(m.metric_name, bucket);
      }
    }
    return Array.from(byMetric.entries()).map(([name, v]) => ({
      name,
      rate: v.total > 0 ? v.pass / v.total : null,
    }));
  }, [data]);

  const columns: Column<Evaluation>[] = [
    {
      key: "trace_id",
      header: "Trace ID",
      render: (e) => (
        <span className="font-mono text-xs text-accent">
          {truncate(e.trace_id, 20)}
        </span>
      ),
      sortValue: (e) => e.trace_id,
    },
    {
      key: "created_at",
      header: "Time",
      render: (e) => <span className="font-mono text-xs">{formatDate(e.created_at)}</span>,
      sortValue: (e) => e.created_at,
    },
    {
      key: "overall_quality",
      header: "Overall quality",
      align: "right",
      render: (e) => e.overall_quality.toFixed(2),
      sortValue: (e) => e.overall_quality,
    },
    {
      key: "metrics",
      header: "Metrics",
      render: (e) => (
        <div className="flex flex-wrap gap-1">
          {e.metrics.map((m) => (
            <StatusBadge
              key={m.metric_name}
              status={`${m.metric_name} ${m.score.toFixed(2)}`}
              tone={m.passed === false ? "err" : m.passed === true ? "ok" : "neutral"}
            />
          ))}
        </div>
      ),
    },
    {
      key: "hallucination",
      header: "Hallucination score",
      align: "right",
      render: (e) =>
        e.hallucination ? e.hallucination.hallucination_score.toFixed(2) : "—",
      sortValue: (e) => e.hallucination?.hallucination_score ?? -1,
    },
  ];

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (
        <Panel title="Pass rate by metric">
          {loading || !data ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <MetricCard key={i} label="" value="" loading />
              ))}
            </div>
          ) : passRates.length === 0 ? (
            <p className="text-xs text-base-400">No evaluations recorded yet.</p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {passRates.map((p) => (
                <MetricCard
                  key={p.name}
                  label={p.name.replace(/_/g, " ")}
                  value={formatPercent(p.rate)}
                />
              ))}
            </div>
          )}
        </Panel>
      )}

      {!error && (loading || !data) && <SkeletonTable rows={8} cols={5} />}

      {!error && data && (
        <>
          <DataTable<Evaluation>
            columns={columns}
            rows={data.items}
            rowKey={(e) => e.trace_id}
            onRowClick={(e) => router.push(`/trace/${encodeURIComponent(e.trace_id)}`)}
            emptyTitle="No evaluations found"
            emptyMessage="Evaluation runs will appear here once traces have been scored."
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
