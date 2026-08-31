"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { TimeRange } from "./types";

interface FiltersState {
  timeRange: TimeRange;
  setTimeRange: (r: TimeRange) => void;
  environment: string;
  setEnvironment: (e: string) => void;
}

const FiltersContext = createContext<FiltersState | null>(null);

export function FiltersProvider({ children }: { children: ReactNode }) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [environment, setEnvironment] = useState<string>("all");

  const value = useMemo(
    () => ({ timeRange, setTimeRange, environment, setEnvironment }),
    [timeRange, environment]
  );

  return (
    <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>
  );
}

export function useFilters(): FiltersState {
  const ctx = useContext(FiltersContext);
  if (!ctx) {
    throw new Error("useFilters must be used within FiltersProvider");
  }
  return ctx;
}

export const TIME_RANGES: TimeRange[] = ["1h", "24h", "7d", "30d"];
export const ENVIRONMENTS = ["all", "production", "staging", "development"];
