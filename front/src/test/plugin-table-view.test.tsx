import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TableView } from "../components/plugin-renderers/TableView";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { createPluginTableFixture } from "./fixtures/performance";
import type { TableSessionRenderResult } from "../services/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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

  it("uses a filtered session count of zero instead of the original total", async () => {
    const user = userEvent.setup();
    const client = new MockWebBotClient();
    const row = { id: "entry", cells: { name: "entry" } };
    const view: TableSessionRenderResult = {
      pluginId: "test", viewId: "table", title: "table", renderer: "table", mode: "session", sessionId: "table-session",
      summary: { columns: [{ id: "name", title: "名称" }], totalRows: 100, defaultPageSize: 50 },
      initialWindow: { offset: 0, limit: 50, totalRows: 100, rows: [row] },
    };
    vi.spyOn(client, "queryPluginViewWindow").mockImplementation(async (_bot, _plugin, _session, request) => ({
      offset: 0, limit: 50, totalRows: request.query ? 0 : 100, rows: request.query ? [] : [row],
    }));
    render(<TableView botAlias="main" client={client} view={view} />);
    await user.type(screen.getByLabelText("搜索"), "absent");
    expect(await screen.findByText("第 1/1 页 · 共 0 行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });
});
