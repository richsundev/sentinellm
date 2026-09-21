"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useFilters } from "@/lib/filters-context";
import { FilterBar } from "@/components/FilterBar";
import { DataTable, Pagination, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { Trace } from "@/lib/types";
import { formatCost, formatDate, formatMs, truncate } from "@/lib/format";

const LIMIT = 25;

export default function TracesPage() {
  const router = useRouter();
  const { environment } = useFilters();
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [offset, setOffset] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  // The environment lives in the top bar, so changing it doesn't pass through
  // the filter handlers below; without this the page stays on (say) page 4 of a
  // result set that no longer has one.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOffset(0);
  }, [environment]);

  const activeFilters = {
    model: model.trim() || undefined,
    provider: provider.trim() || undefined,
    application_id: applicationId.trim() || undefined,
    environment: environment === "all" ? undefined : environment,
    status: status || undefined,
    q: search.trim() || undefined,
    tag: tag.trim() || undefined,
  };

  const { data, loading, error, refetch } = useFetch(
    () => api.listTraces({ limit: LIMIT, offset, ...activeFilters }),
    [model, provider, applicationId, environment, status, search, tag, offset]
  );

  async function handleExport() {
    setExporting(true);
    setExportError(null);
    try {
      await api.exportTracesCsv(activeFilters);
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  const columns: Column<Trace>[] = [
    {
      key: "created_at",
      header: "Time",
      render: (t) => <span className="font-mono text-xs">{formatDate(t.created_at)}</span>,
      sortValue: (t) => t.created_at,
    },
    {
      key: "trace_id",
      header: "Trace ID",
      render: (t) => (
        <span className="font-mono text-xs text-accent">{truncate(t.trace_id, 18)}</span>
      ),
      sortValue: (t) => t.trace_id,
    },
    {
      key: "application_id",
      header: "Application",
      render: (t) => t.application_id,
      sortValue: (t) => t.application_id,
    },
    {
      key: "model",
      header: "Model",
      render: (t) => <span className="font-mono text-xs">{t.model}</span>,
      sortValue: (t) => t.model,
    },
    {
      key: "provider",
      header: "Provider",
      render: (t) => t.provider,
      sortValue: (t) => t.provider,
    },
    {
      key: "status",
      header: "Status",
      render: (t) => <StatusBadge status={t.status} />,
      sortValue: (t) => t.status,
    },
    {
      key: "latency_ms",
      header: "Latency",
      align: "right",
      render: (t) => formatMs(t.latency_ms),
      sortValue: (t) => t.latency_ms,
    },
    {
      key: "estimated_cost",
      header: "Cost",
      align: "right",
      render: (t) => formatCost(t.estimated_cost),
      sortValue: (t) => t.estimated_cost,
    },
    {
      key: "quality",
      header: "Quality",
      align: "right",
      render: (t) =>
        t.evaluation ? t.evaluation.overall_quality.toFixed(2) : "—",
      sortValue: (t) => t.evaluation?.overall_quality ?? -1,
    },
  ];

  return (
    <div className="space-y-4">
      <FilterBar
        model={model}
        onModelChange={(v) => {
          setModel(v);
          setOffset(0);
        }}
        provider={provider}
        onProviderChange={(v) => {
          setProvider(v);
          setOffset(0);
        }}
        applicationId={applicationId}
        onApplicationIdChange={(v) => {
          setApplicationId(v);
          setOffset(0);
        }}
        status={status}
        onStatusChange={(v) => {
          setStatus(v);
          setOffset(0);
        }}
        search={search}
        onSearchChange={(v) => {
          setSearch(v);
          setOffset(0);
        }}
        tag={tag}
        onTagChange={(v) => {
          setTag(v);
          setOffset(0);
        }}
      />

      <div className="flex items-center justify-end gap-2">
        {exportError && <span className="text-xs text-red-400">{exportError}</span>}
        <button
          type="button"
          onClick={handleExport}
          disabled={exporting}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

      {error && <ErrorState message={error} onRetry={refetch} />}

      {!error && (loading || !data) && <SkeletonTable rows={8} cols={9} />}

      {!error && data && (
        <>
          <DataTable<Trace>
            columns={columns}
            rows={data.items}
            rowKey={(t) => t.id}
            onRowClick={(t) => router.push(`/trace/${encodeURIComponent(t.trace_id)}`)}
            emptyTitle="No traces found"
            emptyMessage="Try widening or clearing your filters."
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
