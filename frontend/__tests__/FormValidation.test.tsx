import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ModelsPage from "@/app/models/page";
import RolloutsPage from "@/app/rollouts/page";
import { FormError, parseNumberField, parseRolloutGuards } from "@/lib/validate";
import type { ModelInfo, PromptVersion } from "@/lib/types";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

/** The <input> inside the <label> whose caption is `caption` (the forms use bare labels). */
const field = (caption: string) =>
  screen.getByText(caption).closest("label")!.querySelector("input")!;

const model = (id: string): ModelInfo => ({
  id,
  name: id.split(":")[1],
  provider: "mock",
  input_price_per_1k: 0.001,
  output_price_per_1k: 0.003,
  context_window: 8000,
  avg_quality: null,
  avg_latency_ms: null,
  status: "healthy",
  status_auto: true,
  status_reason: null,
});

describe("parseNumberField", () => {
  it("accepts numbers in range and trims", () => {
    expect(parseNumberField("x", " 0.5 ", { min: 0, max: 1 })).toBe(0.5);
  });

  it.each(["", "  ", "abc", "1e999", "NaN"])("rejects %j, naming the field", (raw) => {
    expect(() => parseNumberField("Max error rate", raw, { min: 0, max: 1 })).toThrow(
      /Max error rate must be a number between 0 and 1/
    );
  });

  it("enforces bounds and whole numbers", () => {
    expect(() => parseNumberField("p", "-1", { min: 0 })).toThrow(FormError);
    expect(() => parseNumberField("n", "2.5", { min: 1, integer: true })).toThrow(/whole number/);
    expect(parseNumberField("n", "3", { min: 1, integer: true })).toBe(3);
  });

  it("parses a full set of rollout guards or names the first bad one", () => {
    const ok = { initialPct: "10", qualityFloor: "0.7", maxDrop: "0.1", maxErrorRate: "0.1", minSample: "10", stepPct: "10" };
    expect(parseRolloutGuards(ok)).toMatchObject({ initial_pct: 10, min_sample_size: 10 });
    expect(() => parseRolloutGuards({ ...ok, stepPct: "" })).toThrow(/Step %/);
  });
});

describe("Models page forms", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  async function fillRegister(input: string, output: string) {
    fireEvent.change(await screen.findByPlaceholderText("openai:gpt-4o-mini"), { target: { value: "acme:m" } });
    fireEvent.change(screen.getByPlaceholderText("gpt-4o-mini"), { target: { value: "m" } });
    fireEvent.change(screen.getByPlaceholderText("openai"), { target: { value: "acme" } });
    fireEvent.change(screen.getByPlaceholderText("0.00015"), { target: { value: input } });
    fireEvent.change(screen.getByPlaceholderText("0.0006"), { target: { value: output } });
    fireEvent.click(screen.getByText("Register"));
  }

  it.each([["abc", "0.1"], ["0.1", "-2"]])(
    "refuses prices %j / %j instead of sending null/negative to the server",
    async (input, output) => {
      const api = mockApi({ "GET /models": page([]), "POST /models": model("acme:m") });
      render(<ModelsPage />);

      await fillRegister(input, output);

      expect(await screen.findByText(/must be a number of at least 0/)).toBeInTheDocument();
      expect(api.called("POST", "/models")).toHaveLength(0);
    }
  );

  it("shows why a status change failed instead of failing silently", async () => {
    mockApi({
      "GET /models": page([model("mock:a")]),
      "PATCH /models/mock%3Aa": new HttpFailure(403, "requires an unscoped key"),
    });
    render(<ModelsPage />);
    const select = await screen.findByDisplayValue("healthy");

    fireEvent.change(select, { target: { value: "down" } });

    expect(await screen.findByText("requires an unscoped key")).toBeInTheDocument();
  });
});

describe("Rollout forms", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("names the bad field when a model canary's numbers are invalid", async () => {
    const api = mockApi({
      "GET /rollouts": page([]),
      "GET /models": page([model("mock:a"), model("mock:b")]),
      "POST /rollouts": {},
    });
    render(<RolloutsPage />);
    fireEvent.change(await screen.findByPlaceholderText("application_id"), { target: { value: "app" } });
    const [incumbent, challenger] = await waitFor(() => {
      const selects = screen.getAllByRole("combobox");
      expect(selects[0].querySelectorAll("option").length).toBeGreaterThan(2);
      return selects;
    });
    fireEvent.change(incumbent, { target: { value: "mock:a" } });
    fireEvent.change(challenger, { target: { value: "mock:b" } });

    fireEvent.change(field("Initial %"), { target: { value: "" } });
    fireEvent.click(screen.getByText("Start rollout"));

    expect(await screen.findByText(/Initial % must be a number between 0 and 100/)).toBeInTheDocument();
    expect(api.called("POST", "/rollouts")).toHaveLength(0);
  });

  it("names the bad field when a prompt canary's numbers are invalid", async () => {
    const versions: PromptVersion[] = [1, 2].map((v) => ({
      prompt_id: "p", version: v, template: "t", variables: [], status: "production", author: "a", created_at: "2026-09-01T00:00:00Z",
    }));
    const api = mockApi({
      "GET /rollouts": page([]),
      "GET /models": page([]),
      "GET /prompt-rollouts": page([]),
      "GET /prompts": page(versions),
      "POST /prompt-rollouts": {},
    });
    render(<RolloutsPage />);
    fireEvent.click(await screen.findByText("Prompt canaries"));
    fireEvent.change(await screen.findByPlaceholderText("application_id"), { target: { value: "app" } });
    fireEvent.change(await screen.findByLabelText("Prompt"), { target: { value: "p" } });
    fireEvent.change(screen.getByLabelText("Incumbent version"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Challenger version"), { target: { value: "2" } });

    fireEvent.change(field("Step %"), { target: { value: "abc" } });
    fireEvent.click(screen.getByText("Start prompt canary"));

    expect(await screen.findByText(/Step % must be a number between 1 and 100/)).toBeInTheDocument();
    expect(api.called("POST", "/prompt-rollouts")).toHaveLength(0);
  });
});
