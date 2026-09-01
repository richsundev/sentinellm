"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { Alert, AlertRule, ApiKey } from "@/lib/types";
import { formatDate } from "@/lib/format";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
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
          URL, delivered by the worker.
        </p>
      </Panel>
    </div>
  );
}

function ApiKeysPanel() {
  const { data: keys, loading, error, refetch: refetchKeys } = useFetch(() => api.listApiKeys(), []);
  const { data: apps } = useFetch(() => api.listApplications(), []);
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  const defaultApplicationId = apps?.items[0]?.id;

  async function handleCreate() {
    if (!defaultApplicationId || !newKeyName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await api.createApiKey({
        application_id: defaultApplicationId,
        name: newKeyName.trim(),
        role: "write",
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

      <div className="mt-3 flex items-center gap-2">
        <input
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          placeholder="Key name (e.g. ci-pipeline)"
          disabled={!defaultApplicationId || creating}
          className="rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-200 placeholder:text-base-500 disabled:cursor-not-allowed"
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={!defaultApplicationId || !newKeyName.trim() || creating}
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

  async function toggleEnabled(rule: AlertRule) {
    await api.updateAlertRule(rule.rule, { enabled: !rule.enabled });
    await refetch();
  }

  async function saveThreshold(rule: AlertRule) {
    const draft = drafts[rule.rule];
    if (draft === undefined || draft === rule.threshold) return;
    setSavingRule(rule.rule);
    try {
      await api.updateAlertRule(rule.rule, { threshold: draft });
      await refetch();
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
                  onChange={(e) =>
                    setDrafts((d) => ({ ...d, [rule.rule]: Number(e.target.value) }))
                  }
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
