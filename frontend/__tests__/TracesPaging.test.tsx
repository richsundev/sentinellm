import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TracesPage from "@/app/traces/page";
import { FiltersProvider, useFilters } from "@/lib/filters-context";
import { mockApi } from "../test-utils/mockApi";

jest.mock("next/navigation", () => ({ useRouter: () => ({ push: jest.fn() }) }));

function EnvPicker() {
  const { setEnvironment } = useFilters();
  return <button onClick={() => setEnvironment("staging")}>go staging</button>;
}

describe("Traces page", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("returns to the first page when the environment changes", async () => {
    const api = mockApi({
      "GET /traces": (call: { query: Record<string, string> }) => ({
        items: [],
        total: 100,
        limit: 25,
        offset: Number(call.query.offset ?? 0),
      }),
    });
    render(
      <FiltersProvider>
        <EnvPicker />
        <TracesPage />
      </FiltersProvider>
    );
    fireEvent.click(await screen.findByText("Next"));
    await waitFor(() =>
      expect(api.called("GET", "/traces").some((c) => c.query.offset === "25")).toBe(true)
    );

    fireEvent.click(screen.getByText("go staging"));

    await waitFor(() => {
      const last = api.called("GET", "/traces").at(-1)!;
      expect(last.query.environment).toBe("staging");
      expect(last.query.offset ?? "0").toBe("0");
    });
  });

  it("trims whitespace out of filters before sending them", async () => {
    const api = mockApi({ "GET /traces": { items: [], total: 0, limit: 25, offset: 0 } });
    render(
      <FiltersProvider>
        <TracesPage />
      </FiltersProvider>
    );
    fireEvent.change(await screen.findByPlaceholderText("e.g. gpt-4o"), {
      target: { value: "  " },
    });

    await waitFor(() => expect(api.called("GET", "/traces").length).toBeGreaterThan(1));
    expect(api.called("GET", "/traces").at(-1)!.query.model).toBeUndefined();
  });
});
