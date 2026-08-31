"use client";

import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import type { Dataset } from "@/lib/types";
import { formatCompactNumber, formatDate } from "@/lib/format";

export default function DatasetsPage() {
  const router = useRouter();
  const { data, loading, error, refetch } = useFetch(
    () => api.listDatasets({ limit: 100 }),
    []
  );

  const columns: Column<Dataset>[] = [
    {
      key: "name",
      header: "Name",
      render: (d) => <span className="font-medium text-base-100">{d.name}</span>,
      sortValue: (d) => d.name,
    },
    {
      key: "version",
      header: "Version",
      render: (d) => <span className="font-mono text-xs">{d.version}</span>,
      sortValue: (d) => d.version,
    },
    {
      key: "record_count",
      header: "Records",
      align: "right",
      render: (d) => formatCompactNumber(d.record_count),
      sortValue: (d) => d.record_count,
    },
    {
      key: "created_at",
      header: "Created",
      render: (d) => <span className="font-mono text-xs">{formatDate(d.created_at)}</span>,
      sortValue: (d) => d.created_at,
    },
  ];

  return (
    <div className="space-y-4">
      {error && <ErrorState message={error} onRetry={refetch} />}
      {!error && (loading || !data) && <SkeletonTable rows={6} cols={4} />}
      {!error && data && (
        <DataTable<Dataset>
          columns={columns}
          rows={data.items}
          rowKey={(d) => d.id}
          onRowClick={(d) => router.push(`/datasets/${encodeURIComponent(d.id)}`)}
          emptyTitle="No datasets"
          emptyMessage="No evaluation datasets have been registered yet."
          defaultSortKey="created_at"
        />
      )}
    </div>
  );
}
