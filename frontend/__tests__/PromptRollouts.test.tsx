import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RolloutsPage from "@/app/rollouts/page";
import type { PromptRollout, PromptRolloutDetail, PromptVersion } from "@/lib/types";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

const rollout = (over: Partial<PromptRollout> = {}): PromptRollout => ({
  id: "pr1",
  application_id: "checkout-assistant",
  prompt_id: "support-answer",
  incumbent_version: 1,
  challenger_version: 2,
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

const detail = (over: Partial<PromptRolloutDetail> = {}): PromptRolloutDetail => ({
  ...rollout(),
  incumbent_stats: {
    version: 1,
    request_count: 40,
    error_rate: 0,
    avg_quality: 0.81,
    avg_latency_ms: 120,
    avg_cost: 0.001,
  },
  challenger_stats: {
    version: 2,
    request_count: 15,
    error_rate: 0.0667,
    avg_quality: 0.77,
    avg_latency_ms: 90,
    avg_cost: 0.0008,
  },
  ...over,
});

const prompt = (version: number): PromptVersion => ({
  prompt_id: "support-answer",
  version,
  template: `v${version} {{question}}`,
  variables: ["question"],
  status: "production",
  author: "team",
  created_at: "2026-09-01T00:00:00Z",
});

async function openPromptTab() {
  fireEvent.click(await screen.findByText("Prompt canaries"));
}

describe("Rollouts page — prompt canaries", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("keeps model canaries as the default tab", async () => {
    const api = mockApi({ "GET /rollouts": page([]), "GET /models": page([]) });
    render(<RolloutsPage />);

    await screen.findByText("Start a canary rollout");
    expect(api.called("GET", "/prompt-rollouts")).toHaveLength(0);
  });

  it("lists prompt rollouts with versions, traffic and stage", async () => {
    mockApi({
      "GET /rollouts": page([]),
      "GET /models": page([]),
      "GET /prompt-rollouts": page([rollout()]),
      "GET /prompts": page([prompt(1), prompt(2)]),
    });
    render(<RolloutsPage />);
    await openPromptTab();

    expect(await screen.findByText(/support-answer v1/)).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });

  it("shows each version's live stats and lets an operator roll back", async () => {
    let stage: PromptRollout["stage"] = "running";
    const api = mockApi({
      "GET /rollouts": page([]),
      "GET /models": page([]),
      "GET /prompt-rollouts": () => page([rollout({ stage })]),
      "GET /prompt-rollouts/pr1": () => detail({ stage }),
      "POST /prompt-rollouts/pr1/rollback": () => {
        stage = "rolled_back";
        return rollout({ stage });
      },
      "GET /prompts": page([prompt(1), prompt(2)]),
    });
    render(<RolloutsPage />);
    await openPromptTab();

    fireEvent.click(await screen.findByText(/support-answer v1/));
    expect(await screen.findByText("0.81")).toBeInTheDocument(); // incumbent quality
    expect(screen.getByText("0.77")).toBeInTheDocument(); // challenger quality

    fireEvent.click(screen.getByText("Roll back now"));
    await waitFor(() =>
      expect(api.called("POST", "/prompt-rollouts/pr1/rollback")).toHaveLength(1)
    );
    await waitFor(() => expect(screen.queryByText("Roll back now")).not.toBeInTheDocument());
  });

  it("starts a canary between two versions of the chosen prompt", async () => {
    const api = mockApi({
      "GET /rollouts": page([]),
      "GET /models": page([]),
      "GET /prompt-rollouts": page([]),
      "GET /prompts": page([prompt(1), prompt(2), { ...prompt(1), prompt_id: "other" }]),
      "POST /prompt-rollouts": rollout(),
    });
    render(<RolloutsPage />);
    await openPromptTab();
    await screen.findByText("Start a prompt canary");
    const start = screen.getByText("Start prompt canary");
    expect(start).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("application_id"), {
      target: { value: " checkout " },
    });
    fireEvent.change(await screen.findByLabelText("Prompt"), {
      target: { value: "support-answer" },
    });
    fireEvent.change(screen.getByLabelText("Incumbent version"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Challenger version"), { target: { value: "1" } });
    expect(start).toBeDisabled(); // the two versions must differ
    fireEvent.change(screen.getByLabelText("Challenger version"), { target: { value: "2" } });
    expect(start).toBeEnabled();

    fireEvent.click(start);

    await waitFor(() => expect(api.called("POST", "/prompt-rollouts")).toHaveLength(1));
    expect(api.called("POST", "/prompt-rollouts")[0].body).toMatchObject({
      application_id: "checkout",
      prompt_id: "support-answer",
      incumbent_version: 1,
      challenger_version: 2,
    });
  });

  it("shows the server's reason when a canary can't be started", async () => {
    mockApi({
      "GET /rollouts": page([]),
      "GET /models": page([]),
      "GET /prompt-rollouts": page([]),
      "GET /prompts": page([prompt(1), prompt(2)]),
      "POST /prompt-rollouts": new HttpFailure(409, "already has an active rollout"),
    });
    render(<RolloutsPage />);
    await openPromptTab();
    fireEvent.change(await screen.findByPlaceholderText("application_id"), {
      target: { value: "a" },
    });
    fireEvent.change(await screen.findByLabelText("Prompt"), {
      target: { value: "support-answer" },
    });
    fireEvent.change(screen.getByLabelText("Incumbent version"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Challenger version"), { target: { value: "2" } });
    fireEvent.click(screen.getByText("Start prompt canary"));

    expect(await screen.findByText("already has an active rollout")).toBeInTheDocument();
  });
});
