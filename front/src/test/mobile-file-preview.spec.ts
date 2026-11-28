import { expect, test, type Locator, type Page, type Route, type TestInfo } from "@playwright/test";
import { existsSync } from "node:fs";
import { join, posix } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { FileOpenTarget, PluginRenderResult, TableWindowPayload } from "../services/types";

test.skip(!process.env.PLAYWRIGHT_BASE_URL, "Requires a user-started host serving the built frontend");
test.use({ hasTouch: true, serviceWorkers: "block" });

const root = "/workspace";
const directory = root + "/reports";
const namedSession = "ses_00000002";
const note = "review.md";
const other = "details.md";
const noteTitle = "Review notes";
const otherTitle = "Reference measurements";
const html = "dashboard.html";
const pdf = "manual.pdf";
const csv = "measurements.csv";
const vcd = "signals.vcd";
const filenames = [html, pdf, csv, vcd];
const tableColumns = Array.from({ length: 12 }, (_, i) => ({
  id: "ch" + i, title: "Channel_" + String(i + 1).padStart(2, "0"),
}));
function measurementsWindow(totalRows: number): TableWindowPayload {
  return {
    totalRows, offset: 0, limit: totalRows,
    rows: Array.from({ length: totalRows }, (_, i) => ({
      id: String(i), cells: Object.fromEntries(tableColumns.map((c, j) => [c.id, (i + j) * 100])),
    })),
  };
}

function fileTarget(path: string): FileOpenTarget {
  const name = path.split("/").pop();
  const input = { path };
  if (name === html) return { kind: "file", pluginTargets: [{ pluginId: "pdf", viewId: "document", title: "转换为 PDF", input }] };
  if (name === pdf) return { kind: "plugin_view", pluginId: "pdf", viewId: "document", title: "PDF 阅读器", input };
  if (name === csv) return { kind: "plugin_view", pluginId: "csv", viewId: "table", title: "测量数据", input };
  if (name === vcd) return { kind: "plugin_view", pluginId: "vcd", viewId: "waveform", title: "波形", input };
  return { kind: "file" };
}

function pluginView(pluginId: string, path: string, tableWindow: TableWindowPayload): PluginRenderResult {
  if (pluginId === "pdf") return {
    pluginId, viewId: "document", title: "PDF 阅读器", renderer: "document", mode: "snapshot",
    payload: { path, blocks: [], pdf: { artifactId: "manual" } },
  };
  if (pluginId === "csv") return {
    pluginId, viewId: "table", title: "测量数据", renderer: "table", mode: "session", sessionId: "csv-session",
    summary: { columns: tableColumns, defaultPageSize: tableWindow.limit!, totalRows: tableWindow.totalRows }, initialWindow: tableWindow,
  };
  if (pluginId === "vcd") return {
    pluginId, viewId: "waveform", title: "波形", renderer: "waveform", mode: "snapshot",
    payload: {
      path, timescale: "1ns", startTime: 0, endTime: 100,
      tracks: ["clock", "enable"].map((label, index) => ({
        signalId: label, label, width: 1,
        segments: Array.from({ length: 10 }, (_, i) => ({ start: 10 * i, end: 10 * (i + 1), value: String((i + index) % 2) })),
      })),
    },
  };
  throw new Error("Unexpected plugin " + pluginId);
}

// A real, self-contained two-page document for PDF.js, including a valid byte-offset table.
function manualPdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 /MediaBox [0 0 320 380] /Resources << /Font << /F1 5 0 R >> >> >>",
    "<< /Type /Page /Parent 2 0 R /Contents 6 0 R >>",
    "<< /Type /Page /Parent 2 0 R /Contents 7 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ...["Introduction", "Measurements"].map((title, i) => {
      const content = `0.18 0.37 0.52 rg 0 362 320 18 re f BT /F1 20 Tf 24 315 Td (${title}) Tj /F1 12 Tf 0 -32 Td (Field manual - page ${i + 1}) Tj ET\n`;
      return `<< /Length ${content.length} >>\nstream\n${content}endstream`;
    }),
  ];
  let file = "%PDF-1.4\n";
  const offsets = objects.map((object, i) => {
    const offset = file.length;
    file += `${i + 1} 0 obj\n${object}\nendobj\n`;
    return String(offset).padStart(10, "0") + " 00000 n \n";
  });
  const xref = file.length;
  file += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.join("")}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(file, "ascii");
}

function backendPython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const executable = process.platform === "win32" ? "Scripts/python.exe" : "bin/python";
  for (const directory of [process.env.VIRTUAL_ENV, join(root, ".venv"), join(root, "venv")]) {
    if (directory && existsSync(join(directory, executable))) return join(directory, executable);
  }
  return process.platform === "win32" ? "python" : "python3";
}

function tab(page: Page, name: "文件" | "聊天") {
  return page.getByRole("navigation", { name: "主导航" }).getByRole("button", { name, exact: true });
}

function fileRow(page: Page, name: string) {
  return page.getByRole("button", { name: "打开 " + name, exact: true });
}

async function snapshot(page: Page, info: TestInfo, name: string) {
  const path = info.outputPath(name + ".png");
  await page.screenshot({ path, animations: "disabled" });
  await info.attach(name, { path, contentType: "image/png" });
}

async function openPhone(page: Page, width: number, supportsWorkspaceFileBase = true) {
  const bot = { alias: "main", cli_type: "codex", status: "running", working_dir: root, can_operate: true };
  const agents = [{ id: "main", name: "main" }];
  let cwd = root;
  const fileCalls: Array<{ operation: string; path: string }> = [];
  const disposals: string[] = [];
  const streams: Route[] = [];
  const kills: string[] = [];
  // Exercise both the virtualized grid and the small native table.
  const tableWindow = measurementsWindow(width === 360 ? 140 : 6);
  await page.routeWebSocket("**/*", (socket) => socket.close());
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.split("/api/")[1];
    const named = path.startsWith("bots/main/sessions/" + namedSession);
    let data: unknown = {};
    if (path === "auth/me") data = {
      is_logged_in: true, role: "member", account_id: "preview-qa", username: "preview-qa", current_bot_alias: bot.alias,
      capabilities: ["view_bots", "view_bot_status", "view_file_tree", "read_file_content", "view_chat_history", "chat_send", "view_plugins", "run_plugins"],
    };
    else if (path === "bots") data = [bot];
    else if (path === "bots/main" || path === "bots/main/sessions/" + namedSession) {
      data = { bot, agents, session: { working_dir: root, is_processing: false, history_count: 2 } };
    } else if (path === "bots/main/sessions") data = {
      enabled: true, cli_options: [{ cli_type: "codex", available: true }],
      items: [{ id: "main", title: "主会话" }, { id: namedSession, title: "测量复核" }]
        .map((s) => ({ ...s, selected_cli_type: null, effective_cli_type: "codex" })),
    };
    else if (path.endsWith("/agents")) data = { items: agents, active_agent_id: "main" };
    else if (path.endsWith("/conversations")) data = { items: [], active_conversation_id: "" };
    else if (path.endsWith("/favorites") || path === "announcements") data = { items: [] };
    else if (path.endsWith("/history")) {
      const links = `[${named ? "复核参考文件" : "参考文件"}](${directory}/${other}) · [评审笔记](${directory}/${note})`;
      const readings = Array.from({ length: 24 }, (_, i) => `测量记录 ${i + 1} · ${(i * 2.5).toFixed(1)} mV`);
      data = {
        revision: 1, items: [
        { id: "u1", role: "user", turn_id: "t1", content: "查看测量数据", created_at: "2026-11-20T08:00:00Z" },
        { id: "a1", role: "assistant", turn_id: "t1", created_at: "2026-11-20T08:00:02Z", state: "done",
          content: named ? [...readings, links, ...readings].join("\n\n") : links },
        ],
      };
    }
    else if (path.endsWith("/history/delta")) data = { items: [], revision: 1, reset: false };
    else if (path.endsWith("/chat/stream")) { streams.push(route); return; }
    else if (path.endsWith("/kill")) kills.push(path);
    else if (path.endsWith("/terminal-actions/config")) data = { schemaVersion: 1, runtimePlatform: "linux", actions: [] };
    else if (path.endsWith("/pwd")) data = { working_dir: root };
    else if (path.endsWith("/cd")) {
      const target = req.postDataJSON().path;
      cwd = target === "reports" || target === directory ? directory : root;
      data = { working_dir: cwd };
    } else if (path.endsWith("/ls")) {
      const location = url.searchParams.get("path") || cwd;
      const names = location === directory
        ? [...Array.from({ length: 60 }, (_, i) => "record-" + i + ".txt"), note, other]
        : ["reports", ...filenames];
      data = {
        working_dir: location, entries: names.map((name) => ({ name, is_dir: name === "reports" })),
        ...(supportsWorkspaceFileBase ? { supports_workspace_file_base: true } : {}),
      };
    } else if (path.endsWith("/plugins/resolve-file-target")) {
      const filename: string = req.postDataJSON().path;
      fileCalls.push({ operation: "resolve", path: filename });
      data = fileTarget(filename);
    } else if (path.endsWith("/files/read")) {
      const filename = url.searchParams.get("filename")!;
      const filePath = posix.resolve(supportsWorkspaceFileBase && url.searchParams.get("base") === "workspace" ? root : cwd, filename);
      fileCalls.push({ operation: "read", path: filePath });
      if (filePath !== directory + "/" + note && filePath !== directory + "/" + other) {
        return route.fulfill({ status: 404, json: { ok: false, error: { code: "file_not_found", message: filePath } } });
      }
      data = { mode: "head", is_full_content: true, content: filePath.endsWith(note)
        ? `# ${noteTitle}\n\n[Related measurements](./${other})` : "# " + otherTitle };
    } else if (path.endsWith("/open") && path.includes("/plugins/")) {
      const filename = req.postDataJSON().input.path;
      fileCalls.push({ operation: "plugin", path: filename });
      data = pluginView(path.split("/plugins/")[1].split("/")[0], filename, tableWindow);
    } else if (path.endsWith("/artifacts/manual")) {
      return route.fulfill({ contentType: "application/pdf", body: manualPdf() });
    } else if (path.endsWith("/csv-session/window")) data = tableWindow;
    else if (path.endsWith("/files/html-preview")) {
      const filename = req.postDataJSON().filename;
      fileCalls.push({ operation: "html", path: filename });
      data = { session_id: "html-session", entry_path: filename, entry_url: "/api/fixture-dashboard", expires_at: new Date(Date.now() + 300000).toISOString() };
    } else if (path === "fixture-dashboard") {
      return route.fulfill({ contentType: "text/html", body: `<!doctype html><meta charset="utf-8"><button onclick="this.textContent='Recorded'">Record</button>
        <script>addEventListener('load', () => setTimeout(() => parent.postMessage({type:'orbit-html-preview',sessionId:'html-session',event:'ready'}, '*'), 0))</script>` });
    } else if (req.method() === "DELETE") disposals.push(path);
    await route.fulfill({ json: { ok: true, data } });
  });
  await page.setViewportSize({ width, height: width === 360 ? 780 : 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  // Exercise the explicit portrait preference as well as automatic phone layout.
  if (width === 390) await page.addInitScript(() => localStorage.setItem("web-view-mode", "mobile"));
  await page.goto("./");
  await expect(tab(page, "文件")).toBeInViewport();
  return { fileCalls, disposals, streams, kills, resetBrowseDirectory: () => { cwd = root; } };
}

async function checkLayout(page: Page, preview: Locator) {
  const back = preview.getByRole("button", { name: "返回", exact: true });
  await expect(back).toBeInViewport({ ratio: 1 });
  await expect(tab(page, "聊天")).toBeInViewport({ ratio: 1 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const box = (await preview.boundingBox())!;
  expect(box.width).toBeGreaterThan(page.viewportSize()!.width * 0.9);
  expect(box.height).toBeGreaterThan(page.viewportSize()!.height * 0.6);
}

for (const width of [360, 390]) {
  test(`Files keeps its scrolled folder and reserves the preview across Chat at ${width}px`, async ({ page }, info) => {
    const { fileCalls } = await openPhone(page, width);
    const preview = page.getByTestId("mobile-file-preview");
    const chatLink = page.getByRole("link", { name: "参考文件", exact: true });
    let firstRead: Route | undefined;
    await page.route("**/files/read?**", (route) => {
      if (new URL(route.request().url()).searchParams.get("filename")?.endsWith(note) && !firstRead) {
        firstRead = route;
        return;
      }
      return route.fallback();
    });

    await tab(page, "文件").tap();
    await page.getByRole("button", { name: "进入 reports" }).tap();
    const row = fileRow(page, note);
    await row.scrollIntoViewIfNeeded();
    await expect(row).toBeInViewport({ ratio: 1 });
    const scrollTop = () => row.evaluate((el) => {
      for (let p = el.parentElement; p; p = p.parentElement) if (p.scrollHeight > p.clientHeight && /auto|scroll/.test(getComputedStyle(p).overflowY)) return p.scrollTop;
      return 0;
    });
    const before = await scrollTop();
    expect(before).toBeGreaterThan(0);
    const historyLength = await page.evaluate(() => history.length);
    await row.tap();
    await expect(preview).toContainText(note);
    await expect.poll(() => Boolean(firstRead)).toBe(true);
    await expect.poll(() => page.evaluate(() => history.length)).toBe(historyLength + 1);

    async function blockFromChat() {
      await tab(page, "聊天").tap();
      await chatLink.tap();
      await expect(page.getByText("请先关闭当前预览", { exact: true }).first()).toBeVisible();
      await tab(page, "文件").tap();
      await expect(preview).toContainText(note);
      expect(fileCalls.filter((call) => call.path.endsWith(other))).toEqual([]);
    }
    await blockFromChat();
    if (width === 360) {
      await firstRead!.fulfill({ status: 500, json: { ok: false, error: { code: "read_failed", message: "读取失败" } } });
      const retry = preview.getByRole("button", { name: "重试", exact: true });
      await expect(retry).toBeVisible();
      await blockFromChat();
      await retry.tap();
    } else {
      await firstRead!.fallback();
    }
    await expect(preview.getByRole("heading", { name: noteTitle })).toBeVisible();
    await blockFromChat();
    const requestsForNote = () => fileCalls.filter((call) => call.path.endsWith(note)).length;
    const beforeRepeat = requestsForNote();
    await tab(page, "聊天").tap();
    await page.getByRole("link", { name: "评审笔记" }).tap();
    await expect(preview.getByRole("heading", { name: noteTitle })).toBeVisible();
    expect(requestsForNote()).toBe(beforeRepeat);
    expect(await page.evaluate(() => history.length)).toBe(historyLength + 1);
    await preview.getByRole("link", { name: "Related measurements" }).tap();
    await expect(page.getByText("请先关闭当前预览", { exact: true }).first()).toBeVisible();
    await checkLayout(page, preview);
    await snapshot(page, info, `mobile-markdown-${width}`);
    await page.goBack();
    await expect(preview).toBeHidden();
    await expect(row).toBeInViewport({ ratio: 1 });
    expect(await scrollTop()).toBe(before);
    expect(fileCalls.filter((call) => call.path.endsWith(other))).toEqual([]);
    await tab(page, "聊天").tap();
    await chatLink.tap();
    await expect(preview.getByRole("heading", { name: otherTitle })).toBeVisible();
    await expect(preview).toContainText(directory + "/" + other);
    expect(fileCalls.filter((call) => call.operation === "read" && call.path.endsWith(other))).toHaveLength(1);
  });

  test(`PDF paging, session table scrolling and waveform selection at ${width}px`, async ({ page }, info) => {
    const { disposals } = await openPhone(page, width);
    const preview = page.getByTestId("mobile-file-preview");
    const back = preview.getByRole("button", { name: "返回", exact: true });
    await tab(page, "文件").tap();
    await fileRow(page, pdf).tap();
    const next = preview.getByRole("button", { name: "下一页" });
    await expect(next).toBeInViewport({ ratio: 1 });
    await next.tap();
    await expect(preview.getByRole("spinbutton", { name: "页码" })).toHaveValue("2");
    const canvas = preview.locator("canvas[aria-label='第 2 页']");
    await expect(canvas).toBeInViewport();
    await expect(preview.getByTestId("pdf-page")).toHaveAttribute("aria-busy", "false");
    await checkLayout(page, preview);
    await snapshot(page, info, `mobile-pdf-${width}`);
    const fitWidth = (await canvas.boundingBox())!.width;
    await preview.getByRole("combobox", { name: "缩放" }).selectOption({ label: "150%" });
    await expect.poll(async () => (await canvas.boundingBox())?.width ?? 0).toBeGreaterThan(fitWidth);
    await expect(preview.getByTestId("pdf-page")).toHaveAttribute("aria-busy", "false");
    await checkLayout(page, preview);
    await preview.getByRole("button", { name: "上一页" }).tap();
    await expect(preview.getByRole("spinbutton", { name: "页码" })).toHaveValue("1");
    await back.tap();

    await fileRow(page, csv).tap();
    const table = preview.getByRole("table");
    const finalColumn = table.getByRole("columnheader", { name: "Channel_12" });
    await expect(table.getByRole("cell").first()).toBeInViewport();
    await expect(finalColumn).not.toBeInViewport();
    await table.getByRole("cell").first().hover();
    await page.mouse.wheel(2500, 0);
    await expect(finalColumn).toBeInViewport({ ratio: 1 });
    await checkLayout(page, preview);
    await snapshot(page, info, `mobile-table-${width}`);
    await back.tap();
    await expect.poll(() => disposals.filter((p) => p.endsWith("/csv-session")).length).toBe(1);

    await fileRow(page, vcd).tap();
    const chooseSignals = preview.getByRole("button", { name: /^选择信号/ });
    await chooseSignals.tap();
    const signal = preview.getByRole("checkbox", { name: "加载 enable" });
    const track = preview.getByTestId("waveform-grid").getByText("enable", { exact: true });
    await expect(signal).toBeChecked();
    await signal.uncheck();
    await preview.getByRole("button", { name: "返回波形" }).tap();
    await expect(track).toHaveCount(0);
    await chooseSignals.tap();
    await signal.check();
    await preview.getByRole("button", { name: "返回波形" }).tap();
    await expect(track).toBeVisible();
    const axis = preview.getByTestId("waveform-time-axis");
    const scroll = preview.getByTestId("waveform-scroll");
    for (const fraction of [1 / 3, 2 / 3]) {
      const graph = (await axis.boundingBox())!;
      const viewport = (await scroll.boundingBox())!;
      const x1 = Math.max(graph.x, viewport.x);
      const x2 = Math.min(graph.x + graph.width, viewport.x + viewport.width, width);
      expect(x2 - x1).toBeGreaterThan(width * 0.4);
      const tapX = x1 + (x2 - x1) * fraction;
      await page.touchscreen.tap(tapX, graph.y + graph.height / 2);
      const cursor = preview.getByTestId("waveform-cursor");
      await expect(cursor).toBeInViewport();
      await expect.poll(async () => Math.abs((await cursor.boundingBox())!.x - tapX)).toBeLessThan(3);
    }
    await expect(preview.getByText(/^Δt [1-9]/)).toBeVisible();
    await checkLayout(page, preview);
    await snapshot(page, info, `mobile-waveform-${width}`);
  });
}

for (const workspaceBase of [false, true]) {
  const scenario = workspaceBase ? "after the shared directory changes" : "on a browse-relative host";
  test(`opens the selected nested file ${scenario}`, async ({ page }) => {
    const { fileCalls, resetBrowseDirectory } = await openPhone(page, 390, workspaceBase);
    await tab(page, "文件").tap();
    await page.getByRole("button", { name: "进入 reports" }).tap();
    const row = fileRow(page, note);
    await expect(row).toBeVisible();
    if (workspaceBase) resetBrowseDirectory();
    await row.tap();
    await expect(page.getByTestId("mobile-file-preview").getByRole("heading", { name: noteTitle })).toBeVisible();
    expect(fileCalls).toEqual([
      { operation: "resolve", path: directory + "/" + note },
      { operation: "read", path: directory + "/" + note },
    ]);
  });
}

test("the HTML chooser preserves interactive ordinary preview and optional PDF conversion", async ({ page }) => {
  const { fileCalls, disposals } = await openPhone(page, 390);
  await tab(page, "文件").tap();
  const preview = page.getByTestId("mobile-file-preview");
  await fileRow(page, html).tap();
  const ordinary = preview.getByRole("button", { name: "普通预览" });
  const convert = preview.getByRole("button", { name: "转换为 PDF" });
  await expect(ordinary).toBeVisible();
  await expect(convert).toBeVisible();
  expect(fileCalls.map((call) => call.operation)).toEqual(["resolve"]);
  await ordinary.tap();
  const frame = preview.frameLocator("iframe");
  await frame.getByRole("button", { name: "Record", exact: true }).tap();
  await expect(frame.getByRole("button", { name: "Recorded" })).toBeVisible();
  await preview.getByRole("button", { name: "返回", exact: true }).tap();
  await expect.poll(() => disposals.filter((p) => p.endsWith("/html-session")).length).toBe(1);
  await fileRow(page, html).tap();
  await convert.tap();
  await expect(preview.getByTestId("pdf-page")).toHaveAttribute("aria-busy", "false");
  expect(fileCalls.filter((call) => call.operation === "plugin")).toHaveLength(1);
});

for (const legacy of [false, true]) {
  test(`HTML document and hash navigation preserve preview Back ${legacy ? "without" : "with"} the Navigation API`, async ({ page }) => {
    if (legacy) await page.addInitScript(() => Object.defineProperty(window, "navigation", { value: undefined }));
    await openPhone(page, 390);
    const url = new URL(page.url());
    const fixtureScript = fileURLToPath(new URL("../../scripts/html-preview-browser-fixture.py", import.meta.url));
    const fixture = JSON.parse(execFileSync(backendPython(),
      [fixtureScript, url.origin, url.pathname.replace(/\/$/, "")], { encoding: "utf8" })) as {
      session: { session_id: string; entry_path: string };
      resources: Record<string, { status: number; headers: Record<string, string>; body: string }>;
      refreshed: { status: number; headers: Record<string, string>; body: string };
    };
    await page.route("**/files/html-preview*", route => route.fulfill({ json: { ok: true, data: fixture.session } }));
    let refreshed = false;
    await page.route("**/api/file-previews/**", route => {
      const requestUrl = new URL(route.request().url());
      const path = decodeURIComponent(requestUrl.pathname.split(fixture.session.session_id + "/")[1]);
      const resource = refreshed && path.endsWith("/pages/details.html") ? fixture.refreshed
        : fixture.resources[path + requestUrl.search] ?? fixture.resources[path];
      if (!resource) return route.fulfill({ status: 404, body: "" });
      return route.fulfill({ status: resource.status, headers: resource.headers, body: Buffer.from(resource.body, "base64") });
    });
    await tab(page, "文件").tap();
    const preview = page.getByTestId("mobile-file-preview");
    const frame = preview.frameLocator("iframe");
    const origin = await page.evaluate(() => history.state);
    const openHtml = async () => {
      await fileRow(page, html).tap();
      await preview.getByRole("button", { name: "普通预览" }).tap();
      await expect(frame.getByRole("heading", { name: "Interactive HTML" })).toBeVisible();
    };
    const back = () => page.evaluate(() => history.back());
    const expectOrigin = async () => {
      await expect(preview).toBeHidden();
      await expect(fileRow(page, html)).toBeInViewport();
      await expect.poll(() => page.evaluate(() => history.state)).toEqual(origin);
    };

    await openHtml();
    if (!legacy) {
      await expect(frame.locator("h1")).toHaveCSS("color", "rgb(18, 52, 86)");
      await expect(frame.locator("#signed")).toHaveCSS("padding-left", "13px");
      await expect(frame.locator("#signed")).toHaveCSS("background-image", /\/file-previews\/.+\/dist\/assets\/pixel\.svg/);
      await expect(frame.locator("#module")).toHaveText("module ready");
      await expect(frame.locator("#json")).toHaveText("JSON ready");
      await expect(frame.locator("#font")).toHaveText("font ready");
      for (const alt of ["Preview image", "Bundle logo"]) {
        await expect(frame.getByAltText(alt)).toHaveJSProperty("naturalWidth", 24);
      }
      for (const id of ["parent", "storage", "api"]) await expect(frame.locator("#" + id)).toHaveText("blocked");
      await expect(preview.getByRole("button", { name: "刷新", exact: true })).toBeEnabled();
      await frame.getByRole("link", { name: "Contact" }).tap();
      await expect(preview.getByTitle(/contact\/\?via=preview#address$/)).toBeVisible();
      await expect(frame.getByAltText("Map")).toHaveJSProperty("naturalWidth", 10);
      await preview.getByRole("button", { name: "返回入口" }).tap();
      await expect(frame.getByRole("heading", { name: "Interactive HTML" })).toBeVisible();
    }
    const hashTitle = "当前页面：" + encodeURI(fixture.session.entry_path) + "#route";
    await frame.getByRole("link", { name: "Hash route" }).tap();
    await expect(preview.getByTitle(hashTitle)).toBeVisible();
    await back();
    await expectOrigin();

    await openHtml();
    await frame.getByRole("link", { name: "Details" }).tap();
    await expect(frame.getByRole("heading", { name: "Details version 1" })).toBeVisible();
    await back();
    await expectOrigin();

    await openHtml();
    await frame.getByRole("link", { name: "Hash route" }).tap();
    await expect(preview.getByTitle(hashTitle)).toBeVisible();
    await frame.getByRole("link", { name: "Details" }).tap();
    await expect(frame.getByRole("heading", { name: "Details version 1" })).toBeVisible();
    if (!legacy) {
      refreshed = true;
      await preview.getByRole("button", { name: "刷新", exact: true }).tap();
      await expect(frame.getByRole("heading", { name: "Details version 2" })).toBeVisible();
    }
    await preview.getByRole("button", { name: "返回", exact: true }).tap();
    await fileRow(page, csv).tap();
    await expect(preview.getByRole("table")).toBeVisible();
    await back();
    await expectOrigin();
    await page.goForward();
    await expect(preview).toBeHidden();
    await fileRow(page, csv).tap();
    await expect(preview.getByRole("table")).toBeVisible();
    await back();
    await expectOrigin();
  });
}

test("Back restores the named chat, unsent draft and running reply", async ({ page }) => {
  const { streams, kills } = await openPhone(page, 390);
  const options = page.getByRole("button", { name: "聊天选项", exact: true });
  await options.tap();
  await page.getByRole("combobox", { name: "当前聊天会话" }).selectOption(namedSession);
  const link = page.getByRole("link", { name: "复核参考文件" });
  await expect(link).toBeVisible();
  const draft = page.getByPlaceholder("输入消息", { exact: true });
  await draft.fill("请复核记录");
  await page.getByRole("button", { name: "发送", exact: true }).tap();
  await expect.poll(() => streams.length).toBe(1);
  expect(new URL(streams[0].request().url()).pathname).toMatch(new RegExp("/sessions/" + namedSession + "/chat/stream$"));
  await draft.fill("保留这段未发送的草稿");
  const scroll = page.getByTestId("chat-scroll-container");
  await scroll.hover();
  await page.mouse.wheel(0, -400);
  await link.evaluate(element => element.scrollIntoView({ block: "center" }));
  const position = await scroll.evaluate(element => element.scrollTop);
  expect(position).toBeGreaterThan(0);
  expect(await scroll.evaluate(element => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeGreaterThan(100);
  await link.tap();
  const preview = page.getByTestId("mobile-file-preview");
  await expect(preview.getByRole("heading", { name: otherTitle })).toBeVisible();
  await tab(page, "文件").tap();
  await tab(page, "聊天").tap();
  await preview.getByRole("button", { name: "返回", exact: true }).tap();
  await expect.poll(() => scroll.evaluate(element => element.scrollTop)).toBe(position);
  await expect(link).toBeInViewport();
  await expect(options).toContainText("测量复核");
  await expect(draft).toHaveValue("保留这段未发送的草稿");
  const done = { type: "done", turn_id: "turn-review", assistant_message_id: "a2", output: "测量复核完成" };
  await streams[0].fulfill({ contentType: "text/event-stream", body: "event: done\ndata: " + JSON.stringify(done) + "\n\n" });
  await expect(page.getByText("测量复核完成", { exact: true })).toBeVisible();
  expect(streams).toHaveLength(1);
  expect(kills).toEqual([]);
});

test("leaving forced portrait releases a pending plugin and the desktop PDF pane can page independently", async ({ page }, info) => {
  const { disposals } = await openPhone(page, 390);
  await page.setViewportSize({ width: 1440, height: 900 });
  await tab(page, "文件").tap();
  let opening: Route | undefined;
  await page.route("**/plugins/csv/views/table/open", route => { opening = route; });
  await fileRow(page, csv).tap();
  await expect.poll(() => Boolean(opening)).toBe(true);
  await page.getByRole("button", { name: "视图模式" }).tap();
  await page.getByRole("menuitemradio", { name: "横屏版" }).tap();
  await expect(page.getByTestId("desktop-workbench-columns")).toBeVisible();
  await opening!.fallback();
  await expect.poll(() => disposals.filter(path => path.endsWith("/csv-session")).length).toBe(1);
  await expect(page.getByTestId("mobile-file-preview")).toHaveCount(0);
  await page.getByRole("button", { name: "隐藏终端", exact: true }).click();
  await fileRow(page, pdf).click();
  const viewer = page.getByTestId("desktop-plugin-view");
  await viewer.getByRole("button", { name: "下一页" }).click();
  await expect(viewer.getByRole("spinbutton", { name: "页码" })).toHaveValue("2");
  await expect(viewer.getByTestId("pdf-page")).toHaveAttribute("aria-busy", "false");
  await snapshot(page, info, "desktop-pdf");
});
