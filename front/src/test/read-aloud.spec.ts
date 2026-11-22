import { expect, test, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

type SpeechLog = { spoken: string[]; pauses: number; resumes: number; cancellations: number };

async function openChat(page: Page, width: number) {
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
  const items = [
    { id: "u1", role: "user", content: "请读出回答", created_at: "2026-11-22T02:00:00Z", state: "done" },
    { id: "a1", role: "assistant", content: "**你好**，这是第一条回答。\n\n```js\nsecret_code()\n```", created_at: "2026-11-22T02:00:30Z", state: "done" },
    { id: "a2", role: "assistant", content: "这是第二条回答。", created_at: "2026-11-22T02:01:00Z", state: "done" },
  ];
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "speech-qa", account_id: "speech-qa", role: "member", current_bot_alias: "main",
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "view_chat_history", "chat_send"],
    };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = {
      bot, session: { working_dir: "C:/workspace", is_processing: false, history_count: items.length },
      agents: [{ id: "main", name: "main" }],
    };
    else if (path === "bots/main/ls") data = { working_dir: "C:/workspace", entries: [] };
    else if (path === "bots/main/pwd") data = { working_dir: "C:/workspace" };
    else if (path.endsWith("/history")) data = { items, revision: 1, reset: false };
    else if (path.endsWith("/history/delta")) data = { items: [], revision: 1, reset: false };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/terminal-actions/config")) data = {
      schemaVersion: 1, configPath: "", exists: false, mtimeNs: "", editable: false, errors: [], runtimePlatform: "windows", actions: [],
    };
    await route.fulfill({ json: { ok: true, data } });
  });
  // Native speech needs OS voices and an audio device. Exercise UI/queue behavior
  // deterministically here; this does not claim to verify audible voice quality.
  await page.addInitScript((mobile) => {
    localStorage.setItem("web-view-mode", mobile ? "mobile" : "desktop");
    const log: SpeechLog = { spoken: [], pauses: 0, resumes: 0, cancellations: 0 };
    Object.assign(window, { __speechLog: log });
    Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
      paused: false,
      getVoices: () => [],
      speak: (utterance: SpeechSynthesisUtterance) => {
        log.spoken.push(utterance.text);
        utterance.dispatchEvent(new Event("start"));
      },
      pause: () => { log.pauses += 1; },
      resume: () => { log.resumes += 1; },
      cancel: () => { log.cancellations += 1; },
    } });
  }, width < 1000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width, height: 900 });
  await page.goto("./");
}

for (const width of [1440, 390]) {
  test(`reads answers with usable controls at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await openChat(page, width);
    const first = page.getByTestId("chat-message-row").filter({ hasText: "这是第一条回答" });
    const second = page.getByTestId("chat-message-row").filter({ hasText: "这是第二条回答" });
    await first.getByRole("button", { name: "朗读回答", exact: true }).click();
    await first.getByRole("button", { name: "暂停朗读", exact: true }).click();
    await first.getByRole("button", { name: "继续朗读", exact: true }).click();
    await second.getByRole("button", { name: "朗读回答", exact: true }).click();
    await expect(first.getByRole("button", { name: "朗读回答", exact: true })).toBeVisible();
    await expect(second.getByRole("button", { name: "暂停朗读", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`read-aloud-${width}.png`) });
    await second.getByRole("button", { name: "停止朗读", exact: true }).click();
    const log = await page.evaluate(() => (window as unknown as { __speechLog: SpeechLog }).__speechLog);
    expect(log).toEqual({ spoken: ["你好，这是第一条回答。", "这是第二条回答。"], pauses: 1, resumes: 1, cancellations: 2 });
    expect(errors).toEqual([]);
  });
}
