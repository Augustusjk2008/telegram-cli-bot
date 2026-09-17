import { expect, test } from "@playwright/test";

test("聊天翻译配置、附件和原生最终回答适配桌面及移动布局", async ({ page }) => {
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:\\workspace", supported_execution_modes: ["cli", "native_agent"] };
  const translation = { status: "completed", target_language: "简体中文", source_digest: "qa-digest", text: "# 翻译后的最终回答\n\n" + "长段落用于检查移动端换行和切换后的布局。".repeat(30) + "\n\n```ts\nconst preserved = 'code';\n```" };
  const messages = [
    { id: "user-qa", turn_id: "turn-qa", role: "user", content: "Explain the attachment\n\n附件路径为：C:\\workspace\\source.txt", created_at: "2026-09-16T08:00:00Z", state: "done", translation: { ...translation, text: "请解释附件" } },
    { id: "assistant-qa", turn_id: "turn-qa", role: "assistant", content: "# Original final answer\n\nOriginal paragraph.", created_at: "2026-09-16T08:00:01Z", state: "done", translation, meta: { native_source: { provider: "native_agent", session_id: "qa" }, completion_state: "completed" } },
  ];
  // Only the existing service supplies the page and built assets; all API data is isolated here.
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = { is_logged_in: true, username: "translation-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["admin_ops", "chat_send", "view_chat_trace"] };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:\\workspace", is_processing: false, history_count: 2 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/history") data = { items: messages, revision: 1 };
    else if (path === "bots/main/history/delta") data = { items: [], revision: 1, reset: false };
    else if (path === "admin/users") data = [];
    else if (path === "admin/chat-translation/config") data = { translate_user_enabled: true, translate_assistant_enabled: true, base_url: "https://example.test/v1", api_key_set: true, model: "translator", user_prompt: "Translate into English.", assistant_prompt: "Translate into Simplified Chinese.", request_timeout_seconds: 15 };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const final = page.getByTestId("native-agent-final-result");
  await expect(final.getByRole("heading", { name: "翻译后的最终回答" })).toBeVisible();
  await expect(page.getByText("source.txt", { exact: true })).toBeVisible();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await final.getByRole("button", { name: "显示原文", exact: true }).click();
    await expect(final.getByRole("heading", { name: "Original final answer" })).toBeVisible();
    await final.getByRole("button", { name: "显示译文", exact: true }).click();
    await expect(final.getByRole("heading", { name: "翻译后的最终回答" })).toBeVisible();
    const user = page.locator('[data-message-id="user-qa"]');
    const userToggle = user.getByRole("button", { name: "显示原文", exact: true });
    const userCopy = user.getByRole("button", { name: "复制当前提问", exact: true });
    await userToggle.click();
    await expect(user.getByText("Explain the attachment", { exact: true })).toBeVisible();
    await user.getByRole("button", { name: "显示译文", exact: true }).click();
    await expect(user.getByText("请解释附件", { exact: true })).toBeVisible();
    expect(await userCopy.evaluate((button) => {
      const bubble = button.closest('[data-message-id]')!.querySelector('.chat-message-bubble-delight')!;
      return !bubble.contains(button) && button.getBoundingClientRect().top >= bubble.getBoundingClientRect().bottom;
    })).toBe(true);
    expect(await userToggle.evaluate((button) => button.textContent)).toBe("");
    expect(await userCopy.evaluate((button) => button.textContent)).toBe("");
    expect(await final.getByRole("button", { name: "显示原文", exact: true }).evaluate((button) => (
      button.parentElement!.querySelector('[aria-label="复制最终回答"]') !== null
    ))).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    const screenshotPath = test.info().outputPath(`chat-translation-${width}.png`);
    await page.screenshot({ path: screenshotPath });
    await test.info().attach(`chat-translation-${width}`, { path: screenshotPath, contentType: "image/png" });
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "切换 Bot: main", exact: true }).click();
  await page.getByRole("button", { name: "管理中心", exact: true }).click();
  await page.getByRole("tab", { name: "聊天翻译", exact: true }).click();
  const panel = page.getByRole("region", { name: "聊天翻译配置" });
  await expect(panel.getByLabel("用户消息翻译提示词")).toHaveValue("Translate into English.");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(panel.getByRole("button", { name: "保存聊天翻译配置" })).toBeVisible();
    expect(await panel.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return bounds.left >= 0 && bounds.right <= document.documentElement.clientWidth;
    })).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});
