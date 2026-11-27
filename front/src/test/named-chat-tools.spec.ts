import { expect, test, type Page, type Route } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Uses the real client on a user-started host");

type Session = { id: string; title: string; selected_cli_type: string | null; effective_cli_type: string };

async function openWorkbench(page: Page, width: number, legacy = false) {
  const bot = { alias: "main", cli_type: "codex", status: "running", working_dir: "/workspace", can_operate: true };
  const sessions: Session[] = [{ id: "main", title: "主会话", selected_cli_type: null, effective_cli_type: "codex" }];
  const posts: Record<string, string>[] = [];
  const sends = new Map<string, Route>();
  const stops: string[] = [];
  const settingsRequests: string[] = [];
  const options = ["codex", "codex_server", "claude", "antigravity", "deepseek"]
    .map((cli_type) => ({ cli_type, available: cli_type !== "deepseek" }));
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    const [, sessionId, operation] = /^bots\/main(?:\/sessions\/([^/]+))?(?:\/(.+))?$/.exec(path) ?? [];
    let data: unknown = {};
    if (path === "auth/me") {
      data = { is_logged_in: true, username: "chat-qa", account_id: "chat-qa", role: "member",
        current_bot_alias: "main", capabilities: ["view_bots", "view_bot_status", "view_chat_history", "chat_send"] };
    } else if (path === "bots") {
      data = [bot];
    } else if (path === "bots/main/sessions") {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON();
        posts.push(body);
        const item = { id: "ses_" + sessions.length, title: body.title,
          selected_cli_type: body.cli_type ?? null, effective_cli_type: body.cli_type ?? bot.cli_type };
        sessions.push(item);
        data = legacy ? { id: item.id, title: item.title } : item;
      } else {
        data = legacy ? { enabled: true, items: sessions.map(({ id, title }) => ({ id, title })) }
          : { enabled: true, items: sessions, cli_options: options };
      }
    } else if (path === "bots/main" || (sessionId && !operation)) {
      data = { bot, session: { working_dir: bot.working_dir, is_processing: sends.has(sessionId),
        cli_type: sessions.find((item) => item.id === sessionId)?.effective_cli_type ?? bot.cli_type },
        agents: [{ id: "main", name: "main" }] };
    } else if (operation === "chat/stream") {
      sends.set(sessionId ?? "main", route);
      return;
    } else if (operation === "cli-params") {
      settingsRequests.push(sessionId ?? "main");
      const kind = sessions.find((item) => item.id === sessionId)?.effective_cli_type ?? bot.cli_type;
      data = { cli_type: kind, params: { model: "none" }, defaults: { model: "none" },
        schema: { model: { type: "string", description: "模型", enum: ["none"] } } };
    } else if (operation === "kill") {
      stops.push(sessionId ?? "main");
    } else if (operation === "ls" || operation === "pwd") {
      data = { working_dir: bot.working_dir, entries: [] };
    } else if (operation === "history" || operation === "history/delta") {
      data = { items: [], revision: 0, reset: false };
    } else if (operation === "agents" || operation === "conversations" || operation === "favorites" || path === "announcements") {
      data = { items: [], active_conversation_id: "" };
    }
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.addInitScript((mode) => localStorage.setItem("web-view-mode", mode), width < 700 ? "mobile" : "desktop");
  await page.setViewportSize({ width, height: 900 });
  await page.goto("./");
  return { posts, sends, stops, settingsRequests };
}

for (const width of [1440, 390]) {
  test(`creates, switches and reopens pinned chats at ${width}px`, async ({ page }) => {
    const { posts, sends, stops, settingsRequests } = await openWorkbench(page, width);
    const selector = page.getByRole("combobox", { name: "当前聊天会话" });
    for (const [title, cli] of [["Implementation", "codex"], ["Review", "claude"]]) {
      await selector.selectOption("");
      const dialog = page.getByRole("dialog", { name: "新建聊天会话" });
      const name = dialog.getByLabel("聊天会话名称");
      const tool = dialog.getByLabel("AI 工具");
      await expect(name).toBeFocused();
      await name.fill(title);
      await name.press("Tab");
      await expect(tool).toBeFocused();
      await expect(tool).toHaveValue("codex");
      await expect(tool.locator('option[value="deepseek"]')).toHaveJSProperty("disabled", true);
      await tool.selectOption(cli);
      if (cli === "claude") {
        await expect(dialog).toBeInViewport();
        await page.screenshot({ path: test.info().outputPath(`new-chat-${width}.png`) });
      }
      await dialog.getByRole("button", { name: "创建", exact: true }).press("Enter");
      await expect(selector).toHaveAttribute("title", `${title} · ${cli}`);
      await expect(selector).toBeFocused();
      // The native control supplies the menu. Its closed text must not overlap the two visible labels.
      await expect(selector).toHaveCSS("color", "rgba(0, 0, 0, 0)");
    }
    expect(posts).toEqual([{ title: "Implementation", cli_type: "codex" }, { title: "Review", cli_type: "claude" }]);
    await selector.selectOption("ses_1");
    await page.getByPlaceholder("输入消息").fill("Run implementation");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => [...sends.keys()]).toEqual(["ses_1"]);
    await selector.selectOption("ses_2");
    await expect(selector).toHaveAttribute("title", "Review · claude");
    await expect.poll(() => settingsRequests.includes("ses_2")).toBe(true);
    await sends.get("ses_1")!.abort();
    await page.reload();
    await expect(selector).toHaveValue("ses_2");
    await expect(selector).toHaveAttribute("title", "Review · claude");
    expect(stops).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`selected-chat-${width}.png`) });
  });
}

test("creates a title-only chat against a phase-one catalog", async ({ page }) => {
  const { posts } = await openWorkbench(page, 1440, true);
  const selector = page.getByRole("combobox", { name: "当前聊天会话" });
  await selector.selectOption("");
  const dialog = page.getByRole("dialog", { name: "新建聊天会话" });
  await expect(dialog.getByRole("combobox")).toHaveCount(0);
  await dialog.getByLabel("聊天会话名称").fill("Legacy");
  await dialog.getByRole("button", { name: "创建", exact: true }).click();
  await expect(selector).toHaveValue("ses_1");
  expect(posts).toEqual([{ title: "Legacy" }]);
});
