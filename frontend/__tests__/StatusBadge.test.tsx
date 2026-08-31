import { render, screen } from "@testing-library/react";
import { StatusBadge } from "@/components/StatusBadge";

describe("StatusBadge", () => {
  it("renders the given status text", () => {
    render(<StatusBadge status="ok" />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("ok");
  });

  it("infers an error tone for error-like statuses", () => {
    render(<StatusBadge status="error" />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.className).toMatch(/text-err/);
  });

  it("infers an ok tone for healthy statuses", () => {
    render(<StatusBadge status="healthy" />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.className).toMatch(/text-ok/);
  });

  it("respects an explicit tone override", () => {
    render(<StatusBadge status="custom" tone="crit" />);
    const badge = screen.getByTestId("status-badge");
    expect(badge.className).toMatch(/text-crit/);
  });
});
