"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ScoreBar } from "@/components/ScoreBar";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorState, SkeletonTable, EmptyState } from "@/components/StateViews";
import { formatCost, formatDate, formatMs, formatPercent } from "@/lib/format";
import type { Rollout, RolloutArmStats } from "@/lib/types";
import {
  ActionButton,
  LabeledField,
  STAGE_TONE,
  Stat,
} from "@/components/RolloutParts";
import { PromptRollouts } from "@/components/PromptRollouts";
import { FormError, parseRolloutGuards } from "@/lib/validate";

export default function RolloutsPage() {
  const [tab, setTab] = useState<"models" | "prompts">("models");

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-base-700">
        {(
          [
            ["models", "Model canaries"],
            ["prompts", "Prompt canaries"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={
              tab === key
                ? "border-b-2 border-accent px-3 py-2 text-xs text-accent"
                : "px-3 py-2 text-xs text-base-400 hover:text-base-200"
            }
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "models" ? <ModelRollouts /> : <PromptRollouts />}
    </div>
  );
}

function ModelRollouts() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listRollouts({ limit: 100 }),
    [],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const columns: Column<Rollout>[] = [
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
      key: "models",
      header: "Incumbent → Challenger",
      render: (r) => (
        <span className="font-mono text-xs text-base-300">
          {r.incumbent_model} <span className="text-base-500">→</span>{" "}
          {r.challenger_model}
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
        <StartRolloutPanel onCreated={refetch} />

        {error && <ErrorState message={error} onRetry={refetch} />}
        {!error && (loading || !data) && <SkeletonTable rows={4} cols={5} />}
        {!error && data && data.items.length === 0 && (
          <EmptyState
            title="No rollouts yet"
            message="Start one above to progressively shift an application's traffic from an incumbent model to a challenger, monitored automatically."
          />
        )}
        {!error && data && data.items.length > 0 && (
          <DataTable<Rollout>
            columns={columns}
            rows={data.items}
            rowKey={(r) => r.id}
            onRowClick={(r) => setSelectedId(r.id)}
            emptyTitle="No rollouts"
            emptyMessage="No rollouts match the current filters."
            defaultSortKey="created_at"
          />
        )}
      </div>

      <div className="lg:sticky lg:top-0 lg:h-fit">
        {selectedId ? (
          <RolloutDetailPanel rolloutId={selectedId} onChanged={refetch} />
        ) : (
          <Panel title="Rollout detail">
            <p className="text-xs text-base-400">
              Select a rollout from the list to see live incumbent vs.
              challenger stats and controls.
            </p>
          </Panel>
        )}
      </div>
    </div>
  );
}

function StartRolloutPanel({ onCreated }: { onCreated: () => void }) {
  const [applicationId, setApplicationId] = useState("");
  const [incumbentModel, setIncumbentModel] = useState("");
  const [challengerModel, setChallengerModel] = useState("");
  const [initialPct, setInitialPct] = useState("10");
  const [qualityFloor, setQualityFloor] = useState("0.7");
  const [maxQualityRegression, setMaxQualityRegression] = useState("0.1");
  const [maxErrorRate, setMaxErrorRate] = useState("0.1");
  const [minSampleSize, setMinSampleSize] = useState("10");
  const [stepPct, setStepPct] = useState("10");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: models } = useFetch(() => api.listModels({ limit: 200 }), []);

  const canSubmit =
    applicationId.trim() &&
    incumbentModel &&
    challengerModel &&
    incumbentModel !== challengerModel;

  async function handleCreate() {
    if (!canSubmit) return;
    setCreating(true);
    setCreateError(null);
    try {
      const guards = parseRolloutGuards({
        initialPct,
        qualityFloor,
        maxDrop: maxQualityRegression,
        maxErrorRate,
        minSample: minSampleSize,
        stepPct,
      });
      await api.createRollout({
        application_id: applicationId.trim(),
        incumbent_model: incumbentModel,
        challenger_model: challengerModel,
        ...guards,
      });
      setApplicationId("");
      onCreated();
    } catch (err) {
      setCreateError(
        err instanceof ApiError || err instanceof FormError
          ? err.message
          : "Failed to start rollout",
      );
    } finally {
      setCreating(false);
    }
  }

  const modelOptions = models?.items ?? [];

  return (
    <Panel
      title="Start a canary rollout"
      action={
        <span className="text-[10px] text-base-500">
          progressively shifts an application&apos;s un-pinned traffic;
          auto-advances, auto-promotes, or auto-rolls-back from real trailing
          quality/error-rate
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
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
          />
        </LabeledField>
        <LabeledField label="Incumbent model">
          <ModelSelect
            value={incumbentModel}
            onChange={setIncumbentModel}
            options={modelOptions.map((m) => m.id)}
            disabled={creating}
          />
        </LabeledField>
        <LabeledField label="Challenger model">
          <ModelSelect
            value={challengerModel}
            onChange={setChallengerModel}
            options={modelOptions.map((m) => m.id)}
            disabled={creating}
          />
        </LabeledField>
        <LabeledField label="Initial %">
          <input
            type="number"
            min="0"
            max="100"
            step="1"
            value={initialPct}
            onChange={(e) => setInitialPct(e.target.value)}
            disabled={creating}
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
          />
        </LabeledField>
        <LabeledField label="Quality floor">
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={qualityFloor}
            onChange={(e) => setQualityFloor(e.target.value)}
            disabled={creating}
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
          />
        </LabeledField>
        <LabeledField label="Max drop vs incumbent">
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={maxQualityRegression}
            onChange={(e) => setMaxQualityRegression(e.target.value)}
            disabled={creating}
            title="How far below the incumbent's own quality (same window) the challenger may fall before rollback"
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
          />
        </LabeledField>
        <LabeledField label="Max error rate">
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={maxErrorRate}
            onChange={(e) => setMaxErrorRate(e.target.value)}
            disabled={creating}
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
          />
        </LabeledField>
        <LabeledField label="Min sample size">
          <input
            type="number"
            min="1"
            step="1"
            value={minSampleSize}
            onChange={(e) => setMinSampleSize(e.target.value)}
            disabled={creating}
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
          />
        </LabeledField>
        <LabeledField label="Step %">
          <input
            type="number"
            min="1"
            max="100"
            step="1"
            value={stepPct}
            onChange={(e) => setStepPct(e.target.value)}
            disabled={creating}
            className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
          />
        </LabeledField>
      </div>
      <button
        type="button"
        onClick={handleCreate}
        disabled={!canSubmit || creating}
        className="mt-3 rounded border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {creating ? "Starting…" : "Start rollout"}
      </button>
      {createError && (
        <p className="mt-2 text-xs text-red-400">{createError}</p>
      )}
    </Panel>
  );
}

function ModelSelect({
  value,
  onChange,
  options,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="w-full rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 disabled:cursor-not-allowed"
    >
      <option value="">select…</option>
      {options.map((id) => (
        <option key={id} value={id}>
          {id}
        </option>
      ))}
    </select>
  );
}

function RolloutDetailPanel({
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
  } = useFetch(() => api.getRollout(rolloutId), [rolloutId]);
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
      title={rollout.application_id}
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
            label={rollout.challenger_model}
            score={rollout.traffic_pct / 100}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <ArmStatsCard title="Incumbent" stats={rollout.incumbent_stats} />
          <ArmStatsCard title="Challenger" stats={rollout.challenger_stats} />
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
              onClick={() => runAction(api.pauseRollout)}
              disabled={acting}
            >
              Pause
            </ActionButton>
          )}
          {rollout.stage === "paused" && (
            <ActionButton
              onClick={() => runAction(api.resumeRollout)}
              disabled={acting}
            >
              Resume
            </ActionButton>
          )}
          {(rollout.stage === "running" || rollout.stage === "paused") && (
            <>
              <ActionButton
                onClick={() => runAction(api.promoteRollout)}
                disabled={acting}
                tone="ok"
              >
                Promote now
              </ActionButton>
              <ActionButton
                onClick={() => runAction(api.rollbackRollout)}
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

function ArmStatsCard({
  title,
  stats,
}: {
  title: string;
  stats: RolloutArmStats;
}) {
  return (
    <div className="rounded border border-base-700 bg-base-900 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-base-200">{title}</span>
        <span className="font-mono text-[10px] text-base-500">
          {stats.model}
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
