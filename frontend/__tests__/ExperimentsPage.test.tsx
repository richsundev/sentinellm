import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ExperimentsPage from "@/app/experiments/page";
import { buildComparison } from "@/lib/experiment-compare";
import type { Experiment } from "@/lib/types";
import { mockApi, page } from "../test-utils/mockApi";

const experiment = (id: string, over: Partial<Experiment> = {}): Experiment => ({
  id,
  name: "baseline",
  model: "mock:sentinel-flash",
  prompt_id: "support",
  prompt_version: 1,
  dataset_id: "ds-1",
  faithfulness: 0.9,
  relevance: 0.8,
  hallucination_rate: 0.1,
  p95_latency_ms: 100,
  cost_per_request: 0.001,
  pass_rate: 0.7,
  git_commit: "abcdef123456",
  parameters: {},
  created_at: "2026-09-01T00:00:00Z",
  ...over,
});

describe("ExperimentsPage", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("refuses a prompt version that is not a whole number instead of running v1", async () => {
    const api = mockApi({ "GET /experiments": page([]), "POST /experiments/run": {} });
    render(<ExperimentsPage />);
    await waitFor(() => expect(screen.getByText("Run")).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("e.g. flash-vs-pro"), { target: { value: "x" } });
    fireEvent.change(screen.getByPlaceholderText("mock:sentinel-flash"), { target: { value: "m" } });
    fireEvent.change(screen.getByPlaceholderText("support-answer"), { target: { value: "p" } });
    fireEvent.change(screen.getByPlaceholderText("from /datasets"), { target: { value: "d" } });
    const version = screen.getByDisplayValue("1");

    for (const bad of ["abc", "0", "", "1.5"]) {
      fireEvent.change(version, { target: { value: bad } });
      fireEvent.click(screen.getByText("Run"));
      expect(await screen.findByText(/whole number, 1 or higher/)).toBeInTheDocument();
    }
    expect(api.called("POST", "/experiments/run")).toHaveLength(0);

    fireEvent.change(version, { target: { value: "3" } });
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(api.called("POST", "/experiments/run")).toHaveLength(1));
    expect((api.called("POST", "/experiments/run")[0].body as { prompt_version: number }).prompt_version).toBe(3);
  });

  it("keys the comparison series by id, so experiments sharing a name stay separate", () => {
    const rows = buildComparison(
      experiment("e1", { faithfulness: 0.9 }),
      experiment("e2", { faithfulness: 0.5 })
    );
    expect(rows[0]).toEqual({ metric: "Faithfulness", e1: 0.9, e2: 0.5 });
  });
});
