import { render, screen } from "@testing-library/react";
import { Sidebar } from "@/components/Sidebar";

let mockPath = "/";
jest.mock("next/navigation", () => ({ usePathname: () => mockPath }));

function activeLabels(path: string): string[] {
  mockPath = path;
  render(<Sidebar />);
  return screen
    .getAllByRole("link")
    .filter((a) => a.className.includes("border-accent"))
    .map((a) => a.textContent?.replace(/^\S\s*/, "").trim() ?? "");
}

describe("Sidebar", () => {
  it("highlights Traces on a trace's detail page (/trace/[id], singular)", () => {
    expect(activeLabels("/trace/trc_123")).toEqual(["Traces"]);
  });

  it("highlights only the section being viewed", () => {
    expect(activeLabels("/traces")).toEqual(["Traces"]);
  });

  it("highlights Datasets on a dataset's detail page", () => {
    expect(activeLabels("/datasets/abc")).toEqual(["Datasets"]);
  });
});
