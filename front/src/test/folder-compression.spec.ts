import { expect, test } from "@playwright/test";

// Reuse a user-started host serving the built frontend.
test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started service");

for (const width of [1440, 390]) {
  test(`folder compression refreshes the directory through the menu at ${width}px`, async ({ page }) => {
    const folder = "资料.v1";
    const root = "C:/workspace";
    const bot = { alias: "main", cli_type: "codex", status: "running", working_dir: root };
    const requests: unknown[] = [];
    const errors: string[] = [];
    const dialogs: string[] = [];
    let archiveExists = false;
    let failCompression = false;
    let releaseCompression!: () => void;
    const pendingCompression = new Promise<void>((resolve) => { releaseCompression = resolve; });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("dialog", (dialog) => { dialogs.push(dialog.message()); void dialog.dismiss(); });
    await page.routeWebSocket("**/*", (socket) => socket.close());
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.split("/api/")[1];
      let data: unknown = {};
      if (path === "auth/me") data = {
        is_logged_in: true, username: "compression-qa", account_id: "compression-qa", role: "member", current_bot_alias: "main",
        capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send"],
      };
      else if (path === "bots") data = [bot];
      else if (path === "bots/main") data = { bot, session: { working_dir: root, is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
      else if (path === "bots/main/ls") data = {
        working_dir: root,
        entries: [
          { name: folder, is_dir: true }, { name: "README.md", is_dir: false },
          ...(archiveExists ? [{ name: `${folder}.zip`, is_dir: false, size: 128 }] : []),
        ],
      };
      else if (path === "bots/main/pwd") data = { working_dir: root };
      else if (path === "bots/main/files/compress") {
        expect(request.method()).toBe("POST");
        requests.push(request.postDataJSON());
        if (requests.length === 1) await pendingCompression;
        if (failCompression) {
          await route.fulfill({ status: 500, json: { ok: false, error: { code: "compress_directory_failed", message: "压缩文件夹失败" } } });
          return;
        }
        archiveExists = true;
        data = { source_path: folder, path: `${folder}.zip`, file_size_bytes: 128, last_modified_ns: "1780000000000000001" };
      }
      else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
      else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
      else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
      else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
      else if (path.endsWith("/terminal-actions/config")) data = { schemaVersion: 1, actions: [], configPath: "", exists: false, mtimeNs: "", editable: false, errors: [], runtimePlatform: "windows" };
      await route.fulfill({ json: { ok: true, data } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("./");
    if (width === 390) await page.getByRole("button", { name: "文件", exact: true }).click();
    const openMenu = async (name: string, isDir: boolean) => {
      if (width === 390) {
        await page.getByRole("button", { name: `更多操作 ${name}`, exact: true }).click();
      } else {
        await page.getByRole("button", { name: `${isDir ? "展开" : "打开"} ${name}`, exact: true }).click({ button: "right" });
      }
      return page.getByRole("menu");
    };
    const compressButton = () => width === 390
      ? page.getByRole("menuitem", { name: `压缩 ${folder}`, exact: true })
      : page.getByRole("button", { name: "压缩", exact: true });

    const fileMenu = await openMenu("README.md", false);
    await expect(fileMenu.getByText("压缩", { exact: true })).toHaveCount(0);
    await page.keyboard.press("Escape");
    const folderMenu = await openMenu(folder, true);
    await expect(compressButton()).toBeVisible();
    const bounds = (await folderMenu.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(900);
    await page.screenshot({ path: test.info().outputPath(`folder-menu-${width}.png`) });
    await compressButton().click();
    await expect.poll(() => requests.length).toBe(1);
    await expect(page.getByRole("status").filter({ hasText: `正在压缩 ${folder}` })).toBeVisible();
    await openMenu(folder, true);
    await expect(compressButton()).toBeDisabled();
    await page.keyboard.press("Escape");
    releaseCompression();
    await expect(page.getByRole("button", { name: `打开 ${folder}.zip`, exact: true })).toBeVisible();

    await openMenu(folder, true);
    await expect(compressButton()).toBeEnabled();
    await compressButton().click();
    await expect.poll(() => requests.length).toBe(2);
    await expect(page.getByText(`正在压缩 ${folder}…`, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `打开 ${folder}.zip`, exact: true })).toHaveCount(1);

    failCompression = true;
    await openMenu(folder, true);
    await compressButton().click();
    await expect(page.getByText("压缩文件夹失败", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: `打开 ${folder}.zip`, exact: true })).toBeVisible();
    expect(requests).toEqual([{ path: folder }, { path: folder }, { path: folder }]);
    expect(dialogs).toEqual([]);
    expect(errors).toEqual([]);
  });
}
