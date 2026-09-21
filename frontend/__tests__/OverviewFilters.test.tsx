import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import OverviewPage from "@/app/overview/page";
import { FiltersProvider, useFilters } from "@/lib/filters-context";
import type { OverviewMetrics } from "@/lib/types";
import { mockApi } from "../test-utils/mockApi";

const overview: OverviewMetrics = {
  request_volume: 10,
  error_rate: 0,
  p50_latency_ms: 1,
  p95_latency_ms: 1,
  p99_latency_ms: 1,
  avg_cost_per_request: 0,
  avg_tokens_per_request: 0,
  hallucination_rate: 0,
  avg_faithfulness: 0,
  avg_relevance: 0,
  model_usage: [],
  provider_reliability: [],
  timeseries: [],
  human_feedback_count: 0,
  human_judge_agreement_rate: null,
  cache_hit_count: 0,
  cache_hit_rate: 0,
  estimated_cache_savings: 0,
};

function EnvPicker() {
  const { setEnvironment } = useFilters();
  return <button onClick={() => setEnvironment("staging")}>go staging</button>;
}

describe("Overview filters", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("sends the filter-bar values and the selected environment to the API", async () => {
    const api = mockApi({ "GET /metrics/overview": overview });
    render(
      <FiltersProvider>
        <EnvPicker />
        <OverviewPage />
      </FiltersProvider>
    );
    await waitFor(() => expect(api.called("GET", "/metrics/overview").length).toBe(1));
    // Nothing is filtered by default — no empty params on the wire.
    expect(api.calls[0].query).toEqual({ range: "24h" });

    fireEvent.change(screen.getByPlaceholderText("e.g. gpt-4o"), {
      target: { value: "mock:sentinel-pro" },
    });
    fireEvent.change(screen.getByPlaceholderText("application_id"), {
      target: { value: "checkout" },
    });
    fireEvent.click(screen.getByText("go staging"));

    await waitFor(() => {
      const last = api.called("GET", "/metrics/overview").at(-1)!;
      expect(last.query).toMatchObject({
        range: "24h",
        model: "mock:sentinel-pro",
        application_id: "checkout",
        environment: "staging",
      });
    });
  });
});
