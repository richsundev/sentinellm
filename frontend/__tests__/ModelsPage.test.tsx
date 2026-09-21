import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ModelsPage from "@/app/models/page";
import type { ModelInfo } from "@/lib/types";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

const model = (over: Partial<ModelInfo> = {}): ModelInfo => ({
  id: "mock:sentinel-pro",
  name: "sentinel-pro",
  provider: "mock",
  input_price_per_1k: 0.003,
  output_price_per_1k: 0.015,
  context_window: 32768,
  avg_quality: null, // keeps the scatter chart out of these tests
  avg_latency_ms: null,
  status: "healthy",
  status_auto: true,
  status_reason: null,
  ...over,
});

describe("ModelsPage — health status", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("labels auto-managed models and explains the detected reason", async () => {
    mockApi({
      "GET /models": page([
        model({
          id: "mock:flaky",
          name: "flaky",
          status: "down",
          status_reason: "error rate 83% over last 12 requests (trailing 1h)",
        }),
      ]),
    });

    render(<ModelsPage />);

    const auto = await screen.findByText("auto");
    expect(auto).toHaveAttribute("title", "error rate 83% over last 12 requests (trailing 1h)");
    expect(screen.queryByRole("button", { name: "manual" })).not.toBeInTheDocument();
  });

  it("shows a manually pinned model as such, with a way to hand it back to the monitor", async () => {
    mockApi({
      "GET /models": page([model({ status_auto: false, status: "healthy" })]),
    });

    render(<ModelsPage />);

    expect(await screen.findByRole("button", { name: "manual" })).toBeInTheDocument();
    expect(screen.queryByText("auto")).not.toBeInTheDocument();
  });

  it("pinning a status sends only the status (the API pins it as a side effect)", async () => {
    const api = mockApi({
      "GET /models": page([model()]),
      "PATCH /models/mock%3Asentinel-pro": model({ status: "degraded", status_auto: false }),
    });
    render(<ModelsPage />);

    fireEvent.change(await screen.findByRole("combobox"), { target: { value: "degraded" } });

    await waitFor(() => expect(api.calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "degraded" });
  });

  it("handing a pinned model back re-enables automatic management", async () => {
    const api = mockApi({
      "GET /models": page([model({ status_auto: false })]),
      "PATCH /models/mock%3Asentinel-pro": model(),
    });
    render(<ModelsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "manual" }));

    await waitFor(() => expect(api.calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ status_auto: true });
  });
});

describe("ModelsPage — register a model", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  async function fill() {
    fireEvent.change(await screen.findByLabelText("ID"), {
      target: { value: "openai:gpt-4o-mini" },
    });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "gpt-4o-mini" } });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText("In $/1K"), { target: { value: "0.00015" } });
    fireEvent.change(screen.getByLabelText("Out $/1K"), { target: { value: "0.0006" } });
  }

  it("is disabled until every field is filled", async () => {
    mockApi({ "GET /models": page([]) });
    render(<ModelsPage />);
    const register = await screen.findByRole("button", { name: "Register" });
    expect(register).toBeDisabled();

    await fill();

    expect(register).toBeEnabled();
  });

  it("submits prices as numbers and refreshes the catalog", async () => {
    const api = mockApi({
      "GET /models": page([]),
      "POST /models": model({ id: "openai:gpt-4o-mini" }),
    });
    render(<ModelsPage />);
    await fill();

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(api.called("POST", "/models")).toHaveLength(1));
    expect(api.called("POST", "/models")[0].body).toEqual({
      id: "openai:gpt-4o-mini",
      name: "gpt-4o-mini",
      provider: "openai",
      input_price_per_1k: 0.00015,
      output_price_per_1k: 0.0006,
    });
    await waitFor(() => expect(api.called("GET", "/models").length).toBeGreaterThan(1));
  });

  it("shows why registration was refused", async () => {
    mockApi({
      "GET /models": page([]),
      "POST /models": new HttpFailure(409, "model 'openai:gpt-4o-mini' already exists"),
    });
    render(<ModelsPage />);
    await fill();

    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText("model 'openai:gpt-4o-mini' already exists")
    ).toBeInTheDocument();
  });
});
