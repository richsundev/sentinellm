import type {
  Alert,
  CostSummary,
  Dataset,
  DatasetRecord,
  Evaluation,
  Experiment,
  ModelInfo,
  OverviewMetrics,
  Paginated,
  PromptVersion,
  Regression,
  RoutingDecision,
  TimeRange,
  Trace,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "demo-api-key";

const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type QueryParams = Record<
  string,
  string | number | boolean | undefined | null
>;

async function request<T>(path: string, params?: QueryParams): Promise<T> {
  const url = new URL(`${API_PREFIX}${path}`, API_BASE_URL);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  let res: Response;
  try {
    res = await fetch(url.toString(), {
      headers: {
        "X-API-Key": API_KEY,
        Accept: "application/json",
      },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiError(
      err instanceof Error ? err.message : "Network error reaching API",
      0
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        detail = String((body as { detail: unknown }).detail);
      }
    } catch {
      // ignore body parse failures
    }
    throw new ApiError(detail || `Request failed with ${res.status}`, res.status);
  }

  return (await res.json()) as T;
}

export type TraceFilters = {
  limit?: number;
  offset?: number;
  model?: string;
  provider?: string;
  application_id?: string;
  environment?: string;
  status?: string;
};

export type EvaluationFilters = {
  trace_id?: string;
  limit?: number;
  offset?: number;
};

export const api = {
  listTraces: (filters: TraceFilters = {}) =>
    request<Paginated<Trace>>("/traces", filters),
  getTrace: (traceId: string) =>
    request<Trace>(`/traces/${encodeURIComponent(traceId)}`),
  listEvaluations: (filters: EvaluationFilters = {}) =>
    request<Paginated<Evaluation>>("/evaluations", filters),
  listDatasets: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<Dataset>>("/datasets", params),
  listDatasetRecords: (
    datasetId: string,
    params: { limit?: number; offset?: number } = {}
  ) =>
    request<Paginated<DatasetRecord>>(
      `/datasets/${encodeURIComponent(datasetId)}/records`,
      params
    ),
  listExperiments: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<Experiment>>("/experiments", params),
  listPrompts: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<PromptVersion>>("/prompts", params),
  listModels: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<ModelInfo>>("/models", params),
  listRoutingDecisions: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<RoutingDecision>>("/routing/decisions", params),
  listAlerts: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<Alert>>("/alerts", params),
  listRegressions: (params: { limit?: number; offset?: number } = {}) =>
    request<Paginated<Regression>>("/regressions", params),
  getOverviewMetrics: (range: TimeRange = "24h") =>
    request<OverviewMetrics>("/metrics/overview", { range }),
  getCostSummary: (range: TimeRange = "30d") =>
    request<CostSummary>("/metrics/cost", { range }),
};

export type Api = typeof api;
