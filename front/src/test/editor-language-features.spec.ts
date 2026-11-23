import { expect, test, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

const FILE = "device.cpp";
const BODY = Array.from({ length: 70 }, (_, index) => `        total += step(${index});`);
const SOURCE = [
  "namespace demo {",                       // 1
  "int step(int value);",                   // 2
  "int run(int count) {",                   // 3
  "    int total = 0;",                     // 4
  "    for (;;) {",                         // 5
  "#if defined(DEMO_DEBUG)",                // 6
  "        total += step(-1);",             // 7
  "#endif",                                 // 8
  ...BODY,                                  // 9..78
  "        if (total != count) {",          // 79
  "            break;",                     // 80
  "        }",                              // 81
  "    }",                                  // 82
  "    return total;",                      // 83
  "}",                                      // 84
  "}",                                      // 85
].join("\n");

const range = (line: number, column: number, endLine: number, endColumn: number) => ({
  start: { line, column },
  end: { line: endLine, column: endColumn },
});

async function openEditor(page: Page) {
  const queries: Array<{ kind: string; position?: { line: number; column: number } }> = [];
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "editor-qa", account_id: "editor-qa", role: "member", current_bot_alias: "main",
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send", "terminal_exec"],
    };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:/workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/ls") data = { working_dir: "C:/workspace", entries: [{ name: FILE, is_dir: false }] };
    else if (path === "bots/main/pwd") data = { working_dir: "C:/workspace" };
    else if (path.endsWith("/plugins/resolve-file-target")) data = { kind: "file" };
    else if (path.endsWith("/files/read")) data = { content: SOURCE, mode: "cat", is_full_content: true, last_modified_ns: "1" };
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path.endsWith("/terminal-actions/config")) data = { schemaVersion: 1, configPath: "", exists: false, mtimeNs: "", editable: false, errors: [], runtimePlatform: "windows", actions: [] };
    else if (path.endsWith("/workspace/language-servers")) data = {
      can_refresh: true,
      providers: [{
        provider: "clangd", status: "available", source: "managed", version: "1", command_summary: "clangd",
        runtime_state: "ready", implementation_supported: true,
        configuration: { mode: "fallback", summary: "默认参数 -std=c++17", hint: "未找到 compile_commands.json" },
      }],
    };
    else if (path.endsWith("/code-navigation/resolve")) {
      const body = route.request().postDataJSON() as { requestId: string };
      data = { request_id: body.requestId, items: [], message: "未找到语义定义" };
    }
    else if (path.endsWith("/workspace/search")) data = {
      items: [
        { path: FILE, line: 2, column: 5, preview: "int step(int value);" },
        { path: "notes.txt", line: 1, column: 1, preview: "stepping stones" },
      ],
    };
    else if (path.endsWith("/code-intelligence/query")) {
      const body = route.request().postDataJSON() as { kind: string; requestId: string; position?: { line: number; column: number } };
      queries.push({ kind: body.kind, position: body.position });
      const base = { request_id: body.requestId, kind: body.kind, provider: "clangd", available: true, supported: true, message: "" };
      if (body.kind === "documentSymbols") data = {
        ...base,
        items: [{
          name: "demo", detail: "", kind: "namespace", range: range(1, 1, 85, 2), selection_range: range(1, 11, 1, 15),
          children: [{ name: "run", detail: "int (int)", kind: "function", range: range(3, 1, 84, 2), selection_range: range(3, 5, 3, 8), children: [] }],
        }],
      };
      else if (body.kind === "semanticTokens") data = {
        ...base,
        legend: { types: ["variable", "function"], modifiers: [] },
        tokens: [4, 9, 5, 0, 0, 83, 12, 5, 0, 0],
        inactive_ranges: [{ start_line: 7, end_line: 7 }],
        version: 1,
      };
      else if (body.kind === "references") data = {
        ...base,
        items: [{
          target_type: "workspace", path: FILE, provider: "clangd",
          range: range(2, 5, 2, 9), selection_range: range(2, 5, 2, 9), preview: "int step(int value);",
        }],
      };
      else if (body.kind === "diagnostics") data = { ...base, items: [], version: 1, ready: true };
      else data = base;
    }
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("./");
  await expect(page.getByTestId("desktop-workbench-columns")).toBeVisible();
  await page.getByRole("button", { name: `打开 ${FILE}`, exact: true }).click();
  const editor = page.getByTestId("editor-group-left");
  await expect(editor.locator(".cm-content")).toContainText("namespace demo");
  return { editor, queries };
}

test("the editor shows language-server colours, scope headers and symbol breadcrumbs", async ({ page }) => {
  const { editor } = await openEditor(page);

  await expect(editor.locator(".cm-semantic-variable", { hasText: "total" }).first()).toBeVisible();
  await expect(editor.locator(".cm-line.cm-inactive-code")).toHaveText("        total += step(-1);");
  await expect(editor.locator(".cm-line.cm-indent-guides").first()).toBeVisible();
  // Coding fonts must not merge != into one glyph.
  expect(await editor.locator(".cm-editor").evaluate((node) => getComputedStyle(node).fontVariantLigatures)).toBe("none");
  await expect(page.getByTestId("workbench-language-service")).toHaveText("C/C++ · 就绪（默认编译参数）");

  await editor.locator(".cm-scroller").evaluate((node) => {
    node.scrollTop = node.scrollHeight;
  });
  const sticky = editor.locator(".cm-sticky-scroll-row");
  await expect(sticky).toHaveText(["1namespace demo {", "3int run(int count) {", "5    for (;;) {"]);
  // The pinned rows cover the top of the viewport without hiding the line the cursor is put on.
  await editor.locator(".cm-line", { hasText: "return total;" }).click();
  const crumbs = editor.getByTestId("editor-breadcrumb-symbol");
  await expect(crumbs).toHaveText(["demo", "run"]);
  await page.screenshot({ path: test.info().outputPath("editor-language-features.png") });

  // Jumping to the function scrolls back to the top, where nothing is left to pin.
  await crumbs.nth(1).click();
  await expect(editor.locator(".cm-activeLine")).toHaveText("int run(int count) {");
  await expect(sticky).toHaveCount(0);
});

test("the editor menu lists references and falls back to labelled text matches", async ({ page }) => {
  const { editor, queries } = await openEditor(page);
  const call = editor.locator(".cm-line", { hasText: "total += step(0);" }).getByText("step", { exact: true });
  await call.click({ button: "right" });
  const menu = page.getByTestId("file-editor-context-menu");
  await expect(menu.getByRole("menuitem")).toHaveText([
    "转到定义F12", "转到实现Ctrl+F12", "查找所有引用Shift+F12", "剪切Ctrl+X", "复制Ctrl+C", "粘贴Ctrl+V", "全选Ctrl+A",
  ]);
  await menu.getByRole("menuitem", { name: "查找所有引用" }).click();
  const picker = page.getByTestId("desktop-definition-picker");
  await expect(picker).toContainText("引用（1）");
  await expect(picker).toContainText("int step(int value);");
  // The query carries the clicked position inside `step` on line 9 (columns 18 to 22).
  const position = queries.find((query) => query.kind === "references")?.position;
  expect(position?.line).toBe(9);
  expect(position?.column).toBeGreaterThanOrEqual(18);
  expect(position?.column).toBeLessThanOrEqual(22);
  await picker.getByRole("button", { name: "关闭代码跳转" }).click();

  // The language server has no definition here, so matching text is offered and marked as such.
  await call.click();
  await page.keyboard.press("F12");
  await expect(page.getByTestId("desktop-definition-text-fallback")).toContainText("不是语义分析");
  await expect(picker.getByRole("button")).toHaveText(["关闭", /int step\(int value\);.*文本搜索/]);
  await picker.getByRole("button", { name: /int step/ }).click();
  await expect(editor.locator(".cm-activeLine")).toHaveText("int step(int value);");
});
