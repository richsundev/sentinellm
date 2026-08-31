"use client";

import clsx from "clsx";
import { useMemo, useState, type ReactNode } from "react";
import { EmptyState } from "./StateViews";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number;
  className?: string;
  align?: "left" | "right" | "center";
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyMessage?: string;
  defaultSortKey?: string;
  defaultSortDir?: "asc" | "desc";
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  emptyTitle,
  emptyMessage,
  defaultSortKey,
  defaultSortDir = "desc",
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | undefined>(defaultSortKey);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir);

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const va = col.sortValue!(a);
      const vb = col.sortValue!(b);
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortDir, columns]);

  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} message={emptyMessage} />;
  }

  function toggleSort(col: Column<T>) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(col.key);
      setSortDir("desc");
    }
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-base-700 bg-base-850">
      <table data-testid="data-table" className="w-full min-w-max text-left text-sm">
        <thead>
          <tr className="border-b border-base-700 text-[11px] uppercase tracking-wide text-base-400">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={clsx(
                  "whitespace-nowrap px-3 py-2 font-medium",
                  col.sortValue && "cursor-pointer select-none hover:text-base-100",
                  col.align === "right" && "text-right",
                  col.align === "center" && "text-center"
                )}
                onClick={() => toggleSort(col)}
              >
                {col.header}
                {sortKey === col.key && (
                  <span className="ml-1 text-accent">
                    {sortDir === "asc" ? "↑" : "↓"}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={clsx(
                "border-b border-base-800 last:border-0",
                onRowClick && "cursor-pointer hover:bg-base-800/70"
              )}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={clsx(
                    "whitespace-nowrap px-3 py-2 text-base-200",
                    col.className,
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center"
                  )}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({
  offset,
  limit,
  total,
  onPageChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onPageChange: (nextOffset: number) => void;
}) {
  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="flex items-center justify-between px-1 py-2 text-xs text-base-400">
      <span>
        {total === 0
          ? "0 results"
          : `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={offset === 0}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          className="rounded border border-base-600 px-2 py-1 disabled:opacity-30 hover:bg-base-800"
        >
          Prev
        </button>
        <span className="font-mono">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={offset + limit >= total}
          onClick={() => onPageChange(offset + limit)}
          className="rounded border border-base-600 px-2 py-1 disabled:opacity-30 hover:bg-base-800"
        >
          Next
        </button>
      </div>
    </div>
  );
}
