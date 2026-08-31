"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, Pagination, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { Regression, Severity } from "@/lib/types";
import { formatDate, formatPercent } from "@/lib/format";

const LIMIT = 25;
const SEVERITY_RANK: Record<Severity, number> = {
  critical: 3,
  high: 2,
  medium: 1,
  low: 0,
};

export default function RegressionsPage() {
  const [offset, setOffset] = useState(0);
  const { data, loading, error, refetch } = useFetch(
    () => api.listRegressions({ limit: LIMIT, offset }),
    [offset]
  );

  const spotlight = useMemo(() => {
    if (!data || data.items.length === 0) return null;
    return [...data.items].sort(
      (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]
    )[0];
  }, [data]);

  const columns: Column<Regression>[] = [
    {
      key: "detected_at",
      header: "Detected",
      render: (r) => <span className="font-mono text-xs">{formatDate(r.detected_at)}</span>,
      sortValue: (r) => r.detected_at,
    },
    {
      key: "metric_name",
      header: "Metric",
      render: (r) => <span className="font-mono text-xs">{r.metric_name}</span>,
      sortValue: (r) => r.metric_name,
    },
    {
      key: "application_id",
      header: "Application",
      render: (r) => r.application_id,
      sortValue: (r) => r.application_id,
    },
    {
      key: "previous_value",
      header: "Previous",
      align: "right",
      render: (r) => r.previous_value.toFixed(3),
      sortValue: (r) => r.previous_value,
    },
    {
      key: "new_value",
      header: "New",
      align: "right",
      render: (r) => r.new_value.toFixed(3),
      sortValue: (r) => r.new_value,
    },
    {
      key: "delta_pct",
      header: "Delta",
      align: "right",
      render: (r) => (
        <span className={r.delta_pct < 0 ? "text-err" : "text-ok"}>
          {r.delta_pct > 0 ? "+" : ""}
          {formatPercent(r.delta_pct)}
        </span>
      ),
      sortValue: (r) => r.delta_pct,
    },
    {
      key: "severity",
      header: "Severity",
      render: (r) => <StatusBadge status={r.severity} />,
      sortValue: (r) => SEVERITY_RANK[r.severity],
    },
    {
      key: "likely_cause",
      header: "Likely cause",
      render: (r) => <span className="text-xs text-base-300">{r.likely_cause}</span>,
    },
  ];

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (loading || !data) && <SkeletonTable rows={2} cols={1} />}

      {!error && spotlight && (
        <Panel
          title="Highest-severity regression"
          className="border-crit/40 bg-crit/5"
        >
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={spotlight.severity} />
            <span className="font-mono text-sm text-base-100">
              {spotlight.metric_name}
            </span>
            <span className="text-xs text-base-400">on {spotlight.application_id}</span>
            <span className="font-mono text-sm">
              {spotlight.previous_value.toFixed(3)} → {spotlight.new_value.toFixed(3)}{" "}
              <span className={spotlight.delta_pct < 0 ? "text-err" : "text-ok"}>
                ({spotlight.delta_pct > 0 ? "+" : ""}
                {formatPercent(spotlight.delta_pct)})
              </span>
            </span>
            <span className="text-xs text-base-500">
              detected {formatDate(spotlight.detected_at)}
            </span>
          </div>
          <p className="mt-2 text-xs text-base-300">{spotlight.likely_cause}</p>
        </Panel>
      )}

      {!error && (loading || !data) && <SkeletonTable rows={8} cols={8} />}

      {!error && data && (
        <>
          <DataTable<Regression>
            columns={columns}
            rows={data.items}
            rowKey={(r) => r.id}
            emptyTitle="No regressions detected"
            emptyMessage="No quality or performance regressions have been detected."
            defaultSortKey="detected_at"
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
