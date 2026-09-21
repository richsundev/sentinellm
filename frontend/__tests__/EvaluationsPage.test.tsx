import { render, screen, waitFor } from "@testing-library/react";
import EvaluationsPage from "@/app/evaluations/page";
import type { Evaluation } from "@/lib/types";
import { mockApi, page } from "../test-utils/mockApi";

jest.mock("next/navigation", () => ({ useRouter: () => ({ push: jest.fn() }) }));

const metric = (name: string, passed: boolean | null) => ({
  metric_name: name,
  score: 0.5,
  threshold: passed === null ? null : 0.5,
  passed,
  reason: "",
  evaluator_version: "v1",
});

const evaluation = (id: string, passed: boolean | null): Evaluation => ({
  trace_id: id,
  metrics: [metric("faithfulness", passed)],
  hallucination: null,
  overall_quality: 0.5,
  created_at: "2026-09-01T00:00:00Z",
});

describe("EvaluationsPage pass rate", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("ignores metrics that have no pass/fail verdict", async () => {
    // 1 pass, 1 fail, 2 with no threshold: the rate is 50%, not 25%.
    mockApi({
      "GET /evaluations": page([
        evaluation("t1", true),
        evaluation("t2", false),
        evaluation("t3", null),
        evaluation("t4", null),
      ]),
    });
    render(<EvaluationsPage />);

    await waitFor(() => expect(screen.getAllByTestId("metric-card").length).toBeGreaterThan(0));
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.queryByText("25.0%")).not.toBeInTheDocument();
  });
});
