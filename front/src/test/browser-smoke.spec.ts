import { expect, test } from "@playwright/test";

test("登录页支持桌面和移动端输入、切换及截图", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  // The running application supplies assets; API responses stay inside this test.
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    const json = path === "health"
      ? { ok: true, host_info: { username: "browser-smoke", operating_system: "Windows", hardware_platform: "x64", hardware_spec: "Test host" } }
      : { ok: true, data: path === "auth/me" ? { is_logged_in: false } : path === "public/ui/themes"
        ? { schemaVersion: 1, scope: "global", revision: 0, selectedThemeId: "paper-daylight", themes: [] } : {} };
    await route.fulfill({ json });
  });
  await page.goto("/");

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByLabel("用户名", { exact: true }).fill("browser-smoke");
    await page.getByLabel("密码", { exact: true }).fill("fixture-password");
    await page.getByRole("checkbox", { name: "记住登录" }).check();
    await page.getByRole("tab", { name: "注册", exact: true }).click();
    await expect(page.getByLabel("注册码", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "登录", exact: true }).click();
    await expect(page.getByLabel("注册码", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("用户名", { exact: true })).toHaveValue("browser-smoke");
    await expect(page.getByLabel("密码", { exact: true })).toHaveValue("fixture-password");
    await expect(page.getByRole("checkbox", { name: "记住登录" })).toBeChecked();
    await expect(page.getByRole("button", { name: "登录", exact: true })).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    const screenshotPath = test.info().outputPath(`login-${width}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    await test.info().attach(`login-${width}`, { path: screenshotPath, contentType: "image/png" });
  }

  expect(pageErrors).toEqual([]);
});
