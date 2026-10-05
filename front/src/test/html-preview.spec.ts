import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

// The application assets come from a user-started service. Python produces the
// actual preview bodies and security headers without opening a listening socket.
test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started application");

type Resource = { status: number; headers: Record<string, string>; body: string };
type Fixture = {
  session: { session_id: string; entry_url: string; entry_path: string; expires_at: string };
  resources: Record<string, Resource>;
  refreshed: Resource;
};

for (const prefix of ["", "/node/html-preview-qa"]) {
  for (const width of [1440, 390]) {
    test(`local HTML interaction and sandbox at ${prefix || "/"}, ${width}px`, async ({ page, baseURL }) => {
      test.setTimeout(60_000);
      const serviceUrl = new URL(baseURL!);
      const origin = serviceUrl.origin;
      const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:/workspace", supported_execution_modes: ["cli"] };
      const entries = [{ name: "index.html", is_dir: false, size: 1024 }];
      let fixture: Fixture | undefined;
      let changed = false;
      let attempts = 0;
      let closed = 0;
      const resourceRequests: { path: string; origin?: string; authorization?: string; referer?: string }[] = [];
      const fileReads: string[] = [];
      const previewManagementRequests: string[] = [];
      await page.setViewportSize({ width, height: 960 });
      await page.addInitScript((desktop) => {
        if (window === window.top) localStorage.setItem("web-view-mode", desktop ? "desktop" : "mobile");
      }, width > 600);
      await page.route((url) => url.origin === origin && url.pathname === `${prefix}/`, async (route) => {
        const response = await route.fetch({ url: serviceUrl.href });
        const html = (await response.text()).replace(
          /window\.__TCB_PUBLIC_ENV__\s*=\s*\{[^;]*\};/,
          `window.__TCB_PUBLIC_ENV__=${JSON.stringify({ WEB_BASE_PATH: prefix, VITE_BASE_PATH: prefix, VITE_API_BASE_URL: prefix })};`,
        );
        await route.fulfill({ response, body: html });
      });
      if (prefix) await page.route(`${origin}${prefix}/assets/**`, async (route) => {
        const url = new URL(route.request().url());
        url.pathname = url.pathname.slice(prefix.length);
        await route.fulfill({ response: await route.fetch({ url: url.href }) });
      });
      await page.route("**/api/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname.split("/api/")[1];
        if (path.startsWith("file-previews/")) {
          const key = decodeURIComponent(path.split("/").slice(2).join("/"));
          const headers = request.headers();
          resourceRequests.push({ path: key, origin: headers.origin, authorization: headers.authorization, referer: headers.referer });
          const resource = changed && key === "pages/details.html" ? fixture?.refreshed : fixture?.resources[key];
          expect(resource, `Python fixture contains ${key}`).toBeDefined();
          await route.fulfill({ status: resource!.status, headers: resource!.headers, body: Buffer.from(resource!.body, "base64") });
          return;
        }
        if (request.headers().origin === "null") previewManagementRequests.push(path);
        let data: unknown = {};
        if (path === "auth/me") data = { is_logged_in: true, username: "preview-qa", account_id: "preview-qa", role: "admin", current_bot_alias: "main", capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "view_chat_history", "chat_send"] };
        else if (path === "bots") data = [bot];
        else if (path === "bots/main") data = { bot, session: { working_dir: bot.working_dir, is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
        else if (path === "bots/main/ls") data = { working_dir: bot.working_dir, entries };
        else if (path === "bots/main/pwd") data = { working_dir: bot.working_dir };
        else if (path === "bots/main/files/reveal") data = { root_path: bot.working_dir, highlight_path: "index.html", branches: { "": entries } };
        else if (path === "bots/main/plugins/resolve-file-target") data = { kind: "file" };
        else if (path === "bots/main/files/read") {
          fileReads.push(path);
          data = { content: "", mode: "head", is_full_content: true };
        } else if (path === "bots/main/files/html-preview") {
          attempts += 1;
          if (attempts === 1) {
            await route.fulfill({ status: 503, json: { ok: false, error: { code: "preview_unavailable", message: "预览暂时不可用" } } });
            return;
          }
          fixture = JSON.parse(execFileSync(process.env.PYTHON || "python", ["scripts/html-preview-browser-fixture.py", origin, prefix], { encoding: "utf8", maxBuffer: 4 * 1024 * 1024 })) as Fixture;
          expect(url.pathname).toBe(`${prefix}/api/bots/main/files/html-preview`);
          data = fixture.session;
        } else if (path.startsWith("bots/main/files/html-preview/") && request.method() === "DELETE") {
          closed += 1;
        } else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1 };
        else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
        else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
        else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
        else if (path === "admin/users") data = [];
        await route.fulfill({ json: { ok: true, data } });
      });
      await page.goto(`${origin}${prefix}/`);
      if (width > 600) {
        await page.getByRole("button", { name: "打开 index.html", exact: true }).click({ button: "right" });
        await page.getByRole("button", { name: "预览", exact: true }).click();
      } else {
        await page.getByRole("button", { name: "文件", exact: true }).click();
        await page.getByRole("button", { name: "打开 index.html", exact: true }).click();
      }
      await expect(page.getByRole("status").filter({ hasText: "预览暂时不可用" })).toBeVisible();
      await page.getByRole("button", { name: "重试", exact: true }).click();
      const iframe = page.locator('iframe[title="index.html"]');
      const preview = iframe.contentFrame();
      await expect(iframe).toHaveAttribute("sandbox", "allow-scripts allow-forms allow-downloads");
      await expect(preview.locator("#module")).toHaveText("module ready");
      await expect(preview.locator("#json")).toHaveText("JSON ready");
      await expect(preview.locator("#font")).toHaveText("font ready");
      await expect(preview.locator("h1")).toHaveCSS("color", "rgb(18, 52, 86)");
      await expect.poll(() => preview.locator("img").evaluate((element) => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
      await preview.getByRole("button", { name: "Count 0", exact: true }).click();
      await expect(preview.getByRole("button", { name: "Count 1", exact: true })).toBeVisible();
      await preview.getByRole("button", { name: "Submit locally", exact: true }).click();
      await expect(preview.locator("#form-result")).toHaveText("form handled");
      for (const id of ["parent", "storage", "api"]) await expect(preview.locator(`#${id}`)).toHaveText("blocked");
      await preview.getByRole("link", { name: "Hash route", exact: true }).click();
      await expect.poll(() => iframe.contentFrame().locator("body").evaluate(() => location.hash)).toBe("#route");
      await preview.getByRole("link", { name: "Details", exact: true }).click();
      await expect(preview.getByRole("heading", { name: "Details version 1", exact: true })).toBeVisible();
      changed = true;
      await page.getByRole("button", { name: "刷新", exact: true }).click();
      await expect(preview.getByRole("heading", { name: "Details version 2", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "返回入口", exact: true }).click();
      await expect(preview.getByRole("heading", { name: "Interactive HTML", exact: true })).toBeVisible();
      expect(attempts).toBe(2);
      expect(fileReads).toEqual([]);
      expect(previewManagementRequests).toEqual([]);
      expect(resourceRequests.every((request) => !request.authorization && !request.referer)).toBe(true);
      for (const path of ["assets/app.mjs", "assets/helper.mjs", "assets/font.woff2", "data.json"]) {
        expect(resourceRequests.some((request) => request.path === path && request.origin === "null"), path).toBe(true);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      const bounds = await iframe.boundingBox();
      expect(bounds!.width).toBeGreaterThan(200);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      if (!prefix && width === 1440) {
        await page.getByRole("button", { name: "隐藏编辑/预览区", exact: true }).click();
        await expect(iframe).toHaveCount(0);
        await page.getByRole("button", { name: "显示编辑/预览区", exact: true }).click();
        await expect(preview.locator("#module")).toHaveText("module ready");
        expect(attempts).toBe(3);
        // A missing linked document has no bridge; the parent still offers retry.
        await preview.getByRole("link", { name: "Hash route", exact: true }).click();
        await preview.getByRole("link", { name: "Missing page", exact: true }).click();
        await expect(page.getByRole("button", { name: "重试", exact: true })).toBeVisible({ timeout: 20_000 });
        await page.getByRole("button", { name: "重试", exact: true }).click();
        await expect(preview.getByRole("heading", { name: "Interactive HTML", exact: true })).toBeVisible();
        expect(attempts).toBe(4);
      }
      await page.screenshot({ path: test.info().outputPath(`html-preview-${width}.png`) });

      // Top-level visits must retain the response-level sandbox as well.
      const direct = await page.context().newPage();
      await direct.route("**/api/file-previews/**", async (route) => {
        const key = decodeURIComponent(new URL(route.request().url()).pathname.split("/api/file-previews/")[1].split("/").slice(1).join("/"));
        const resource = fixture!.resources[key];
        await route.fulfill({ status: resource.status, headers: resource.headers, body: Buffer.from(resource.body, "base64") });
      });
      await direct.goto(`${origin}${fixture!.session.entry_url}`);
      await expect(direct.locator("#module")).toHaveText("module ready");
      expect(await direct.evaluate(() => window.origin)).toBe("null");
      await expect(direct.locator("#storage")).toHaveText("blocked");
      await direct.close();
      if (width > 600) await page.getByRole("button", { name: "关闭 index.html 预览", exact: true }).click();
      else await page.getByRole("button", { name: "关闭", exact: true }).click();
      await expect.poll(() => closed).toBeGreaterThan(0);
    });
  }
}
