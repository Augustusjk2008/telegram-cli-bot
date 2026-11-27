import { expect, test, type Page, type Route, type WebSocketRoute } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Uses the real client on a user-started host");

type Session = { id: string; title: string; selected_cli_type: string | null; effective_cli_type: string };

async function openWorkbench(page: Page, width: number, legacy = false, named: Session[] = []) {
  const bot = { alias: "main", cli_type: "codex", status: "running", working_dir: "/workspace", can_operate: true };
  const sessions: Session[] = [{ id: "main", title: "主会话", selected_cli_type: null, effective_cli_type: "codex" }, ...named];
  const running = new Set<string>();
  const sockets = new Set<WebSocketRoute>();
  let workerRunning = false;
  function setRunning(ids: string[], notify = true, worker = false) {
    running.clear();
    for (const id of ids) running.add(id);
    workerRunning = worker;
    if (notify) {
      for (const socket of sockets) socket.send(JSON.stringify({ type: "chat_sync", botAlias: "main", agentId: "main", reason: "turn_finished" }));
    }
  }
  const posts: Record<string, string>[] = [];
  const sends = new Map<string, Route>();
  const stops: string[] = [];
  const settingsRequests: string[] = [];
  const options = ["codex", "codex_server", "claude", "antigravity", "deepseek"]
    .map((cli_type) => ({ cli_type, available: cli_type !== "deepseek" }));
  await page.routeWebSocket("**/*", (socket) => {
    if (!socket.url().includes("/api/notifications/ws")) return socket.close();
    sockets.add(socket);
    socket.onClose(() => sockets.delete(socket));
    socket.onMessage((message) => {
      if (JSON.parse(String(message)).type === "hello") socket.send(JSON.stringify({ type: "hello", features: ["chat_sync"] }));
    });
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    const [, sessionId, operation] = /^bots\/main(?:\/sessions\/([^/]+))?(?:\/(.+))?$/.exec(path) ?? [];
    const rows = sessions.map((item) => ({ ...item, is_processing: running.has(item.id) }));
    const active = rows.filter((item) => item.is_processing);
    const agents = [...(active.length ? ["main"] : []), ...(workerRunning ? ["tester"] : [])];
    const summary = { ...bot, busy_agent_ids: agents, busy_agent_names: agents.map((id) => id === "main" ? "主 agent" : "验证员"),
      busy_agent_count: agents.length, activity_status: agents.length ? "busy" : "idle",
      ...(legacy ? {} : { busy_chat_sessions: active }) };
    let data: unknown = {};
    if (path === "auth/me") {
      data = { is_logged_in: true, username: "chat-qa", account_id: "chat-qa", role: "member",
        current_bot_alias: "main", capabilities: ["view_bots", "view_bot_status", "view_chat_history", "chat_send", "manage_bots"] };
    } else if (path === "bots" || path === "admin/bots") {
      data = [summary];
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
          : { enabled: true, items: rows, cli_options: options };
      }
    } else if (path === "bots/main" || (sessionId && !operation)) {
      data = { bot: summary, session: { working_dir: bot.working_dir, is_processing: running.has(sessionId ?? "main"),
        cli_type: sessions.find((item) => item.id === sessionId)?.effective_cli_type ?? bot.cli_type },
        agents: [{ id: "main", name: "main" }] };
    } else if (operation === "chat/stream") {
      sends.set(sessionId ?? "main", route);
      running.add(sessionId ?? "main");
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
  return { posts, sends, stops, settingsRequests, setRunning };
}

for (const width of [1440, 390]) {
  test(`identifies running default and named chats in open lists at ${width}px`, async ({ page }) => {
    const { setRunning } = await openWorkbench(page, width, false, [
      { id: "ses_a", title: "Implementation", selected_cli_type: "codex", effective_cli_type: "codex" },
      { id: "ses_b", title: "Review", selected_cli_type: "claude", effective_cli_type: "claude" },
    ]);
    const selector = page.getByRole("combobox", { name: "当前聊天会话" });
    await expect(selector.locator('option[value="ses_b"]')).toContainText("空闲");
    setRunning(["ses_b"], true, true);
    await expect(selector.locator('option[value="ses_b"]')).toContainText("处理中");
    await expect(selector.locator('option[value="main"]')).toContainText("空闲");
    const desktop = width > 700;
    await page.getByRole("button", { name: desktop ? "切换 Bot: main" : "main", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "智能体切换" });
    const row = dialog.getByRole("button", { name: /^main\b/ });
    await expect(row).toContainText("会话「Review」（claude）");
    await expect(row).toContainText("子 Agent「验证员」");
    await expect(row).not.toContainText("主会话（codex）");
    setRunning(["main", "ses_a"]);
    await expect(row).toContainText("主会话（codex）");
    await expect(row).toContainText("会话「Implementation」（codex）");
    await expect(row).not.toContainText("Review");
    await expect(row).not.toContainText("验证员");
    await page.screenshot({ path: test.info().outputPath(`running-sessions-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await dialog.getByRole("button", { name: "智能体管理", exact: true }).click();
    const managerRow = desktop ? page.getByRole("row").filter({ has: page.getByRole("button", { name: "聚焦 main" }) })
      : page.locator(".am-card").filter({ has: page.getByRole("heading", { name: "main", exact: true }) });
    await expect(managerRow).toContainText("会话「Implementation」（codex）");
    // Simulate a missed hint. The visible manager must still converge without reopening it.
    setRunning(["ses_b"], false);
    await expect(managerRow).toContainText("会话「Review」（claude）", { timeout: 19_000 });
    await expect(managerRow).not.toContainText("主会话（codex）");
  });

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
