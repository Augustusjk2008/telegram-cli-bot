import { expect, test } from "@playwright/test";
import type { TreeNode, TreeSessionRenderResult } from "../services/types";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires PLAYWRIGHT_BASE_URL pointing to the user-started application");

test("ZIP expands on demand, caches descendants and disposes the closed editor session", async ({ page }) => {
  const filename = "sample.zip";
  const sessionId = "zip-session-1";
  const roots: TreeNode[] = [
    { id: "dir:docs", label: "docs", kind: "folder", hasChildren: true, expandable: true },
    { id: "file:0:README.md", label: "README.md", kind: "file", expandable: false },
  ];
  const childrenByNodeId = new Map<string | null, TreeNode[]>([
    [null, roots],
    ["dir:docs", [
      { id: "dir:docs/guides", label: "guides", kind: "folder", hasChildren: true, expandable: true },
      { id: "file:1:docs/readme.txt", label: "readme.txt", kind: "file", expandable: false },
    ]],
    ["dir:docs/guides", [
      { id: "file:2:docs/guides/setup.txt", label: "setup.txt", kind: "file", expandable: false },
    ]],
  ]);
  const summary = { path: filename, roots, searchable: false, statsText: "3 文件 · 2 文件夹", emptySearchText: "压缩包为空" };
  const view: TreeSessionRenderResult = {
    pluginId: "zip-preview", viewId: "archive-tree", renderer: "tree", mode: "session", title: filename, sessionId,
    summary,
    initialWindow: { op: "children", nodeId: null, nodes: roots },
  };
  const entries = [{ name: filename, is_dir: false, size: 1024 }];
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:\\workspace", supported_execution_modes: ["cli"] };
  const sessionPath = `bots/main/plugins/zip-preview/sessions/${sessionId}`;
  const windowRequests: Record<string, unknown>[] = [];
  const disposals: string[] = [];
  const errors: string[] = [];
  let disposed = false;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  // Keep production assets from the running application; all API traffic stays in this test.
  await page.routeWebSocket("**/api/**", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = { is_logged_in: true, username: "zip-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["chat_send", "read_file_content", "view_plugins", "run_plugins"] };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:\\workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/ls") data = { working_dir: "C:\\workspace", entries };
    else if (path === "bots/main/pwd") data = { working_dir: "C:\\workspace" };
    else if (path === "bots/main/files/reveal") data = { root_path: "C:\\workspace", highlight_path: filename, branches: { "": entries } };
    else if (path === "bots/main/plugins/resolve-file-target") data = { kind: "plugin_view", pluginId: "zip-preview", viewId: "archive-tree", title: filename, input: { path: filename } };
    else if (path === "bots/main/plugins/zip-preview/views/archive-tree/open") data = view;
    else if (path === `${sessionPath}/window`) {
      const body = request.postDataJSON() as Record<string, unknown>;
      windowRequests.push(body);
      const nodeId = body.nodeId ?? null;
      const nodes = nodeId === null ? childrenByNodeId.get(null)
        : typeof nodeId === "string" ? childrenByNodeId.get(nodeId) : undefined;
      if (disposed || request.method() !== "POST" || body.op !== "children" || !nodes) {
        await route.fulfill({ status: 400, json: { ok: false, error: { message: "无效 ZIP children 请求" } } });
        return;
      }
      data = { op: "children", nodeId, nodes };
    } else if (path === sessionPath && request.method() === "DELETE") {
      disposals.push(path);
      disposed = true;
      data = { disposed: true };
    } else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1 };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path === "admin/users") data = [];
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator('script[type="module"][src]')).toHaveAttribute("src", /\/assets\/.+\.js$/);
  await page.getByRole("button", { name: `打开 ${filename}`, exact: true }).click();
  const tree = page.getByTestId("plugin-tree-virtual-list");
  await expect(tree).toBeVisible();
  await page.getByRole("button", { name: "聚焦编辑器", exact: true }).click();
  expect(windowRequests).toEqual([]);
  await expect(tree.getByRole("button", { name: "guides", exact: true })).toHaveCount(0);

  await tree.getByRole("button", { name: "展开 docs", exact: true }).click();
  await expect(tree.getByRole("button", { name: "readme.txt", exact: true })).toBeVisible();
  await expect(tree.getByRole("button", { name: "展开 guides", exact: true })).toBeVisible();
  await expect(tree.getByRole("button", { name: "setup.txt", exact: true })).toHaveCount(0);
  expect(windowRequests).toEqual([{ op: "children", nodeId: "dir:docs" }]);

  await tree.getByRole("button", { name: "展开 guides", exact: true }).click();
  await expect(tree.getByRole("button", { name: "setup.txt", exact: true })).toBeVisible();
  expect(windowRequests).toEqual([
    { op: "children", nodeId: "dir:docs" },
    { op: "children", nodeId: "dir:docs/guides" },
  ]);
  await tree.getByRole("button", { name: "折叠 docs", exact: true }).click();
  await expect(tree.getByRole("button", { name: "setup.txt", exact: true })).toHaveCount(0);
  await tree.getByRole("button", { name: "展开 docs", exact: true }).click();
  await expect(tree.getByRole("button", { name: "readme.txt", exact: true })).toBeVisible();
  await expect(tree.getByRole("button", { name: "setup.txt", exact: true })).toBeVisible();

  const screenshot = test.info().outputPath("zip-expanded-tree.png");
  await tree.screenshot({ path: screenshot });
  await test.info().attach("ZIP expanded tree", { path: screenshot, contentType: "image/png" });
  expect(disposals).toEqual([]);
  const tab = page.getByRole("tab", { name: filename, exact: true });
  await tab.locator("..").getByRole("button", { name: /^关闭 / }).click();
  await expect(tree).toHaveCount(0);
  await expect.poll(() => disposals).toEqual([sessionPath]);
  expect(windowRequests).toHaveLength(2);
  expect(errors).toEqual([]);
});
