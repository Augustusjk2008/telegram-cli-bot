import { expect, test } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started application");

test("terminal title bar only scrolls horizontally when tabs overflow", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const key = new URL(route.request().url()).pathname.split("/api/")[1];
    const bot = { alias: "layout", cli_type: "codex", status: "running", working_dir: "C:/layout" };
    let data: unknown = {};
    if (key === "auth/me") data = { is_logged_in: true, username: "layout", account_id: "layout", role: "member", current_bot_alias: "layout", capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "view_chat_history"] };
    else if (key === "bots") data = [bot];
    else if (key === "bots/layout") data = { bot, session: { working_dir: bot.working_dir }, agents: [{ id: "main", name: "main" }] };
    else if (key.endsWith("/ls")) data = { working_dir: bot.working_dir, entries: [] };
    else if (key.endsWith("/pwd")) data = { working_dir: bot.working_dir };
    else if (key === "ui/themes") data = { schemaVersion: 1, scope: "global", revision: 0, selectedThemeId: "paper-daylight", themes: [] };
    else if (key.endsWith("/history") || key.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (key.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (key.endsWith("/conversations") || key === "announcements" || key.endsWith("/favorites")) data = { items: [] };
    if (route.request().method() !== "GET") return route.fulfill({ status: 403, json: { ok: false, error: { message: "Layout fixture is read-only" } } });
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.addInitScript(() => {
    localStorage.setItem("web-view-mode", "desktop");
  });
  for (const width of [1600, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("./");
    for (const count of [1, 12]) {
      await page.evaluate((tabCount) => {
        localStorage.setItem("web-terminal-tabs:v1", JSON.stringify(Array.from({ length: tabCount }, (_, index) => ({
          id: `layout-${index}`, ownerId: `layout-${index}`, title: `终端 ${index + 1}`, cwd: "C:/layout", shell: "auto",
        }))));
      }, count);
      await page.reload();
      const tabs = page.getByRole("tablist", { name: "终端选项卡" });
      await expect(tabs.getByRole("tab")).toHaveCount(count);
      await expect(tabs).toHaveCSS("overflow-y", "hidden");
      const sizes = await tabs.evaluate((element) => ({
        height: element.clientHeight, contentHeight: element.scrollHeight,
        width: element.clientWidth, contentWidth: element.scrollWidth,
      }));
      expect(sizes.contentHeight).toBeLessThanOrEqual(sizes.height);
      if (count > 1) {
        expect(sizes.contentWidth).toBeGreaterThan(sizes.width);
        await tabs.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
        expect(await tabs.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      }
      await tabs.screenshot({ path: test.info().outputPath(`terminal-header-${width}-${count}.png`) });
    }
  }
  expect(errors).toEqual([]);
});
