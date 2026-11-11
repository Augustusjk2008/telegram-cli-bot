// Browser smoke check without starting a server: bundle the shared workbench
// with an in-memory SSH API fixture.
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
  plugins: [{
    name: "asset-url-fixture",
    setup(bundler) {
      bundler.onResolve({ filter: /\?url$/ }, (args) => ({ path: args.path, namespace: "asset-url-fixture" }));
      bundler.onLoad({ filter: /.*/, namespace: "asset-url-fixture" }, () => ({ contents: 'export default ""', loader: "js" }));
    },
  }],
  define: { "process.env.NODE_ENV": '"production"', "import.meta.env": '{}', "__APP_VERSION__": '"test"' },
  stdin: { loader: "tsx", resolveDir: root, contents: `
    import { useState } from "react";
    import { createRoot } from "react-dom/client";
    import { RemoteWorkspacePicker } from "./src/components/RemoteWorkspacePicker";
    import { RemoteSshMenu } from "./src/components/RemoteSshMenu";
    import { applyResolvedAppearance } from "./src/theme/appearanceRuntime";
    import { builtinLibrary, resolveAppearance } from "./src/theme/resolveAppearance";
    import { FilesScreen } from "./src/screens/FilesScreen";
    import { DesktopWorkbench } from "./src/workbench/DesktopWorkbench";
    import { PersistentTerminalProvider } from "./src/terminal/PersistentTerminalProvider";
    import { WebApiClientError } from "./src/services/types";
    const themes = builtinLibrary().themes;
    applyResolvedAppearance(resolveAppearance(themes.find((theme) => theme.appearance.colors.scheme === window.remoteThemeScheme) || themes[0]));
    const windows = window.remotePlatform === "windows";
    const remote = { connectionId: "ssh-1", host: windows ? "windows.test" : "linux.test", port: 22, username: "dev", root: windows ? "/C:/Users/dev" : "/home/dev", hostKeyFingerprint: "SHA256:browser-check", ...(windows ? { platform: "windows" } : {}) };
    let currentPath = remote.root;
    const uploads = [];
    window.remoteSmoke = { connections: 0, confirmed: false, writes: 0, localCalls: [], directories: [], platform: "", uploads, listings: 0, passwordSaved: false, lastConnection: null, reconnected: false };
    const client = {
      async getRemoteCredentialStatus() { return { passwordSaved: window.remoteSmoke.passwordSaved }; },
      async connectRemote(input, botAlias) {
        window.remoteSmoke.connections++;
        window.remoteSmoke.platform = input.platform;
        if (!botAlias && !input.hostKeyFingerprint) throw new WebApiClientError("Unknown host", { code: "remote_host_key_unknown", status: 409, data: { fingerprint: remote.hostKeyFingerprint } });
        window.remoteSmoke.confirmed = input.hostKeyFingerprint === remote.hostKeyFingerprint;
        window.remoteSmoke.passwordSaved = Boolean(input.rememberPassword);
        window.remoteSmoke.lastConnection = input;
        return remote;
      },
      async listRemoteDirectories(_id, dir) { window.remoteSmoke.directories.push(dir); return { workingDir: dir, entries: dir === remote.root || dir === "/D:/" ? [{ name: "project", isDir: true }] : [] }; },
      async getCurrentPath() { return currentPath; },
      async listFiles(_alias, dir) {
        window.remoteSmoke.listings++;
        const workingDir = dir || currentPath;
        return { workingDir, entries: [{ name: "README.md", isDir: false }, ...uploads.filter((upload) => upload.path === workingDir).map((upload) => ({ name: upload.name, isDir: false }))] };
      },
      async uploadFile(alias, file) { uploads.push({ alias, name: file.name, path: currentPath }); },
      async revealFileTreePath() { return { rootPath: currentPath, highlightPath: "README.md", expandedPaths: [], branches: { "": [{ name: "README.md", isDir: false }, ...uploads.filter((upload) => upload.path === currentPath).map((upload) => ({ name: upload.name, isDir: false }))] } }; },
      async readFile() { return { content: "Remote workspace text", mode: "head", isFullContent: true, lastModifiedNs: "123", encoding: "utf-8" }; },
      async readFileFull() { return { content: "Remote workspace text", mode: "cat", isFullContent: true, lastModifiedNs: "123", encoding: "utf-8" }; },
      async writeFile() { window.remoteSmoke.writes++; return { lastModifiedNs: "124" }; },
      async getTerminalSession() { return { started: false, closed: false, cwd: remote.root, ptyMode: null, connectionText: "未启动", lastSeq: 0 }; },
      async resolveFileOpenTarget() { window.remoteSmoke.localCalls.push("resolveFileOpenTarget"); throw Error("local-only API"); },
      async getGitOverview() { return { repoFound: false, canInit: false, workingDir: currentPath, changedFiles: [], recentCommits: [] }; },
      async getGitTreeStatus() { return { repoFound: false, workingDir: currentPath, items: {} }; },
      async syncWorkspaceDocuments() { window.remoteSmoke.localCalls.push("syncWorkspaceDocuments"); throw Error("local-only API"); },
    };
    function Harness() {
      const [selected, setSelected] = useState(null);
      if (window.reconnectSmoke) return <main className="p-4"><RemoteSshMenu client={client} botAlias="remote" remote={remote} compact onConnected={() => { window.remoteSmoke.reconnected = true; }} /></main>;
      if (window.workbenchSmoke) return <PersistentTerminalProvider client={client}><DesktopWorkbench
        botAlias="remote" client={client} remoteWorkspace={remote} chatPaneContent={<div className="p-4">Remote agent chat</div>}
      /></PersistentTerminalProvider>;
      return selected ? <div style={{ height: "100dvh" }}><FilesScreen client={client} botAlias="remote" remoteWorkspace={selected} /></div>
        : <main className="mx-auto max-w-lg space-y-4 p-4"><h1 className="text-lg font-semibold">远程 SSH 工作区</h1><RemoteWorkspacePicker client={client} onPick={(workspace) => { currentPath = workspace.root; setSelected(workspace); }} /></main>;
    }
    createRoot(document.getElementById("root")).render(<Harness />);
  ` },
});
const assets = path.join(root, "dist/assets");
const cssNames = (await readdir(assets)).filter((name) => name.endsWith(".css"));
const css = (await Promise.all(cssNames.map((name) => readFile(path.join(assets, name), "utf8")))).join("\n");
const output = path.join(root, "test-results/remote-workspace");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : process.platform === "win32" ? { channel: "chrome" } : {}) });
try {
  for (const platform of ["posix", "windows"]) {
    for (const viewport of [{ width: 390, height: 844 }, { width: 1280, height: 900 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setContent('<html><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
      await page.addStyleTag({ content: css });
      await page.evaluate((platform) => { window.remotePlatform = platform; }, platform);
      await page.addScriptTag({ content: result.outputFiles[0].text });
      await page.getByLabel("目标系统").selectOption(platform);
      await page.getByLabel("SSH 主机", { exact: true }).fill(platform === "windows" ? "windows.test" : "linux.test");
      await page.getByLabel("SSH 用户名").fill("dev");
      await page.getByLabel("SSH 密码").fill("fixture-password");
      await page.getByRole("button", { name: "测试并连接 SSH" }).click();
      await page.getByText("SHA256:browser-check", { exact: true }).waitFor();
      assert.equal(await page.evaluate(() => window.remoteSmoke.connections), 1);
      await page.screenshot({ path: path.join(output, `host-confirmation-${platform}-${viewport.width}.png`), fullPage: true });
      await page.getByRole("button", { name: "信任此主机密钥并连接" }).click();
      if (platform === "windows") {
        await page.getByLabel("远程目录路径").fill("c:\\");
        await page.getByRole("button", { name: "打开", exact: true }).click();
        await page.waitForFunction(() => document.querySelector('[aria-label="远程目录路径"]').value === "/C:/");
        assert.equal(await page.getByRole("button", { name: "上级目录" }).isDisabled(), true);
        await page.getByLabel("远程目录路径").fill("d:\\");
        await page.getByRole("button", { name: "打开", exact: true }).click();
      }
      await page.getByRole("button", { name: "📁 project" }).click();
      await page.getByLabel("远程目录路径").waitFor();
      await page.waitForFunction((expected) => document.querySelector('[aria-label="远程目录路径"]').value === expected, platform === "windows" ? "/D:/project" : "/home/dev/project");
      await page.getByRole("button", { name: "选择此远程工作目录" }).click();
      await page.getByRole("button", { name: "打开 README.md" }).waitFor();
      const listingsBeforeUpload = await page.evaluate(() => window.remoteSmoke.listings);
      await page.getByLabel("上传文件", { exact: true }).setInputFiles({ name: "report.txt", mimeType: "text/plain", buffer: Buffer.from("remote upload") });
      await page.getByRole("button", { name: "打开 report.txt" }).waitFor();
      assert.deepEqual(await page.evaluate(() => window.remoteSmoke.uploads), [{ alias: "remote", name: "report.txt", path: platform === "windows" ? "/D:/project" : "/home/dev/project" }]);
      assert.equal(await page.evaluate((count) => window.remoteSmoke.listings > count, listingsBeforeUpload), true);
      await page.getByRole("button", { name: "更多操作 report.txt" }).click();
      assert.equal(await page.getByRole("menuitem", { name: /重命名|删除/ }).count(), 0);
      await page.keyboard.press("Escape");
      assert.equal(await page.evaluate(() => window.remoteSmoke.confirmed), true);
      assert.equal(await page.evaluate(() => window.remoteSmoke.platform), platform);
      assert.equal(await page.evaluate(() => window.remoteSmoke.directories.includes("/")), false);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "horizontal overflow");
      assert.deepEqual(errors, []);
      await page.screenshot({ path: path.join(output, `files-${platform}-${viewport.width}.png`), fullPage: true });
      await page.close();
    }
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("https://remote-workspace.invalid/", (route) => route.fulfill({ contentType: "text/html", body: '<html><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>' }));
    await page.route("**/assets/app-logo*.svg", async (route) => route.fulfill({ contentType: "image/svg+xml", body: await readFile(path.join(root, "public/assets/app-logo.svg"), "utf8") }));
    await page.goto("https://remote-workspace.invalid/");
    await page.addStyleTag({ content: css });
    await page.evaluate((platform) => { window.workbenchSmoke = true; window.remotePlatform = platform; }, platform);
    await page.addScriptTag({ content: result.outputFiles[0].text });
    await page.getByText("Remote agent chat", { exact: true }).waitFor();
    await page.getByRole("button", { name: "更多文件操作", exact: true }).click();
    const [chooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByRole("menuitem", { name: "上传文件", exact: true }).click(),
    ]);
    await chooser.setFiles({ name: "desktop-upload.txt", mimeType: "text/plain", buffer: Buffer.from("desktop remote upload") });
    await page.getByRole("button", { name: "打开 desktop-upload.txt" }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.remoteSmoke.uploads), [{ alias: "remote", name: "desktop-upload.txt", path: platform === "windows" ? "/C:/Users/dev" : "/home/dev" }]);
    await page.getByRole("button", { name: "打开 README.md" }).click();
    await page.getByRole("tab", { name: "README.md" }).waitFor();
    await page.getByRole("button", { name: "隐藏终端", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.remoteSmoke.localCalls), []);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "workbench horizontal overflow");
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, `workbench-${platform}-1280.png`), fullPage: true });
    await page.close();
  }
  for (const scheme of ["light", "dark"]) {
    for (const viewport of [{ width: 390, height: 844 }, { width: 1280, height: 900 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setContent('<html><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
      await page.addStyleTag({ content: css });
      await page.evaluate((scheme) => { window.reconnectSmoke = true; window.remoteThemeScheme = scheme; }, scheme);
      await page.addScriptTag({ content: result.outputFiles[0].text });
      await page.getByRole("button", { name: "SSH 连接", exact: true }).click();
      await page.getByRole("button", { name: "SSH 重新登录", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "SSH 重新登录", exact: true });
      await dialog.getByLabel("SSH 密码", { exact: true }).fill("fixture-password");
      await dialog.getByRole("checkbox", { name: "记住密码" }).check();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, "SSH dialog horizontal overflow");
      const bounds = await dialog.boundingBox();
      assert.ok(bounds && bounds.y >= 0 && bounds.y + bounds.height <= viewport.height + 1, "SSH dialog fits viewport");
      await page.screenshot({ path: path.join(output, `ssh-login-${scheme}-${viewport.width}.png`), fullPage: true, animations: "disabled" });
      await dialog.getByRole("button", { name: "测试并连接 SSH" }).click();
      await dialog.waitFor({ state: "hidden" });
      assert.equal(await page.evaluate(() => window.remoteSmoke.passwordSaved), true);
      await page.getByRole("button", { name: "SSH 连接", exact: true }).click();
      await page.getByRole("button", { name: "SSH 重新登录", exact: true }).click();
      await dialog.getByText("已保存密码，输入新密码可更新。", { exact: true }).waitFor();
      assert.equal(await dialog.getByLabel("SSH 密码", { exact: true }).inputValue(), "");
      await page.screenshot({ path: path.join(output, `ssh-saved-${scheme}-${viewport.width}.png`), fullPage: true, animations: "disabled" });
      await dialog.getByRole("checkbox", { name: "记住密码" }).uncheck();
      await dialog.getByRole("button", { name: "测试并连接 SSH" }).click();
      await dialog.waitFor({ state: "hidden" });
      const input = await page.evaluate(() => window.remoteSmoke.lastConnection);
      assert.equal(input.useSavedPassword, true);
      assert.equal(input.rememberPassword, false);
      assert.equal("password" in input, false);
      assert.equal(await page.evaluate(() => window.remoteSmoke.passwordSaved), false);
      assert.deepEqual(errors, []);
      await page.close();
    }
  }
  console.log("SSH remember, reconnect and forget passed in light/dark themes at 390px and 1280px.");
  console.log("Remote POSIX/Windows SSH shared UI and uploads passed at 390px and 1280px; no server started.");
} finally { await browser.close(); }
