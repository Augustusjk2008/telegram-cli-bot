import { expect, test, type Page } from "@playwright/test";

// Run against a user-started service with PLAYWRIGHT_BASE_URL set; without it Playwright would start a dev server.
test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

const PANES = {
  sidebar: "desktop-pane-files",
  editor: "desktop-pane-editor",
  terminal: "desktop-pane-terminal",
  chat: "desktop-pane-chat",
} as const;

type Box = { x: number; y: number; width: number; height: number };
type PaneBoxes = Record<keyof typeof PANES | "grid", Box>;

async function openWorkbench(page: Page, viewport = { width: 1440, height: 900 }) {
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
  // Keep the terminal and notification sockets away from the real host.
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "layout-qa", account_id: "layout-qa", role: "member", current_bot_alias: "main",
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
    else if (path.endsWith("/terminal-actions/config")) data = { actions: [] };
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize(viewport);
  await page.goto("./");
  await expect(page.getByTestId("desktop-workbench-columns")).toBeVisible();
}

async function paneBoxes(page: Page): Promise<PaneBoxes> {
  const entries = await Promise.all(
    [...Object.entries(PANES), ["grid", "desktop-workbench-columns"]].map(async ([key, testId]) => {
      const box = await page.getByTestId(testId).boundingBox();
      return [key, box ?? { x: 0, y: 0, width: 0, height: 0 }] as const;
    }),
  );
  return Object.fromEntries(entries) as PaneBoxes;
}

/** Grid tracks animate, so geometry is polled until it settles into the expected relation. */
async function expectLayout(page: Page, predicate: (boxes: PaneBoxes) => boolean) {
  await expect.poll(async () => predicate(await paneBoxes(page)), { timeout: 5000 }).toBe(true);
}

async function chooseLayoutMenuItem(page: Page, name: string) {
  await page.getByRole("button", { name: "窗口布局", exact: true }).click();
  await page.getByRole("dialog", { name: "窗口布局" }).getByRole("button", { name, exact: true }).click();
}

const leftOf = (a: Box, b: Box) => a.x + a.width <= b.x + 1;
const above = (a: Box, b: Box) => a.y + a.height <= b.y + 1;

test("presets, drag-to-swap and reset persist in the browser", async ({ page }) => {
  await openWorkbench(page);
  const grid = page.getByTestId("desktop-workbench-columns");

  await expectLayout(page, ({ sidebar, editor, terminal, chat }) => leftOf(sidebar, editor) && above(editor, terminal) && leftOf(editor, chat));

  await chooseLayoutMenuItem(page, "底部通栏");
  await expect(grid).toHaveAttribute("data-layout-template", "bottomPanel");
  await expectLayout(page, ({ grid: gridBox, editor, terminal, chat }) => (
    terminal.width >= gridBox.width - 24 && above(editor, terminal) && above(chat, terminal)
  ));

  await chooseLayoutMenuItem(page, "调整窗口位置…");
  const chatOverlay = page.getByTestId("workbench-layout-slot-chat");
  const sidebarOverlay = page.getByTestId("workbench-layout-slot-sidebar");
  const from = (await chatOverlay.boundingBox())!;
  const to = (await sidebarOverlay.boundingBox())!;
  // Grab near a corner: the swap buttons sit in the middle of each overlay.
  await page.mouse.move(from.x + 24, from.y + from.height - 24);
  await page.mouse.down();
  await page.mouse.move(to.x + to.width / 2, to.y + to.height - 24, { steps: 12 });
  await expect(sidebarOverlay).toHaveAttribute("data-drop-target", "true");
  await page.mouse.up();
  await expect(page.getByTestId(PANES.chat)).toHaveAttribute("data-layout-slot", "left");
  await page.getByRole("toolbar", { name: "窗口布局编辑" }).getByRole("button", { name: "完成", exact: true }).click();
  await expect(sidebarOverlay).toHaveCount(0);
  await expectLayout(page, ({ sidebar, chat }) => leftOf(chat, sidebar));
  await page.screenshot({ path: test.info().outputPath("workbench-bottom-panel-swapped.png") });

  await page.reload();
  await expect(grid).toHaveAttribute("data-layout-template", "bottomPanel");
  await expectLayout(page, ({ sidebar, chat, terminal }) => leftOf(chat, sidebar) && above(sidebar, terminal));

  await chooseLayoutMenuItem(page, "恢复默认（当前布局）");
  await expect(page.getByTestId(PANES.sidebar)).toHaveAttribute("data-layout-slot", "left");
  await expectLayout(page, ({ sidebar, editor, chat }) => leftOf(sidebar, editor) && leftOf(editor, chat));
});

test("the bottom panel divider resizes the terminal and the height survives a reload", async ({ page }) => {
  await openWorkbench(page);
  await chooseLayoutMenuItem(page, "底部通栏");
  await expect(page.getByTestId("desktop-workbench-columns")).toHaveAttribute("data-layout-template", "bottomPanel");
  await expectLayout(page, ({ terminal }) => Math.abs(terminal.height - 280) <= 2);

  const divider = page.getByRole("separator", { name: "调整终端高度", exact: true });
  const handle = (await divider.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2 - 100, { steps: 10 });
  await page.mouse.up();
  await expectLayout(page, ({ terminal }) => Math.abs(terminal.height - 380) <= 2);

  await page.reload();
  await expect(page.getByTestId("desktop-workbench-columns")).toHaveAttribute("data-layout-template", "bottomPanel");
  await expectLayout(page, ({ terminal }) => Math.abs(terminal.height - 380) <= 2);
});

for (const viewport of [{ width: 1280, height: 800 }, { width: 1920, height: 1080 }]) {
  test(`four columns fit side by side at ${viewport.width}px`, async ({ page }) => {
    await openWorkbench(page, viewport);
    await chooseLayoutMenuItem(page, "四列并排");
    const grid = page.getByTestId("desktop-workbench-columns");
    await expect(grid).toHaveAttribute("data-layout-template", "columns");

    for (const testId of Object.values(PANES)) {
      await expect(page.getByTestId(testId)).toBeVisible();
    }
    await expectLayout(page, ({ grid: gridBox, sidebar, editor, terminal, chat }) => (
      leftOf(sidebar, editor) && leftOf(editor, terminal) && leftOf(terminal, chat)
      && chat.x + chat.width <= gridBox.x + gridBox.width + 1
    ));
    expect(await grid.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const screenshotPath = test.info().outputPath(`workbench-columns-${viewport.width}.png`);
    await page.screenshot({ path: screenshotPath });
    await test.info().attach(`workbench-columns-${viewport.width}`, { path: screenshotPath, contentType: "image/png" });
  });
}
