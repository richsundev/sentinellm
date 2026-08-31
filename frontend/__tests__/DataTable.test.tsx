import { render, screen } from "@testing-library/react";
import { DataTable, type Column } from "@/components/DataTable";

interface Row {
  id: string;
  name: string;
}

const columns: Column<Row>[] = [
  { key: "name", header: "Name", render: (r) => r.name, sortValue: (r) => r.name },
];

describe("DataTable", () => {
  it("renders an empty state when there are no rows", () => {
    render(
      <DataTable<Row>
        columns={columns}
        rows={[]}
        rowKey={(r) => r.id}
        emptyTitle="No traces found"
        emptyMessage="Try widening your filters."
      />
    );
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText("No traces found")).toBeInTheDocument();
    expect(screen.queryByTestId("data-table")).not.toBeInTheDocument();
  });

  it("renders a row per item when rows are present", () => {
    render(
      <DataTable<Row>
        columns={columns}
        rows={[
          { id: "1", name: "alpha" },
          { id: "2", name: "beta" },
        ]}
        rowKey={(r) => r.id}
      />
    );
    expect(screen.getByTestId("data-table")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
  });
});
