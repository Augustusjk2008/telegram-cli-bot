import { expect, test, type Page } from "@playwright/test";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service serving the built frontend");

const PARAGRAPH_COUNT = 90;

async function openSplitChat(page: Page) {
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
  const answer = Array.from({ length: PARAGRAPH_COUNT }, (_, index) => (
    `段落${index + 1}号：这一段用来检查分栏后左栏底部与右栏顶部的内容是否连续，文字足够长，可以在一栏里折成两行以上，方便判断断点落在行与行之间。`
  )).join("\n\n");
  const items = [
    { id: "u1", turn_id: "t1", role: "user", content: "写一段很长的回答", created_at: "2026-11-13T02:00:00Z", state: "done" },
    { id: "a1", turn_id: "t1", role: "assistant", content: answer, created_at: "2026-11-13T02:00:30Z", state: "done" },
  ];
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, username: "split-qa", account_id: "split-qa", role: "member", current_bot_alias: "main",
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
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  // Positions are compared to the pixel, so the message entrance animation must not be running.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.goto("./");
  await expect(page.getByTestId("chat-message-row").first()).toBeVisible();
  for (const name of ["隐藏侧边栏", "隐藏编辑/预览区", "隐藏终端"]) {
    await page.getByRole("button", { name, exact: true }).click();
  }
  await page.getByRole("button", { name: "开启聊天分栏" }).click();
  await expect(page.getByTestId("chat-message-column-flow")).toBeVisible();
}

// Paragraph numbers whose text is on screen, per column, plus whether any line is cut off.
// Lines leaving through the top of the left column are ordinary scrolling, not a cut.
async function readColumns(page: Page) {
  return page.getByTestId("chat-message-column-flow").evaluate((flow) => {
    const pager = flow.parentElement as HTMLElement;
    const frame = pager.getBoundingClientRect();
    const middle = frame.left + frame.width / 2;
    const left: number[] = [];
    const right: number[] = [];
    const tops: Record<number, number> = {};
    let cutLines = 0;
    for (const paragraph of flow.querySelectorAll("p")) {
      const number = Number(/段落(\d+)号/.exec(paragraph.textContent || "")?.[1]);
      if (!number) continue;
      for (const rect of paragraph.getClientRects()) {
        if (rect.right <= frame.left || rect.left >= frame.right || rect.bottom <= frame.top) continue;
        const inRight = rect.left >= middle;
        if (rect.bottom > frame.bottom + 2 || (inRight && rect.top < frame.top - 2)) cutLines += 1;
        (inRight ? right : left).push(number);
        if (!inRight && rect.top >= frame.top) tops[number] ??= rect.top;
      }
    }
    return { left, right, tops, cutLines };
  });
}

function expectContinuous(columns: { left: number[]; right: number[]; cutLines: number }) {
  expect(columns.cutLines).toBe(0);
  expect(columns.left.length).toBeGreaterThan(0);
  // The right column starts where the left one stops (a paragraph may straddle the two).
  const seam = Math.min(...columns.right) - Math.max(...columns.left);
  expect(seam).toBeGreaterThanOrEqual(0);
  expect(seam).toBeLessThanOrEqual(1);
}

test("split chat continues the left column at the top of the right column", async ({ page }) => {
  await openSplitChat(page);
  const scroller = page.getByTestId("chat-scroll-container");

  // It opens on the newest text: the final paragraph is in view.
  await expect.poll(async () => Math.max(...(await readColumns(page)).right, 0)).toBe(PARAGRAPH_COUNT);
  const newest = await readColumns(page);
  expectContinuous(newest);

  // Scrolling is pixel-smooth: one wheel notch moves the left column by 100px, not by a column.
  const tracked = Number(Object.keys(newest.tops).sort((a, b) => Number(a) - Number(b))[2]);
  const box = await scroller.boundingBox();
  await page.mouse.move(box!.x + box!.width / 4, box!.y + box!.height / 2);
  await page.mouse.wheel(0, -100);
  await expect.poll(async () => Math.round((await readColumns(page)).tops[tracked] - newest.tops[tracked])).toBe(100);
  expectContinuous(await readColumns(page));

  // The whole transcript stays reachable with the columns continuous all the way to the start.
  const range = await scroller.evaluate((element) => element.scrollHeight - element.clientHeight);
  for (let top = range; top > 0; top -= 400) {
    await scroller.evaluate((element, value) => { element.scrollTop = value; }, top);
    expectContinuous(await readColumns(page));
  }
  await scroller.evaluate((element) => { element.scrollTop = 0; });
  await expect.poll(async () => Math.min(...(await readColumns(page)).left)).toBe(1);
  expectContinuous(await readColumns(page));
});
