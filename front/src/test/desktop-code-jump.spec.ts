import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 960 } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("web-session-token", "playwright-session");
    window.localStorage.setItem("web-view-mode", "desktop");
  });
});

test("desktop code jump opens the resolved target file", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("jump-demo.py");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();
  await page.keyboard.insertText("from service import run\nrun()\n");

  const secondLine = page.locator(".cm-content .cm-line").nth(1);
  await expect(secondLine).toContainText("run()");
  const box = await secondLine.boundingBox();
  if (!box) {
    throw new Error("second editor line not found");
  }

  const modifier = process.platform === "darwin" ? "Meta" : "Control";
  await page.keyboard.down(modifier);
  await page.mouse.click(box.x + 18, box.y + box.height / 2);
  await page.keyboard.up(modifier);

  await expect(page.getByRole("tab", { name: /service\.py/ })).toBeVisible();
  await expect(page.locator(".cm-content")).toContainText("Mock full content for src/service.py");
});
