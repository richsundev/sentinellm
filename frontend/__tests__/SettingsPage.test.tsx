import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SettingsPage from "@/app/settings/page";
import type { AlertRule, Application } from "@/lib/types";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

const application = (over: Partial<Application> = {}): Application => ({
  id: "a1",
  name: "checkout",
  description: null,
  daily_cost_budget: 5,
  created_at: "2026-09-01T00:00:00Z",
  ...over,
});

const rule = (over: Partial<AlertRule> = {}): AlertRule => ({
  id: "r1",
  rule: "high_error_rate",
  threshold: 0.1,
  enabled: true,
  severity: "high",
  description: "Error rate over threshold",
  ...over,
});

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /applications": page([application()]),
    "GET /applications/api-keys": page([]),
    "GET /alerts/rules": [rule()],
    "GET /alerts": page([]),
    ...extra,
  };
}

describe("Settings page", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("clears an application's budget by sending null (undefined is dropped from JSON)", async () => {
    const api = mockApi(routes({ "PATCH /applications/a1": application({ daily_cost_budget: null }) }));
    render(<SettingsPage />);
    const budget = await screen.findByDisplayValue("5");

    fireEvent.change(budget, { target: { value: "" } });
    fireEvent.blur(budget);

    await waitFor(() => expect(api.called("PATCH", "/applications/a1")).toHaveLength(1));
    expect(api.called("PATCH", "/applications/a1")[0].body).toEqual({ daily_cost_budget: null });
  });

  it("shows why a budget save failed instead of failing silently", async () => {
    mockApi(routes({ "PATCH /applications/a1": new HttpFailure(422, "budget too high") }));
    render(<SettingsPage />);
    const budget = await screen.findByDisplayValue("5");

    fireEvent.change(budget, { target: { value: "9" } });
    fireEvent.blur(budget);

    expect(await screen.findByText("budget too high")).toBeInTheDocument();
  });

  it("does not let an emptied threshold box be saved as 0", async () => {
    const api = mockApi(routes({ "PATCH /alerts/rules/high_error_rate": rule() }));
    render(<SettingsPage />);
    const threshold = await screen.findByDisplayValue("0.1");
    const save = threshold.parentElement!.querySelector("button")!;

    fireEvent.change(threshold, { target: { value: "0.3" } });
    expect(save).toBeEnabled();
    fireEvent.change(threshold, { target: { value: "" } });

    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(api.called("PATCH", "/alerts/rules/high_error_rate")).toHaveLength(0);
  });

  it("reports a failed rule update", async () => {
    mockApi(routes({ "PATCH /alerts/rules/high_error_rate": new HttpFailure(500, "db down") }));
    render(<SettingsPage />);
    fireEvent.click(await screen.findByText("Enabled"));

    expect(await screen.findByText("db down")).toBeInTheDocument();
  });
});
