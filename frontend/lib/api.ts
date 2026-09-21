import type {
  Alert,
  AlertRule,
  ApiKey,
  ApiKeyCreated,
  Application,
  ApplicationCreateRequest,
  ApplicationUpdateRequest,
  CostSummary,
  Dataset,
  DatasetRecord,
  Evaluation,
  Experiment,
  ExperimentComparison,
  ExperimentRunRequest,
  FeedbackRating,
  ModelCreateRequest,
  ModelInfo,
  ModelUpdateRequest,
  OverviewMetrics,
  Paginated,
  PromptPromotionResult,
  PromptRollout,
  PromptRolloutCreateRequest,
  PromptRolloutDetail,
  PromptVersion,
  Regression,
  Rollout,
  RolloutCreateRequest,
  RolloutDetail,
  RoutingDecision,
  TimeRange,
  Trace,
  TraceFeedback,
  TraceReplayRequest,
  TraceTags,
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

async function mutate<T>(
  path: string,
  options: { method: "POST" | "PATCH"; body?: unknown; formData?: FormData }
): Promise<T> {
  const url = new URL(`${API_PREFIX}${path}`, API_BASE_URL);
  const headers: Record<string, string> = { "X-API-Key": API_KEY, Accept: "application/json" };
  let bodyInit: BodyInit | undefined;
  if (options.formData) {
    // Let the browser set Content-Type (with multipart boundary) itself.
    bodyInit = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    bodyInit = JSON.stringify(options.body);
  }

  let res: Response;
  try {
    res = await fetch(url.toString(), { method: options.method, headers, body: bodyInit });
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
  q?: string;
  tag?: string;
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
  getOverviewMetrics: (
    range: TimeRange = "24h",
    filters: {
      model?: string;
      provider?: string;
      application_id?: string;
      environment?: string;
    } = {}
  ) => request<OverviewMetrics>("/metrics/overview", { range, ...filters }),
  getCostSummary: (range: TimeRange = "30d") =>
    request<CostSummary>("/metrics/cost", { range }),

  // Alert rule configuration (Settings page).
  listAlertRules: () => request<AlertRule[]>("/alerts/rules"),
  updateAlertRule: (rule: string, payload: { threshold?: number; enabled?: boolean }) =>
    mutate<AlertRule>(`/alerts/rules/${encodeURIComponent(rule)}`, { method: "PATCH", body: payload }),

  // Application / API key management (Settings page).
  listApplications: () => request<Paginated<Application>>("/applications", { limit: 200 }),
  listApiKeys: () => request<Paginated<ApiKey>>("/applications/api-keys", { limit: 200 }),
  createApiKey: (payload: {
    application_id: string;
    name: string;
    role: "read" | "write" | "admin";
    scoped_to_application?: boolean;
  }) => mutate<ApiKeyCreated>("/applications/api-keys", { method: "POST", body: payload }),

  // Dataset import (Datasets page).
  importDataset: (formData: FormData) =>
    mutate<Dataset>("/datasets/import", { method: "POST", formData }),

  // Experiment runs + comparison (Experiments page).
  runExperiment: (payload: ExperimentRunRequest) =>
    mutate<Experiment>("/experiments/run", { method: "POST", body: payload }),
  compareExperiments: (a: string, b: string) =>
    request<ExperimentComparison>("/experiments/compare", { a, b }),

  // Trace feedback (Trace detail page) + search (Traces page).
  submitTraceFeedback: (traceId: string, rating: FeedbackRating, note?: string) =>
    mutate<TraceFeedback>(`/traces/${encodeURIComponent(traceId)}/feedback`, {
      method: "POST",
      body: { rating, note },
    }),

  // Prompt promotion gate (Prompts page).
  promotePromptVersion: (promptId: string, version: number, qualityPassThreshold = 0.7) =>
    mutate<PromptPromotionResult>(
      `/prompts/${encodeURIComponent(promptId)}/versions/${version}/promote`,
      { method: "POST", body: { quality_pass_threshold: qualityPassThreshold } }
    ),

  // Model catalog management (Models page).
  createModel: (payload: ModelCreateRequest) =>
    mutate<ModelInfo>("/models", { method: "POST", body: payload }),
  updateModel: (modelId: string, payload: ModelUpdateRequest) =>
    mutate<ModelInfo>(`/models/${encodeURIComponent(modelId)}`, { method: "PATCH", body: payload }),

  // Application budgets (Settings page).
  createApplication: (payload: ApplicationCreateRequest) =>
    mutate<Application>("/applications", { method: "POST", body: payload }),
  updateApplication: (applicationId: string, payload: ApplicationUpdateRequest) =>
    mutate<Application>(`/applications/${encodeURIComponent(applicationId)}`, {
      method: "PATCH",
      body: payload,
    }),

  // Trace tags (Trace detail + Traces list filter).
  updateTraceTags: (traceId: string, tags: string[]) =>
    mutate<TraceTags>(`/traces/${encodeURIComponent(traceId)}/tags`, {
      method: "PATCH",
      body: { tags },
    }),

  // Trace replay (Trace detail page).
  replayTrace: (traceId: string, payload: TraceReplayRequest = {}) =>
    mutate<Trace>(`/traces/${encodeURIComponent(traceId)}/replay`, {
      method: "POST",
      body: payload,
    }),

  // Trace CSV export (Traces page) — triggers a browser download rather
  // than returning parsed JSON, since the endpoint streams text/csv.
  exportTracesCsv: async (filters: TraceFilters = {}): Promise<void> => {
    const url = new URL(`${API_PREFIX}/traces/export`, API_BASE_URL);
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
    const res = await fetch(url.toString(), { headers: { "X-API-Key": API_KEY } });
    if (!res.ok) {
      throw new ApiError(`Export failed with ${res.status}`, res.status);
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = "traces.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objectUrl);
  },

  // Progressive model canary rollouts (Rollouts page).
  listRollouts: (params: { application_id?: string; stage?: string; limit?: number } = {}) =>
    request<Paginated<Rollout>>("/rollouts", params),
  getRollout: (rolloutId: string) =>
    request<RolloutDetail>(`/rollouts/${encodeURIComponent(rolloutId)}`),
  createRollout: (payload: RolloutCreateRequest) =>
    mutate<Rollout>("/rollouts", { method: "POST", body: payload }),
  pauseRollout: (rolloutId: string) =>
    mutate<Rollout>(`/rollouts/${encodeURIComponent(rolloutId)}/pause`, { method: "POST" }),
  resumeRollout: (rolloutId: string) =>
    mutate<Rollout>(`/rollouts/${encodeURIComponent(rolloutId)}/resume`, { method: "POST" }),
  promoteRollout: (rolloutId: string) =>
    mutate<Rollout>(`/rollouts/${encodeURIComponent(rolloutId)}/promote`, { method: "POST" }),
  rollbackRollout: (rolloutId: string) =>
    mutate<Rollout>(`/rollouts/${encodeURIComponent(rolloutId)}/rollback`, { method: "POST" }),

  // Progressive prompt-version canary rollouts (Rollouts page, "Prompt canaries" tab).
  listPromptRollouts: (
    params: { application_id?: string; prompt_id?: string; stage?: string; limit?: number } = {}
  ) => request<Paginated<PromptRollout>>("/prompt-rollouts", params),
  getPromptRollout: (rolloutId: string) =>
    request<PromptRolloutDetail>(`/prompt-rollouts/${encodeURIComponent(rolloutId)}`),
  createPromptRollout: (payload: PromptRolloutCreateRequest) =>
    mutate<PromptRollout>("/prompt-rollouts", { method: "POST", body: payload }),
  pausePromptRollout: (rolloutId: string) =>
    mutate<PromptRollout>(`/prompt-rollouts/${encodeURIComponent(rolloutId)}/pause`, {
      method: "POST",
    }),
  resumePromptRollout: (rolloutId: string) =>
    mutate<PromptRollout>(`/prompt-rollouts/${encodeURIComponent(rolloutId)}/resume`, {
      method: "POST",
    }),
  promotePromptRollout: (rolloutId: string) =>
    mutate<PromptRollout>(`/prompt-rollouts/${encodeURIComponent(rolloutId)}/promote`, {
      method: "POST",
    }),
  rollbackPromptRollout: (rolloutId: string) =>
    mutate<PromptRollout>(`/prompt-rollouts/${encodeURIComponent(rolloutId)}/rollback`, {
      method: "POST",
    }),
};

export type Api = typeof api;
