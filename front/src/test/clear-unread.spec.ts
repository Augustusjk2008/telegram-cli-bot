import { expect, test, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

async function openUnreadWorkbench(page: Page, width: number, {
  failAnnouncement = false,
  botUnread = true,
  announcementUnread = true,
} = {}) {
  const accountId = "unread-qa";
  let terminalAt = "2026-08-27T01:10:00Z";
  let announcementSeen = !announcementUnread;
  let lanReadSeq = 0;
  const bot = (alias: string) => ({
    alias, name: alias, cli_type: "codex", status: "running", working_dir: "C:/workspace",
    last_answer_terminal_at: terminalAt,
  });
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: accountId, account_id: accountId, role: "member", current_bot_alias: "main",
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "view_chat_history", "chat_send"],
    };
    else if (path === "bots") data = [bot("main"), bot("worker")];
    else if (path === "bots/main") data = {
      bot: bot("main"), session: { working_dir: "C:/workspace", is_processing: false, history_count: 0 },
      agents: [{ id: "main", name: "main" }],
    };
    else if (path === "bots/main/ls") data = { working_dir: "C:/workspace", entries: [] };
    else if (path === "bots/main/pwd") data = { working_dir: "C:/workspace" };
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path === "announcements/seen") {
      if (path.endsWith("/seen")) {
        if (failAnnouncement) {
          await route.fulfill({ status: 503, json: { ok: false, error: { message: "offline" } } });
          return;
        }
        expect(route.request().postDataJSON()).toEqual({ latest_id: "notice-1" });
        announcementSeen = true;
      }
      data = { items: [], latest_id: "notice-1", last_seen_id: announcementSeen ? "notice-1" : "", has_unseen: !announcementSeen };
    }
    else if (path === "lan-chat/conversations") data = { items: [{
      id: "group:default", kind: "group", title: "工作室", participant_ids: [], unread_count: lanReadSeq < 7 ? 3 : 0,
      last_message: { id: "lan-7", seq: 7, conversation_id: "group:default", kind: "group", text: "消息", sender: {} },
    }] };
    else if (path === "lan-chat/conversations/group%3Adefault/read") {
      lanReadSeq = route.request().postDataJSON().seq;
    }
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/favorites")) data = { items: [] };
    else if (path.endsWith("/terminal-actions/config")) data = {
      schemaVersion: 1, configPath: "", exists: false, mtimeNs: "", editable: false, errors: [], runtimePlatform: "windows", actions: [],
    };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width, height: 900 });
  await page.goto("./");
  await expect(page.getByRole("button", { name: "清除全部未读", exact: true })).toBeVisible();
  if (botUnread) await page.evaluate(({ accountId, terminalAt }) => {
    const prefix = `tcb-chat-unread-watermark:v2:${accountId}:`;
    localStorage.setItem(`${prefix}initialized`, "1");
    for (const alias of ["main", "worker"]) {
      localStorage.setItem(`${prefix}read:${alias}:${encodeURIComponent("2026-08-27T01:00:00Z")}`, "1");
      localStorage.removeItem(`${prefix}read:${alias}:${encodeURIComponent(terminalAt)}`);
    }
    localStorage.setItem(`${prefix}pending:worker:unread`, "1");
  }, { accountId, terminalAt });
  await page.reload();
  await expect(page.getByRole("button", { name: "公告", exact: true })).toBeVisible();
  await expect(page.getByTestId("bot-switcher-unread-indicator")).toHaveCount(botUnread ? 1 : 0);
  await expect(page.getByTestId("announcement-unseen-dot")).toHaveCount(announcementUnread ? 1 : 0);
  return {
    readSeq: () => lanReadSeq,
    nextCompletion: () => { terminalAt = "2026-08-27T01:20:00Z"; },
    recoverAnnouncements: () => { failAnnouncement = false; },
  };
}

for (const width of [1440, 390]) {
  test(`clears all unread and preserves later notifications at ${width}px`, async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const state = await openUnreadWorkbench(page, width);
    const clear = page.getByRole("button", { name: "清除全部未读", exact: true });
    if (width > 1000) await expect(page.getByRole("button", { name: "成员聊天，3 条未读" })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`unread-before-${width}.png`) });
    await clear.click();
    await expect(clear).toHaveCount(0);
    await expect(page.getByTestId("bot-switcher-unread-indicator")).toHaveCount(0);
    await expect(page.getByTestId("announcement-unseen-dot")).toHaveCount(0);
    await expect.poll(state.readSeq).toBe(7);
    if (width > 1000) await expect(page.getByRole("button", { name: "成员聊天", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`unread-cleared-${width}.png`) });

    await page.reload();
    await expect(page.getByRole("button", { name: "公告", exact: true })).toBeVisible();
    await expect(clear).toHaveCount(0);
    await expect(page.getByTestId("bot-switcher-unread-indicator")).toHaveCount(0);
    await expect(page.getByTestId("announcement-unseen-dot")).toHaveCount(0);
    state.nextCompletion();
    await page.reload();
    await expect(page.getByTestId("bot-switcher-unread-indicator")).toBeVisible();
    await expect(clear).toBeVisible();
    expect(pageErrors).toEqual([]);
  });
}

test("failed remote reads remain visible and can be retried", async ({ page }) => {
  const state = await openUnreadWorkbench(page, 390, { failAnnouncement: true });
  const clear = page.getByRole("button", { name: "清除全部未读", exact: true });
  await clear.click();
  await expect(page.getByRole("alert")).toHaveText("部分未读未能清除，请重试");
  await expect(page.getByTestId("announcement-unseen-dot")).toBeVisible();
  await expect(page.getByTestId("bot-switcher-unread-indicator")).toHaveCount(0);
  expect(state.readSeq()).toBe(7);
  state.recoverAnnouncements();
  await clear.click();
  await expect(clear).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByTestId("announcement-unseen-dot")).toHaveCount(0);
});

test("member chat unread alone shows the desktop clear action", async ({ page }) => {
  const state = await openUnreadWorkbench(page, 1440, { botUnread: false, announcementUnread: false });
  const clear = page.getByRole("button", { name: "清除全部未读", exact: true });
  await expect(page.getByRole("button", { name: "成员聊天，3 条未读" })).toBeVisible();
  await expect(clear).toBeVisible();
  await clear.click();
  await expect(page.getByRole("button", { name: "成员聊天", exact: true })).toBeVisible();
  await expect(clear).toHaveCount(0);
  expect(state.readSeq()).toBe(7);
});
