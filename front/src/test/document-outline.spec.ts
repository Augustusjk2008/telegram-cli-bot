import { expect, test, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Uses a user-started host serving the built frontend");

const filename = "report.docx";
const incompatible = "damaged.doc";
const incompatibilityMessage = "无法预览此 DOC 文件，格式不兼容或文件已损坏。请将文件另存为 .docx 后重试";
const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "/workspace", can_operate: true };
const sections = ["Overview", "Measurements", "Conclusions"].map((title, i) => ({
  id: `section-${i + 1}`, title, headingLevel: i === 1 ? 2 : 1,
}));

function sectionWindow(id: string) {
  const section = sections.find((row) => row.id === id)!;
  return { sectionId: id, blocks: [
    { type: "heading", level: section.headingLevel, runs: [{ text: section.title }] },
    ...Array.from({ length: id === sections[0].id ? 70 : 2 }, (_, i) => ({
      type: "paragraph", runs: [{ text: `${section.title} paragraph ${i + 1}` }],
    })),
  ] };
}

async function openWord(page: Page, width: number, loadSections: Promise<void>, initialFile = filename) {
  const target = { kind: "plugin_view", pluginId: "docx-preview", viewId: "document" };
  const agents = [{ id: "main", name: "main" }];
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = { is_logged_in: true, username: "word-qa", account_id: "word-qa", role: "member",
      current_bot_alias: "main", capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "view_plugins", "run_plugins"] };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, agents, session: { working_dir: bot.working_dir, is_processing: false } };
    else if (path.endsWith("/pwd")) data = { working_dir: bot.working_dir };
    else if (path.endsWith("/ls")) data = { working_dir: bot.working_dir, entries: [filename, incompatible].map((name) => ({ name, is_dir: false })) };
    else if (path.endsWith("/agents")) data = { items: agents, active_agent_id: "main" };
    else if (path.endsWith("/plugins/resolve-file-target")) {
      const file = route.request().postDataJSON().path;
      data = { ...target, title: file.split("/").pop(), input: { path: file } };
    } else if (path.endsWith("/views/document/open")) {
      if (route.request().postDataJSON().input.path.endsWith(incompatible)) {
        return route.fulfill({ status: 500, json: { ok: false, error: { code: "plugin_open_failed", message: incompatibilityMessage } } });
      }
      data = {
        pluginId: target.pluginId, viewId: target.viewId, renderer: "document", mode: "session", sessionId: "word-1",
        summary: { title: filename, path: filename, formatting: "document", sections }, initialWindow: sectionWindow(sections[0].id),
      };
    } else if (path.endsWith("/sessions/word-1/window")) {
      await loadSections;
      data = sectionWindow(route.request().postDataJSON().sectionId);
    } else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0 };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width, height: 900 });
  await page.goto("./");
  if (width < 500) await page.getByRole("navigation", { name: "主导航" }).getByRole("button", { name: "文件", exact: true }).click();
  await page.getByRole("button", { name: `打开 ${initialFile}`, exact: true }).click();
}

for (const width of [1366, 390]) {
  test(`an incompatible DOC reports its error and the next file opens at ${width}px`, async ({ page }) => {
    await openWord(page, width, Promise.resolve(), incompatible);
    await expect(page.getByText(incompatibilityMessage, { exact: true }).first()).toBeVisible();
    await expect(page.getByText("正在加载插件视图", { exact: true })).toHaveCount(0);
    if (width === 390) await page.getByTestId("mobile-file-preview").getByRole("button", { name: "返回", exact: true }).click();
    await page.getByRole("button", { name: `打开 ${filename}`, exact: true }).click();
    await expect(page.getByTestId("document-view").getByRole("heading", { name: "Overview" })).toBeVisible();
  });

  test(`Word outline navigates loaded and pending sections at ${width}px`, async ({ page }) => {
    let finishLoading!: () => void;
    await openWord(page, width, new Promise<void>((resolve) => { finishLoading = resolve; }));
    const reader = page.getByTestId("document-view");
    const nav = page.getByRole("navigation", { name: "文档章节" });
    const toggle = page.getByRole("button", { name: "目录", exact: true });
    const narrow = width === 390;
    if (narrow) {
      await expect(nav).toBeHidden();
      await toggle.click();
    } else {
      await expect(nav).toBeVisible();
      const bounds = (await nav.boundingBox())!;
      expect(bounds.x + bounds.width).toBeLessThanOrEqual((await reader.boundingBox())!.x + 1);
    }
    const first = nav.getByRole("button", { name: "Overview" });
    const second = nav.getByRole("button", { name: "Measurements" });
    await expect(first).toHaveAttribute("aria-current", "location");
    expect((await second.boundingBox())!.y).toBeGreaterThan((await first.boundingBox())!.y);
    await second.click();
    finishLoading();
    await expect(reader.getByRole("heading", { name: "Measurements" })).toBeInViewport();
    if (narrow) {
      await expect(nav).toBeHidden();
      await expect(toggle).toBeFocused();
      await toggle.click();
    }
    await expect(second).toHaveAttribute("aria-current", "location");
    if (narrow) await page.keyboard.press("Escape");
    await reader.evaluate((element) => element.scrollTo({ top: 0 }));
    if (narrow) await toggle.click();
    await expect(first).toHaveAttribute("aria-current", "location");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
