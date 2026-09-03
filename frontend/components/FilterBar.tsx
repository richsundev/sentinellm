"use client";

export interface FilterBarProps {
  model: string;
  onModelChange: (v: string) => void;
  provider: string;
  onProviderChange: (v: string) => void;
  applicationId: string;
  onApplicationIdChange: (v: string) => void;
  status?: string;
  onStatusChange?: (v: string) => void;
  search?: string;
  onSearchChange?: (v: string) => void;
  tag?: string;
  onTagChange?: (v: string) => void;
}

export function FilterBar({
  model,
  onModelChange,
  provider,
  onProviderChange,
  applicationId,
  onApplicationIdChange,
  status,
  onStatusChange,
  search,
  onSearchChange,
  tag,
  onTagChange,
}: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-base-700 bg-base-850 p-3">
      <FilterInput
        label="Model"
        value={model}
        onChange={onModelChange}
        placeholder="e.g. gpt-4o"
      />
      <FilterInput
        label="Provider"
        value={provider}
        onChange={onProviderChange}
        placeholder="e.g. openai"
      />
      <FilterInput
        label="App"
        value={applicationId}
        onChange={onApplicationIdChange}
        placeholder="application_id"
      />
      {onStatusChange && (
        <label className="flex items-center gap-1.5 text-xs text-base-400">
          Status
          <select
            value={status}
            onChange={(e) => onStatusChange(e.target.value)}
            className="rounded border border-base-600 bg-base-800 px-2 py-1 text-xs text-base-100 focus:border-accent focus:outline-none"
          >
            <option value="">all</option>
            <option value="ok">ok</option>
            <option value="error">error</option>
          </select>
        </label>
      )}
      {onSearchChange && (
        <FilterInput
          label="Search"
          value={search ?? ""}
          onChange={onSearchChange}
          placeholder="prompt or response text"
        />
      )}
      {onTagChange && (
        <FilterInput label="Tag" value={tag ?? ""} onChange={onTagChange} placeholder="e.g. escalation" />
      )}
    </div>
  );
}

function FilterInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-base-400">
      {label}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-32 rounded border border-base-600 bg-base-800 px-2 py-1 text-xs text-base-100 placeholder:text-base-500 focus:border-accent focus:outline-none"
      />
    </label>
  );
}
