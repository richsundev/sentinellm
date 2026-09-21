import { render, screen } from "@testing-library/react";
import { Topbar } from "@/components/Topbar";
import { FiltersProvider } from "@/lib/filters-context";

let mockPath = "/";
jest.mock("next/navigation", () => ({ usePathname: () => mockPath }));

function renderAt(path: string) {
  mockPath = path;
  render(
    <FiltersProvider>
      <Topbar />
    </FiltersProvider>
  );
}

describe("Topbar", () => {
  it("titles the rollouts page", () => {
    renderAt("/rollouts");
    expect(screen.getByRole("heading", { name: "Rollouts" })).toBeInTheDocument();
  });

  it.each(["/overview", "/cost"])("offers a time range on %s, which follows it", (path) => {
    renderAt(path);
    expect(screen.getByRole("button", { name: "24h" })).toBeInTheDocument();
  });

  it.each(["/traces", "/evaluations", "/regressions", "/models"])(
    "does not offer a time range on %s, which ignores it",
    (path) => {
      renderAt(path);
      expect(screen.queryByRole("button", { name: "24h" })).not.toBeInTheDocument();
    }
  );
});
