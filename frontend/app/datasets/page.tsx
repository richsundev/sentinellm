"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { DataTable, type Column } from "@/components/DataTable";
import { ErrorState, SkeletonTable } from "@/components/StateViews";
import { Panel } from "@/components/Panel";
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
      // The Experiments form asks for this id; it was only discoverable by
      // opening the dataset and reading the page title.
      key: "id",
      header: "ID",
      render: (d) => <span className="font-mono text-[11px] text-base-400">{d.id}</span>,
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
      <ImportDatasetPanel onImported={refetch} />
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

function ImportDatasetPanel({ onImported }: { onImported: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [version, setVersion] = useState("v1");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importedName, setImportedName] = useState<string | null>(null);

  async function handleImport() {
    const file = fileInputRef.current?.files?.[0];
    if (!file || !name.trim()) return;
    setImporting(true);
    setImportError(null);
    setImportedName(null);
    try {
      const formData = new FormData();
      formData.append("name", name.trim());
      formData.append("version", version.trim() || "v1");
      formData.append("file", file);
      const dataset = await api.importDataset(formData);
      setImportedName(`${dataset.name} (${dataset.record_count} records)`);
      setName("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      onImported();
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  return (
    <Panel
      title="Import dataset"
      action={<span className="text-[10px] text-base-500">.jsonl or .csv, question column required</span>}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Dataset name"
          className="rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 placeholder:text-base-500"
        />
        <input
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          placeholder="Version"
          className="w-20 rounded border border-base-600 bg-base-800 px-2 py-1.5 text-base-200 placeholder:text-base-500"
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".jsonl,.ndjson,.csv"
          className="text-base-300 file:mr-2 file:rounded file:border file:border-base-600 file:bg-base-800 file:px-2 file:py-1 file:text-base-200"
        />
        <button
          type="button"
          onClick={handleImport}
          disabled={!name.trim() || importing}
          className="rounded border border-base-600 bg-base-800 px-3 py-1.5 text-base-200 hover:bg-base-700 disabled:cursor-not-allowed disabled:text-base-500"
        >
          {importing ? "Importing…" : "Import"}
        </button>
      </div>
      {importError && <p className="mt-2 text-xs text-red-400">{importError}</p>}
      {importedName && <p className="mt-2 text-xs text-ok">Imported {importedName}.</p>}
    </Panel>
  );
}
