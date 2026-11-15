import { expect, test, type Page } from "@playwright/test";

// Run against a user-started service with PLAYWRIGHT_BASE_URL set; without it Playwright would start a dev server.
test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

/** Same API mocking as workbench-layout.spec.ts: a local bot with an empty chat, sockets kept off the real host. */
async function openWorkbench(page: Page, viewport = { width: 1440, height: 900 }) {
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "tutorial-qa", account_id: "tutorial-qa", role: "member", current_bot_alias: "main",
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send", "terminal_exec"],
    };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:/workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/ls") data = { working_dir: "C:/workspace", entries: [{ name: "README.md", is_dir: false }] };
    else if (path === "bots/main/pwd") data = { working_dir: "C:/workspace" };
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path.endsWith("/terminal-actions/config")) data = { schemaVersion: 1, configPath: "", exists: false, mtimeNs: "", editable: false, errors: [], runtimePlatform: "linux", actions: [] };
    await route.fulfill({ json: { ok: true, data } });
  });
  // Keep the desktop workbench below the automatic 1280 px breakpoint too.
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  await page.setViewportSize(viewport);
  await page.goto("./");
  await expect(page.getByTestId("desktop-workbench-columns")).toBeVisible();
}

async function openGuide(page: Page) {
  await page.getByRole("button", { name: "使用教程", exact: true }).click();
  await page.getByRole("button", { name: "查看教程", exact: true }).click();
  const guide = page.getByTestId("tutorial-overlay");
  await expect(guide).toHaveAttribute("data-phase", "open");
  return guide;
}

const hasHorizontalOverflow = (page: Page) => page.evaluate(() => (
  [document.documentElement, ...document.querySelectorAll('[data-testid="tutorial-overlay"], [data-testid="tutorial-overlay"] *')]
    .some((element) => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX !== "hidden")
));

test("opens from the logo, takes over from the workbench and closes back into it", async ({ page }, testInfo) => {
  await openWorkbench(page);
  const workbench = page.getByTestId("desktop-workbench-root");
  const guide = await openGuide(page);

  expect(await guide.boundingBox()).toEqual({ x: 0, y: 0, width: 1440, height: 900 });
  await expect(guide).toHaveAttribute("data-motion", "full");
  await expect(guide.getByRole("listitem")).toHaveCount(11);
  await expect.poll(() => hasHorizontalOverflow(page)).toBe(false);
  await testInfo.attach("cover", { body: await page.screenshot(), contentType: "image/png" });

  // Screenshots are served under the host's path prefix, next to the app's other public assets.
  await guide.getByRole("button", { name: /^对话/ }).click();
  const image = guide.getByTestId("tutorial-stage-image");
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await expect(guide.getByTestId("tutorial-hotspot")).toBeVisible();
  // The active step's text is also drawn on the screenshot: inside the frame, beside the hotspot.
  const callout = guide.getByTestId("tutorial-callout");
  await expect(callout).toContainText("发送消息");
  await expect.poll(async () => {
    const box = await callout.boundingBox();
    const frame = await guide.locator(".tut-stage-frame").boundingBox();
    const hotspot = await guide.getByTestId("tutorial-hotspot").boundingBox();
    if (!box || !frame || !hotspot) return false;
    const inside = box.x >= frame.x - 1 && box.y >= frame.y - 1
      && box.x + box.width <= frame.x + frame.width + 1 && box.y + box.height <= frame.y + frame.height + 1;
    const intersects = box.x < hotspot.x + hotspot.width && hotspot.x < box.x + box.width
      && box.y < hotspot.y + hotspot.height && hotspot.y < box.y + box.height;
    return inside && !intersects;
  }).toBe(true);
  await expect.poll(() => hasHorizontalOverflow(page)).toBe(false);
  await testInfo.attach("reader", { body: await page.screenshot(), contentType: "image/png" });

  // The workbench underneath is out of reach: no focus, no clicks, no shortcuts.
  await expect(workbench).toHaveAttribute("inert", "");
  await page.keyboard.press("Control+P");
  await page.keyboard.press("ArrowRight");
  await expect(guide.getByRole("button", { name: "模型与附件" })).toHaveAttribute("aria-current", "step");
  await expect(callout).toContainText("模型与附件");
  await expect(page.getByRole("dialog", { name: "命令面板" })).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(guide).toHaveCount(0);
  await expect(workbench).not.toHaveAttribute("inert", "");
  await expect(page.getByRole("button", { name: "使用教程", exact: true })).toBeFocused();
  await page.keyboard.press("Control+P");
  await expect(page.getByRole("dialog", { name: "命令面板" })).toBeVisible();
});

test("loads the first screenshot of every chapter", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openWorkbench(page);
  const guide = await openGuide(page);
  await guide.getByRole("button", { name: "从头开始", exact: true }).click();
  const rail = guide.getByRole("navigation", { name: "教程章节" });
  const chapters = rail.getByRole("button");
  await expect(chapters).toHaveCount(11);
  const image = guide.getByTestId("tutorial-stage-image");
  for (let index = 0; index < 11; index += 1) {
    await expect(chapters.nth(index)).toBeEnabled();
    await chapters.nth(index).click();
    await expect(chapters.nth(index)).toHaveAttribute("aria-current", "true");
    await expect(image).toHaveAttribute("data-loaded", "true");
    expect(await image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBe(2880);
  }
});

test("opens and closes with a plain fade under reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openWorkbench(page);
  const guide = await openGuide(page);
  await expect(guide).toHaveAttribute("data-motion", "reduced");
  expect(await guide.locator(".tutorial-surface").evaluate((element) => element.getAnimations().length)).toBe(0);
  await page.keyboard.press("Escape");
  await expect(guide).toHaveCount(0);
  await expect(page.getByRole("button", { name: "使用教程", exact: true })).toBeFocused();
});

test("stacks the reader in a 1024 px wide window without horizontal overflow", async ({ page }, testInfo) => {
  await openWorkbench(page, { width: 1024, height: 768 });
  const guide = await openGuide(page);
  await expect.poll(() => hasHorizontalOverflow(page)).toBe(false);
  await guide.getByRole("button", { name: /^工作台布局/ }).click();
  const image = guide.getByTestId("tutorial-stage-image");
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await expect(guide.getByRole("navigation", { name: "教程章节" })).toBeHidden();
  // The step text sits directly under the screenshot here, so the on-screenshot callout is not shown.
  await expect(guide.getByTestId("tutorial-callout")).toBeHidden();
  // Polled: the reader slides in, so geometry is only meaningful once it has settled.
  await expect.poll(async () => {
    const stage = await guide.getByTestId("tutorial-stage").boundingBox();
    const steps = await guide.getByRole("region", { name: "工作台布局的步骤" }).boundingBox();
    return Boolean(stage && steps && stage.y + stage.height <= steps.y + 1);
  }).toBe(true);
  await expect.poll(() => hasHorizontalOverflow(page)).toBe(false);
  await testInfo.attach("reader-1024", { body: await page.screenshot(), contentType: "image/png" });
});
