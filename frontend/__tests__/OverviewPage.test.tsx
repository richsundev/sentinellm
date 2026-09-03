import { render, screen, waitFor } from "@testing-library/react";
import OverviewPage from "@/app/overview/page";
import { FiltersProvider } from "@/lib/filters-context";

describe("OverviewPage (smoke test)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.resetAllMocks();
  });

  it("renders an error state when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network error"));

    render(
      <FiltersProvider>
        <OverviewPage />
      </FiltersProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("error-state")).toBeInTheDocument();
    });
  });

  it("renders KPI cards once the overview metrics load", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        request_volume: 1000,
        error_rate: 0.02,
        p50_latency_ms: 200,
        p95_latency_ms: 500,
        p99_latency_ms: 800,
        avg_cost_per_request: 0.002,
        avg_tokens_per_request: 450,
        hallucination_rate: 0.03,
        avg_faithfulness: 0.91,
        avg_relevance: 0.88,
        model_usage: [{ model: "gpt-4o", count: 100 }],
        provider_reliability: [{ provider: "openai", success_rate: 0.99 }],
        timeseries: [
          { timestamp: "2026-08-31T00:00:00Z", volume: 10, p95_latency_ms: 400, cost: 1.2 },
        ],
        human_feedback_count: 5,
        human_judge_agreement_rate: 0.8,
      }),
    });

    render(
      <FiltersProvider>
        <OverviewPage />
      </FiltersProvider>
    );

    await waitFor(() => {
      expect(screen.getAllByTestId("metric-card").length).toBeGreaterThan(0);
    });
  });
});
