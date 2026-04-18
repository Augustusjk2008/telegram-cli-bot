import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 960 } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("web-api-token", "playwright-token");
    window.localStorage.setItem("web-view-mode", "auto");
  });
});

test("desktop workbench stays viewport-bound and keeps overflow inside panes", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("desktop-workbench-root")).toBeVisible();
  await expect(page.getByTestId("desktop-pane-files")).toBeVisible();
  await expect(page.getByTestId("desktop-pane-editor")).toBeVisible();
  await expect(page.getByTestId("desktop-pane-terminal")).toBeVisible();
  await expect(page.getByTestId("desktop-pane-chat")).toBeVisible();
  await expect(page.getByTestId("desktop-workbench-statusbar")).toHaveCount(0);

  const metrics = await page.evaluate(() => ({
    viewportHeight: window.innerHeight,
    documentHeight: document.documentElement.scrollHeight,
  }));

  expect(metrics.documentHeight).toBeLessThanOrEqual(metrics.viewportHeight + 2);
});
