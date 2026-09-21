"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { TimelineChart } from "@/components/TimelineChart";
import { ScoreBar } from "@/components/ScoreBar";
import { JsonViewer } from "@/components/JsonViewer";
import { ErrorState, Skeleton } from "@/components/StateViews";
import { DataTable, type Column } from "@/components/DataTable";
import { formatCost, formatDate, formatMs } from "@/lib/format";
import type {
  FeedbackRating,
  HallucinationClaim,
  RoutingCandidate,
  Trace,
  TraceFeedback,
} from "@/lib/types";

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
            {trace.prompt_id && (
              <div className="mt-1 text-xs text-base-400">
                prompt <span className="font-mono">{trace.prompt_id}</span>
                {trace.prompt_version !== null && (
                  <span className="font-mono"> v{trace.prompt_version}</span>
                )}
                {typeof trace.metadata.prompt_rollout_arm === "string" && (
                  <span className="ml-1.5">
                    <StatusBadge
                      status={`canary ${trace.metadata.prompt_rollout_arm}`}
                      tone="info"
                    />
                  </span>
                )}
              </div>
            )}
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
          {typeof trace.metadata.rendered_prompt === "string" && (
            <div className="mb-3">
              <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
                Rendered prompt
                {trace.prompt_version !== null && ` (v${trace.prompt_version})`} — what the model
                was given as its system prompt
              </div>
              <pre className="whitespace-pre-wrap rounded bg-base-900 p-3 text-xs text-base-300">
                {trace.metadata.rendered_prompt}
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

      <TraceTagsPanel traceId={trace.trace_id} current={trace.tags} onUpdated={refetch} />

      <ReviewerFeedbackPanel traceId={trace.trace_id} current={trace.feedback} onSubmitted={refetch} />

      <ReplayPanel trace={trace} />

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

function ReplayPanel({ trace }: { trace: Trace }) {
  const router = useRouter();
  const { data: models } = useFetch(() => api.listModels({ limit: 200 }), []);
  const [modelOverride, setModelOverride] = useState("");
  const [replaying, setReplaying] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [replayed, setReplayed] = useState<Trace | null>(null);

  async function handleReplay() {
    setReplaying(true);
    setReplayError(null);
    try {
      const result = await api.replayTrace(trace.trace_id, {
        model: modelOverride || undefined,
      });
      setReplayed(result);
    } catch (err) {
      setReplayError(err instanceof ApiError ? err.message : "Replay failed");
    } finally {
      setReplaying(false);
    }
  }

  return (
    <Panel
      title="Replay"
      action={
        <span className="text-[10px] text-base-500">
          resubmit this prompt, optionally against a different model
        </span>
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={modelOverride}
          onChange={(e) => setModelOverride(e.target.value)}
          disabled={replaying}
          className="rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 disabled:cursor-not-allowed"
        >
          <option value="">router picks (same as original if unset)</option>
          {(models?.items ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleReplay}
          disabled={replaying}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {replaying ? "Replaying…" : "Re-run this prompt"}
        </button>
      </div>
      {replayError && <p className="mt-2 text-xs text-red-400">{replayError}</p>}
      {replayed && (
        <div className="mt-3 space-y-2 rounded border border-base-700 bg-base-900 p-3">
          <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <ReplayStat label="Model" original={trace.model} replayed={replayed.model} />
            <ReplayStat
              label="Cost"
              original={formatCost(trace.estimated_cost)}
              replayed={formatCost(replayed.estimated_cost)}
            />
            <ReplayStat
              label="Latency"
              original={formatMs(trace.latency_ms)}
              replayed={formatMs(replayed.latency_ms)}
            />
            <ReplayStat
              label="Quality"
              original={trace.evaluation ? trace.evaluation.overall_quality.toFixed(2) : "—"}
              replayed={replayed.evaluation ? replayed.evaluation.overall_quality.toFixed(2) : "—"}
            />
          </div>
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
              New response
            </div>
            <pre className="whitespace-pre-wrap rounded bg-base-800 p-2 text-xs text-base-300">
              {replayed.response}
            </pre>
          </div>
          <button
            type="button"
            onClick={() => router.push(`/trace/${encodeURIComponent(replayed.trace_id)}`)}
            className="text-xs text-accent hover:underline"
          >
            View full replayed trace →
          </button>
        </div>
      )}
    </Panel>
  );
}

function ReplayStat({
  label,
  original,
  replayed,
}: {
  label: string;
  original: string;
  replayed: string;
}) {
  const changed = original !== replayed;
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-base-500">{label}</div>
      <div className="font-mono text-base-400 line-through">{original}</div>
      <div className={`font-mono ${changed ? "text-accent" : "text-base-200"}`}>{replayed}</div>
    </div>
  );
}

function TraceTagsPanel({
  traceId,
  current,
  onUpdated,
}: {
  traceId: string;
  current: string[];
  onUpdated: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function save(next: string[]) {
    setSaving(true);
    setSaveError(null);
    try {
      await api.updateTraceTags(traceId, next);
      onUpdated();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Failed to update tags");
    } finally {
      setSaving(false);
    }
  }

  function addTag() {
    const value = draft.trim();
    if (!value || current.includes(value.toLowerCase())) return;
    setDraft("");
    void save([...current, value]);
  }

  return (
    <Panel title="Tags">
      <div className="flex flex-wrap items-center gap-2">
        {current.map((t) => (
          <span
            key={t}
            className="flex items-center gap-1 rounded-full border border-base-600 bg-base-800 px-2.5 py-1 text-xs text-base-200"
          >
            {t}
            <button
              type="button"
              onClick={() => void save(current.filter((existing) => existing !== t))}
              disabled={saving}
              className="text-base-500 hover:text-err disabled:cursor-not-allowed"
              aria-label={`Remove tag ${t}`}
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addTag();
            }
          }}
          placeholder="Add a tag…"
          disabled={saving}
          className="w-32 rounded border border-base-600 bg-base-800 px-2 py-1 text-xs text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={addTag}
          disabled={saving || !draft.trim()}
          className="rounded border border-base-600 bg-base-800 px-2.5 py-1 text-xs text-base-300 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          Add
        </button>
      </div>
      {saveError && <p className="mt-2 text-xs text-red-400">{saveError}</p>}
    </Panel>
  );
}

function ReviewerFeedbackPanel({
  traceId,
  current,
  onSubmitted,
}: {
  traceId: string;
  current: TraceFeedback | null;
  onSubmitted: () => void;
}) {
  const [note, setNote] = useState(current?.note ?? "");
  const [submitting, setSubmitting] = useState<FeedbackRating | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function submit(rating: FeedbackRating) {
    setSubmitting(rating);
    setSubmitError(null);
    try {
      await api.submitTraceFeedback(traceId, rating, note.trim() || undefined);
      onSubmitted();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to submit feedback");
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <Panel
      title="Human review"
      action={
        current && (
          <span className="text-[10px] text-base-500">
            last reviewed {formatDate(current.created_at)}
          </span>
        )
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => submit("up")}
          disabled={submitting !== null}
          className={
            current?.rating === "up"
              ? "rounded border border-ok bg-ok/10 px-3 py-1.5 text-xs text-ok"
              : "rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-300 hover:bg-base-700 disabled:cursor-not-allowed"
          }
        >
          {submitting === "up" ? "Saving…" : "👍 Good answer"}
        </button>
        <button
          type="button"
          onClick={() => submit("down")}
          disabled={submitting !== null}
          className={
            current?.rating === "down"
              ? "rounded border border-err bg-err/10 px-3 py-1.5 text-xs text-err"
              : "rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-300 hover:bg-base-700 disabled:cursor-not-allowed"
          }
        >
          {submitting === "down" ? "Saving…" : "👎 Bad answer"}
        </button>
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Optional note"
          className="min-w-[12rem] flex-1 rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 placeholder:text-base-500"
        />
      </div>
      {current && (
        <p className="mt-2 text-xs text-base-400">
          Currently rated <StatusBadge status={current.rating === "up" ? "good" : "bad"} tone={current.rating === "up" ? "ok" : "err"} />
          {current.note && <span className="ml-2">— &ldquo;{current.note}&rdquo;</span>}
        </p>
      )}
      {submitError && <p className="mt-2 text-xs text-red-400">{submitError}</p>}
    </Panel>
  );
}
