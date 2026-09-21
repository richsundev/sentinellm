// Types mirroring the SentinelLLM backend API contract (/api/v1/*).

export interface Span {
  name: string;
  start_ms: number;
  duration_ms: number;
  status: "ok" | "error";
  metadata: Record<string, unknown>;
}

export interface RetrievedDocument {
  doc_id: string;
  content: string;
  score: number;
  rank: number;
}

export interface EvaluationMetric {
  metric_name: string;
  score: number;
  threshold: number | null;
  passed: boolean | null;
  reason: string;
  evaluator_version: string;
}

export type HallucinationStatus =
  | "SUPPORTED"
  | "PARTIALLY_SUPPORTED"
  | "UNSUPPORTED";

export interface HallucinationClaim {
  claim: string;
  status: HallucinationStatus;
  support_score: number;
  evidence: string;
}

export interface Hallucination {
  hallucination_score: number;
  claims: HallucinationClaim[];
}

export interface Evaluation {
  trace_id: string;
  metrics: EvaluationMetric[];
  hallucination: Hallucination | null;
  overall_quality: number;
  created_at: string;
}

export interface RoutingCandidate {
  model: string;
  routing_score: number;
  predicted_quality: number;
  normalized_cost: number;
  normalized_latency: number;
  risk: number;
}

export interface RoutingDecision {
  trace_id: string;
  selected_model: string;
  reason: string;
  candidates: RoutingCandidate[];
  created_at: string;
}

export type TraceStatus = "ok" | "error";

export interface Trace {
  id: string;
  trace_id: string;
  request_id: string;
  application_id: string;
  environment: string;
  model: string;
  provider: string;
  prompt: string;
  system_prompt: string | null;
  response: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  estimated_cost: number;
  retrieved_documents: RetrievedDocument[];
  metadata: Record<string, unknown>;
  status: TraceStatus;
  error: string | null;
  prompt_id: string | null;
  prompt_version: number | null;
  created_at: string;
  spans: Span[];
  evaluation: Evaluation | null;
  routing_decision: RoutingDecision | null;
  feedback: TraceFeedback | null;
  cache_hit: boolean;
  similarity_score: number | null;
  tags: string[];
}

export type FeedbackRating = "up" | "down";

export interface TraceFeedback {
  trace_id: string;
  rating: FeedbackRating;
  note: string | null;
  created_at: string;
}

export interface TraceTags {
  trace_id: string;
  tags: string[];
}

export interface TraceReplayRequest {
  model?: string;
  prompt_version?: number;
  use_cache?: boolean;
}

export type ModelStatus = "healthy" | "degraded" | "down";

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  input_price_per_1k: number;
  output_price_per_1k: number;
  context_window: number;
  avg_quality: number | null;
  avg_latency_ms: number | null;
  status: ModelStatus;
  status_auto: boolean;
  status_reason: string | null;
}

export interface ModelCreateRequest {
  id: string;
  name: string;
  provider: string;
  input_price_per_1k: number;
  output_price_per_1k: number;
  context_window?: number;
  quality_tier?: number;
  avg_latency_ms_prior?: number;
  status?: ModelStatus;
}

export interface ModelUpdateRequest {
  name?: string;
  input_price_per_1k?: number;
  output_price_per_1k?: number;
  context_window?: number;
  quality_tier?: number;
  avg_latency_ms_prior?: number;
  status?: ModelStatus;
  status_auto?: boolean;
}

export type Severity = "low" | "medium" | "high" | "critical";

export interface Regression {
  id: string;
  metric_name: string;
  previous_value: number;
  new_value: number;
  delta_pct: number;
  severity: Severity;
  detected_at: string;
  application_id: string;
  likely_cause: string;
}

export interface Alert {
  id: string;
  rule: string;
  current_value: number;
  threshold: number;
  severity: Severity;
  timestamp: string;
  affected_service: string;
  affected_model: string | null;
}

export interface AlertRule {
  id: string;
  rule: string;
  threshold: number;
  severity: Severity;
  enabled: boolean;
  description: string;
}

export interface Application {
  id: string;
  name: string;
  description: string | null;
  daily_cost_budget: number | null;
  created_at: string;
}

export interface ApplicationCreateRequest {
  name: string;
  description?: string;
  daily_cost_budget?: number;
}

export interface ApplicationUpdateRequest {
  description?: string | null;
  // `null` clears the budget; omitting the field leaves it unchanged.
  daily_cost_budget?: number | null;
}

export interface ApiKey {
  id: string;
  application_id: string;
  name: string;
  role: "read" | "write" | "admin";
  key_prefix: string;
  revoked: boolean;
  scoped_to_application: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated {
  id: string;
  name: string;
  role: string;
  key_prefix: string;
  plaintext_key: string;
  scoped_to_application: boolean;
}

export type PromptStatus = "draft" | "testing" | "production" | "deprecated";

export interface PromptVersion {
  prompt_id: string;
  version: number;
  template: string;
  variables: string[];
  status: PromptStatus;
  author: string;
  created_at: string;
}

export interface PromptPromotionResult {
  promoted: PromptVersion;
  justifying_experiment_id: string;
  justifying_experiment_pass_rate: number;
  demoted_version: number | null;
}

export interface Experiment {
  id: string;
  name: string;
  model: string;
  prompt_id: string;
  prompt_version: number;
  dataset_id: string;
  faithfulness: number;
  relevance: number;
  hallucination_rate: number;
  p95_latency_ms: number;
  cost_per_request: number;
  pass_rate: number;
  git_commit: string;
  parameters: Record<string, unknown>;
  created_at: string;
}

export interface ExperimentRunRequest {
  name: string;
  model: string;
  prompt_id: string;
  prompt_version: number;
  dataset_id: string;
  application_id?: string;
  sample_size?: number;
  quality_pass_threshold?: number;
}

export interface MetricComparison {
  metric_name: string;
  value_a: number;
  value_b: number;
  delta: number;
  delta_pct: number | null;
  better: "a" | "b" | "tie";
}

export interface ExperimentComparison {
  experiment_a: Experiment;
  experiment_b: Experiment;
  metrics: MetricComparison[];
}

export interface Dataset {
  id: string;
  name: string;
  version: string;
  record_count: number;
  created_at: string;
}

export interface DatasetRecord {
  id: string;
  question: string;
  context: string;
  expected_answer: string;
  metadata: Record<string, unknown>;
}

export interface OverviewMetrics {
  request_volume: number;
  error_rate: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  avg_cost_per_request: number;
  avg_tokens_per_request: number;
  hallucination_rate: number;
  avg_faithfulness: number;
  avg_relevance: number;
  model_usage: { model: string; count: number }[];
  provider_reliability: { provider: string; success_rate: number }[];
  timeseries: {
    timestamp: string;
    volume: number;
    p95_latency_ms: number;
    cost: number;
  }[];
  human_feedback_count: number;
  human_judge_agreement_rate: number | null;
  cache_hit_count: number;
  cache_hit_rate: number;
  estimated_cache_savings: number;
}

export interface CostSummary {
  total_cost: number;
  daily: { date: string; cost: number }[];
  by_model: { model: string; cost: number }[];
  by_application: { application_id: string; cost: number }[];
  insight_text: string | null;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type TimeRange = "1h" | "24h" | "7d" | "30d";

export type RolloutStage = "running" | "paused" | "promoted" | "rolled_back";

export interface Rollout {
  id: string;
  application_id: string;
  incumbent_model: string;
  challenger_model: string;
  traffic_pct: number;
  stage: RolloutStage;
  quality_floor: number;
  max_quality_regression: number;
  max_error_rate: number;
  min_sample_size: number;
  step_pct: number;
  max_pct: number;
  last_evaluated_at: string | null;
  outcome_reason: string | null;
  created_at: string;
}

export interface RolloutArmStats {
  model: string;
  request_count: number;
  error_rate: number;
  avg_quality: number | null;
  avg_latency_ms: number;
  avg_cost: number;
}

export interface RolloutDetail extends Rollout {
  incumbent_stats: RolloutArmStats;
  challenger_stats: RolloutArmStats;
}

export interface RolloutCreateRequest {
  application_id: string;
  incumbent_model: string;
  challenger_model: string;
  initial_pct?: number;
  quality_floor?: number;
  max_quality_regression?: number;
  max_error_rate?: number;
  min_sample_size?: number;
  step_pct?: number;
  max_pct?: number;
}

export interface PromptRollout {
  id: string;
  application_id: string;
  prompt_id: string;
  incumbent_version: number;
  challenger_version: number;
  traffic_pct: number;
  stage: RolloutStage;
  quality_floor: number;
  max_quality_regression: number;
  max_error_rate: number;
  min_sample_size: number;
  step_pct: number;
  max_pct: number;
  last_evaluated_at: string | null;
  outcome_reason: string | null;
  created_at: string;
}

export interface PromptArmStats {
  version: number;
  request_count: number;
  error_rate: number;
  avg_quality: number | null;
  avg_latency_ms: number;
  avg_cost: number;
}

export interface PromptRolloutDetail extends PromptRollout {
  incumbent_stats: PromptArmStats;
  challenger_stats: PromptArmStats;
}

export interface PromptRolloutCreateRequest {
  application_id: string;
  prompt_id: string;
  incumbent_version: number;
  challenger_version: number;
  initial_pct?: number;
  quality_floor?: number;
  max_quality_regression?: number;
  max_error_rate?: number;
  min_sample_size?: number;
  step_pct?: number;
  max_pct?: number;
}
