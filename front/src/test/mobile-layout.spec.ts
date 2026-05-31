import { test, expect } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

test("app has no horizontal overflow on mobile", async ({ page }) => {
  await page.goto("http://localhost:3000/");
  await page.getByRole("button", { name: "以 guest 进入" }).click();
  const closeAnnouncement = page.getByRole("button", { name: "关闭公告" });
  if (await closeAnnouncement.isVisible()) {
    await closeAnnouncement.click();
  }

  const actionBar = page.getByTestId("chat-action-bar");
  await expect(actionBar).toBeVisible();
  await expect(page.getByTestId("chat-scroll-content")).not.toHaveClass(/max-w-5xl/);
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const innerWidth = await page.evaluate(() => window.innerWidth);
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);

  const actionBarBounds = await actionBar.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
    overflowX: window.getComputedStyle(element).overflowX,
  }));
  expect(actionBarBounds.scrollWidth).toBeGreaterThanOrEqual(actionBarBounds.clientWidth);
  expect(actionBarBounds.overflowX).toBe("auto");
  await expect(page.getByLabel("模型")).toBeVisible();
  await expect(page.getByRole("button", { name: "计划模式" })).toHaveText("计划");
  await expect(page.getByRole("button", { name: "历史会话" })).toBeVisible();
});

test("settings git proxy controls do not overflow on mobile", async ({ page }) => {
  await page.goto("http://localhost:3000/");
  await page.getByLabel("用户名").fill("demo");
  await page.getByLabel("密码").fill("demo");
  await page.getByRole("button", { name: "登录" }).click();
  const closeAnnouncement = page.getByRole("button", { name: "关闭公告" });
  if (await closeAnnouncement.isVisible()) {
    await closeAnnouncement.click();
  }

  await page.getByRole("button", { name: "设置" }).click();
  const row = page.getByTestId("git-proxy-control-row");
  await expect(row).toBeVisible();
  const rowBounds = await row.evaluate((element) => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  expect(rowBounds.scrollWidth).toBeLessThanOrEqual(rowBounds.clientWidth);

  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const innerWidth = await page.evaluate(() => window.innerWidth);
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});
