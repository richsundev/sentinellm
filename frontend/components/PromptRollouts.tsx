"use client";

import { useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ScoreBar } from "@/components/ScoreBar";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, SkeletonTable, EmptyState } from "@/components/StateViews";
import {
  ActionButton,
  LabeledField,
  STAGE_TONE,
  Stat,
} from "@/components/RolloutParts";
import { formatCost, formatDate, formatMs, formatPercent } from "@/lib/format";
import type { PromptArmStats, PromptRollout } from "@/lib/types";

/** The "Prompt canaries" tab: progressive rollouts of one prompt version over another. */
export function PromptRollouts() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listPromptRollouts({ limit: 100 }),
    [],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const columns: Column<PromptRollout>[] = [
    {
      key: "application_id",
      header: "Application",
      render: (r) => (
        <span className="font-mono text-xs text-base-200">
          {r.application_id}
        </span>
      ),
      sortValue: (r) => r.application_id,
    },
    {
      key: "versions",
      header: "Prompt · incumbent → challenger",
      render: (r) => (
        <span className="font-mono text-xs text-base-300">
          {r.prompt_id} v{r.incumbent_version}{" "}
          <span className="text-base-500">→</span> v{r.challenger_version}
        </span>
      ),
    },
    {
      key: "traffic_pct",
      header: "Traffic",
      render: (r) => (
        <div className="w-32">
          <ScoreBar label="challenger" score={r.traffic_pct / 100} />
        </div>
      ),
      sortValue: (r) => r.traffic_pct,
    },
    {
      key: "stage",
      header: "Stage",
      render: (r) => (
        <StatusBadge status={r.stage} tone={STAGE_TONE[r.stage]} />
      ),
      sortValue: (r) => r.stage,
    },
    {
      key: "created_at",
      header: "Started",
      render: (r) => (
        <span className="font-mono text-xs text-base-500">
          {formatDate(r.created_at)}
        </span>
      ),
      sortValue: (r) => r.created_at,
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <StartPromptRolloutPanel onCreated={refetch} />

        {error && <ErrorState message={error} onRetry={refetch} />}
        {!error && (loading || !data) && <SkeletonTable rows={4} cols={5} />}
        {!error && data && data.items.length === 0 && (
          <EmptyState
            title="No prompt canaries yet"
            message="Start one above to progressively serve a new prompt version to an application's traffic, judged automatically against the current one."
          />
        )}
        {!error && data && data.items.length > 0 && (
          <DataTable<PromptRollout>
            columns={columns}
            rows={data.items}
            rowKey={(r) => r.id}
            onRowClick={(r) => setSelectedId(r.id)}
            emptyTitle="No prompt rollouts"
            emptyMessage="No prompt rollouts match the current filters."
            defaultSortKey="created_at"
          />
        )}
      </div>

      <div className="lg:sticky lg:top-0 lg:h-fit">
        {selectedId ? (
          <PromptRolloutDetail rolloutId={selectedId} onChanged={refetch} />
        ) : (
          <Panel title="Rollout detail">
            <p className="text-xs text-base-400">
              Select a rollout to see live stats for each prompt version, and
              controls.
            </p>
          </Panel>
        )}
      </div>
    </div>
  );
}

const INPUT =
  "w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed";

function StartPromptRolloutPanel({ onCreated }: { onCreated: () => void }) {
  const [applicationId, setApplicationId] = useState("");
  const [promptId, setPromptId] = useState("");
  const [incumbent, setIncumbent] = useState("");
  const [challenger, setChallenger] = useState("");
  const [initialPct, setInitialPct] = useState("10");
  const [qualityFloor, setQualityFloor] = useState("0.7");
  const [maxDrop, setMaxDrop] = useState("0.1");
  const [maxErrorRate, setMaxErrorRate] = useState("0.1");
  const [minSample, setMinSample] = useState("10");
  const [stepPct, setStepPct] = useState("10");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: prompts } = useFetch(() => api.listPrompts({ limit: 500 }), []);
  const promptIds = useMemo(
    () =>
      Array.from(
        new Set((prompts?.items ?? []).map((p) => p.prompt_id)),
      ).sort(),
    [prompts],
  );
  const versions = useMemo(
    () =>
      (prompts?.items ?? [])
        .filter((p) => p.prompt_id === promptId)
        .map((p) => p.version)
        .sort((a, b) => b - a),
    [prompts, promptId],
  );

  const canSubmit =
    applicationId.trim() &&
    promptId &&
    incumbent &&
    challenger &&
    incumbent !== challenger;

  async function handleCreate() {
    if (!canSubmit) return;
    setCreating(true);
    setCreateError(null);
    try {
      await api.createPromptRollout({
        application_id: applicationId.trim(),
        prompt_id: promptId,
        incumbent_version: Number(incumbent),
        challenger_version: Number(challenger),
        initial_pct: Number(initialPct),
        quality_floor: Number(qualityFloor),
        max_quality_regression: Number(maxDrop),
        max_error_rate: Number(maxErrorRate),
        min_sample_size: Number(minSample),
        step_pct: Number(stepPct),
      });
      setApplicationId("");
      onCreated();
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? err.message : "Failed to start the rollout",
      );
    } finally {
      setCreating(false);
    }
  }

  const number = (
    value: string,
    set: (v: string) => void,
    props: Record<string, string>,
  ) => (
    <input
      type="number"
      {...props}
      value={value}
      onChange={(e) => set(e.target.value)}
      disabled={creating}
      className={INPUT}
    />
  );

  return (
    <Panel
      title="Start a prompt canary"
      action={
        <span className="text-[10px] text-base-500">
          serves the challenger version to a share of an application&apos;s
          requests that use this prompt (
          <code className="font-mono">prompt_variables</code> set, no pinned
          version); auto-advances, promotes, or rolls back from real quality and
          error rate
        </span>
      }
    >
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <LabeledField label="Application">
          <input
            value={applicationId}
            onChange={(e) => setApplicationId(e.target.value)}
            placeholder="application_id"
            disabled={creating}
            className={INPUT}
          />
        </LabeledField>
        <LabeledField label="Prompt">
          <select
            aria-label="Prompt"
            value={promptId}
            onChange={(e) => {
              setPromptId(e.target.value);
              setIncumbent("");
              setChallenger("");
            }}
            disabled={creating}
            className={INPUT}
          >
            <option value="">select…</option>
            {promptIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </LabeledField>
        <LabeledField label="Incumbent version">
          <VersionSelect
            label="Incumbent version"
            value={incumbent}
            onChange={setIncumbent}
            options={versions}
            disabled={creating || !promptId}
          />
        </LabeledField>
        <LabeledField label="Challenger version">
          <VersionSelect
            label="Challenger version"
            value={challenger}
            onChange={setChallenger}
            options={versions}
            disabled={creating || !promptId}
          />
        </LabeledField>
        <LabeledField label="Initial %">
          {number(initialPct, setInitialPct, {
            min: "0",
            max: "100",
            step: "1",
          })}
        </LabeledField>
        <LabeledField label="Quality floor">
          {number(qualityFloor, setQualityFloor, {
            min: "0",
            max: "1",
            step: "0.05",
          })}
        </LabeledField>
        <LabeledField label="Max drop vs incumbent">
          {number(maxDrop, setMaxDrop, { min: "0", max: "1", step: "0.05" })}
        </LabeledField>
        <LabeledField label="Max error rate">
          {number(maxErrorRate, setMaxErrorRate, {
            min: "0",
            max: "1",
            step: "0.05",
          })}
        </LabeledField>
        <LabeledField label="Min sample size">
          {number(minSample, setMinSample, { min: "1", step: "1" })}
        </LabeledField>
        <LabeledField label="Step %">
          {number(stepPct, setStepPct, { min: "1", max: "100", step: "1" })}
        </LabeledField>
      </div>
      <button
        type="button"
        onClick={handleCreate}
        disabled={!canSubmit || creating}
        className="mt-3 rounded border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {creating ? "Starting…" : "Start prompt canary"}
      </button>
      {createError && (
        <p className="mt-2 text-xs text-red-400">{createError}</p>
      )}
    </Panel>
  );
}

function VersionSelect({
  label,
  value,
  onChange,
  options,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: number[];
  disabled?: boolean;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={INPUT}
    >
      <option value="">select…</option>
      {options.map((v) => (
        <option key={v} value={String(v)}>
          v{v}
        </option>
      ))}
    </select>
  );
}

function PromptRolloutDetail({
  rolloutId,
  onChanged,
}: {
  rolloutId: string;
  onChanged: () => void;
}) {
  const {
    data: rollout,
    loading,
    error,
    refetch,
  } = useFetch(() => api.getPromptRollout(rolloutId), [rolloutId]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  async function runAction(action: (id: string) => Promise<unknown>) {
    setActing(true);
    setActionError(null);
    try {
      await action(rolloutId);
      await refetch();
      onChanged();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed");
    } finally {
      setActing(false);
    }
  }

  if (error) return <ErrorState message={error} onRetry={refetch} />;
  if (loading || !rollout)
    return <Panel title="Rollout detail">Loading…</Panel>;

  return (
    <Panel
      title={`${rollout.application_id} · ${rollout.prompt_id}`}
      action={
        <StatusBadge status={rollout.stage} tone={STAGE_TONE[rollout.stage]} />
      }
    >
      <div className="space-y-4">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-base-400">
            Traffic to challenger
          </div>
          <ScoreBar
            label={`v${rollout.challenger_version}`}
            score={rollout.traffic_pct / 100}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <ArmCard title="Incumbent" stats={rollout.incumbent_stats} />
          <ArmCard title="Challenger" stats={rollout.challenger_stats} />
        </div>

        <div className="rounded border border-base-700 bg-base-900 p-2.5 text-xs">
          <div className="text-base-500">
            floor {rollout.quality_floor.toFixed(2)} · max drop vs incumbent{" "}
            {rollout.max_quality_regression.toFixed(2)} · max error{" "}
            {formatPercent(rollout.max_error_rate)} · step {rollout.step_pct}% ·
            min sample {rollout.min_sample_size}
          </div>
          {rollout.last_evaluated_at && (
            <div className="mt-1 text-base-500">
              last evaluated {formatDate(rollout.last_evaluated_at)}
            </div>
          )}
          {rollout.outcome_reason && (
            <div className="mt-1 text-base-300">{rollout.outcome_reason}</div>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {rollout.stage === "running" && (
            <ActionButton
              onClick={() => runAction(api.pausePromptRollout)}
              disabled={acting}
            >
              Pause
            </ActionButton>
          )}
          {rollout.stage === "paused" && (
            <ActionButton
              onClick={() => runAction(api.resumePromptRollout)}
              disabled={acting}
            >
              Resume
            </ActionButton>
          )}
          {(rollout.stage === "running" || rollout.stage === "paused") && (
            <>
              <ActionButton
                onClick={() => runAction(api.promotePromptRollout)}
                disabled={acting}
                tone="ok"
              >
                Promote now
              </ActionButton>
              <ActionButton
                onClick={() => runAction(api.rollbackPromptRollout)}
                disabled={acting}
                tone="err"
              >
                Roll back now
              </ActionButton>
            </>
          )}
        </div>
        {actionError && <p className="text-xs text-red-400">{actionError}</p>}
      </div>
    </Panel>
  );
}

function ArmCard({ title, stats }: { title: string; stats: PromptArmStats }) {
  return (
    <div className="rounded border border-base-700 bg-base-900 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-base-200">{title}</span>
        <span className="font-mono text-[10px] text-base-500">
          v{stats.version}
        </span>
      </div>
      <dl className="space-y-1 text-xs">
        <Stat label="Requests" value={String(stats.request_count)} />
        <Stat label="Error rate" value={formatPercent(stats.error_rate)} />
        <Stat
          label="Avg quality"
          value={
            stats.avg_quality !== null ? stats.avg_quality.toFixed(2) : "—"
          }
        />
        <Stat label="Avg latency" value={formatMs(stats.avg_latency_ms)} />
        <Stat label="Avg cost" value={formatCost(stats.avg_cost)} />
      </dl>
    </div>
  );
}
