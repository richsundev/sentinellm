import { render, screen, waitFor } from "@testing-library/react";
import RegressionsPage from "@/app/regressions/page";
import type { Regression } from "@/lib/types";
import { mockApi, page } from "../test-utils/mockApi";

const regression = (over: Partial<Regression>): Regression => ({
  id: "r1",
  metric_name: "faithfulness",
  previous_value: 0.9,
  new_value: 0.8,
  delta_pct: 11.11,
  severity: "medium",
  detected_at: "2026-09-01T00:00:00Z",
  application_id: "app-1",
  likely_cause: "prompt change",
  ...over,
});

async function renderWith(items: Regression[]) {
  mockApi({ "GET /regressions": page(items) });
  const view = render(<RegressionsPage />);
  await waitFor(() => expect(screen.getAllByText("app-1").length).toBeGreaterThan(0));
  return view;
}

describe("RegressionsPage", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("shows a quality drop as a decrease, in the error colour", async () => {
    await renderWith([regression({})]);
    const cell = screen.getAllByText("−11.1%")[0];
    expect(cell).toHaveClass("text-err");
  });

  it("shows a latency-style regression as an increase — still an error, not green", async () => {
    await renderWith([
      regression({
        metric_name: "hallucination_score",
        previous_value: 0.1,
        new_value: 0.2,
        delta_pct: 100,
      }),
    ]);
    const cell = screen.getAllByText("+100.0%")[0];
    expect(cell).toHaveClass("text-err");
  });

  it("does not misread a 1% change as 100%", async () => {
    await renderWith([regression({ previous_value: 0.9, new_value: 0.891, delta_pct: 1 })]);
    expect(screen.getAllByText("−1.0%").length).toBeGreaterThan(0);
    expect(screen.queryByText(/100\.0%/)).not.toBeInTheDocument();
  });
});
