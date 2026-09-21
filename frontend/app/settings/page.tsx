"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { Alert, AlertRule, ApiKey, Application } from "@/lib/types";
import { formatDate } from "@/lib/format";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <ApplicationsPanel />
      <ApiKeysPanel />
      <AlertRulesPanel />
      <RecentAlertsPanel />
      <Panel title="Webhook configuration">
        <p className="text-xs text-base-400">
          The alert webhook target is set via the{" "}
          <code className="rounded bg-base-800 px-1 py-0.5 font-mono text-base-300">
            SENTINEL_ALERT_WEBHOOK_URL
          </code>{" "}
          environment variable (see <code className="font-mono">.env.example</code>), not
          editable from the dashboard — every fired alert is a real HTTP POST to that
          URL, delivered by the worker. Set{" "}
          <code className="rounded bg-base-800 px-1 py-0.5 font-mono text-base-300">
            SENTINEL_ALERT_WEBHOOK_FORMAT=slack
          </code>{" "}
          to post Slack-compatible <code className="font-mono">{"{text: ...}"}</code> messages
          instead of the default generic JSON payload — works directly with a Slack Incoming
          Webhook URL.
        </p>
      </Panel>
    </div>
  );
}

function ApplicationsPanel() {
  const { data: apps, loading, error, refetch } = useFetch(() => api.listApplications(), []);
  const [name, setName] = useState("");
  const [budget, setBudget] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      await api.createApplication({
        name: name.trim(),
        daily_cost_budget: budget ? Number(budget) : undefined,
      });
      setName("");
      setBudget("");
      await refetch();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to create application");
    } finally {
      setCreating(false);
    }
  }

  async function handleBudgetChange(app: Application, value: string) {
    const budget = value.trim() === "" ? null : Number(value);
    if (budget !== null && (!Number.isFinite(budget) || budget < 0)) {
      setSaveError("Budget must be a number, 0 or higher");
      return;
    }
    setSavingId(app.id);
    setSaveError(null);
    try {
      // `null` (not `undefined`, which JSON drops) is what clears a budget.
      await api.updateApplication(app.id, { daily_cost_budget: budget });
      await refetch();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Failed to update the budget");
    } finally {
      setSavingId(null);
    }
  }

  const columns: Column<Application>[] = [
    { key: "name", header: "Name", render: (a) => <span className="text-base-200">{a.name}</span> },
    {
      key: "description",
      header: "Description",
      render: (a) => <span className="text-base-400">{a.description ?? "—"}</span>,
    },
    {
      key: "daily_cost_budget",
      header: "Daily cost budget",
      render: (a) => (
        <input
          type="number"
          step="0.01"
          min="0"
          defaultValue={a.daily_cost_budget ?? ""}
          disabled={savingId === a.id}
          onBlur={(e) => {
            if (e.target.value !== String(a.daily_cost_budget ?? "")) {
              void handleBudgetChange(a, e.target.value);
            }
          }}
          placeholder="no budget"
          className="w-24 rounded border border-base-600 bg-base-800 px-2 py-1 text-xs text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
        />
      ),
      sortValue: (a) => a.daily_cost_budget ?? -1,
    },
    {
      key: "created_at",
      header: "Created",
      render: (a) => <span className="font-mono text-xs text-base-500">{formatDate(a.created_at)}</span>,
      sortValue: (a) => a.created_at,
    },
  ];

  return (
    <Panel
      title="Applications"
      action={
        <span className="text-[10px] text-base-500">
          set a daily cost budget to alert when an application overspends
        </span>
      }
    >
      {error && <ErrorState message={error} onRetry={refetch} />}
      {!error && (loading || !apps) && <SkeletonTable rows={2} cols={4} />}
      {!error && apps && (
        <DataTable<Application>
          columns={columns}
          rows={apps.items}
          rowKey={(a) => a.id}
          emptyTitle="No applications"
          emptyMessage="Create one below to get started."
          defaultSortKey="name"
        />
      )}

      <div className="mt-3 flex items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Application name"
          disabled={creating}
          className="rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
        />
        <input
          type="number"
          step="0.01"
          min="0"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          placeholder="Budget (optional)"
          disabled={creating}
          className="w-32 rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={!name.trim() || creating}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {creating ? "Creating…" : "+ Create application"}
        </button>
      </div>
      {createError && <p className="mt-2 text-xs text-red-400">{createError}</p>}
      {saveError && <p className="mt-2 text-xs text-red-400">{saveError}</p>}
    </Panel>
  );
}

function ApiKeysPanel() {
  const { data: keys, loading, error, refetch: refetchKeys } = useFetch(() => api.listApiKeys(), []);
  const { data: apps } = useFetch(() => api.listApplications(), []);
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [scopedToApplication, setScopedToApplication] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const selectedApplicationId = applicationId || apps?.items[0]?.id;

  async function handleCreate() {
    if (!selectedApplicationId || !newKeyName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createApiKey({
        application_id: selectedApplicationId,
        name: newKeyName.trim(),
        role: "write",
        scoped_to_application: scopedToApplication,
      });
      setRevealedKey(created.plaintext_key);
      setNewKeyName("");
      await refetchKeys();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to create key");
    } finally {
      setCreating(false);
    }
  }

  const columns: Column<ApiKey>[] = [
    { key: "name", header: "Name", render: (k) => <span className="text-base-200">{k.name}</span> },
    {
      key: "key_prefix",
      header: "Key",
      render: (k) => <span className="font-mono text-base-400">{k.key_prefix}••••••••</span>,
    },
    { key: "role", header: "Role", render: (k) => <StatusBadge status={k.role} tone="info" /> },
    {
      key: "scoped_to_application",
      header: "Scope",
      render: (k) =>
        k.scoped_to_application ? (
          <StatusBadge status="own app only" tone="info" />
        ) : (
          <span className="text-base-500">all applications</span>
        ),
    },
    {
      key: "revoked",
      header: "Status",
      render: (k) => <StatusBadge status={k.revoked ? "revoked" : "active"} />,
    },
    {
      key: "created_at",
      header: "Created",
      render: (k) => <span className="font-mono text-xs text-base-500">{formatDate(k.created_at)}</span>,
      sortValue: (k) => k.created_at,
    },
  ];

  return (
    <Panel title="API keys">
      {revealedKey && (
        <div className="mb-3 rounded border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-xs">
          <p className="mb-1 text-amber-300">
            Copy this key now — it is only ever shown once (matches the backend&apos;s
            one-time-reveal design).
          </p>
          <div className="flex items-center justify-between gap-2">
            <code className="overflow-x-auto font-mono text-amber-100">{revealedKey}</code>
            <button
              type="button"
              onClick={() => setRevealedKey(null)}
              className="shrink-0 rounded border border-amber-700 px-2 py-1 text-amber-300 hover:bg-amber-900/40"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {error && <ErrorState message={error} onRetry={refetchKeys} />}
      {!error && (loading || !keys) && <SkeletonTable rows={2} cols={5} />}
      {!error && keys && (
        <DataTable<ApiKey>
          columns={columns}
          rows={keys.items}
          rowKey={(k) => k.id}
          emptyTitle="No API keys"
          emptyMessage="Create one below to get started."
          defaultSortKey="created_at"
        />
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          value={selectedApplicationId ?? ""}
          onChange={(e) => setApplicationId(e.target.value)}
          disabled={creating}
          className="rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 disabled:cursor-not-allowed"
        >
          {(apps?.items ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <input
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          placeholder="Key name (e.g. ci-pipeline)"
          disabled={!selectedApplicationId || creating}
          className="rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
        />
        <label className="flex items-center gap-1.5 text-xs text-base-400">
          <input
            type="checkbox"
            checked={scopedToApplication}
            onChange={(e) => setScopedToApplication(e.target.checked)}
            disabled={creating}
          />
          scope to this application only
        </label>
        <button
          type="button"
          onClick={handleCreate}
          disabled={!selectedApplicationId || !newKeyName.trim() || creating}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {creating ? "Creating…" : "+ Create key"}
        </button>
      </div>
      {createError && <p className="mt-2 text-xs text-red-400">{createError}</p>}
    </Panel>
  );
}

function AlertRulesPanel() {
  const { data: rules, loading, error, refetch } = useFetch(() => api.listAlertRules(), []);
  const [drafts, setDrafts] = useState<Record<string, number>>({});
  const [savingRule, setSavingRule] = useState<string | null>(null);
  const [ruleError, setRuleError] = useState<string | null>(null);

  async function toggleEnabled(rule: AlertRule) {
    setRuleError(null);
    try {
      await api.updateAlertRule(rule.rule, { enabled: !rule.enabled });
      await refetch();
    } catch (err) {
      setRuleError(err instanceof ApiError ? err.message : "Failed to update the rule");
    }
  }

  async function saveThreshold(rule: AlertRule) {
    const draft = drafts[rule.rule];
    if (draft === undefined || draft === rule.threshold) return;
    setSavingRule(rule.rule);
    setRuleError(null);
    try {
      await api.updateAlertRule(rule.rule, { threshold: draft });
      await refetch();
    } catch (err) {
      setRuleError(err instanceof ApiError ? err.message : "Failed to update the rule");
    } finally {
      setSavingRule(null);
    }
  }

  return (
    <Panel
      title="Alert rule thresholds"
      action={<span className="text-[10px] text-base-500">evaluated by the worker every ~60s</span>}
    >
      {error && <ErrorState message={error} onRetry={refetch} />}
      {!error && (loading || !rules) && <SkeletonTable rows={5} cols={4} />}
      {!error && rules && (
        <div className="space-y-2">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded border border-base-700 bg-base-900 px-3 py-2 text-xs"
            >
              <div className="min-w-[10rem]">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-base-200">{rule.rule}</span>
                  <StatusBadge status={rule.severity} />
                </div>
                <p className="mt-0.5 text-[11px] text-base-500">{rule.description}</p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  step="0.01"
                  defaultValue={rule.threshold}
                  onChange={(e) => {
                    // An emptied box is "no value yet", not 0 — saving a
                    // threshold of 0 would make the rule fire constantly.
                    const value = e.target.value.trim();
                    setDrafts((d) => {
                      const { [rule.rule]: _dropped, ...rest } = d;
                      return value !== "" && Number.isFinite(Number(value))
                        ? { ...rest, [rule.rule]: Number(value) }
                        : rest;
                    });
                  }}
                  className="w-24 rounded border border-base-600 bg-base-800 px-2 py-1 text-right font-mono text-base-200"
                />
                <button
                  type="button"
                  onClick={() => saveThreshold(rule)}
                  disabled={savingRule === rule.rule || drafts[rule.rule] === undefined}
                  className="rounded border border-base-600 px-2 py-1 text-base-300 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-600"
                >
                  {savingRule === rule.rule ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={() => toggleEnabled(rule)}
                  className={
                    rule.enabled
                      ? "rounded border border-emerald-700 px-2 py-1 text-emerald-300 hover:bg-emerald-900/30"
                      : "rounded border border-base-600 px-2 py-1 text-base-500 hover:bg-base-700"
                  }
                >
                  {rule.enabled ? "Enabled" : "Disabled"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {ruleError && <p className="mt-2 text-xs text-red-400">{ruleError}</p>}
    </Panel>
  );
}

function RecentAlertsPanel() {
  const { data, loading, error, refetch } = useFetch(() => api.listAlerts({ limit: 25 }), []);

  const columns: Column<Alert>[] = [
    { key: "rule", header: "Rule", render: (a) => <span className="font-mono text-xs">{a.rule}</span> },
    { key: "current_value", header: "Value", align: "right", render: (a) => a.current_value.toFixed(3) },
    { key: "threshold", header: "Threshold", align: "right", render: (a) => a.threshold.toFixed(3) },
    { key: "severity", header: "Severity", render: (a) => <StatusBadge status={a.severity} /> },
    { key: "affected_service", header: "Service", render: (a) => a.affected_service },
    {
      key: "timestamp",
      header: "Fired",
      render: (a) => <span className="font-mono text-xs text-base-500">{formatDate(a.timestamp)}</span>,
      sortValue: (a) => a.timestamp,
    },
  ];

  return (
    <Panel title="Recently fired alerts">
      {error && <ErrorState message={error} onRetry={refetch} />}
      {!error && (loading || !data) && <SkeletonTable rows={3} cols={6} />}
      {!error && data && (
        <DataTable<Alert>
          columns={columns}
          rows={data.items}
          rowKey={(a) => a.id}
          emptyTitle="No alerts fired"
          emptyMessage="Nothing has breached a threshold recently."
          defaultSortKey="timestamp"
        />
      )}
    </Panel>
  );
}
