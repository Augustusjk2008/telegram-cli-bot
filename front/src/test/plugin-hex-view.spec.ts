import { expect, test } from "@playwright/test";
import type { HexViewPayload } from "../services/types";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started application");

for (const bytesPerRow of [8, 16, 32]) {
  test(`hex rows align and scroll at ${bytesPerRow} bytes per row`, async ({ page }) => {
    const filename = `sample-${bytesPerRow}.bin`;
    const rowCount = 8192;
    const lastOffset = (rowCount - 1) * bytesPerRow;
    const payload: HexViewPayload = {
      path: filename,
      fileSizeBytes: rowCount * bytesPerRow + 1024,
      previewBytes: lastOffset + 3,
      bytesPerRow,
      truncated: true,
      entropyBuckets: [0.2, 0.5, 0.8].map((entropy, index) => ({
        index, startOffset: index * bytesPerRow, endOffset: (index + 1) * bytesPerRow, entropy,
      })),
      rows: Array.from({ length: rowCount }, (_, index) => ({
        offset: index * bytesPerRow,
        hex: index === rowCount - 1 ? ["4F", "52", "42"] : Array<string>(bytesPerRow).fill("41"),
        ascii: index === rowCount - 1 ? "ORB" : "A".repeat(bytesPerRow),
      })),
    };
    const entries = [{ name: filename, is_dir: false, size: payload.fileSizeBytes }];
    const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:\\workspace", supported_execution_modes: ["cli"] };
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname.split("/api/")[1];
      let data: unknown = {};
      if (path === "auth/me") data = { is_logged_in: true, username: "hex-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["chat_send", "read_file_content", "view_plugins", "run_plugins"] };
      else if (path === "bots") data = [bot];
      else if (path === "bots/main") data = { bot, session: { working_dir: "C:\\workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
      else if (path === "bots/main/ls") data = { working_dir: "C:\\workspace", entries };
      else if (path === "bots/main/pwd") data = { working_dir: "C:\\workspace" };
      else if (path === "bots/main/files/reveal") data = { root_path: "C:\\workspace", highlight_path: filename, branches: { "": entries } };
      else if (path.endsWith("resolve-file-target")) data = { kind: "plugin_view", pluginId: "hex-preview", viewId: "hex", title: filename, input: { path: filename } };
      else if (path.endsWith("/views/hex/open")) data = { pluginId: "hex-preview", viewId: "hex", renderer: "hex", mode: "snapshot", title: filename, payload };
      else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1 };
      else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
      else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
      else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
      else if (path === "admin/users") data = [];
      await route.fulfill({ json: { ok: true, data } });
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await page.getByRole("button", { name: `打开 ${filename}`, exact: true }).click();
    const view = page.getByTestId("hex-view");
    const list = view.getByTestId("virtualized-hex-rows");
    await expect(list).toBeVisible();
    await page.getByRole("button", { name: "聚焦编辑器", exact: true }).click();

    for (const width of [1440, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await view.evaluate((element, viewportWidth) => {
        element.parentElement!.style.width = viewportWidth === 320 ? "312px" : "";
      }, width);
      await list.evaluate((element) => { element.scrollTop = 0; element.scrollLeft = 0; });
      await expect(list.getByText("00000000", { exact: true })).toBeVisible();
      const firstRow = list.getByTestId("hex-row").first();
      expect(await firstRow.evaluate((element) => element.getBoundingClientRect().height)).toBe(24);
      const columnLefts = await firstRow.evaluate((element) => Array.from(element.children, (cell) => cell.getBoundingClientRect().left - element.getBoundingClientRect().left));
      if (width === 1440) await view.screenshot({ path: test.info().outputPath(`hex-${bytesPerRow}-wide.png`) });

      await list.evaluate((element) => { element.scrollTop = element.scrollHeight; });
      const lastAddress = lastOffset.toString(16).toUpperCase().padStart(8, "0");
      const lastRow = list.getByTestId("hex-row").filter({ hasText: lastAddress });
      await expect(lastRow).toBeVisible();
      expect(await lastRow.evaluate((element) => Array.from(element.children, (cell) => cell.getBoundingClientRect().left - element.getBoundingClientRect().left))).toEqual(columnLefts);
      expect(await lastRow.evaluate((element) => {
        const viewport = element.closest('[data-testid="virtualized-hex-rows"]')!;
        const row = element.getBoundingClientRect();
        const top = viewport.getBoundingClientRect().top;
        return row.top >= top && row.bottom <= top + viewport.clientHeight + 1;
      })).toBe(true);
      expect(await view.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      if (width === 320) {
        await view.screenshot({ path: test.info().outputPath(`hex-${bytesPerRow}-narrow-left.png`) });
        expect(await list.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
        await list.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
        expect(await list.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
        expect(await lastRow.evaluate((element) => {
          const viewport = element.closest('[data-testid="virtualized-hex-rows"]')!;
          return element.children[2].getBoundingClientRect().right <= viewport.getBoundingClientRect().left + viewport.clientWidth + 1;
        })).toBe(true);
        await view.screenshot({ path: test.info().outputPath(`hex-${bytesPerRow}-narrow-right.png`) });
      }
    }
    expect(errors).toEqual([]);
  });
}
