"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { ErrorState, SkeletonTable, EmptyState } from "@/components/StateViews";

export default function DatasetDetailPage() {
  const params = useParams<{ id: string }>();
  const datasetId = decodeURIComponent(params.id);

  const { data, loading, error, refetch } = useFetch(
    () => api.listDatasetRecords(datasetId, { limit: 50 }),
    [datasetId]
  );

  return (
    <div className="space-y-4">
      <Panel title={`Dataset ${datasetId}`}>
        <p className="text-xs text-base-400">
          {data
            ? `Showing ${data.items.length} of ${data.total} records for this dataset version.`
            : "Loading records…"}
        </p>
      </Panel>

      {error && <ErrorState message={error} onRetry={refetch} />}
      {!error && (loading || !data) && <SkeletonTable rows={5} cols={1} />}
      {!error && data && data.items.length === 0 && (
        <EmptyState
          title="No records"
          message="This dataset has no records, or they haven't loaded yet."
        />
      )}
      {!error && data && data.items.length > 0 && (
        <div className="space-y-3">
          {data.items.map((record) => (
            <Panel key={record.id}>
              <div className="mb-2 font-mono text-[10px] text-base-500">{record.id}</div>
              <div className="mb-2">
                <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                  Question
                </div>
                <p className="text-sm text-base-100">{record.question}</p>
              </div>
              <div className="mb-2">
                <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                  Context
                </div>
                <p className="whitespace-pre-wrap text-xs text-base-300">
                  {record.context}
                </p>
              </div>
              <div>
                <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                  Expected answer
                </div>
                <p className="text-xs text-ok">{record.expected_answer}</p>
              </div>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
