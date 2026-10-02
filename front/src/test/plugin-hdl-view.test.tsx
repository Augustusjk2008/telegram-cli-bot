import { useState } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PluginCatalog } from "../components/PluginCatalog";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { HostEffect, PluginRenderResult, PluginSummary, TableWindowPayload, TreeNode, TreeWindowPayload } from "../services/types";

const pluginId = "hdl-workbench";
const projectPath = "/Users/demo/orbit-safe-claw/src";

async function openTree(client: MockWebBotClient, path = projectPath, botAlias = "main") {
  const view = await client.openPluginView(botAlias, pluginId, "module-tree", { path });
  if (view.renderer !== "tree" || view.mode !== "session") throw new Error("Expected HDL tree session");
  return view;
}

async function children(client: MockWebBotClient, sessionId: string, nodeId: string | null) {
  return (await client.queryPluginViewWindow("main", pluginId, sessionId, { op: "children", nodeId }) as TreeWindowPayload).nodes!;
}

async function coreInstance(client: MockWebBotClient, sessionId: string) {
  const tops = await children(client, sessionId, "group:tops");
  return (await children(client, sessionId, tops.find((node) => node.label === "system")!.id)).find((node) => node.label === "u_core : core")!;
}

async function openDetails(client: MockWebBotClient, sessionId: string, node: TreeNode) {
  const result = await client.invokePluginAction("main", pluginId, { viewId: "module-tree", sessionId, actionId: "open-details", payload: { nodeId: node.id } });
  const effect = result.hostEffects![0];
  if (effect.type !== "open_plugin_view") throw new Error("Expected details effect");
  const view = await client.openPluginView("main", effect.pluginId, effect.viewId, effect.input);
  if (view.renderer !== "table" || view.mode !== "session") throw new Error("Expected HDL details session");
  return view;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("HDL mock session contracts", () => {
  it("returns shallow direct children and isolates owners, projects and disposed sessions", async () => {
    const client = new MockWebBotClient();
    const first = await openTree(client);
    const second = await openTree(client, "/another-project");
    expect(first.sessionId).not.toBe(second.sessionId);
    expect(first.initialWindow.nodes!.map((node) => node.label)).toEqual(["候选顶层", "全部模块", "诊断"]);
    const tops = await children(client, first.sessionId, "group:tops");
    expect(tops.map((node) => node.label)).toEqual(["system", "utility"]);
    expect(tops.every((node) => !node.children)).toBe(true);
    const instances = await children(client, first.sessionId, tops[0].id);
    expect(instances.every((node) => !node.children)).toBe(true);
    expect(instances[1].badges).toEqual([{ text: "条件分支 `ifdef ENABLE_OPTIONAL", tone: "warning" }]);
    expect(await children(client, first.sessionId, instances[0].id)).toEqual([]);
    // Returned metadata must not mutate the session's trusted index.
    tops[0].payload!.source = { path: "/forged.sv", line: 999 };
    expect((await children(client, first.sessionId, tops[0].id))[0].secondaryText).toContain(projectPath);
    await expect(client.queryPluginViewWindow("team2", pluginId, first.sessionId, { op: "children", nodeId: null })).rejects.toThrow("插件会话不存在");
    await expect(client.queryPluginViewWindow("main", "rtl-hierarchy", first.sessionId, { op: "children", nodeId: null })).rejects.toThrow("插件会话不存在");
    await expect(children(client, first.sessionId, "unknown")).rejects.toThrow("HDL 节点不存在");
    await client.disposePluginViewSession("team2", pluginId, first.sessionId);
    expect(await children(client, first.sessionId, null)).toEqual(first.initialWindow.nodes);
    await client.disposePluginViewSession("main", pluginId, first.sessionId);
    await client.disposePluginViewSession("main", pluginId, first.sessionId);
    await expect(children(client, first.sessionId, null)).rejects.toThrow("插件会话不存在");
    const otherTops = await children(client, second.sessionId, "group:tops");
    expect(otherTops[0].secondaryText).toContain("/another-project/");
    const search = await client.queryPluginViewWindow("main", pluginId, second.sessionId, { op: "search", query: "utility" }) as TreeWindowPayload;
    expect(search.nodes!.map((node) => node.label)).toEqual(["utility"]);
    await client.login("other-owner");
    await expect(children(client, second.sessionId, null)).rejects.toThrow("插件会话不存在");
    await client.disposePluginViewSession("main", pluginId, second.sessionId);
    await client.login("demo");
    expect(await children(client, second.sessionId, null)).toEqual(second.initialWindow.nodes);
  });

  it("pages filtered/sorted details, trusts indexed IDs for navigation and blocks stale source", async () => {
    const client = new MockWebBotClient();
    const tree = await openTree(client);
    const instance = await coreInstance(client, tree.sessionId);
    const details = await openDetails(client, tree.sessionId, instance);
    const plainCore = (await children(client, tree.sessionId, "group:all")).find((node) => node.label === "core")!;
    const plainDetails = await openDetails(client, tree.sessionId, plainCore);
    expect(details.sessionId).not.toBe(tree.sessionId);
    expect(details.sessionId).not.toBe(plainDetails.sessionId);
    expect(details.initialWindow).toMatchObject({ offset: 0, limit: 2, totalRows: 3 });
    expect(details.initialWindow.rows.map((row) => row.cells.name)).toEqual(["WIDTH", "clk"]);
    expect(details.initialWindow.rows[0].cells).toMatchObject({ default: "4", override: "8" });
    expect(plainDetails.initialWindow.rows[0].cells.override).toBe("");
    const query = (request: Record<string, unknown>) => client.queryPluginViewWindow("main", pluginId, details.sessionId, request) as Promise<TableWindowPayload>;
    const last = await query({ offset: 2, limit: 2 });
    expect(last.rows.map((row) => row.cells.name)).toEqual(["data"]);
    expect(last.rows[0].cells.width).toBe("[WIDTH-1:0]");
    expect((await query({ offset: 3, limit: 2 })).rows).toEqual([]);
    expect(await query({ offset: 0, limit: 1, query: "input", sort: { columnId: "name", direction: "desc" } })).toMatchObject({ totalRows: 2, rows: [{ cells: { name: "data" } }] });
    expect(await query({ offset: 0, limit: 2, query: "missing" })).toMatchObject({ totalRows: 0, rows: [] });
    const action = { viewId: "module-details", sessionId: details.sessionId, actionId: "open-declaration", payload: { rowId: details.initialWindow.rows[0].id, path: "/forged.sv", line: 999 } };
    const result = await client.invokePluginAction("main", pluginId, action);
    expect(result.hostEffects).toEqual([{ type: "open_file", path: `${projectPath}/rtl/core.sv`, line: 2 }]);
    const source = await client.readFileFull("main", `${projectPath}/rtl/core.sv`);
    expect(source.content.split("\n")[1]).toBe("  parameter int WIDTH = 4");
    const instanceSource = await client.invokePluginAction("main", pluginId, { viewId: "module-tree", sessionId: tree.sessionId, actionId: "open-instance", payload: { nodeId: instance.id, path: "/forged.sv", line: 999 } });
    expect(instanceSource.hostEffects).toEqual([{ type: "open_file", path: `${projectPath}/rtl/system.sv`, line: 5 }]);
    await expect(client.invokePluginAction("main", pluginId, { ...action, payload: { rowId: "unknown" } })).rejects.toThrow("HDL 声明不存在");
    await expect(client.openPluginView("main", pluginId, "module-details", { path: "/another-project", parentSessionId: tree.sessionId, definitionId: plainCore.payload!.definitionId })).rejects.toThrow("HDL 项目会话不匹配");
    await client.writeFile("main", `${projectPath}/rtl/core.sv`, `${source.content}// changed\n`);
    expect(await client.invokePluginAction("main", pluginId, action)).toMatchObject({ message: expect.stringContaining("源码已变化"), hostEffects: [] });
    await client.disposePluginViewSession("main", pluginId, details.sessionId);
    await expect(query({ offset: 0, limit: 2 })).rejects.toThrow("插件会话不存在");
    expect((await children(client, tree.sessionId, "group:all")).length).toBe(4);
    expect((await client.queryPluginViewWindow("main", pluginId, plainDetails.sessionId, { offset: 0, limit: 2 }) as TableWindowPayload).rows).toHaveLength(2);
  });
});

function HdlFlow({ client, plugins, onEffects }: { client: MockWebBotClient; plugins: PluginSummary[]; onEffects: (effects: HostEffect[]) => void }) {
  const [view, setView] = useState<PluginRenderResult>();
  async function applyEffects(effects: HostEffect[]) {
    onEffects(effects);
    for (const effect of effects) {
      if (effect.type === "open_plugin_view") setView(await client.openPluginView("main", effect.pluginId, effect.viewId, effect.input));
    }
  }
  return <>
    <PluginCatalog plugins={plugins} client={client} botAlias="main" onOpenPluginView={async (target) => setView(await client.openPluginView("main", target.pluginId, target.viewId, target.input))} />
    {view ? <PluginViewSurface key={view.mode === "session" ? view.sessionId : view.viewId} botAlias="main" client={client} view={view} onApplyHostEffects={applyEffects} /> : null}
  </>;
}

it("connects catalog folder selection, lazy hierarchy, details paging and declaration actions", async () => {
  const client = new MockWebBotClient();
  const plugins = (await client.listPlugins()).filter((plugin) => plugin.id === pluginId);
  const user = userEvent.setup();
  const open = vi.spyOn(client, "openPluginView");
  const query = vi.spyOn(client, "queryPluginViewWindow");
  const invoke = vi.spyOn(client, "invokePluginAction");
  const effects = vi.fn();
  render(<HdlFlow client={client} plugins={plugins} onEffects={effects} />);
  await user.click(screen.getByRole("button", { name: "展开 HDL Workbench" }));
  await user.click(screen.getByRole("button", { name: "选择 HDL 项目" }));
  const picker = await screen.findByRole("dialog", { name: "选择 HDL 项目目录" });
  await user.click(await within(picker).findByRole("button", { name: "进入目录 src" }));
  await waitFor(() => expect(within(picker).getByText(projectPath)).toBeInTheDocument());
  await user.click(within(picker).getByRole("button", { name: "使用当前目录" }));
  await screen.findByTestId("plugin-tree-virtual-list");
  expect(open).toHaveBeenCalledWith("main", pluginId, "module-tree", { path: projectPath });
  expect(query).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "展开 候选顶层" }));
  await user.click(await screen.findByRole("button", { name: "展开 system" }));
  await user.click(await screen.findByRole("button", { name: "查看端口/参数 u_core : core" }));
  await screen.findByRole("table");
  await user.click(screen.getByRole("button", { name: "下一页" }));
  const row = await screen.findByRole("row", { name: /端口 data/ });
  await user.click(within(row).getByRole("button", { name: "打开声明" }));
  await waitFor(() => expect(invoke).toHaveBeenLastCalledWith("main", pluginId, expect.objectContaining({ viewId: "module-details", actionId: "open-declaration", payload: { rowId: "definition:rtl/core.sv:core:端口:data" } })));
  expect(effects).toHaveBeenLastCalledWith([{ type: "open_file", path: `${projectPath}/rtl/core.sv`, line: 5 }]);
});
