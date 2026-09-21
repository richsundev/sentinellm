import { render, screen } from "@testing-library/react";
import TraceDetailPage from "@/app/trace/[id]/page";
import type { Trace } from "@/lib/types";
import { mockApi, page } from "../test-utils/mockApi";

jest.mock("next/navigation", () => ({
  useParams: () => ({ id: "trc_1" }),
  useRouter: () => ({ push: jest.fn() }),
}));

const trace = (over: Partial<Trace> = {}): Trace => ({
  id: "1",
  trace_id: "trc_1",
  request_id: "req_1",
  application_id: "app",
  environment: "production",
  model: "mock:sentinel-flash",
  provider: "mock",
  prompt: "What is the refund policy?",
  system_prompt: null,
  response: "30 days.",
  input_tokens: 10,
  output_tokens: 5,
  latency_ms: 100,
  estimated_cost: 0.001,
  retrieved_documents: [],
  metadata: {},
  status: "ok",
  error: null,
  prompt_id: null,
  prompt_version: null,
  created_at: "2026-09-01T00:00:00Z",
  spans: [],
  evaluation: null,
  routing_decision: null,
  feedback: null,
  cache_hit: false,
  similarity_score: null,
  tags: [],
  ...over,
});

describe("Trace detail — served prompts", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("shows which prompt version answered, the canary arm, and the rendered prompt", async () => {
    mockApi({
      "GET /traces/trc_1": trace({
        prompt_id: "support-answer",
        prompt_version: 2,
        metadata: {
          rendered_prompt: "You are concise. Q: What is the refund policy?",
          prompt_variables: {},
          prompt_rollout_arm: "challenger",
        },
      }),
      "GET /models": page([]),
    });
    render(<TraceDetailPage />);

    expect(await screen.findByText("support-answer")).toBeInTheDocument();
    expect(screen.getAllByText(/v2/).length).toBeGreaterThan(0);
    expect(screen.getByText("canary challenger")).toBeInTheDocument();
    expect(screen.getByText("You are concise. Q: What is the refund policy?")).toBeInTheDocument();
  });

  it("shows nothing prompt-related for a trace that never used the registry", async () => {
    mockApi({ "GET /traces/trc_1": trace(), "GET /models": page([]) });
    render(<TraceDetailPage />);

    await screen.findByText("trc_1");
    expect(screen.queryByText(/Rendered prompt/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^prompt$/)).not.toBeInTheDocument();
  });
});

describe("Trace detail — routing candidates", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("says why a candidate model was excluded instead of showing its -1 marker score", async () => {
    mockApi({
      "GET /traces/trc_1": trace({
        routing_decision: {
          trace_id: "trc_1",
          selected_model: "mock:sentinel-pro",
          reason: "picked pro",
          created_at: "2026-09-01T00:00:00Z",
          candidates: [
            { model: "mock:sentinel-pro", routing_score: 0.61, predicted_quality: 0.9, normalized_cost: 0.5, normalized_latency: 0.4, risk: 0.1 },
            {
              model: "mock:sentinel-nano",
              routing_score: -1,
              predicted_quality: 0.4,
              normalized_cost: 0,
              normalized_latency: 0,
              risk: 0.1,
              excluded_reason: "request (~9000 tokens) exceeds the model's 8000-token context window",
            },
          ],
        },
      }),
      "GET /models": page([]),
    });
    render(<TraceDetailPage />);

    expect(await screen.findByText(/excluded: request \(~9000 tokens\)/)).toBeInTheDocument();
    expect(screen.queryByText("-1.000")).not.toBeInTheDocument();
    expect(screen.getByText("0.610")).toBeInTheDocument();
  });
});
