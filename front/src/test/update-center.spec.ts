import { expect, test } from "@playwright/test";

for (const width of [1280, 390]) {
  test(`升级确认、断线恢复与任务刷新 ${width}px`, async ({ page }) => {
    test.skip(!process.env.PLAYWRIGHT_BASE_URL, "仅复用用户已启动的实例");
    const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace" };
    const launcher = { supported: true, protocol: 1, command: "start.bat", reason: "" };
    const status = {
      current_version: "1.0.0", current_package_kind: "installer", update_enabled: true, revision: 5,
      last_available_version: "2.0.0", update_available: true, pending_update_notes: "升级恢复能力验证", launcher,
      last_check: { ok: true, cached: false, error: "", checked_at: "2026-10-24T12:00:00Z" },
      job: { job_id: "browser-update", revision: 5, phase: "ready", current_version: "1.0.0", target_version: "2.0.0",
        package_kind: "installer", error: "", progress: { percent: 100, message: "准备完成" }, launcher },
    };
    let disconnected = false;
    const mutations: string[] = [];
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.routeWebSocket("**/*", (socket) => socket.close());
    // Every API request is intercepted, including apply and ordinary restart.
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.split("/api/")[1];
      if (request.method() !== "GET") mutations.push(path);
      if (path === "admin/update/jobs/browser-update/apply") {
        expect(request.postDataJSON()).toEqual({ revision: 5 });
        status.job.phase = "waiting_restart";
        status.revision = status.job.revision = 6;
        disconnected = true;
        await route.abort("connectionreset");
        return;
      }
      if (path === "admin/update/jobs/current" && disconnected) {
        await route.abort("connectionrefused");
        return;
      }
      let data: unknown = {};
      if (path === "auth/me") data = { is_logged_in: true, username: "update-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["admin_ops", "chat_send"] };
      else if (path === "bots") data = [bot];
      else if (path === "bots/main") data = { bot, session: { working_dir: "C:/workspace", is_processing: false }, agents: [{ id: "main", name: "main" }] };
      else if (path === "admin/users") data = [];
      else if (path === "admin/update" || path === "admin/update/jobs/current") data = status;
      else if (path === "admin/update/offline/packages") data = { artifacts_dir: "C:/packages", items: [] };
      else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1, reset: false };
      else if (path.endsWith("/ls")) data = { working_dir: "C:/workspace", entries: [] };
      else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
      else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
      else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
      await route.fulfill({ json: { ok: true, data } });
    });

    async function openUpdates() {
      await page.getByRole("button", { name: width < 768 ? "main" : "切换 Bot: main", exact: true }).click();
      await page.getByRole("button", { name: "管理中心", exact: true }).click();
      await page.getByRole("tab", { name: "升级", exact: true }).click();
    }
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await openUpdates();
    const panel = page.getByRole("region", { name: "升级", exact: true });
    await expect(panel.getByRole("button", { name: "应用更新", exact: true })).toBeEnabled();
    await expect(panel.getByLabel("宿主机器上的离线包路径")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.reload();
    await openUpdates();
    await expect(panel.getByTestId("update-job")).toContainText("browser-update");
    expect(mutations).toEqual([]);
    await panel.getByRole("button", { name: "应用更新", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "确认应用更新" });
    await expect(dialog).toContainText("服务将暂时断开");
    const screenshot = test.info().outputPath(`update-confirm-${width}.png`);
    await page.screenshot({ path: screenshot });
    await test.info().attach(`update-confirm-${width}`, { path: screenshot, contentType: "image/png" });
    await dialog.getByRole("button", { name: "确认应用并重启服务" }).click();
    await expect(panel.getByText(/正在确认后台状态/)).toBeVisible();
    await expect(panel.getByTestId("update-job")).not.toContainText("升级成功");
    disconnected = false;
    status.job.phase = "awaiting_health";
    status.revision = status.job.revision = 7;
    await expect(panel.getByTestId("update-job")).toContainText("等待新版本健康确认");
    status.job.phase = "succeeded";
    status.revision = status.job.revision = 8;
    await expect(panel.getByTestId("update-job")).toContainText("正在核对运行版本");
    status.current_version = "2.0.0";
    await expect(panel.getByTestId("update-job")).toContainText("升级成功");
    expect(mutations).toEqual(["admin/update/jobs/browser-update/apply"]);
    expect(pageErrors).toEqual([]);
  });
}
