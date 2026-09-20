import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import type { DocumentViewPayload } from "../services/types";

// A parser-produced payload can also be checked without installing the plugin.
const payload: DocumentViewPayload = process.env.DOCX_PREVIEW_PAYLOAD_FILE
  ? JSON.parse(readFileSync(process.env.DOCX_PREVIEW_PAYLOAD_FILE, "utf8"))
  : {
    path: "formatting.docx",
    formatting: "document",
    blocks: [
      { type: "heading", level: 1, format: { align: "center", spaceAfterPx: 12 }, runs: [{ text: "Document formatting", fontSizePx: 28, bold: true }] },
      { type: "paragraph", format: { indentLeftPx: 24, firstLineIndentPx: 16, spaceBeforePx: 0, spaceAfterPx: 0, lineSpacing: { mode: "exact", value: 28 } }, runs: [{ text: "Mixed English 中文", fontFamily: "Arial", fontFamilyEastAsia: "SimSun", fontSizePx: 20, color: "#123456", highlightColor: "#ffff00", bold: false }] },
      { type: "paragraph", format: { lineSpacing: { mode: "exact", value: 24 } }, runs: [] },
      { type: "table", width: { unit: "px", value: 640 }, columnWidthsPx: [320, 320], rows: [
        { cells: [{ runs: [{ text: "Merged cell" }], colSpan: 2, shadingColor: "#eeeeee", borders: { bottom: { style: "solid", widthPx: 2, color: "#123456" } } }] },
        { cells: [{ runs: [], rowSpan: 2, paragraphs: [{ type: "paragraph", runs: [{ text: "First cell paragraph" }] }, { type: "paragraph", format: { align: "right" }, runs: [{ text: "Second cell paragraph" }] }] }, { runs: [{ text: "Top right" }] }] },
        { cells: [{ runs: [{ text: "Bottom right" }] }] },
      ] },
    ],
  };

test("document formatting stays selectable and legible across themes and viewport widths", async ({ page }) => {
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:\\workspace", supported_execution_modes: ["cli"] };
  const entries = [{ name: "formatting.docx", is_dir: false, size: 1024 }];
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  // Use assets from the user-started application and isolate all API traffic.
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    let data: unknown = {};
    if (path === "auth/me") data = { is_logged_in: true, username: "document-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["chat_send", "read_file_content", "view_plugins", "run_plugins"] };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:\\workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/ls") data = { working_dir: "C:\\workspace", entries };
    else if (path === "bots/main/pwd") data = { working_dir: "C:\\workspace" };
    else if (path === "bots/main/files/reveal") data = { root_path: "C:\\workspace", highlight_path: "formatting.docx", branches: { "": entries } };
    else if (path === "bots/main/plugins/resolve-file-target") data = { kind: "plugin_view", pluginId: "docx-preview", viewId: "document", title: "formatting.docx", input: { path: "formatting.docx" } };
    else if (path.endsWith("/views/document/open")) data = { pluginId: "docx-preview", viewId: "document", renderer: "document", mode: "snapshot", title: "formatting.docx", payload };
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1 };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path === "admin/users") data = [];
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "打开 formatting.docx", exact: true }).click();
  const view = page.getByTestId("document-view");
  await expect(view).toBeVisible();
  await page.getByRole("button", { name: "聚焦编辑器", exact: true }).click();
  for (const theme of ["classic", "deep-space"]) {
    await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      // Exercise a narrow preview host independently of desktop chrome's minimum width.
      await view.evaluate((element, viewportWidth) => {
        element.parentElement!.style.width = viewportWidth === 390 ? "382px" : "";
      }, width);
      await expect.poll(() => view.evaluate((element) => element.getBoundingClientRect().right)).toBeLessThanOrEqual(width);
      const paragraph = view.locator("p").filter({ hasText: "Mixed English 中文" });
      const text = paragraph.locator(":scope > span").first();
      await expect(text).toHaveCSS("color", "rgb(18, 52, 86)");
      await expect(text).toHaveCSS("font-size", "20px");
      await expect(text).toHaveCSS("font-weight", "400");
      await expect(paragraph).toHaveCSS("line-height", "28px");
      await expect(paragraph).toHaveCSS("margin-left", "24px");
      await expect(paragraph).toHaveCSS("text-indent", "16px");
      expect(await paragraph.evaluate((element) => {
        let surface: Element | null = element;
        while (surface && getComputedStyle(surface).backgroundColor === "rgba(0, 0, 0, 0)") surface = surface.parentElement;
        return surface ? getComputedStyle(surface).backgroundColor : "";
      })).toBe("rgb(255, 255, 255)");
      expect(await text.evaluate((element) => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
        return selection.toString();
      })).toBe("Mixed English 中文");
      await page.evaluate(() => window.getSelection()?.removeAllRanges());
      const merged = view.getByRole("cell", { name: "Merged cell", exact: true });
      await expect(merged).toHaveAttribute("colspan", "2");
      await expect(merged).toHaveCSS("background-color", "rgb(238, 238, 238)");
      const vertical = view.getByRole("cell", { name: "First cell paragraph Second cell paragraph" });
      await expect(vertical).toHaveAttribute("rowspan", "2");
      await expect(vertical.locator("p")).toHaveCount(2);
      const table = view.getByRole("table");
      await expect(table).toHaveCSS("width", "640px");
      if (width === 390) {
        expect(await table.evaluate((element) => {
          const scroller = element.parentElement!;
          scroller.scrollLeft = scroller.scrollWidth;
          const canScroll = scroller.scrollLeft > 0;
          scroller.scrollLeft = 0;
          return canScroll;
        })).toBe(true);
      }
      expect(await view.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      const screenshot = test.info().outputPath(`document-${theme}-${width}.png`);
      await view.screenshot({ path: screenshot });
      await test.info().attach(`${theme}-${width}`, { path: screenshot, contentType: "image/png" });
    }
  }
});
