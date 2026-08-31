"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { TimelineChart } from "@/components/TimelineChart";
import { ScoreBar } from "@/components/ScoreBar";
import { JsonViewer } from "@/components/JsonViewer";
import { ErrorState, Skeleton } from "@/components/StateViews";
import { DataTable, type Column } from "@/components/DataTable";
import { formatCost, formatDate, formatMs } from "@/lib/format";
import type { HallucinationClaim, RoutingCandidate } from "@/lib/types";

export default function TraceDetailPage() {
  const params = useParams<{ id: string }>();
  const traceId = decodeURIComponent(params.id);

  const { data: trace, loading, error, refetch } = useFetch(
    () => api.getTrace(traceId),
    [traceId]
  );

  if (error) {
    return <ErrorState message={error} onRetry={refetch} />;
  }

  if (loading || !trace) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const claimColumns: Column<HallucinationClaim>[] = [
    {
      key: "claim",
      header: "Claim",
      render: (c) => <span className="text-xs">{c.claim}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (c) => <StatusBadge status={c.status} />,
      sortValue: (c) => c.status,
    },
    {
      key: "support_score",
      header: "Support",
      align: "right",
      render: (c) => c.support_score.toFixed(2),
      sortValue: (c) => c.support_score,
    },
    {
      key: "evidence",
      header: "Evidence",
      render: (c) => <span className="text-xs text-base-400">{c.evidence}</span>,
    },
  ];

  const candidateColumns: Column<RoutingCandidate>[] = [
    {
      key: "model",
      header: "Model",
      render: (c) => (
        <span className="font-mono text-xs">
          {c.model}
          {c.model === trace.routing_decision?.selected_model && (
            <span className="ml-1.5 text-accent">selected</span>
          )}
        </span>
      ),
      sortValue: (c) => c.model,
    },
    {
      key: "routing_score",
      header: "Routing score",
      align: "right",
      render: (c) => c.routing_score.toFixed(3),
      sortValue: (c) => c.routing_score,
    },
    {
      key: "predicted_quality",
      header: "Predicted quality",
      align: "right",
      render: (c) => c.predicted_quality.toFixed(3),
      sortValue: (c) => c.predicted_quality,
    },
    {
      key: "normalized_cost",
      header: "Norm. cost",
      align: "right",
      render: (c) => c.normalized_cost.toFixed(3),
      sortValue: (c) => c.normalized_cost,
    },
    {
      key: "normalized_latency",
      header: "Norm. latency",
      align: "right",
      render: (c) => c.normalized_latency.toFixed(3),
      sortValue: (c) => c.normalized_latency,
    },
    {
      key: "risk",
      header: "Risk",
      align: "right",
      render: (c) => c.risk.toFixed(3),
      sortValue: (c) => c.risk,
    },
  ];

  return (
    <div className="space-y-5">
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-mono text-sm text-base-100">{trace.trace_id}</h2>
              <StatusBadge status={trace.status} />
              {trace.cache_hit && <StatusBadge status="cache hit" tone="info" />}
            </div>
            <div className="mt-1 text-xs text-base-400">
              {trace.application_id} · {trace.environment} · {trace.model} ({trace.provider}) ·{" "}
              {formatDate(trace.created_at)}
            </div>
            {trace.error && (
              <div className="mt-1 text-xs text-err">{trace.error}</div>
            )}
          </div>
          <div className="flex gap-6">
            <HeaderStat label="Total latency" value={formatMs(trace.latency_ms)} />
            <HeaderStat label="Cost" value={formatCost(trace.estimated_cost)} />
            <HeaderStat
              label="Quality"
              value={
                trace.evaluation ? trace.evaluation.overall_quality.toFixed(2) : "—"
              }
            />
            <HeaderStat
              label="Tokens"
              value={`${trace.input_tokens} in / ${trace.output_tokens} out`}
            />
          </div>
        </div>
      </Panel>

      <Panel title="Span timeline">
        <TimelineChart spans={trace.spans} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Input">
          {trace.system_prompt && (
            <div className="mb-3">
              <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                System prompt
              </div>
              <pre className="whitespace-pre-wrap rounded bg-base-900 p-3 text-xs text-base-300">
                {trace.system_prompt}
              </pre>
            </div>
          )}
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
              Prompt
            </div>
            <pre className="whitespace-pre-wrap rounded bg-base-900 p-3 text-xs text-base-300">
              {trace.prompt}
            </pre>
          </div>
        </Panel>

        <Panel title="Output">
          <pre className="whitespace-pre-wrap rounded bg-base-900 p-3 text-xs text-base-300">
            {trace.response}
          </pre>
        </Panel>
      </div>

      <Panel title={`Retrieved context (${trace.retrieved_documents.length})`}>
        {trace.retrieved_documents.length === 0 ? (
          <p className="text-xs text-base-400">No documents retrieved.</p>
        ) : (
          <div className="space-y-2">
            {trace.retrieved_documents
              .slice()
              .sort((a, b) => a.rank - b.rank)
              .map((doc) => (
                <div
                  key={doc.doc_id}
                  className="rounded border border-base-700 bg-base-900 p-3"
                >
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="font-mono text-base-300">
                      #{doc.rank} · {doc.doc_id}
                    </span>
                    <span className="font-mono text-accent">
                      score {doc.score.toFixed(3)}
                    </span>
                  </div>
                  <p className="text-xs text-base-400">{doc.content}</p>
                </div>
              ))}
          </div>
        )}
      </Panel>

      <Panel title="Evaluation">
        {!trace.evaluation ? (
          <p className="text-xs text-base-400">No evaluation recorded for this trace.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {trace.evaluation.metrics.map((m) => (
              <div
                key={m.metric_name}
                className="rounded border border-base-700 bg-base-900 p-3"
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium capitalize text-base-200">
                    {m.metric_name.replace(/_/g, " ")}
                  </span>
                  {m.passed !== null && (
                    <StatusBadge status={m.passed ? "passed" : "failed"} />
                  )}
                </div>
                <ScoreBar
                  label="score"
                  score={m.score}
                  threshold={m.threshold}
                  passed={m.passed}
                />
                <p className="mt-2 text-xs text-base-400">{m.reason}</p>
                <p className="mt-1 font-mono text-[10px] text-base-500">
                  {m.evaluator_version}
                </p>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {trace.evaluation?.hallucination && (
        <Panel
          title={`Hallucination evidence — score ${trace.evaluation.hallucination.hallucination_score.toFixed(2)}`}
        >
          <DataTable<HallucinationClaim>
            columns={claimColumns}
            rows={trace.evaluation.hallucination.claims}
            rowKey={(c) => `${c.claim}-${c.status}-${c.support_score}`.slice(0, 200)}
            emptyTitle="No claims extracted"
            emptyMessage="No claims were extracted for hallucination analysis."
          />
        </Panel>
      )}

      {trace.routing_decision && (
        <Panel title="Routing decision">
          <div className="mb-3 rounded border border-accent/30 bg-accent/5 p-3 text-xs">
            <span className="font-mono text-accent">
              {trace.routing_decision.selected_model}
            </span>{" "}
            selected — {trace.routing_decision.reason}
          </div>
          <DataTable<RoutingCandidate>
            columns={candidateColumns}
            rows={trace.routing_decision.candidates}
            rowKey={(c) => c.model}
            emptyTitle="No candidates"
            emptyMessage="No routing candidates recorded."
            defaultSortKey="routing_score"
          />
        </Panel>
      )}

      <JsonViewer data={trace.metadata} title="Raw metadata" />
    </div>
  );
}

function HeaderStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wide text-base-400">{label}</div>
      <div className="font-mono text-sm text-base-100">{value}</div>
    </div>
  );
}
