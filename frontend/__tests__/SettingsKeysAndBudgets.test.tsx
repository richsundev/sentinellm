import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import SettingsPage from "@/app/settings/page";
import type { ApiKey, Application, BudgetStatus } from "@/lib/types";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

const application = (over: Partial<Application> = {}): Application => ({
  id: "a1",
  name: "checkout",
  description: null,
  daily_cost_budget: 10,
  budget_action: "alert",
  created_at: "2026-09-01T00:00:00Z",
  ...over,
});

const key = (over: Partial<ApiKey> = {}): ApiKey => ({
  id: "k1",
  application_id: "a1",
  name: "ci-pipeline",
  role: "write",
  key_prefix: "sk_sentinel_abc",
  revoked: false,
  revoked_at: null,
  expires_at: null,
  scoped_to_application: false,
  created_at: "2026-09-01T00:00:00Z",
  last_used_at: null,
  ...over,
});

const budget = (over: Partial<BudgetStatus> = {}): BudgetStatus => ({
  application_id: "a1",
  daily_cost_budget: 10,
  budget_action: "alert",
  spent_24h: 3.5,
  remaining: 6.5,
  exceeded: false,
  ...over,
});

function routes(extra: Record<string, unknown> = {}, keys: ApiKey[] = [key()]) {
  return {
    "GET /applications": page([application()]),
    "GET /applications/a1/budget": budget(),
    "GET /applications/api-keys": page(keys),
    "GET /alerts/rules": [],
    "GET /alerts": page([]),
    ...extra,
  };
}

describe("Settings — API key lifecycle", () => {
  const originalFetch = global.fetch;
  const originalConfirm = window.confirm;
  afterEach(() => {
    global.fetch = originalFetch;
    window.confirm = originalConfirm;
  });

  it("shows whether each key is active, expired or revoked, and when it expires / was used", async () => {
    const past = new Date(Date.now() - 86_400_000).toISOString();
    const future = new Date(Date.now() + 40 * 86_400_000).toISOString();
    mockApi(
      routes({}, [
        key({ id: "k1", name: "live", expires_at: future, last_used_at: "2026-09-02T00:00:00Z" }),
        key({ id: "k2", name: "lapsed", expires_at: past }),
        key({ id: "k3", name: "gone", revoked: true, revoked_at: past }),
      ])
    );
    render(<SettingsPage />);

    const rowOf = async (name: string) => (await screen.findByText(name)).closest("tr")!;
    expect(within(await rowOf("live")).getByText("active")).toBeInTheDocument();
    expect(within(await rowOf("lapsed")).getByText("expired")).toBeInTheDocument();
    expect(within(await rowOf("gone")).getByText("revoked")).toBeInTheDocument();
    // a revoked key offers no actions; the others do
    expect(within(await rowOf("gone")).queryByText("Revoke")).not.toBeInTheDocument();
    expect(within(await rowOf("live")).getByText("Revoke")).toBeInTheDocument();
    expect(within(await rowOf("live")).queryAllByText("never")).toHaveLength(0);
    expect(within(await rowOf("lapsed")).getByText("never")).toBeInTheDocument(); // last used
  });

  it("revokes only after confirmation", async () => {
    const api = mockApi(routes({ "POST /applications/api-keys/k1/revoke": key({ revoked: true }) }));
    render(<SettingsPage />);
    const revoke = await screen.findByText("Revoke");

    window.confirm = jest.fn(() => false);
    fireEvent.click(revoke);
    expect(api.called("POST", "/applications/api-keys/k1/revoke")).toHaveLength(0);

    window.confirm = jest.fn(() => true);
    fireEvent.click(revoke);
    await waitFor(() =>
      expect(api.called("POST", "/applications/api-keys/k1/revoke")).toHaveLength(1)
    );
  });

  it("shows why a revoke failed", async () => {
    mockApi(
      routes({
        "POST /applications/api-keys/k1/revoke": new HttpFailure(409, "a key can't revoke itself"),
      })
    );
    window.confirm = jest.fn(() => true);
    render(<SettingsPage />);

    fireEvent.click(await screen.findByText("Revoke"));

    expect(await screen.findByText("a key can't revoke itself")).toBeInTheDocument();
  });

  it("rotates with a grace period and reveals the replacement key once", async () => {
    const api = mockApi(
      routes({
        "POST /applications/api-keys/k1/rotate": {
          id: "k9",
          name: "ci-pipeline",
          role: "write",
          key_prefix: "sk_sentinel_new",
          plaintext_key: "sk_sentinel_the_new_secret",
          scoped_to_application: false,
        },
      })
    );
    render(<SettingsPage />);

    fireEvent.click(await screen.findByText("Rotate"));
    expect(screen.getByLabelText("Grace period in minutes")).toHaveValue(60);
    fireEvent.change(screen.getByLabelText("Grace period in minutes"), { target: { value: "15" } });
    fireEvent.click(screen.getByText("Confirm rotate"));

    expect(await screen.findByText("sk_sentinel_the_new_secret")).toBeInTheDocument();
    expect(api.called("POST", "/applications/api-keys/k1/rotate")[0].body).toEqual({
      grace_minutes: 15,
    });
  });

  it("refuses a nonsensical grace period instead of sending it", async () => {
    const api = mockApi(routes({ "POST /applications/api-keys/k1/rotate": {} }));
    render(<SettingsPage />);

    fireEvent.click(await screen.findByText("Rotate"));
    fireEvent.change(screen.getByLabelText("Grace period in minutes"), { target: { value: "-5" } });
    fireEvent.click(screen.getByText("Confirm rotate"));

    expect(await screen.findByText(/Grace period \(minutes\) must be a number between 0 and 10080/)).toBeInTheDocument();
    expect(api.called("POST", "/applications/api-keys/k1/rotate")).toHaveLength(0);
  });

  it("issues a key with a lifetime, and validates it", async () => {
    const api = mockApi(
      routes({
        "POST /applications/api-keys": {
          id: "k2",
          name: "temp",
          role: "write",
          key_prefix: "sk_",
          plaintext_key: "sk_sentinel_temp",
          scoped_to_application: false,
        },
      })
    );
    render(<SettingsPage />);
    fireEvent.change(await screen.findByPlaceholderText("Key name (e.g. ci-pipeline)"), {
      target: { value: "temp" },
    });
    const days = screen.getByPlaceholderText("Expires in (days)");

    fireEvent.change(days, { target: { value: "0" } });
    fireEvent.click(screen.getByText("+ Create key"));
    expect(await screen.findByText(/Expires in \(days\) must be a number between 1 and 3650/)).toBeInTheDocument();
    expect(api.called("POST", "/applications/api-keys")).toHaveLength(0);

    fireEvent.change(days, { target: { value: "30" } });
    fireEvent.click(screen.getByText("+ Create key"));
    await waitFor(() => expect(api.called("POST", "/applications/api-keys")).toHaveLength(1));
    expect(api.called("POST", "/applications/api-keys")[0].body).toMatchObject({
      name: "temp",
      expires_in_days: 30,
    });
  });
});

describe("Settings — budget enforcement", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("shows the day's spend against the budget, flagged when it is exceeded", async () => {
    mockApi(
      routes({
        "GET /applications/a1/budget": budget({ spent_24h: 12.25, remaining: 0, exceeded: true }),
      })
    );
    render(<SettingsPage />);

    const spend = await screen.findByText(/\$12\.2500 \/ \$10\.0000/);
    expect(spend).toHaveClass("text-err");
  });

  it("changes what happens over budget, and only offers it when there is a budget", async () => {
    const api = mockApi(
      routes({
        "PATCH /applications/a1": application({ budget_action: "block" }),
        "GET /applications": page([
          application(),
          application({ id: "a2", name: "no-budget", daily_cost_budget: null }),
        ]),
      })
    );
    render(<SettingsPage />);

    const select = await screen.findByLabelText("Over-budget action for checkout");
    expect(screen.getByLabelText("Over-budget action for no-budget")).toBeDisabled();

    fireEvent.change(select, { target: { value: "block" } });

    await waitFor(() => expect(api.called("PATCH", "/applications/a1")).toHaveLength(1));
    expect(api.called("PATCH", "/applications/a1")[0].body).toEqual({ budget_action: "block" });
  });

  it("reports a failed change instead of failing silently", async () => {
    mockApi(routes({ "PATCH /applications/a1": new HttpFailure(500, "db down") }));
    render(<SettingsPage />);

    fireEvent.change(await screen.findByLabelText("Over-budget action for checkout"), {
      target: { value: "downgrade" },
    });

    expect(await screen.findByText("db down")).toBeInTheDocument();
  });
});
