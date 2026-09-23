// Browser smoke check without starting a server: bundle the real components and
// render them in an isolated page with an in-memory SSH API fixture.
import assert from "node:assert/strict";
import { mkdir, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { chromium } from "@playwright/test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const result = await build({
  absWorkingDir: root, bundle: true, write: false, format: "iife", jsx: "automatic",
  loader: { ".css": "empty" },
  define: { "process.env.NODE_ENV": '"production"', "import.meta.env": '{}', "__APP_VERSION__": '"test"' },
  stdin: { loader: "tsx", resolveDir: root, contents: `
    import { useState } from "react";
    import { createRoot } from "react-dom/client";
    import { RemoteWorkspacePicker } from "./src/components/RemoteWorkspacePicker";
    import { RemoteFilesPane } from "./src/components/RemoteFilesPane";
    import { RemoteWorkbench } from "./src/workbench/RemoteWorkbench";
    import { PersistentTerminalProvider } from "./src/terminal/PersistentTerminalProvider";
    import { WebApiClientError } from "./src/services/types";
    const remote = { connectionId: "ssh-1", host: "linux.test", port: 22, username: "dev", root: "/home/dev", hostKeyFingerprint: "SHA256:browser-check" };
    window.remoteSmoke = { connections: 0, confirmed: false, saved: false };
    const client = {
      async connectRemote(input) {
        window.remoteSmoke.connections++;
        if (!input.hostKeyFingerprint) throw new WebApiClientError("Unknown host", { code: "remote_host_key_unknown", status: 409, data: { fingerprint: remote.hostKeyFingerprint } });
        window.remoteSmoke.confirmed = input.hostKeyFingerprint === remote.hostKeyFingerprint;
        return remote;
      },
      async listRemoteDirectories(_id, dir) { return { workingDir: dir, entries: dir === "/home/dev" ? [{ name: "project", isDir: true }] : [] }; },
      async listFiles(_alias, dir) { return { workingDir: dir, entries: [{ name: "README.md", isDir: false }] }; },
      async getTerminalSession() { return { started: false, closed: false, cwd: remote.root, ptyMode: null, connectionText: "未启动", lastSeq: 0 }; },
      async readFileFull() { return { content: "Remote workspace text", mode: "cat", isFullContent: true, lastModifiedNs: "123", encoding: "utf-8" }; },
      async writeFile(_alias, file, content, mtime) {
        window.remoteSmoke.saved = file === "/home/dev/project/README.md" && content === "Updated remote text" && mtime === "123";
        return { lastModifiedNs: "124" };
      },
    };
    function Harness() {
      const [selected, setSelected] = useState(null);
      if (window.workbenchSmoke) return <PersistentTerminalProvider client={client}><RemoteWorkbench
        bot={{ alias: "remote", cliType: "codex", status: "running", workingDir: "C:/control", lastActiveText: "", remoteWorkspace: remote }}
        client={client} authToken="" chat={<div className="p-4">Remote agent chat</div>} canWrite structureOnly={false}
        terminalDisabledReason="" themeName="deep-space" viewMode="desktop" onViewModeChange={() => {}}
        onOpenBotSwitcher={() => {}} onLogout={() => {}} onDirtyChange={() => {}}
      /></PersistentTerminalProvider>;
      return selected ? <div style={{ height: "100dvh" }}><RemoteFilesPane client={client} botAlias="remote" remote={selected} /></div> : <main className="mx-auto max-w-lg space-y-4 p-4"><h1 className="text-lg font-semibold">远程 SSH 工作区</h1><RemoteWorkspacePicker client={client} onPick={setSelected} /></main>;
    }
    createRoot(document.getElementById("root")).render(<Harness />);
  ` },
});
const assets = path.join(root, "dist/assets");
const cssNames = (await readdir(assets)).filter((name) => name.endsWith(".css"));
const css = (await Promise.all(cssNames.map((name) => readFile(path.join(assets, name), "utf8")))).join("\n");
const output = path.join(root, "test-results/remote-workspace");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}) });
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 1280, height: 900 }]) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    page.on("pageerror", (error) => { errors.push(error.message); console.error(error.message); });
    await page.setContent('<html><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
    await page.addStyleTag({ content: css });
    await page.addScriptTag({ content: result.outputFiles[0].text });
    await page.getByLabel("SSH 主机", { exact: true }).fill("linux.test");
    await page.getByLabel("SSH 用户名").fill("dev");
    await page.getByLabel("SSH 密码").fill("fixture-password");
    await page.getByRole("button", { name: "测试并连接 SSH" }).click();
    await page.getByText("SHA256:browser-check", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.remoteSmoke.connections), 1);
    await page.screenshot({ path: path.join(output, `host-confirmation-${viewport.width}.png`), fullPage: true });
    await page.getByRole("button", { name: "信任此主机密钥并连接" }).click();
    await page.getByRole("button", { name: "📁 project" }).click();
    await page.getByLabel("远程目录路径").waitFor();
    await page.waitForFunction(() => document.querySelector('[aria-label="远程目录路径"]').value === "/home/dev/project");
    await page.getByRole("button", { name: "选择此远程工作目录" }).click();
    await page.getByRole("treeitem", { name: "README.md" }).click();
    await page.getByLabel("远程文本编辑器").fill("Updated remote text");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page.waitForFunction(() => window.remoteSmoke.saved);
    assert.equal(await page.evaluate(() => window.remoteSmoke.confirmed), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "horizontal overflow");
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, `files-${viewport.width}.png`), fullPage: true });
    await page.close();
  }
  const workbench = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const workbenchErrors = [];
  workbench.on("pageerror", (error) => { workbenchErrors.push(error.message); console.error(error.message); });
  await workbench.route("https://remote-workspace.invalid/", (route) => route.fulfill({
    contentType: "text/html", body: '<html><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>',
  }));
  await workbench.route("**/assets/app-logo*.svg", async (route) => route.fulfill({
    contentType: "image/svg+xml", body: await readFile(path.join(root, "public/assets/app-logo.svg"), "utf8"),
  }));
  await workbench.goto("https://remote-workspace.invalid/");
  await workbench.addStyleTag({ content: css });
  await workbench.evaluate(() => { window.workbenchSmoke = true; });
  await workbench.addScriptTag({ content: result.outputFiles[0].text });
  await workbench.getByText("Remote agent chat", { exact: true }).waitFor();
  await workbench.getByRole("treeitem", { name: "README.md" }).waitFor();
  await workbench.getByRole("button", { name: "显示底部终端", exact: true }).click();
  await workbench.getByRole("button", { name: "隐藏底部终端", exact: true }).waitFor();
  assert.equal(await workbench.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "workbench horizontal overflow");
  assert.deepEqual(workbenchErrors, []);
  await workbench.screenshot({ path: path.join(output, "workbench-1280.png"), fullPage: true });
  await workbench.close();
  console.log("Remote SSH browser smoke passed at 390px and 1280px; no server started.");
} finally { await browser.close(); }
