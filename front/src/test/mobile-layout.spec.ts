import { test, expect } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

test("app has no horizontal overflow on mobile", async ({ page }) => {
  await page.goto("http://localhost:3000/");
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const innerWidth = await page.evaluate(() => window.innerWidth);
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});