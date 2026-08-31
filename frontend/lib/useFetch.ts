"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DependencyList,
} from "react";
import { ApiError } from "./api";

export interface FetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Client-side data-fetching hook with loading/error state, intended for
 * dashboard widgets that must render gracefully whether or not the backend
 * is reachable. `deps` should include every value the fetcher closes over.
 */
export function useFetch<T>(
  fetcher: () => Promise<T>,
  deps: DependencyList
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);

  // Keep the ref pointed at the latest closure without mutating it during
  // render (react-hooks/refs) — this effect runs on every commit, ordered
  // before the fetch effect below, so the fetch effect always sees the
  // fetcher from the same render it was triggered by.
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let cancelled = false;
    // This is the standard "reset loading state before a dependency-driven
    // refetch" pattern (see React's own data-fetching docs). The stricter
    // react-hooks/set-state-in-effect rule is aimed at components that will
    // run under the React Compiler, which this project doesn't use; the
    // synchronous reset here is intentional so stale data isn't shown while
    // a new fetch (e.g. after a time-range change) is in flight.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    fetcherRef
      .current()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const message =
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : "Unknown error";
          setError(message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  return { data, loading, error, refetch };
}
