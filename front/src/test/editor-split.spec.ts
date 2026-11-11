import { expect, test, type Locator, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

async function openWorkbench(page: Page, width = 1920) {
  const files = new Map([["alpha.ts", "const value = 1;"], ["beta.ts", "const other = 10;"]]);
  const writes: Array<{ path: string; content: string }> = [];
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "split-qa", account_id: "split-qa", role: "member", current_bot_alias: "main",
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send", "terminal_exec"],
    };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:/workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/ls") data = { working_dir: "C:/workspace", entries: [...files.keys()].map((name) => ({ name, is_dir: false })) };
    else if (path === "bots/main/pwd") data = { working_dir: "C:/workspace" };
    else if (path.endsWith("/plugins/resolve-file-target")) data = { kind: "file" };
    else if (path.endsWith("/files/read")) data = { content: files.get(url.searchParams.get("filename") || ""), mode: "cat", is_full_content: true, last_modified_ns: "1" };
    else if (path.endsWith("/files/write")) {
      const body = route.request().postDataJSON() as { path: string; content: string };
      writes.push(body);
      files.set(body.path, body.content);
      data = { path: body.path, file_size_bytes: body.content.length, last_modified_ns: String(writes.length + 1) };
    }
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path.endsWith("/terminal-actions/config")) data = { schemaVersion: 1, configPath: "", exists: false, mtimeNs: "", editable: false, errors: [], runtimePlatform: "windows", actions: [] };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("./");
  await expect(page.getByTestId("desktop-workbench-columns")).toBeVisible();
  await page.getByRole("button", { name: "打开 alpha.ts", exact: true }).click();
  const left = page.getByTestId("editor-group-left");
  const right = page.getByTestId("editor-group-right");
  await expect(left.locator(".cm-content")).toHaveText("const value = 1;");
  return { left, right, writes };
}

async function replaceDocument(page: Page, group: Locator, content: string) {
  await group.locator(".cm-content").click();
  await page.keyboard.press("Control+a");
  await page.keyboard.insertText(content);
}

test("same-file views share edits, save status and undo while preserving both groups across reload", async ({ page }) => {
  const { left, right, writes } = await openWorkbench(page);
  await left.getByRole("button", { name: "在右侧打开", exact: true }).click();
  await expect(right.locator(".cm-content")).toHaveText("const value = 1;");
  await left.locator(".cm-content").click();
  await page.keyboard.press("Control+f");
  const findInput = left.locator('.cm-search input[name="search"]');
  await expect(findInput).toBeVisible();
  await right.locator(".cm-content").click();
  await findInput.focus();
  await expect(findInput).toBeFocused();
  await findInput.press("Escape");
  await replaceDocument(page, right, "const value = 2;");
  await expect(left.locator(".cm-content")).toHaveText("const value = 2;");
  await expect(page.getByTestId("editor-tab-dirty-dot-alpha.ts")).toHaveCount(2);

  await left.locator(".cm-content").click();
  await page.keyboard.press("Control+s");
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ path: "alpha.ts", content: "const value = 2;" });
  await expect(page.getByTestId("editor-tab-dirty-dot-alpha.ts")).toHaveCount(0);

  await right.locator(".cm-content").click();
  await page.keyboard.press("Control+z");
  await expect(left.locator(".cm-content")).toHaveText("const value = 1;");
  await expect(right.locator(".cm-content")).toHaveText("const value = 1;");
  await left.locator(".cm-content").click();
  await page.keyboard.press("Control+Shift+z");
  await expect(right.locator(".cm-content")).toHaveText("const value = 2;");
  await expect(page.getByTestId("editor-tab-dirty-dot-alpha.ts")).toHaveCount(0);

  await replaceDocument(page, left, "const value = 3;");
  const divider = page.getByRole("separator", { name: "调整编辑组宽度" });
  const before = (await left.boundingBox())!;
  await divider.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await left.boundingBox())!.width).toBeGreaterThan(before.width);
  await expect.poll(() => page.evaluate(() => Object.values(localStorage).some((raw) => {
    try {
      const stored = JSON.parse(raw);
      return stored.editorGroups?.right.activePath === "alpha.ts" && stored.editorGroups.splitRatio === 0.55 && stored.tabs?.[0]?.draftContent === "const value = 3;";
    } catch { return false; }
  }))).toBe(true);
  await page.reload();
  await expect(left.locator(".cm-content")).toHaveText("const value = 3;");
  await expect(right.locator(".cm-content")).toHaveText("const value = 3;");
  await expect(divider).toHaveAttribute("aria-valuenow", "55");
  await page.screenshot({ path: test.info().outputPath("editor-split-shared.png") });

  await right.getByRole("button", { name: "关闭 alpha.ts", exact: true }).click();
  await expect(right).toHaveCount(0);
  await expect(left.locator(".cm-content")).toHaveText("const value = 3;");
  await expect(left.getByTestId("editor-tab-dirty-dot-alpha.ts")).toBeVisible();
});

test("opening a different file to the right saves the focused file and closing the split keeps its draft", async ({ page }) => {
  const { left, right, writes } = await openWorkbench(page, 1280);
  await page.getByRole("button", { name: "打开 beta.ts", exact: true }).click({ button: "right" });
  await page.getByRole("menu").getByRole("button", { name: "在右侧打开", exact: true }).click();
  await expect(right.locator(".cm-content")).toHaveText("const other = 10;");
  await replaceDocument(page, left, "const value = 20;");
  await replaceDocument(page, right, "const other = 30;");
  await page.keyboard.press("Control+s");
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ path: "beta.ts", content: "const other = 30;" });
  await expect(left.getByTestId("editor-tab-dirty-dot-alpha.ts")).toBeVisible();
  await replaceDocument(page, right, "const other = 40;");
  const leftBox = (await left.boundingBox())!;
  const rightBox = (await right.boundingBox())!;
  expect(leftBox.x + leftBox.width).toBeLessThanOrEqual(rightBox.x);
  expect(rightBox.width).toBeGreaterThan(100);
  for (const group of [left, right]) {
    const toolbar = (await group.locator(".editor-tab-strip").boundingBox())!;
    const breadcrumb = (await group.getByRole("navigation", { name: "文件路径" }).boundingBox())!;
    expect(toolbar.y + toolbar.height).toBeLessThanOrEqual(breadcrumb.y + 1);
  }
  await page.screenshot({ path: test.info().outputPath("editor-split-1280.png") });
  await right.getByRole("button", { name: "关闭右侧分栏" }).click();
  await expect(right).toHaveCount(0);
  await expect(left.locator(".cm-content")).toHaveText("const other = 40;");
  await left.getByRole("tab", { name: "alpha.ts", exact: true }).click();
  await expect(left.locator(".cm-content")).toHaveText("const value = 20;");
  await left.getByRole("tab", { name: "beta.ts", exact: true }).click();
  await left.locator(".cm-content").click();
  await page.keyboard.press("Control+z");
  await expect(left.locator(".cm-content")).toHaveText("const other = 30;");
});
