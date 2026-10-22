import { expect, test } from "@playwright/test";
import type { UiTheme, ThemeLibrary } from "../theme/types";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started application");

const BUILTIN_THEME: UiTheme = {
  schemaVersion: 1, id: "paper-daylight", name: "纸感日间", baseId: "paper-daylight",
  appearance: { colors: { scheme: "light", overrides: {} } }, readonly: true, version: 1, updatedAt: "",
};

const night: UiTheme = {
  ...BUILTIN_THEME, id: "theme_login_preview", name: "登录夜间", readonly: false,
  appearance: { colors: { scheme: "dark", overrides: {
    canvas: "#101820", "surface.base": "#18232E", "surface.muted": "#202F3D", "surface.strong": "#223446",
    "text.primary": "#EAF0F6", "text.muted": "#B3C3D1", accent: "#80CBE4", "accent.foreground": "#101820",
  } } },
};

for (const width of [1280, 390]) {
  test(`login can select and remember a theme at ${width}px`, async ({ page }) => {
    const library: ThemeLibrary = { schemaVersion: 1, scope: "global", selectedThemeId: BUILTIN_THEME.id, revision: 3, themes: [BUILTIN_THEME, night] };
    let signedIn = false;
    const writes: string[] = [];
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.routeWebSocket("**/*", socket => socket.close());
    await page.route("**/api/**", async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname.split("/api/")[1];
      let data: unknown = {};
      if (!["GET", "HEAD"].includes(request.method())) {
        writes.push(path);
        if (path !== "auth/login") return route.fulfill({ status: 403, json: { ok: false } });
        signedIn = true;
      }
      if (path === "health") return route.fulfill({ json: { ok: true, host_info: { username: "theme-check", operating_system: "Windows", hardware_platform: "x64", hardware_spec: "Test host" } } });
      if (path === "public/ui/themes" || path === "ui/themes") data = library;
      else if (path === "auth/me" || path === "auth/login") data = { is_logged_in: signedIn, username: "theme-check", account_id: "theme-check", role: "member", current_bot_alias: "", capabilities: ["view_bots"] };
      else if (path === "bots") data = [];
      else if (path === "announcements") data = { items: [] };
      await route.fulfill({ json: { ok: true, data } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("./");
    const chooser = page.getByRole("button", { name: "界面主题", exact: true });
    await expect(chooser).toBeEnabled();
    await chooser.click();
    await expect(page.getByRole("option")).toHaveCount(2);
    await page.getByRole("option", { name: night.name }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", night.id);
    await expect(page.locator("html")).toHaveAttribute("data-color-scheme", "dark");
    await expect(page.getByRole("button", { name: "管理主题", exact: true })).toHaveCount(0);
    await page.reload();
    await expect(chooser).toBeEnabled();
    await expect(chooser).toContainText(night.name);
    await expect(page.locator("html")).toHaveAttribute("data-theme", night.id);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`login-theme-${width}.png`), fullPage: true });
    await page.getByLabel("用户名", { exact: true }).fill("theme-check");
    await page.getByLabel("密码", { exact: true }).fill("fixture-password");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByRole("button", { name: "管理主题", exact: true })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", BUILTIN_THEME.id);
    expect(writes).toEqual(["auth/login"]);
    expect(errors).toEqual([]);
  });
}
