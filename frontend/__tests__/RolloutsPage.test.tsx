import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RolloutsPage from "@/app/rollouts/page";
import type { ModelInfo, Rollout, RolloutDetail } from "@/lib/types";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

const rollout = (over: Partial<Rollout> = {}): Rollout => ({
  id: "r1",
  application_id: "checkout-assistant",
  incumbent_model: "mock:sentinel-pro",
  challenger_model: "mock:sentinel-flash",
  traffic_pct: 30,
  stage: "running",
  quality_floor: 0.7,
  max_quality_regression: 0.1,
  max_error_rate: 0.1,
  min_sample_size: 10,
  step_pct: 10,
  max_pct: 100,
  last_evaluated_at: null,
  outcome_reason: null,
  created_at: "2026-09-01T00:00:00Z",
  ...over,
});

const detail = (over: Partial<RolloutDetail> = {}): RolloutDetail => ({
  ...rollout(),
  incumbent_stats: {
    model: "mock:sentinel-pro",
    request_count: 34,
    error_rate: 0,
    avg_quality: 0.62,
    avg_latency_ms: 140,
    avg_cost: 0.0012,
  },
  challenger_stats: {
    model: "mock:sentinel-flash",
    request_count: 14,
    error_rate: 0.0714,
    avg_quality: 0.58,
    avg_latency_ms: 80,
    avg_cost: 0.0002,
  },
  ...over,
});

const model = (id: string): ModelInfo => ({
  id,
  name: id.split(":")[1],
  provider: "mock",
  input_price_per_1k: 0.001,
  output_price_per_1k: 0.002,
  context_window: 8192,
  avg_quality: null,
  avg_latency_ms: null,
  status: "healthy",
  status_auto: true,
  status_reason: null,
});

const MODELS = page([model("mock:sentinel-pro"), model("mock:sentinel-flash")]);

describe("RolloutsPage", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("lists rollouts with their stage and models", async () => {
    mockApi({
      "GET /rollouts": page([
        rollout(),
        rollout({ id: "r2", application_id: "search", stage: "rolled_back", traffic_pct: 0 }),
      ]),
      "GET /models": MODELS,
    });

    render(<RolloutsPage />);

    expect(await screen.findByText("checkout-assistant")).toBeInTheDocument();
    expect(screen.getByText("search")).toBeInTheDocument();
    const badges = screen.getAllByTestId("status-badge").map((b) => b.textContent);
    expect(badges).toEqual(expect.arrayContaining(["running", "rolled_back"]));
  });

  it("shows an empty state when there are no rollouts", async () => {
    mockApi({ "GET /rollouts": page([]), "GET /models": MODELS });

    render(<RolloutsPage />);

    expect(await screen.findByText("No rollouts yet")).toBeInTheDocument();
  });

  it("surfaces a failed list request instead of an empty table", async () => {
    mockApi({
      "GET /rollouts": new HttpFailure(500, "database unavailable"),
      "GET /models": MODELS,
    });

    render(<RolloutsPage />);

    expect(await screen.findByTestId("error-state")).toBeInTheDocument();
  });

  it("shows incumbent vs challenger stats and live controls for a running rollout", async () => {
    mockApi({
      "GET /rollouts": page([rollout()]),
      "GET /rollouts/r1": detail(),
      "GET /models": MODELS,
    });
    render(<RolloutsPage />);

    fireEvent.click(await screen.findByText("checkout-assistant"));

    expect(await screen.findByText("Incumbent")).toBeInTheDocument();
    expect(screen.getByText("Challenger")).toBeInTheDocument();
    expect(screen.getByText("34")).toBeInTheDocument(); // incumbent request count
    expect(screen.getByText("14")).toBeInTheDocument(); // challenger request count
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Promote now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roll back now" })).toBeInTheDocument();
  });

  it.each([
    ["rolled_back", 0, "challenger error_rate=40% over 10 requests (max 10%)"],
    ["promoted", 100, "promoted to 100% after 14 healthy challenger requests"],
  ] as const)(
    "offers no controls once a rollout has been %s",
    async (stage, trafficPct, reason) => {
      mockApi({
        "GET /rollouts": page([rollout({ stage, traffic_pct: trafficPct })]),
        "GET /rollouts/r1": detail({ stage, traffic_pct: trafficPct, outcome_reason: reason }),
        "GET /models": MODELS,
      });
      render(<RolloutsPage />);

      fireEvent.click(await screen.findByText("checkout-assistant"));

      expect(await screen.findByText(reason)).toBeInTheDocument();
      for (const name of ["Pause", "Resume", "Promote now", "Roll back now"]) {
        expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
      }
    }
  );

  it("offers Resume (not Pause) for a paused rollout", async () => {
    mockApi({
      "GET /rollouts": page([rollout({ stage: "paused" })]),
      "GET /rollouts/r1": detail({ stage: "paused" }),
      "GET /models": MODELS,
    });
    render(<RolloutsPage />);

    fireEvent.click(await screen.findByText("checkout-assistant"));

    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("sends the operator action to the API and reloads", async () => {
    const api = mockApi({
      "GET /rollouts": page([rollout()]),
      "GET /rollouts/r1": detail(),
      "POST /rollouts/r1/pause": rollout({ stage: "paused" }),
      "GET /models": MODELS,
    });
    render(<RolloutsPage />);
    fireEvent.click(await screen.findByText("checkout-assistant"));

    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));

    await waitFor(() => expect(api.called("POST", "/rollouts/r1/pause")).toHaveLength(1));
    // The list and the detail are both refetched after the action.
    await waitFor(() => expect(api.called("GET", "/rollouts").length).toBeGreaterThan(1));
  });

  it("shows the server's reason when an action is rejected", async () => {
    mockApi({
      "GET /rollouts": page([rollout()]),
      "GET /rollouts/r1": detail(),
      "POST /rollouts/r1/promote": new HttpFailure(400, "rollout is already 'promoted'"),
      "GET /models": MODELS,
    });
    render(<RolloutsPage />);
    fireEvent.click(await screen.findByText("checkout-assistant"));

    fireEvent.click(await screen.findByRole("button", { name: "Promote now" }));

    expect(await screen.findByText("rollout is already 'promoted'")).toBeInTheDocument();
  });

  describe("start form", () => {
    async function fillForm(app = "checkout") {
      fireEvent.change(await screen.findByLabelText("Application"), { target: { value: app } });
      // Wait for the model list to populate the selects.
      await screen.findAllByRole("option", { name: "mock:sentinel-pro" });
      fireEvent.change(screen.getByLabelText("Incumbent model"), {
        target: { value: "mock:sentinel-pro" },
      });
      fireEvent.change(screen.getByLabelText("Challenger model"), {
        target: { value: "mock:sentinel-flash" },
      });
    }

    it("keeps Start disabled until both arms are chosen and differ", async () => {
      mockApi({ "GET /rollouts": page([]), "GET /models": MODELS });
      render(<RolloutsPage />);
      const start = await screen.findByRole("button", { name: "Start rollout" });
      expect(start).toBeDisabled();

      await fillForm();
      expect(start).toBeEnabled();

      fireEvent.change(screen.getByLabelText("Challenger model"), {
        target: { value: "mock:sentinel-pro" },
      });
      expect(start).toBeDisabled();
    });

    it("creates the rollout with every configured guard", async () => {
      const api = mockApi({
        "GET /rollouts": page([]),
        "GET /models": MODELS,
        "POST /rollouts": rollout(),
      });
      render(<RolloutsPage />);
      await fillForm("checkout");
      fireEvent.change(screen.getByLabelText("Max drop vs incumbent"), {
        target: { value: "0.25" },
      });

      fireEvent.click(screen.getByRole("button", { name: "Start rollout" }));

      await waitFor(() => expect(api.called("POST", "/rollouts")).toHaveLength(1));
      expect(api.called("POST", "/rollouts")[0].body).toEqual({
        application_id: "checkout",
        incumbent_model: "mock:sentinel-pro",
        challenger_model: "mock:sentinel-flash",
        initial_pct: 10,
        quality_floor: 0.7,
        max_quality_regression: 0.25,
        max_error_rate: 0.1,
        min_sample_size: 10,
        step_pct: 10,
      });
    });

    it("shows the server's conflict message", async () => {
      mockApi({
        "GET /rollouts": page([]),
        "GET /models": MODELS,
        "POST /rollouts": new HttpFailure(409, "application 'checkout' already has an active rollout"),
      });
      render(<RolloutsPage />);
      await fillForm("checkout");

      fireEvent.click(screen.getByRole("button", { name: "Start rollout" }));

      expect(
        await screen.findByText("application 'checkout' already has an active rollout")
      ).toBeInTheDocument();
    });
  });
});
