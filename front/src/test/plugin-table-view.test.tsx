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
    expect(within(list).getAllByTestId("plugin-table-row").length).toBeLessThanOrEqual(100);
    expect(screen.queryByText("row-9999")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("搜索"), "row-9999");

    expect(await screen.findByText("row-9999")).toBeInTheDocument();
  });
});
