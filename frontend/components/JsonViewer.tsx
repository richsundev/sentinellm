"use client";

import { useState } from "react";

export function JsonViewer({
  data,
  title = "Raw metadata",
  defaultOpen = false,
}: {
  data: unknown;
  title?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const json = JSON.stringify(data ?? {}, null, 2);

  return (
    <div className="rounded-lg border border-base-700 bg-base-850">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm font-medium text-base-200"
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className="text-base-400">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="max-h-96 overflow-auto border-t border-base-700 p-4 font-mono text-xs text-base-300">
          {json}
        </pre>
      )}
    </div>
  );
}
