import { render, screen } from "@testing-library/react";
import { MetricCard } from "@/components/MetricCard";

describe("MetricCard", () => {
  it("renders label and value", () => {
    render(<MetricCard label="Error rate" value="1.2%" />);
    expect(screen.getByText("Error rate")).toBeInTheDocument();
    expect(screen.getByText("1.2%")).toBeInTheDocument();
  });

  it("renders a sublabel when provided", () => {
    render(<MetricCard label="P95 latency" value="820 ms" sublabel="last 24h" />);
    expect(screen.getByText("last 24h")).toBeInTheDocument();
  });

  it("renders a skeleton instead of content while loading", () => {
    render(<MetricCard label="Error rate" value="1.2%" loading />);
    expect(screen.getByTestId("metric-card-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("1.2%")).not.toBeInTheDocument();
  });
});
