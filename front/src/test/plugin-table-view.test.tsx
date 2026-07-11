import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TableView } from "../components/plugin-renderers/TableView";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { createPluginTableFixture } from "./fixtures/performance";

describe("TableView", () => {
  it("virtualizes a 10000-row snapshot and searches the data model", async () => {
    const user = userEvent.setup();
    const view = createPluginTableFixture(10_000);
    if (view.renderer !== "table" || view.mode !== "snapshot") {
      throw new Error("Expected a snapshot table fixture");
    }

    render(
      <TableView
        botAlias="main"
        client={new MockWebBotClient()}
        view={view}
      />,
    );

    const list = screen.getByTestId("virtualized-plugin-table");
    expect(list).toHaveClass("min-h-0", "flex-1", "overflow-auto");
    expect(screen.getByRole("table")).toHaveClass("h-full", "min-h-0");
    expect(within(list).getAllByTestId("plugin-table-row").length).toBeLessThanOrEqual(100);
    expect(screen.getByText(/当前快照包含 10000 行/)).toBeInTheDocument();
    expect(screen.getByText("共 10000 行")).toBeInTheDocument();
    expect(screen.queryByText("row-9999")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("搜索"), "row-9999");

    expect(await screen.findByText("row-9999")).toBeInTheDocument();
  });
});
