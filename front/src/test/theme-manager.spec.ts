import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { UiTheme, ThemeLibrary } from "../theme/types";

const BUILTIN_THEME: UiTheme = { schemaVersion: 1, id: "paper-daylight", name: "纸感日间", baseId: "paper-daylight", appearance: { colors: { scheme: "light", overrides: {} } }, readonly: true, version: 1, updatedAt: "" };
const builtinLibrary = (): ThemeLibrary => ({ schemaVersion: 1, scope: "global", revision: 0, selectedThemeId: BUILTIN_THEME.id, themes: [BUILTIN_THEME] });

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started application");

async function installThemeFixture(page: Page, withBot = false) {
  let library: ThemeLibrary = builtinLibrary();
  let identity = { key: "theme-member", role: "member" };
  let serial = 0;
  const mutations: string[] = [];
  const errors: string[] = [];
  const bot = { alias: "theme-check", cli_type: "codex", status: "running", working_dir: "C:/theme-fixture" };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.routeWebSocket("**/*", (socket) => socket.close());
  const assetRoot = process.env.THEME_TEST_ASSET_DIR;
  if (assetRoot) {
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.includes("/api/")) return route.fallback();
      const relative = url.pathname.includes("/assets/") ? `assets/${url.pathname.split("/assets/")[1]}` : "index.html";
      const full = path.resolve(assetRoot, relative);
      if (!full.startsWith(`${path.resolve(assetRoot)}${path.sep}`)) return route.abort();
      try { await route.fulfill({ body: await readFile(full), contentType: relative.endsWith(".js") ? "application/javascript" : relative.endsWith(".css") ? "text/css" : relative.endsWith(".svg") ? "image/svg+xml" : relative.endsWith(".png") ? "image/png" : "text/html" }); }
      catch { await route.fallback(); }
    });
  }
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = url.pathname.split("/api/")[1];
    if (key.startsWith("ui/theme")) expect(request.headers()["x-ui-account-id"]).toBeUndefined();
    let data: unknown = {};
    if (key === "ui/themes" && request.method() === "GET") data = library;
    else if (key.startsWith("ui/theme") && request.method() !== "GET") {
      const input = request.postDataJSON();
      if (input.expectedRevision !== library.revision) return route.fulfill({ status: 409, json: { ok: false, error: { code: "theme_revision_conflict", message: "版本冲突" } } });
      mutations.push(`${request.method()} ${key}`);
      if (request.method() === "POST") {
        const source = library.themes.find((item) => item.id === input.sourceId) || BUILTIN_THEME;
        const theme: UiTheme = { ...source, id: `theme_fixture_${++serial}`, name: input.name, appearance: input.appearance || source.appearance, readonly: false, version: 1, updatedAt: new Date().toISOString() };
        library = { ...library, themes: [...library.themes, theme], selectedThemeId: input.activate ? theme.id : library.selectedThemeId };
      } else if (key === "ui/theme-selection") library = { ...library, selectedThemeId: input.themeId };
      else if (request.method() === "DELETE") {
        const id = key.split("/").at(-1)!;
        library = { ...library, themes: library.themes.filter((item) => item.id !== id), selectedThemeId: library.selectedThemeId === id ? BUILTIN_THEME.id : library.selectedThemeId };
      } else {
        const id = key.split("/").at(-1)!;
        library = { ...library, themes: library.themes.map((theme) => theme.id === id ? { ...theme, name: input.name ?? theme.name, appearance: input.appearance ?? theme.appearance, version: theme.version + 1 } : theme), selectedThemeId: input.activate ? id : library.selectedThemeId };
      }
      library = { ...library, revision: library.revision + 1 };
      data = library;
    } else if (key === "auth/me") data = { is_logged_in: true, username: identity.key, account_id: identity.key, role: identity.role, current_bot_alias: withBot ? bot.alias : "", capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "write_files", "view_chat_history", "chat_send", "git_ops"] };
    else if (key === "bots") data = withBot ? [bot] : [];
    else if (key === `bots/${bot.alias}`) data = { bot, session: { working_dir: bot.working_dir, is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (key.endsWith("/ls")) data = { working_dir: bot.working_dir, entries: [{ name: "added.ts", is_dir: false }, { name: "modified.ts", is_dir: false }, { name: "ignored.log", is_dir: false }] };
    else if (key.endsWith("/pwd")) data = { working_dir: bot.working_dir };
    else if (key.endsWith("/git/tree-status")) data = { repo_found: true, items: { "added.ts": "added", "modified.ts": "modified", "ignored.log": "ignored" } };
    else if (key.endsWith("/git")) data = { repo_found: true, current_branch: "main", changed_files: [], recent_commits: [] };
    else if (key.endsWith("/history") || key.endsWith("/history/delta")) data = { items: [], revision: 0, reset: false };
    else if (key.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (key.endsWith("/conversations") || key === "announcements" || key.endsWith("/favorites")) data = { items: [] };
    else if (!["GET", "HEAD"].includes(request.method())) {
      mutations.push(`${request.method()} ${key}`);
      return route.fulfill({ status: 403, json: { ok: false, error: { code: "fixture_readonly", message: "此验证不执行工作区操作" } } });
    }
    await route.fulfill({ json: { ok: true, data } });
  });
  return { mutations, errors, library: () => library, setIdentity: (key: string, role = "member") => { identity = { key, role }; } };
}

for (const [width, height] of [[1600, 1000], [1280, 900], [390, 844], [360, 800]]) {
  test(`shared theme flow without a Bot at ${width}×${height}`, async ({ page }) => {
    const fixture = await installThemeFixture(page);
    await page.setViewportSize({ width, height });
    await page.goto("./");
    await page.getByRole("button", { name: "管理主题", exact: true }).click();
    const manager = page.locator(".theme-manager");
    await expect(manager).toBeVisible();
    await manager.getByRole("button", { name: "复制后编辑" }).click();
    await manager.getByLabel("主题名称", { exact: true }).fill("共享试色");
    await manager.getByLabel("基础表面 HEX", { exact: true }).fill("#E7EEF4");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "paper-daylight");
    if (width < 768) await manager.getByRole("button", { name: "局部预览", exact: true }).click();
    await expect(manager.getByTestId("theme-local-preview")).toHaveCSS("--surface", "#E7EEF4FF");
    await manager.getByRole("button", { name: "保存并应用", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
    await expect(page.locator("html")).toHaveCSS("--surface", "#E7EEF4FF");
    await page.screenshot({ path: test.info().outputPath(`theme-light-${width}.png`) });
    if (width < 768) await manager.getByRole("button", { name: "主题编辑", exact: true }).click();
    await manager.getByLabel("基础表面 HEX", { exact: true }).fill("#FFFFFF");
    await manager.getByRole("button", { name: "取消", exact: true }).click();
    await manager.getByRole("button", { name: "放弃更改", exact: true }).click();
    await expect(page.locator("html")).toHaveCSS("--surface", "#E7EEF4FF");
    await manager.getByRole("button", { name: "关闭主题管理" }).click();
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
    await page.getByRole("button", { name: "管理主题", exact: true }).click();
    await manager.getByLabel("明暗模式", { exact: true }).selectOption("dark");
    await manager.getByLabel("基础表面 HEX", { exact: true }).fill("#17212C");
    await manager.getByLabel("正文 HEX", { exact: true }).fill("#EBF0F7");
    await manager.getByRole("button", { name: "保存并应用", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-color-scheme", "dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
    await page.screenshot({ path: test.info().outputPath(`theme-dark-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await manager.getByRole("button", { name: "删除主题", exact: true }).click();
    await manager.getByRole("button", { name: "确认删除", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "paper-daylight");
    expect(fixture.library().themes).toHaveLength(1);
    expect(fixture.mutations.every((item) => item.includes("ui/theme"))).toBe(true);
    expect(fixture.errors).toEqual([]);
  });
}

test("theme management keeps the workbench and chat draft mounted", async ({ page }) => {
  const fixture = await installThemeFixture(page, true);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  await page.goto("./");
  const workbench = page.locator(".desktop-workbench-root");
  await expect(workbench).toBeVisible();
  await workbench.evaluate((element) => { (window as unknown as { themeTestWorkbench: Element }).themeTestWorkbench = element; });
  const composer = page.locator('.chat-composer-delight textarea[name="message"]');
  await composer.fill("尚未发送的草稿");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("button", { name: "管理主题", exact: true }).click();
  const manager = page.locator(".theme-manager");
  await manager.getByRole("button", { name: "复制后编辑" }).click();
  await manager.getByLabel("强调色 HEX", { exact: true }).fill("#2468AC");
  await manager.getByRole("button", { name: "保存并应用", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
  await manager.getByLabel("强调色 HEX", { exact: true }).fill("#AC6824");
  await page.keyboard.press("Control+s");
  await manager.getByRole("button", { name: "保存并应用", exact: true }).click();
  await expect(page.locator("html")).toHaveCSS("--accent", "#AC6824FF");
  await manager.getByRole("button", { name: "关闭主题管理" }).click();
  expect(await workbench.evaluate((element) => element === (window as unknown as { themeTestWorkbench: Element }).themeTestWorkbench)).toBe(true);
  await expect(composer).toHaveValue("尚未发送的草稿");
  await page.getByRole("button", { name: "文件", exact: true }).click();
  await expect(page.locator('.file-tree-row[data-git-state="added"]').first()).toHaveCSS("height", "26px");
  await page.screenshot({ path: test.info().outputPath("custom-paper-workbench.png") });
  expect(fixture.mutations.every((item) => item.includes("ui/theme"))).toBe(true);
  expect(fixture.errors).toEqual([]);
});

test("accounts share themes and the applied choice while guests remain read-only", async ({ page }) => {
  const fixture = await installThemeFixture(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("./");
  await page.getByRole("button", { name: "管理主题", exact: true }).click();
  let manager = page.locator(".theme-manager");
  await manager.getByRole("button", { name: "复制后编辑" }).click();
  await manager.getByLabel("主题名称", { exact: true }).fill("共同配色");
  await manager.getByRole("button", { name: "保存并应用", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
  fixture.setIdentity("second-member");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
  await page.getByRole("button", { name: "管理主题", exact: true }).click();
  manager = page.locator(".theme-manager");
  await expect(manager.getByLabel("主题名称", { exact: true })).toHaveValue("共同配色");
  await manager.getByLabel("强调色 HEX", { exact: true }).fill("#27654F");
  await manager.getByRole("button", { name: "保存并应用", exact: true }).click();
  await expect(page.locator("html")).toHaveCSS("--accent", "#27654FFF");
  fixture.setIdentity("guest", "guest");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "theme_fixture_1");
  await expect(page.locator("html")).toHaveCSS("--accent", "#27654FFF");
  await expect(page.getByRole("button", { name: "管理主题", exact: true })).toHaveCount(0);
  fixture.setIdentity("theme-member");
  await page.reload();
  await expect(page.locator("html")).toHaveCSS("--accent", "#27654FFF");
  expect(fixture.library().themes).toHaveLength(2);
  expect(fixture.library().revision).toBe(2);
  expect(fixture.errors).toEqual([]);
});
