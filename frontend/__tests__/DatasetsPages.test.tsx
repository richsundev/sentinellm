import { render, screen, waitFor } from "@testing-library/react";
import DatasetsPage from "@/app/datasets/page";
import DatasetDetailPage from "@/app/datasets/[id]/page";
import { mockApi } from "../test-utils/mockApi";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useParams: () => ({ id: "ds-123" }),
}));

describe("Datasets pages", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("shows each dataset's id, which the Experiments form asks for", async () => {
    mockApi({
      "GET /datasets": {
        items: [
          {
            id: "6f1c2d3e-aaaa-bbbb-cccc-1234567890ab",
            name: "support-bench",
            version: "v1",
            description: null,
            record_count: 40,
            created_at: "2026-09-01T00:00:00Z",
          },
        ],
        total: 1,
        limit: 100,
        offset: 0,
      },
    });
    render(<DatasetsPage />);

    expect(await screen.findByText("6f1c2d3e-aaaa-bbbb-cccc-1234567890ab")).toBeInTheDocument();
  });

  it("says how many records there are in total, not just that it shows some", async () => {
    mockApi({
      "GET /datasets/ds-123/records": {
        items: [{ id: "r1", question: "q", context: "c", expected_answer: "a", metadata: {} }],
        total: 400,
        limit: 50,
        offset: 0,
      },
    });
    render(<DatasetDetailPage />);

    await waitFor(() => expect(screen.getByText(/1 of 400 records/)).toBeInTheDocument());
  });
});
