import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1600, height: 960 } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("web-api-token", "playwright-token");
    window.localStorage.setItem("web-view-mode", "desktop");
  });
});

test("desktop editor fills the pane, focuses immediately, and keeps scrolling inside the scroller", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("debug-scroll.txt");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();

  await page.waitForTimeout(500);

  const beforeClick = await page.evaluate(() => {
    const active = document.activeElement as HTMLElement | null;
    const host = document.querySelector("[data-testid='file-editor-host']") as HTMLElement | null;
    const wrapper = host?.firstElementChild as HTMLElement | null;
    const scroller = document.querySelector(".cm-scroller") as HTMLElement | null;
    const editor = document.querySelector(".cm-editor") as HTMLElement | null;
    return {
      activeTag: active?.tagName || null,
      activeClass: active?.className || null,
      activeInEditor: Boolean(active?.closest(".cm-editor")),
      activeInTerminal: Boolean(active?.closest(".xterm")),
      hostHeight: host?.clientHeight || null,
      wrapperHeight: wrapper?.clientHeight || null,
      editorWidth: editor?.clientWidth || null,
      editorHeight: editor?.clientHeight || null,
      scrollerClientHeight: scroller?.clientHeight || null,
      scrollerScrollHeight: scroller?.scrollHeight || null,
      scrollerOverflow: scroller ? getComputedStyle(scroller).overflow : null,
    };
  });

  expect(beforeClick.activeInEditor).toBe(true);
  expect(beforeClick.activeInTerminal).toBe(false);
  expect(beforeClick.hostHeight).toBeGreaterThan(200);
  expect(beforeClick.wrapperHeight).toBeGreaterThan(200);
  expect(beforeClick.editorHeight).toBeGreaterThan(200);
  expect(beforeClick.scrollerClientHeight).toBeGreaterThan(200);
  expect(beforeClick.scrollerOverflow).toBe("auto");

  await page.keyboard.insertText(
    Array.from({ length: 200 }, (_, index) => `line ${index + 1}`).join("\n"),
  );
  await page.waitForTimeout(250);

  const afterTyping = await page.evaluate(() => {
    const host = document.querySelector("[data-testid='file-editor-host']") as HTMLElement | null;
    const wrapper = host?.firstElementChild as HTMLElement | null;
    const editor = document.querySelector(".cm-editor") as HTMLElement | null;
    const scroller = document.querySelector(".cm-scroller") as HTMLElement | null;
    return {
      hostHeight: host?.clientHeight || null,
      wrapperHeight: wrapper?.clientHeight || null,
      editorHeight: editor?.clientHeight || null,
      editorScrollHeight: editor?.scrollHeight || null,
      scrollerClientHeight: scroller?.clientHeight || null,
      scrollerScrollHeight: scroller?.scrollHeight || null,
      scrollerScrollTop: scroller?.scrollTop || null,
      scrollerOverflow: scroller ? getComputedStyle(scroller).overflow : null,
    };
  });

  expect(afterTyping.hostHeight).toBeGreaterThan(200);
  expect(afterTyping.wrapperHeight).toBeGreaterThan(200);
  expect(afterTyping.editorHeight).toBeGreaterThan(200);
  expect(afterTyping.scrollerClientHeight).toBeGreaterThan(200);
  expect(afterTyping.scrollerScrollHeight).toBeGreaterThan(afterTyping.scrollerClientHeight ?? 0);
  expect(afterTyping.scrollerOverflow).toBe("auto");
});

test("desktop file tree opens saved file content on the first click", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("reopen-once.txt");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();

  await page.keyboard.insertText("reopen-once-line-1\nreopen-once-line-2");
  await page.keyboard.press("Control+S");
  await expect(page.getByTestId("desktop-workbench-statusbar").getByText("已保存")).toBeVisible();

  await page.getByRole("button", { name: "关闭 reopen-once.txt" }).click();
  await expect(page.getByText("Ctrl+P")).toBeVisible();
  await expect(page.getByText("Ctrl+Shift+F")).toBeVisible();

  await page.getByRole("button", { name: "打开 reopen-once.txt" }).click();
  await expect(page.getByText("reopen-once-line-1")).toBeVisible();
  await expect(page.getByText("reopen-once-line-2")).toBeVisible();
});

test("desktop editor remounts codemirror when switching between file tabs", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("first-tab.txt");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();

  const firstToken = await page.evaluate(() => {
    const editor = document.querySelector(".cm-editor");
    if (!(editor instanceof HTMLElement)) {
      return null;
    }
    if (!editor.dataset.testInstanceToken) {
      editor.dataset.testInstanceToken = crypto.randomUUID();
    }
    return editor.dataset.testInstanceToken;
  });

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("second-tab.txt");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();

  const secondToken = await page.evaluate(() => {
    const editor = document.querySelector(".cm-editor");
    if (!(editor instanceof HTMLElement)) {
      return null;
    }
    if (!editor.dataset.testInstanceToken) {
      editor.dataset.testInstanceToken = crypto.randomUUID();
    }
    return editor.dataset.testInstanceToken;
  });

  expect(firstToken).not.toBeNull();
  expect(secondToken).not.toBeNull();
  expect(secondToken).not.toBe(firstToken);

  await page.getByRole("tab", { name: /first-tab\.txt/ }).click();

  const switchedBackToken = await page.evaluate(() => {
    const editor = document.querySelector(".cm-editor");
    if (!(editor instanceof HTMLElement)) {
      return null;
    }
    if (!editor.dataset.testInstanceToken) {
      editor.dataset.testInstanceToken = crypto.randomUUID();
    }
    return editor.dataset.testInstanceToken;
  });

  expect(switchedBackToken).not.toBeNull();
  expect(switchedBackToken).not.toBe(secondToken);
});

test("desktop editor keeps insertion positions correct after opening and switching multiple tabs", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("cursor-first.txt");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();
  await page.keyboard.insertText("alpha");

  await page.getByRole("button", { name: "新建文件", exact: true }).click();
  await page.getByLabel("文件名").fill("cursor-second.txt");
  await page.getByRole("button", { name: "创建" }).click();
  await page.locator(".cm-editor").waitFor();
  await page.keyboard.insertText("beta");

  await page.getByRole("tab", { name: /cursor-first\.txt/ }).click();
  await page.locator(".cm-editor").waitFor();
  await page.keyboard.press("End");
  await page.keyboard.insertText("-one");

  await page.getByRole("tab", { name: /cursor-second\.txt/ }).click();
  await page.locator(".cm-editor").waitFor();
  await page.keyboard.press("End");
  await page.keyboard.insertText("-two");

  const firstText = await page.evaluate(() => {
    const editor = document.querySelector(".cm-editor");
    return editor?.textContent || "";
  });
  expect(firstText).toContain("beta-two");

  await page.getByRole("tab", { name: /cursor-first\.txt/ }).click();
  await page.locator(".cm-editor").waitFor();

  const secondText = await page.evaluate(() => {
    const editor = document.querySelector(".cm-editor");
    return editor?.textContent || "";
  });
  expect(secondText).toContain("alpha-one");
});
