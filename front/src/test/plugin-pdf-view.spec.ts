import { expect, test } from "@playwright/test";

// Real PDF: text and vectors, a rotated image-only page, and a CJK font/CMap.
function samplePdf() {
  const stream = (data: string, dictionary = "") => `<< /Length ${Buffer.byteLength(data)} ${dictionary} >>\nstream\n${data}\nendstream`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 6 0 R 9 0 R] /Count 3 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    stream("BT /F1 24 Tf 20 340 Td (PDF layout) Tj ET 1 0 0 rg 20 20 40 40 re f"),
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Rotate 90 /Resources << /XObject << /Im1 8 0 R >> >> /Contents 7 0 R >>",
    stream("q 100 0 0 100 100 150 cm /Im1 Do Q"),
    stream("ffff00>", "/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /ASCIIHexDecode"),
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Rotate 90 /Resources << /Font << /F1 11 0 R >> >> /Contents 10 0 R >>",
    stream("BT /F1 24 Tf 20 340 Td <4E2D6587> Tj ET"),
    "<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [12 0 R] >>",
    "<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /FontDescriptor 13 0 R /DW 1000 >>",
    "<< /Type /FontDescriptor /FontName /STSong-Light /Flags 6 /FontBBox [0 -200 1000 900] /ItalicAngle 0 /Ascent 900 /Descent -200 /CapHeight 900 /StemV 80 >>",
  ];
  let result = "%PDF-1.7\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(result));
    result += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const start = Buffer.byteLength(result);
  result += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  result += offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  return Buffer.from(`${result}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`);
}

for (const extension of ["pdf", "pptx"]) {
test(`${extension.toUpperCase()} pages preserve layout, images, selection and local CJK resources`, async ({ page, context }) => {
  const filename = `layout.${extension}`;
  const pluginId = `${extension}-preview`;
  const statsText = extension === "pptx" ? "仅预览前 3 页，共 4 页" : "3 页";
  const resourceRequests: string[] = [];
  // Exercise the runtime forwarding prefix using the existing server's assets.
  await context.route("**/node/pdf-qa/assets/**", async (route) => {
    resourceRequests.push(route.request().url());
    const url = new URL(route.request().url());
    url.pathname = url.pathname.replace("/node/pdf-qa", "");
    await route.fulfill({ response: await route.fetch({ url: url.href }) });
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const failedResources: string[] = [];
  page.on("response", (response) => {
    if (response.status() >= 400 && /pdfjs|pdf\.worker/.test(response.url())) failedResources.push(response.url());
  });
  const entries = [{ name: filename, is_dir: false, size: 2048 }];
  const bot = { alias: "main", name: "main", cli_type: "codex", status: "running", working_dir: "C:\\workspace", supported_execution_modes: ["cli"] };
  await page.addInitScript(() => localStorage.setItem("web-view-mode", "desktop"));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/api/")[1];
    if (path.includes("/artifacts/")) {
      await route.fulfill({ contentType: "application/pdf", body: samplePdf() });
      return;
    }
    let data: unknown = {};
    if (path === "auth/me") data = { is_logged_in: true, username: "pdf-qa", account_id: "qa", role: "admin", current_bot_alias: "main", capabilities: ["chat_send", "read_file_content", "view_plugins", "run_plugins"] };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main") data = { bot, session: { working_dir: "C:\\workspace", is_processing: false, history_count: 0 }, agents: [{ id: "main", name: "main" }] };
    else if (path === "bots/main/ls") data = { working_dir: "C:\\workspace", entries };
    else if (path === "bots/main/pwd") data = { working_dir: "C:\\workspace" };
    else if (path === "bots/main/files/reveal") data = { root_path: "C:\\workspace", highlight_path: filename, branches: { "": entries } };
    else if (path.endsWith("resolve-file-target")) data = { kind: "plugin_view", pluginId, viewId: "document", title: filename, input: { path: filename } };
    else if (path.endsWith("/views/document/open")) data = { pluginId, viewId: "document", renderer: "document", mode: "snapshot", title: filename, payload: { path: filename, statsText, pdf: { artifactId: "sample-pdf" }, blocks: [] } };
    else if (path.endsWith("/history") || path.endsWith("/history/delta")) data = { items: [], revision: 1 };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/agents")) data = { items: [{ id: "main", name: "main" }], active_agent_id: "main" };
    else if (path === "announcements" || path.endsWith("/favorites")) data = { items: [] };
    else if (path === "admin/users") data = [];
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.evaluate(() => { window.__TCB_PUBLIC_ENV__ = { ...window.__TCB_PUBLIC_ENV__, VITE_BASE_PATH: "/node/pdf-qa" }; });
  await page.getByRole("button", { name: `打开 ${filename}`, exact: true }).click();
  const view = page.getByTestId("pdf-view");
  await expect(view.getByText(statsText, { exact: true })).toBeVisible();
  const paper = view.getByTestId("pdf-page");
  await expect(paper).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "聚焦编辑器", exact: true }).click();
  for (const theme of ["classic", "deep-space"]) {
    await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await view.evaluate((element, width) => { element.parentElement!.style.width = width === 390 ? "382px" : ""; }, width);
      await expect(paper).toHaveAttribute("aria-busy", "false");
      await expect.poll(() => paper.evaluate((element) => element.getBoundingClientRect().right)).toBeLessThanOrEqual(width);
      await expect(paper).toHaveCSS("background-color", "rgb(255, 255, 255)");
      await expect(view.getByRole("button", { name: "上一页" })).toBeDisabled();
      const text = view.locator(".pdf-text-layer");
      await expect(text).toContainText("PDF layout");
      await expect.poll(() => text.evaluate((element) => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
        return selection.toString();
      })).toContain("PDF layout");
      await page.evaluate(() => window.getSelection()?.removeAllRanges());
      // Check the vector rectangle's original position and color, not just DOM.
      await expect.poll(() => paper.locator("canvas").evaluate((canvas: HTMLCanvasElement) => Array.from(
        canvas.getContext("2d")!.getImageData(Math.floor(canvas.width * 40 / 300), Math.floor(canvas.height * 360 / 400), 1, 1).data,
      ))).toEqual([255, 0, 0, 255]);
      await view.screenshot({ path: test.info().outputPath(`pdf-${theme}-${width}.png`) });
    }
  }
  await view.getByLabel("缩放", { exact: true }).selectOption("2");
  await expect(paper).toHaveAttribute("aria-busy", "false");
  await expect.poll(() => paper.evaluate((element) => element.parentElement!.parentElement!.scrollWidth > element.parentElement!.parentElement!.clientWidth)).toBe(true);
  await view.getByLabel("缩放", { exact: true }).selectOption("fit");
  await view.getByRole("button", { name: "下一页" }).click();
  await expect(paper.locator("canvas")).toHaveAttribute("aria-label", "第 2 页");
  await expect(paper).toHaveAttribute("aria-busy", "false");
  expect(await paper.evaluate((element) => element.clientWidth / element.clientHeight)).toBeCloseTo(4 / 3, 1);
  await expect.poll(() => paper.locator("canvas").evaluate((canvas: HTMLCanvasElement) => Array.from(
    canvas.getContext("2d")!.getImageData(Math.floor(canvas.width / 2), Math.floor(canvas.height / 2), 1, 1).data,
  ))).toEqual([255, 255, 0, 255]);
  await expect(view.locator(".pdf-text-layer")).toBeEmpty();
  await view.getByLabel("页码", { exact: true }).fill("3");
  await view.getByLabel("页码", { exact: true }).press("Enter");
  await expect(paper).toHaveAttribute("aria-busy", "false");
  await expect(view.locator(".pdf-text-layer")).toContainText("中文");
  expect(await view.getByText("中文", { exact: true }).evaluate((element) => {
    const box = element.getBoundingClientRect();
    const page = element.closest(".pdf-page")!.getBoundingClientRect();
    return box.height > box.width && box.left >= page.left && box.right <= page.right;
  })).toBe(true);
  await expect(view.getByRole("button", { name: "下一页" })).toBeDisabled();
  await view.screenshot({ path: test.info().outputPath("pdf-cjk.png") });
  expect(failedResources).toEqual([]);
  expect(resourceRequests.some((url) => url.includes("pdf.worker"))).toBe(true);
  expect(resourceRequests.some((url) => url.includes("/pdfjs/cmaps/"))).toBe(true);
  expect(errors).toEqual([]);
});
}
