import { render, screen } from "@testing-library/react";
import { TimelineChart } from "@/components/TimelineChart";
import type { Span } from "@/lib/types";

const spans: Span[] = [
  { name: "retrieval", start_ms: 0, duration_ms: 120, status: "ok", metadata: {} },
  { name: "llm_generation", start_ms: 120, duration_ms: 480, status: "ok", metadata: {} },
  { name: "evaluation", start_ms: 600, duration_ms: 90, status: "error", metadata: {} },
];

describe("TimelineChart", () => {
  it("renders one row per span", () => {
    render(<TimelineChart spans={spans} />);
    expect(screen.getByTestId("timeline-chart")).toBeInTheDocument();
    expect(screen.getByText("retrieval")).toBeInTheDocument();
    expect(screen.getByText("llm_generation")).toBeInTheDocument();
    expect(screen.getByText("evaluation")).toBeInTheDocument();
  });

  it("shows an empty message when there are no spans", () => {
    render(<TimelineChart spans={[]} />);
    expect(screen.getByTestId("timeline-empty")).toBeInTheDocument();
  });
});
