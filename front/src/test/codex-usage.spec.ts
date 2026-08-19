import { expect, test } from "@playwright/test";

test("Codex 用量趋势在桌面和移动视口可见且页面不横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");

  await page.getByLabel("用户名").fill("127.0.0.1");
  await page.getByLabel("密码").fill("playwright");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("button", { name: "切换 Bot: main", exact: true })).toBeVisible();

  const announcement = page.getByRole("dialog", { name: "公告", exact: true });
  if (await announcement.isVisible()) {
    await announcement.getByRole("button", { name: "关闭", exact: true }).click();
  }

  await page.getByRole("button", { name: "切换 Bot: main", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "智能体切换" })).toBeVisible();
  await page.getByRole("button", { name: "管理中心", exact: true }).click();
  await page.getByRole("tab", { name: "Codex 用量", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Codex 用量", exact: true })).toBeVisible();
  const chart = page.getByRole("img", { name: /gpt-5\.6-sol Codex 剩余额度与剩余时长趋势/ });
  await expect(chart).toBeVisible();
  await expect(page.getByText("当前剩余 92%", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Codex 用量每日明细" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  const tableOverflow = await page.locator(".codex-usage-table-wrap").first().evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  const documentFitsViewport = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  const chartFitsViewport = await chart.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    return bounds.left >= 0 && bounds.right <= document.documentElement.clientWidth;
  });

  expect(tableOverflow.scrollWidth).toBeGreaterThan(tableOverflow.clientWidth);
  expect(chartFitsViewport).toBe(true);
  expect(documentFitsViewport).toBe(true);
});
