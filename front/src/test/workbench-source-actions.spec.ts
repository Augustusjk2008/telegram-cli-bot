import { expect, test, type Locator, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

const source = Array.from({ length: 50 }, (_, i) => `source line ${i + 1}`).join("\n");
const filename = `src/${"module-".repeat(24)}app.ts`;
const patch = "@@ -40,2 +40,3 @@\n same\n-  old\n+  new\n+  extra";

async function openWorkbench(page: Page, { writable = true, ssh = false } = {}) {
  const root = ssh ? "/srv/repo/packages" : "C:/repo/packages";
  const reads: string[] = [];
  const sends: string[] = [];
  const bots = ["main", "other"].map((alias) => ({
    alias, name: alias, cli_type: "codex", status: "running", working_dir: root,
    ...(ssh ? { remote_workspace: { connection_id: "qa", host: "ssh.test", port: 22, username: "qa",
      root, platform: "posix", host_key_fingerprint: "qa" } } : {}),
  }));
  await page.addInitScript(({ root, ssh }) => {
    localStorage.setItem("web-terminal-tabs:v1", JSON.stringify([{
      id: "qa-terminal", ownerId: "qa-owner", title: "QA", cwd: `${root}/build`, shell: "auto",
      ...(ssh ? { botAlias: "main" } : { sourceBotAlias: "main" }),
    }]));
  }, { root, ssh });
  await page.routeWebSocket("**/*", (socket) => {
    if (!new URL(socket.url()).pathname.endsWith("/terminal/ws")) return socket.close();
    socket.onMessage((message) => {
      if (typeof message !== "string" || !message.includes("protocol_version")) return;
      socket.send(JSON.stringify({ pty_mode: true }));
      socket.send(`错误 ${filename}:42:7\r\nC:/other/private.ts:4\r\nhttps://example.org/doc\r\n\x1b]8;;https://example.org/guide\x07帮助.ts:3\x1b]8;;\x07\r\nmissing.ts:2\r\n`);
    });
  });
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.split("/api/")[1];
    const bot = bots.find(({ alias }) => path.startsWith(`bots/${alias}`));
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "source-qa", account_id: "source-qa", role: "member", current_bot_alias: "main",
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", ...(writable ? ["write_files"] : []),
        "view_chat_history", "chat_send", "terminal_exec", "git_ops"],
    };
    else if (path === "bots") data = bots;
    else if (bot && path === `bots/${bot.alias}`) data = { bot, session: { working_dir: root, is_processing: false }, agents: [{ id: "main", name: "main" }] };
    else if (path === "terminal/session") data = { started: true, pty_mode: true, cwd: `${root}/build` };
    else if (path.endsWith("/ls")) data = { working_dir: root, entries: [{ name: "app.ts", is_dir: false }] };
    else if (path.endsWith("/pwd")) data = { working_dir: root };
    else if (path.endsWith("/files/read")) {
      const file = url.searchParams.get("filename") || "";
      reads.push(file);
      if (file === "build/missing.ts") {
        await route.fulfill({ status: 404, json: { ok: false, error: { code: "file_not_found", message: "文件不存在：missing.ts" } } });
        return;
      }
      data = { content: source, mode: "cat", is_full_content: true };
    }
    else if (path.endsWith("/files/reveal")) data = { branches: {}, expanded_paths: [], highlight_path: route.request().postDataJSON()?.path };
    else if (path.endsWith("/git/tree-status")) data = { repo_found: true, repo_path: "C:/repo", working_dir: root, items: { "app.ts": "modified" } };
    else if (path.endsWith("/git/diff")) data = { path: url.searchParams.get("path"), staged: false, diff: patch };
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path.endsWith("/chat/attachments")) data = { filename: "notes.txt", saved_path: "uploads/notes.txt", size: 2 };
    else if (path.endsWith("/chat/stream")) sends.push(path);
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path.endsWith("/terminal-actions/config")) data = { schemaVersion: 1, actions: [], errors: [], runtimePlatform: "windows" };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width: 1680, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("./");
  await expect(page.getByTestId("desktop-workbench-columns")).toBeVisible();
  return { reads, sends };
}

async function textPoint(locator: Locator, text: string) {
  return locator.evaluate((element, needle) => {
    let offset = (element.textContent || "").indexOf(needle);
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    while (offset >= 0 && walker.nextNode()) {
      const node = walker.currentNode as Text;
      if (offset < node.length) {
        const range = document.createRange();
        range.setStart(node, offset);
        range.setEnd(node, offset + 1);
        const rect = range.getBoundingClientRect();
        return { x: Math.floor(rect.x + rect.width / 4), y: Math.floor(rect.y + rect.height / 2) };
      }
      offset -= node.length;
    }
    throw new Error(`Missing text: ${needle}`);
  }, text);
}

async function terminalClick(page: Page, text: string, ctrl = true, expectLink = ctrl) {
  const row = page.locator(".xterm-rows > div").filter({ hasText: text }).first();
  if (expectLink) {
    await expect.poll(async () => {
      const point = await textPoint(row, text);
      await page.mouse.move(point.x, point.y);
      return page.locator(".xterm-screen").evaluate((element) => element.classList.contains("xterm-cursor-pointer"));
    }).toBe(true);
  }
  const { x, y } = await textPoint(row, text);
  await page.mouse.move(x, y);
  if (ctrl) await page.keyboard.down("Control");
  await page.mouse.click(x, y);
  if (ctrl) await page.keyboard.up("Control");
}

test("Ctrl+click on wrapped terminal output reveals the source position and keeps unsaved edits", async ({ page }) => {
  const { reads } = await openWorkbench(page);
  await terminalClick(page, "private.ts", true, false);
  await terminalClick(page, ":42:7", false);
  expect(reads).toEqual([]);
  const row = page.locator(".xterm-rows > div").filter({ hasText: ":42:7" }).first();
  const point = await textPoint(row, ":42:7");
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 25, point.y, { steps: 6 });
  await page.mouse.up();
  expect(reads).toEqual([]);
  for (const [label, url] of [["example.org/doc", "https://example.org/doc"], ["帮助.ts:3", "https://example.org/guide"]]) {
    await page.context().route(url, (route) => route.fulfill({ body: "" }));
    const popup = page.waitForEvent("popup");
    await terminalClick(page, label);
    const opened = await popup;
    expect(opened.url()).toBe(url);
    await opened.close();
  }
  await page.getByRole("button", { name: "聚焦终端", exact: true }).click();
  await expect(page.getByTestId("desktop-pane-editor")).toBeHidden();
  await terminalClick(page, ":42:7");
  const editor = page.locator(".cm-content");
  await expect(editor).toBeFocused();
  await page.keyboard.insertText("EDIT");
  await expect(editor.locator(".cm-line").filter({ hasText: "sourceEDIT line 42" })).toBeVisible();
  await terminalClick(page, ":42:7");
  await expect(editor).toBeFocused();
  await expect(editor).toContainText("sourceEDIT line 42");
  expect(reads).toEqual([`build/${filename}`]);
});

test("an SSH terminal source location opens a read-only editor", async ({ page }) => {
  const { reads } = await openWorkbench(page, { writable: false, ssh: true });
  await terminalClick(page, ":42:7");
  const editor = page.locator(".cm-content");
  await expect(editor).toHaveAttribute("contenteditable", "false");
  await expect(editor).toBeFocused();
  await expect.poll(() => editor.evaluate(() => {
    const selection = document.getSelection();
    const line = selection?.anchorNode?.parentElement?.closest(".cm-line");
    if (!line || !selection?.anchorNode) return null;
    const prefix = document.createRange();
    prefix.selectNodeContents(line);
    prefix.setEnd(selection.anchorNode, selection.anchorOffset);
    return [line.textContent, prefix.toString().length];
  })).toEqual(["source line 42", 6]);
  expect(reads).toEqual([`build/${filename}`]);
  await terminalClick(page, "missing.ts");
  await expect(page.getByText("文件不存在：missing.ts", { exact: true })).toBeVisible();
});

test("a dragged replacement appends to the active Bot draft, reopens chat and leaves sending to the user", async ({ page }) => {
  const { reads, sends } = await openWorkbench(page);
  const input = page.locator('textarea[name="message"]:visible');
  async function switchBot(from: string, to: string) {
    await page.getByRole("button", { name: `切换 Bot: ${from}`, exact: true }).click();
    await page.locator(".desktop-bot-switcher-item").filter({ hasText: to }).click();
    await expect(page.getByRole("button", { name: `切换 Bot: ${to}`, exact: true })).toBeVisible();
  }
  await input.fill("main draft");
  await switchBot("main", "other");
  await terminalClick(page, ":42:7", true, false);
  expect(reads).toEqual([]);
  await input.fill("这段改动");
  const composer = page.getByTestId("chat-composer-root").filter({ visible: true });
  await composer.getByTestId("chat-attachment-input").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("qa") });
  const attachment = page.getByRole("button", { name: "移除附件 notes.txt" });
  await expect(attachment).toBeVisible();
  await page.getByRole("button", { name: "隐藏聊天", exact: true }).click();
  await page.getByRole("button", { name: "打开 app.ts", exact: true }).click({ button: "right" });
  await page.getByRole("button", { name: "Diff", exact: true }).click();
  const diff = page.getByTestId("desktop-git-diff-viewer");
  await expect(diff).toHaveAttribute("data-diff-view-mode", "split");
  const start = await textPoint(diff.locator('[data-diff-side="left"] [data-diff-code]').filter({ hasText: "same" }), "s");
  const end = await textPoint(diff.locator('[data-diff-side="right"] [data-diff-code]').filter({ hasText: "extra" }), "a");
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(end.x, end.y, { steps: 12 });
  await page.mouse.up();
  const quote = diff.getByRole("button", { name: "引用到聊天" });
  await expect(quote).toBeEnabled();
  await quote.click();
  const expected = "这段改动\n\npackages/app.ts · 工作区 Diff · 旧 40–41 行 / 新 40–42 行\n```diff\n same\n-  old\n+  new\n+  extra\n```\n\n";
  await expect(input).toHaveValue(expected);
  await expect(attachment).toBeVisible();
  await expect(input).toBeFocused();
  await page.keyboard.insertText("为什么？");
  await expect(input).toHaveValue(`${expected}为什么？`);
  await switchBot("other", "main");
  await expect(input).toHaveValue("main draft");
  await switchBot("main", "other");
  await expect(input).toHaveValue(`${expected}为什么？`);
  expect(sends).toEqual([]);
});
