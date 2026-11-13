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
async function readColumns(page: Page) {
  return page.getByTestId("chat-message-column-flow").evaluate((flow) => {
    const pager = flow.parentElement as HTMLElement;
    const frame = pager.getBoundingClientRect();
    const middle = frame.left + frame.width / 2;
    const left: number[] = [];
    const right: number[] = [];
    let cutLines = 0;
    for (const paragraph of flow.querySelectorAll("p")) {
      const number = Number(/段落(\d+)号/.exec(paragraph.textContent || "")?.[1]);
      if (!number) continue;
      for (const rect of paragraph.getClientRects()) {
        if (rect.right <= frame.left || rect.left >= frame.right) continue;
        if (rect.bottom > frame.bottom + 1 || rect.top < frame.top - 1) cutLines += 1;
        (rect.left < middle ? left : right).push(number);
      }
    }
    return { left, right, cutLines };
  });
}

test("split chat continues the left column at the top of the right column", async ({ page }) => {
  await openSplitChat(page);

  // It opens on the newest text: the final paragraph is in view.
  await expect.poll(async () => Math.max(...(await readColumns(page)).right, 0)).toBe(PARAGRAPH_COUNT);
  const newest = await readColumns(page);
  expect(newest.cutLines).toBe(0);
  expect(newest.left.length).toBeGreaterThan(0);
  // The right column starts where the left one stops (a paragraph may straddle the two).
  expect(Math.min(...newest.right) - Math.max(...newest.left)).toBeGreaterThanOrEqual(0);
  expect(Math.min(...newest.right) - Math.max(...newest.left)).toBeLessThanOrEqual(1);

  // One wheel notch moves back one column: the old left column becomes the right one.
  const scroller = page.getByTestId("chat-scroll-container");
  const box = await scroller.boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.wheel(0, -100);
  await expect.poll(async () => Math.min(...(await readColumns(page)).right)).toBe(Math.min(...newest.left));
  const earlier = await readColumns(page);
  expect(earlier.cutLines).toBe(0);
  expect(Math.max(...earlier.right)).toBe(Math.max(...newest.left));
  expect(Math.min(...earlier.right) - Math.max(...earlier.left)).toBeLessThanOrEqual(1);

  await page.mouse.wheel(0, 100);
  await expect.poll(async () => Math.max(...(await readColumns(page)).right)).toBe(PARAGRAPH_COUNT);
});
