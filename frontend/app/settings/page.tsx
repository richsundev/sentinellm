"use client";

import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Panel } from "@/components/Panel";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { StatusBadge } from "@/components/StatusBadge";
import type { Alert } from "@/lib/types";
import { formatDate } from "@/lib/format";

interface MaskedApiKey {
  id: string;
  label: string;
  masked: string;
  role: string;
  created_at: string;
}

// The backend does not yet expose key management; these placeholder rows
// illustrate the intended UI shape and are clearly marked as read-only mocks.
const MOCK_API_KEYS: MaskedApiKey[] = [
  {
    id: "key_1",
    label: "Dashboard (this session)",
    masked: "demo-••••••••-key",
    role: "read-only",
    created_at: new Date().toISOString(),
  },
];

export default function SettingsPage() {
  const { data, loading, error, refetch } = useFetch(
    () => api.listAlerts({ limit: 100 }),
    []
  );

  const alertColumns: Column<Alert>[] = [
    {
      key: "rule",
      header: "Rule",
      render: (a) => <span className="text-xs text-base-200">{a.rule}</span>,
      sortValue: (a) => a.rule,
    },
    {
      key: "current_value",
      header: "Current",
      align: "right",
      render: (a) => a.current_value.toFixed(3),
      sortValue: (a) => a.current_value,
    },
    {
      key: "threshold",
      header: "Threshold",
      align: "right",
      render: (a) => a.threshold.toFixed(3),
      sortValue: (a) => a.threshold,
    },
    {
      key: "severity",
      header: "Severity",
      render: (a) => <StatusBadge status={a.severity} />,
      sortValue: (a) => a.severity,
    },
    {
      key: "affected_service",
      header: "Service",
      render: (a) => a.affected_service,
    },
    {
      key: "affected_model",
      header: "Model",
      render: (a) => (
        <span className="font-mono text-xs">{a.affected_model ?? "—"}</span>
      ),
    },
    {
      key: "timestamp",
      header: "Fired",
      render: (a) => <span className="font-mono text-xs">{formatDate(a.timestamp)}</span>,
      sortValue: (a) => a.timestamp,
    },
  ];

  return (
    <div className="space-y-6">
      <Panel title="API keys" action={<span className="text-[10px] text-base-500">read-only preview</span>}>
        <div className="space-y-2">
          {MOCK_API_KEYS.map((k) => (
            <div
              key={k.id}
              className="flex items-center justify-between rounded border border-base-700 bg-base-900 px-3 py-2 text-xs"
            >
              <span className="text-base-200">{k.label}</span>
              <span className="font-mono text-base-400">{k.masked}</span>
              <StatusBadge status={k.role} tone="info" />
              <span className="font-mono text-base-500">{formatDate(k.created_at)}</span>
            </div>
          ))}
        </div>
        <button
          type="button"
          disabled
          className="mt-3 cursor-not-allowed rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-500"
        >
          + Create key (disabled in demo)
        </button>
      </Panel>

      <Panel title="Alert rules">
        {error && <ErrorState message={error} onRetry={refetch} />}
        {!error && (loading || !data) && <SkeletonTable rows={4} cols={7} />}
        {!error && data && (
          <DataTable<Alert>
            columns={alertColumns}
            rows={data.items}
            rowKey={(a) => a.id}
            emptyTitle="No alert rules"
            emptyMessage="No alert rules have fired recently."
            defaultSortKey="timestamp"
          />
        )}
      </Panel>

      <Panel title="Webhook configuration">
        <form className="space-y-3">
          <label className="block text-xs text-base-400">
            Webhook URL
            <input
              disabled
              placeholder="https://hooks.example.com/sentinellm"
              className="mt-1 w-full cursor-not-allowed rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-300 placeholder:text-base-500"
            />
          </label>
          <label className="block text-xs text-base-400">
            Signing secret
            <input
              disabled
              type="password"
              value="••••••••••••••••"
              readOnly
              className="mt-1 w-full cursor-not-allowed rounded border border-base-600 bg-base-800 px-2 py-1.5 text-xs text-base-300"
            />
          </label>
          <button
            type="button"
            disabled
            className="cursor-not-allowed rounded border border-base-600 bg-base-800 px-3 py-1.5 text-xs text-base-500"
          >
            Save (disabled in demo)
          </button>
        </form>
      </Panel>
    </div>
  );
}
