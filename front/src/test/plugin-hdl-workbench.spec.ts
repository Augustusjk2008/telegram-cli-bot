import { expect, test, type Page } from "@playwright/test";
import type { PluginActionInvokeInput, PluginActionResult, PluginViewWindowRequest } from "../services/types";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires PLAYWRIGHT_BASE_URL pointing to the user-started application");

async function setupHdlFixture(page: Page) {
  // The Node fixture shares the mock contract; browser traffic uses the real HTTP client.
  Object.assign(globalThis, { __APP_VERSION__: "hdl-acceptance" });
  const { MockWebBotClient } = await import("../services/mockWebBotClient");
  const client = new MockWebBotClient();
  const workspace = await client.getCurrentPath("main");
  const project = `${workspace}/src`;
  const pluginId = "hdl-workbench";
  const plugins = (await client.listPlugins()).filter((plugin) => plugin.id === pluginId);
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: workspace, supported_execution_modes: ["cli"] };
  const openedViews: Array<{ viewId: string; input: Record<string, unknown>; sessionId: string }> = [];
  const disposed: string[] = [];
  const actions: Array<{ input: PluginActionInvokeInput; result: PluginActionResult }> = [];
  const windows: Array<{ sessionId: string; request: PluginViewWindowRequest }> = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  await page.routeWebSocket("**/api/**", (socket) => socket.close());
  // Fulfill every API request so auth, browse state and source files stay in the fixture.
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.split("/api/")[1];
    let data: unknown = {};
    try {
      if (path === "auth/me") data = { is_logged_in: true, username: "hdl-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["chat_send", "read_file_content", "write_files", "view_plugins", "run_plugins"] };
      else if (path === "bots") data = [bot];
      else if (path === "bots/main") data = { bot, session: { working_dir: workspace, is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
      else if (path === "plugins") data = plugins;
      else if (path === "bots/main/pwd") data = { working_dir: workspace };
      else if (path === "bots/main/cd") data = { working_dir: await client.changeDirectory("main", request.postDataJSON().path) };
      else if (path === "bots/main/ls") {
        const listing = await client.listFiles("main", url.searchParams.get("path") || undefined);
        data = { working_dir: listing.workingDir, entries: listing.entries.map((entry) => ({ name: entry.name, is_dir: entry.isDir, size: entry.size })) };
      } else if (path === "bots/main/files/reveal") {
        const reveal = await client.revealFileTreePath("main", request.postDataJSON().path);
        data = { root_path: reveal.rootPath, highlight_path: reveal.highlightPath, expanded_paths: reveal.expandedPaths, branches: Object.fromEntries(Object.entries(reveal.branches).map(([branch, entries]) => [branch, entries.map((entry) => ({ name: entry.name, is_dir: entry.isDir, size: entry.size }))])) };
      } else if (path === "bots/main/plugins/resolve-file-target") data = { kind: "file" };
      else if (path === "bots/main/files/write") {
        const input = request.postDataJSON();
        if (input.path !== `${project}/rtl/core.sv`) throw new Error("Only the controlled nested HDL fixture can be edited");
        data = await client.writeFile("main", input.path, input.content);
      }
      else if (path === "bots/main/files/read") {
        const source = await client.readFileFull("main", url.searchParams.get("filename")!);
        data = { content: source.content, mode: "cat", working_dir: workspace, is_full_content: true, file_size_bytes: source.fileSizeBytes, last_modified_ns: source.lastModifiedNs };
      } else if (path.startsWith(`bots/main/plugins/${pluginId}/views/`) && path.endsWith("/open")) {
        const viewId = path.split("/").at(-2)!;
        const input = request.postDataJSON().input as Record<string, unknown>;
        const view = await client.openPluginView("main", pluginId, viewId, input);
        if (view.mode !== "session") throw new Error("Expected HDL session");
        openedViews.push({ viewId, input, sessionId: view.sessionId });
        data = view;
      } else if (path === `bots/main/plugins/${pluginId}/actions/invoke`) {
        const input = request.postDataJSON() as PluginActionInvokeInput;
        const result = await client.invokePluginAction("main", pluginId, input);
        actions.push({ input, result });
        data = result;
      } else if (path.startsWith(`bots/main/plugins/${pluginId}/sessions/`)) {
        const segments = path.split("/");
        const sessionId = segments[5];
        if (segments[6] === "window") {
          const windowRequest = request.postDataJSON() as PluginViewWindowRequest;
          windows.push({ sessionId, request: windowRequest });
          data = await client.queryPluginViewWindow("main", pluginId, sessionId, windowRequest);
        }
        else if (request.method() === "DELETE") {
          await client.disposePluginViewSession("main", pluginId, sessionId);
          disposed.push(sessionId);
          data = { disposed: true };
        }
      } else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1 };
      else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
      else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
      else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
      else if (path === "admin/users") data = [];
      await route.fulfill({ json: { ok: true, data } });
    } catch (error) {
      await route.fulfill({ status: 400, json: { ok: false, error: { message: error instanceof Error ? error.message : String(error) } } });
    }
  });
  return { client, project, pluginId, openedViews, disposed, actions, windows, errors };
}

async function selectHdlProject(page: Page, project: string) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(page.locator('script[type="module"][src]')).toHaveAttribute("src", /\/assets\/.+\.js$/);
  await page.getByTestId("desktop-workbench-activity-rail").getByRole("button", { name: "插件", exact: true }).click();
  const catalog = page.getByTestId("plugin-catalog-item-hdl-workbench");
  await catalog.getByRole("button", { name: "展开 HDL Workbench", exact: true }).click();
  await catalog.getByRole("button", { name: "选择 HDL 项目", exact: true }).click();
  const picker = page.getByRole("dialog", { name: "选择 HDL 项目目录", exact: true });
  await picker.getByRole("button", { name: "进入目录 src", exact: true }).click();
  await expect(picker.getByText(project, { exact: true })).toBeVisible();
  await picker.getByRole("button", { name: "使用当前目录", exact: true }).click();
  const tree = page.getByTestId("plugin-tree-virtual-list");
  await expect(tree).toBeVisible();
  await page.getByRole("button", { name: "聚焦编辑器", exact: true }).click();
  return tree;
}

async function expectSourceLine(page: Page, project: string, line: number, text: string, screenshotName: string) {
  const sourceTab = page.getByRole("tab", { name: "core.sv", exact: true });
  await expect(sourceTab).toHaveAttribute("aria-selected", "true");
  await expect(sourceTab).toHaveAttribute("title", `${project}/rtl/core.sv`);
  const editor = page.getByTestId("file-editor-host");
  await expect(editor.locator(".cm-content")).toContainText("module core #(");
  await expect(editor.locator(".cm-activeLine")).toHaveText(text);
  await expect(editor.locator(".cm-lineNumbers .cm-activeLineGutter")).toHaveText(String(line));
  await expect.poll(() => editor.locator(".cm-content").evaluate((element) => {
    const anchor = element.ownerDocument.getSelection()?.anchorNode;
    if (!anchor || !element.contains(anchor)) return "";
    const anchorElement = anchor instanceof Element ? anchor : anchor.parentElement;
    return anchorElement?.closest(".cm-line")?.textContent;
  })).toBe(text);
  const screenshot = test.info().outputPath(`${screenshotName}.png`);
  await editor.screenshot({ path: screenshot });
  await test.info().attach(screenshotName, { path: screenshot, contentType: "image/png" });
}

test("HDL project selection opens lazy instances, details and the highlighted source declaration", async ({ page }) => {
  const { project, openedViews, disposed, errors } = await setupHdlFixture(page);
  const tree = await selectHdlProject(page, project);
  await tree.getByRole("button", { name: "展开 候选顶层", exact: true }).click();
  await tree.getByRole("button", { name: "展开 system", exact: true }).click();
  await tree.getByRole("button", { name: "查看端口/参数 u_core : core", exact: true }).click();
  const table = page.getByRole("table");
  await expect(table.getByRole("cell", { name: "WIDTH", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await table.getByRole("row").filter({ has: page.getByRole("cell", { name: "data", exact: true }) }).getByRole("button", { name: "打开声明", exact: true }).click();

  await expectSourceLine(page, project, 5, "  input logic [WIDTH-1:0] data", "hdl-declaration-source");

  // Closing each plugin tab must release its independent tree/table session.
  for (const view of openedViews) {
    const title = view.viewId === "module-tree" ? "HDL 层级" : "core (u_core) · 端口/参数";
    await page.getByRole("tab", { name: title, exact: true }).locator("..").getByRole("button", { name: /^关闭 / }).click();
    await expect.poll(() => disposed.includes(view.sessionId)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("HDL nested-source refresh keeps old details and navigates the updated declaration at a narrow width", async ({ page }) => {
  const { client, project, openedViews, actions, windows, disposed, errors } = await setupHdlFixture(page);
  const tree = await selectHdlProject(page, project);
  await tree.getByRole("button", { name: "展开 候选顶层", exact: true }).click();
  await tree.getByRole("button", { name: "展开 system", exact: true }).click();
  await tree.getByRole("button", { name: "查看端口/参数 u_core : core", exact: true }).click();
  const table = page.getByRole("table");
  await expect(table.getByRole("cell", { name: "WIDTH", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "搜索", exact: true }).fill("推断");
  await expect(table.getByRole("cell", { name: "时钟候选", exact: true })).toBeVisible();
  await expect(table.getByRole("row").filter({ has: page.getByRole("cell", { name: "时钟候选", exact: true }) })).toContainText("推断候选：事件控制 always_ff");
  await page.getByRole("textbox", { name: "搜索", exact: true }).fill("");
  await expect(table.getByRole("cell", { name: "WIDTH", exact: true })).toBeVisible();
  const oldTreeSession = openedViews[0].sessionId;
  const oldDetailsSession = openedViews[1].sessionId;
  const path = `${project}/rtl/core.sv`;
  const source = await client.readFileFull("main", path);
  // Browser fetch goes through page.route; APIRequestContext would bypass the fixture.
  const edited = await page.evaluate(async (input) => {
    const response = await fetch("/api/bots/main/files/write", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
    return response.json();
  }, { path, content: source.content.replace("WIDTH = 4", "WIDTH = 6").replace("  input logic [WIDTH-1:0] data", "  // nested edit\n\n  input logic [WIDTH:0] data") });
  expect(edited.ok).toBe(true);
  await table.getByRole("row").filter({ has: page.getByRole("cell", { name: "WIDTH", exact: true }) }).getByRole("button", { name: "打开声明", exact: true }).click();
  await expect.poll(() => actions.at(-1)?.result.message).toContain("源码已变化");
  await expect(page.getByRole("tab", { name: "core.sv", exact: true })).toHaveCount(0);

  await page.getByRole("tab", { name: "HDL 层级", exact: true }).click();
  await page.getByRole("button", { name: "刷新项目", exact: true }).click();
  await expect.poll(() => openedViews.length).toBe(3);
  const freshTreeSession = openedViews[2].sessionId;
  expect(freshTreeSession).not.toBe(oldTreeSession);
  await expect(tree.getByRole("button", { name: "查看端口/参数 u_core : core", exact: true })).toHaveCount(0);
  const detailTitle = "core (u_core) · 端口/参数";
  await page.getByRole("tab", { name: detailTitle, exact: true }).click();
  await expect(table.getByRole("row").filter({ has: page.getByRole("cell", { name: "WIDTH", exact: true }) }).getByRole("cell", { name: "4", exact: true })).toBeVisible();
  expect(disposed).not.toContain(oldDetailsSession);

  await page.getByRole("tab", { name: "HDL 层级", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 900 });
  await tree.getByRole("button", { name: "展开 候选顶层", exact: true }).click();
  await tree.getByRole("button", { name: "展开 system", exact: true }).click();
  await tree.getByRole("button", { name: "查看端口/参数 u_core : core", exact: true }).click();
  await expect.poll(() => openedViews.length).toBe(4);
  expect(openedViews[3].input.parentSessionId).toBe(freshTreeSession);
  expect(windows.filter((window) => window.sessionId === freshTreeSession).map((window) => window.request.op)).toEqual(["children", "children"]);
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await table.getByRole("row").filter({ has: page.getByRole("cell", { name: "data", exact: true }) }).getByRole("button", { name: "打开声明", exact: true }).click();
  await expectSourceLine(page, project, 7, "  input logic [WIDTH:0] data", "hdl-refreshed-source-390");
  await expect.poll(() => page.getByTestId("file-editor-host").evaluate((element) => element.getBoundingClientRect().width)).toBeLessThanOrEqual(390);

  await page.getByRole("tab", { name: detailTitle, exact: true }).first().locator("..").getByRole("button", { name: /^关闭 / }).click();
  await expect.poll(() => disposed.includes(oldDetailsSession)).toBe(true);
  await page.getByRole("tab", { name: detailTitle, exact: true }).locator("..").getByRole("button", { name: /^关闭 / }).click();
  await expect.poll(() => disposed.includes(openedViews[3].sessionId)).toBe(true);
  await page.getByRole("tab", { name: "HDL 层级", exact: true }).locator("..").getByRole("button", { name: /^关闭 / }).click();
  await expect.poll(() => disposed.includes(freshTreeSession)).toBe(true);
  expect(errors).toEqual([]);
});
