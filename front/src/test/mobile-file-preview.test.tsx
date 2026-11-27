import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useMobileFilePreview, type MobileFilePreviewRequest, type MobilePreviewScope } from "../hooks/useMobileFilePreview";
import { runPluginAction } from "../components/plugins/pluginActions";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileOpenTarget, FileReadResult, HtmlPreviewSession, PluginRenderResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const head: FileReadResult = { mode: "head", content: "first line", isFullContent: false };
const full: FileReadResult = { mode: "cat", content: "first line\nsecond line", isFullContent: true };
const table = { pluginId: "csv", viewId: "table", title: "Table", input: { path: "/work/results.csv" } };
const target = { kind: "plugin_view" as const, ...table };
const occupied = "请先关闭当前预览";

function session(sessionId: string): PluginRenderResult {
  return {
    pluginId: target.pluginId, viewId: target.viewId, title: target.title, mode: "session", renderer: "table", sessionId,
    summary: { columns: [], totalRows: 0, defaultPageSize: 20 }, initialWindow: { totalRows: 0, rows: [] },
  };
}

function clientDouble() {
  const client: WebBotClient = new MockWebBotClient();
  return Object.assign(client, {
    resolveFileOpenTarget: vi.fn<WebBotClient["resolveFileOpenTarget"]>().mockResolvedValue({ kind: "file" }),
    readFile: vi.fn<WebBotClient["readFile"]>().mockResolvedValue(head),
    readFileFull: vi.fn<WebBotClient["readFileFull"]>().mockResolvedValue(full),
    createHtmlPreview: vi.fn<WebBotClient["createHtmlPreview"]>(),
    closeHtmlPreview: vi.fn<WebBotClient["closeHtmlPreview"]>().mockResolvedValue(undefined),
    openPluginView: vi.fn<WebBotClient["openPluginView"]>().mockResolvedValue(session("first")),
    disposePluginViewSession: vi.fn<WebBotClient["disposePluginViewSession"]>().mockResolvedValue(undefined),
    downloadPluginArtifact: vi.fn<WebBotClient["downloadPluginArtifact"]>().mockResolvedValue(undefined),
    downloadFile: vi.fn<WebBotClient["downloadFile"]>().mockResolvedValue(undefined),
  });
}

function setup(overrides: Partial<MobilePreviewScope> = {}) {
  const client = clientDouble();
  const scope: MobilePreviewScope = {
    accountId: "alice", botAlias: "dev", workspace: "/work", canRead: true, canWrite: true,
    canUsePlugins: true, canReadAbsolute: false, client, ...overrides,
  };
  const showTab = vi.fn();
  const hook = renderHook((props: MobilePreviewScope) => useMobileFilePreview(props, showTab), { initialProps: scope });
  function file(path: string, extra: Partial<MobileFilePreviewRequest> = {}): MobileFilePreviewRequest {
    return { origin: "files", botAlias: scope.botAlias, directory: scope.workspace, path, client, ...extra };
  }
  return { ...hook, scope, client, file, showTab };
}

// Browser Back/Forward is covered in the real-shell spec. Keep jsdom from scheduling popstate across tests.
beforeEach(() => { vi.spyOn(window.history, "pushState").mockImplementation(() => undefined); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("reserves the first tap synchronously across Files and Chat through resolution, read failure, retry and success", async () => {
  const { result, client, file, showTab } = setup();
  const resolving = deferred<FileOpenTarget>();
  const reading = deferred<FileReadResult>();
  client.resolveFileOpenTarget.mockReturnValueOnce(resolving.promise);
  client.readFile.mockReturnValueOnce(reading.promise);
  const a = file("A #1.md", { directory: "/work/notes" });
  const b = file("notes/B.md", { origin: "chat", sessionId: "ses_other" });
  act(() => { result.current.open(a); result.current.open(b); });
  const id = result.current.preview!.id;
  expect(result.current.notice).toBe(occupied);
  expect(client.resolveFileOpenTarget.mock.calls).toEqual([["dev", "/work/notes/A #1.md"]]);
  expect(client.readFile).not.toHaveBeenCalled();

  act(() => result.current.open(file("/work/notes/../notes/A #1.md", { origin: "chat", sessionId: "ses_other" })));
  expect(result.current.notice).toBe("");
  expect(showTab).toHaveBeenLastCalledWith("files");
  expect(result.current.preview).toMatchObject({ id, request: a });
  await act(async () => resolving.resolve({ kind: "file" }));
  expect(client.readFile.mock.calls).toEqual([["dev", "notes/A #1.md", { workspaceRelative: true }]]);
  act(() => result.current.open(b));
  expect(result.current.notice).toBe(occupied);
  await act(async () => reading.reject(new Error("offline")));
  expect(result.current.preview).toMatchObject({ id, error: "offline", loading: false });
  act(() => result.current.open(b));
  await act(async () => result.current.retry());
  expect(result.current.preview).toMatchObject({ id, data: { result: head }, error: "" });
  act(() => { result.current.requestLink("./B.md"); result.current.open(b); });
  expect(result.current.notice).toBe(occupied);
  expect(result.current.preview?.id).toBe(id);
  expect(client.resolveFileOpenTarget).toHaveBeenCalledTimes(1);
  expect(client.readFile).toHaveBeenCalledTimes(2);
  expect(client.readFile).toHaveBeenLastCalledWith("dev", "notes/A #1.md", { workspaceRelative: true });
  act(() => result.current.close());
  expect(result.current.preview).toBeNull();
  expect(client.resolveFileOpenTarget).toHaveBeenCalledTimes(1);
  await act(async () => result.current.open(b));
  expect(client.resolveFileOpenTarget).toHaveBeenLastCalledWith("dev", "/work/notes/B.md");
  expect(client.readFile).toHaveBeenLastCalledWith("dev", "notes/B.md", { workspaceRelative: true });
  expect(result.current.preview?.request).toBe(b);
});

test.each([
  ["account", { accountId: "bob" }],
  ["workspace", { workspace: "/work-2" }],
  ["file permission", { canRead: false }],
  ["plugin permission", { canUsePlugins: false }],
] as const)("changing %s invalidates the active session and its callbacks", async (_label, change) => {
  const { result, client, file, rerender, scope, unmount } = setup();
  client.resolveFileOpenTarget.mockResolvedValue(target);
  await act(async () => result.current.open(file("results.csv")));
  const previous = result.current;
  expect(previous.preview?.view).toEqual(session("first"));
  rerender({ ...scope, ...change });
  expect(result.current.preview).toBeNull();
  await act(async () => {
    previous.retry();
    await previous.applyHostEffects([{ type: "download_artifact", artifactId: "private", filename: "private.csv" }]);
  });
  unmount();
  expect(client.disposePluginViewSession.mock.calls).toEqual([["dev", "csv", "first"]]);
  expect(client.downloadPluginArtifact).not.toHaveBeenCalled();
  expect(client.openPluginView).toHaveBeenCalledTimes(1);
});

test.each(["switch Bot", "unmount portrait shell"])("a session arriving after %s is released once by its original scoped client", async (change) => {
  const { result, client, file, rerender, scope, unmount } = setup();
  const scoped = clientDouble();
  const pending = deferred<PluginRenderResult>();
  scoped.resolveFileOpenTarget.mockResolvedValue(target);
  scoped.openPluginView.mockReturnValueOnce(pending.promise);
  await act(async () => result.current.open(file("results.csv", { client: scoped, origin: "chat", sessionId: "ses_17" })));
  expect(scoped.openPluginView).toHaveBeenCalledWith("dev", "csv", "table", target.input, { isolatedSession: true });
  if (change === "switch Bot") {
    rerender({ ...scope, botAlias: "other" });
    await act(async () => result.current.open(file("new.md", { botAlias: "other" })));
  } else {
    unmount();
  }
  await act(async () => pending.resolve(session("late")));
  if (change === "switch Bot") {
    expect(result.current.preview).toMatchObject({ path: "/work/new.md", data: { result: head } });
    unmount();
  }
  expect(scoped.disposePluginViewSession.mock.calls).toEqual([["dev", "csv", "late"]]);
  expect(client.disposePluginViewSession).not.toHaveBeenCalled();
});

test("revoking read access while resolving a handler prevents its later result from opening a plugin", async () => {
  const { result, scope, client, file, rerender } = setup();
  const resolving = deferred<FileOpenTarget>();
  client.resolveFileOpenTarget.mockReturnValueOnce(resolving.promise);
  act(() => result.current.open(file("results.csv")));
  rerender({ ...scope, canRead: false });
  await act(async () => resolving.resolve(target));
  expect(result.current.preview).toBeNull();
  expect(client.openPluginView).not.toHaveBeenCalled();
  expect(client.readFile).not.toHaveBeenCalled();
});

test("a mandatory HTML conversion still offers interactive HTML, whose late session closes through the original Bot and agent", async () => {
  const { result, client, file, rerender, scope, unmount } = setup();
  const scoped = clientDouble();
  const pending = deferred<HtmlPreviewSession>();
  const conversion = { ...target, input: { path: "/work/charts/a.html" } };
  scoped.resolveFileOpenTarget.mockResolvedValue(conversion);
  scoped.createHtmlPreview.mockReturnValueOnce(pending.promise);
  await act(async () => result.current.open(file("a.html", {
    origin: "chat", directory: "/work/charts", client: scoped, agentId: "review", sessionId: "ses_34",
  })));
  expect(result.current.preview?.choices).toEqual([conversion]);
  expect(scoped.readFile).not.toHaveBeenCalled();
  expect(scoped.openPluginView).not.toHaveBeenCalled();
  expect(scoped.createHtmlPreview).not.toHaveBeenCalled();
  await act(async () => result.current.readFile("preview"));
  const handle = result.current.preview!.data!.htmlPreview!;
  expect(scoped.createHtmlPreview.mock.calls).toEqual([["dev", "charts/a.html", { agentId: "review", workspaceRelative: true }]]);
  rerender({ ...scope, botAlias: "other" });
  await act(async () => result.current.open(file("safe.md", { botAlias: "other" })));
  await act(async () => pending.resolve({ sessionId: "late-html", entryPath: "a.html", entryUrl: "/frame", expiresAt: "" }));
  expect(result.current.preview?.path).toBe("/work/safe.md");
  await expect(handle.acquire()).rejects.toThrow();
  handle.release();
  unmount();
  expect(scoped.closeHtmlPreview.mock.calls).toEqual([["dev", "late-html", { agentId: "review" }]]);
  expect(client.closeHtmlPreview).not.toHaveBeenCalled();
});

test("refresh replaces only the current plugin session and rejects host effects issued by its predecessor", async () => {
  const { result, client, file, unmount } = setup();
  client.resolveFileOpenTarget.mockResolvedValue({ kind: "file", pluginTargets: [table] });
  await act(async () => result.current.open(file("results.csv")));
  expect(result.current.preview?.choices).toEqual([table]);
  expect(client.readFile).not.toHaveBeenCalled();
  expect(client.openPluginView).not.toHaveBeenCalled();
  await act(async () => result.current.choosePlugin(table));
  const old = result.current;
  await act(() => old.applyHostEffects([{ type: "open_file", path: "other.md" }]));
  expect(result.current.notice).toBe(occupied);
  await act(() => old.applyHostEffects([{ ...table, type: "open_plugin_view", viewId: "other" }]));
  expect(client.resolveFileOpenTarget).toHaveBeenCalledTimes(1);
  expect(client.openPluginView).toHaveBeenCalledTimes(1);

  const closeSession = vi.fn();
  const refreshSession = vi.fn();
  vi.spyOn(client, "invokePluginAction").mockResolvedValueOnce({
    closeSession: true, refresh: "none", hostEffects: [{ type: "open_file", path: "other.md" }],
  });
  await act(async () => {
    await runPluginAction({ id: "next", label: "打开文件", target: "plugin", location: "toolbar" }, {
      client, botAlias: "dev", ...table, sessionId: "first", inputPayload: table.input,
      applyHostEffects: old.applyHostEffects, closeSession, refreshSession,
    });
  });
  expect(closeSession).not.toHaveBeenCalled();
  expect(refreshSession).toHaveBeenCalledWith("csv", "first");

  const firstArtifact = deferred<void>();
  client.downloadPluginArtifact.mockReturnValueOnce(firstArtifact.promise);
  const artifact = { type: "download_artifact" as const, artifactId: "one", filename: "first.csv" };
  const pendingEffects = old.applyHostEffects([artifact, { ...artifact, artifactId: "stale-after-await" }]);
  client.openPluginView.mockResolvedValueOnce(session("refreshed"));
  await act(async () => old.retry());
  expect(result.current.preview).toMatchObject({ id: old.preview!.id, view: session("refreshed") });
  expect(client.resolveFileOpenTarget).toHaveBeenCalledTimes(1);
  expect(client.disposePluginViewSession.mock.calls).toEqual([["dev", "csv", "first"]]);
  await act(async () => { firstArtifact.resolve(); await pendingEffects; });
  await act(() => old.applyHostEffects([{ ...artifact, artifactId: "stale" }]));
  await act(() => result.current.applyHostEffects([{ ...artifact, artifactId: "current" }]));
  expect(client.downloadPluginArtifact.mock.calls.map(([, id]) => id)).toEqual(["one", "current"]);
  act(() => old.closePlugin());
  expect(result.current.preview?.view).toEqual(session("refreshed"));
  unmount();
  expect(client.disposePluginViewSession.mock.calls).toEqual([["dev", "csv", "first"], ["dev", "csv", "refreshed"]]);
});

test("structure-only accounts and requests for another Bot acquire no file or plugin resources", () => {
  const { result, scope, client, rerender, file } = setup({ canRead: false });
  act(() => result.current.open(file("private.html")));
  expect(result.current.preview).toBeNull();
  rerender({ ...scope, canRead: true });
  act(() => result.current.open(file("private.html", { botAlias: "elsewhere" })));
  expect(result.current.preview).toBeNull();
  expect(client.resolveFileOpenTarget).not.toHaveBeenCalled();
  expect(client.openPluginView).not.toHaveBeenCalled();
  expect(client.createHtmlPreview).not.toHaveBeenCalled();
  expect(client.readFile).not.toHaveBeenCalled();
  expect(client.readFileFull).not.toHaveBeenCalled();
});

test("SSH HTML and host-local attachments use static reads from their own clients and paths", async () => {
  const remote = {
    platform: "windows" as const, connectionId: "ssh-1", host: "test", port: 22, username: "dev",
    hostKeyFingerprint: "fingerprint", root: "/C:/project",
  };
  const { result, client, file } = setup({ remote, workspace: remote.root });
  const scoped = clientDouble();
  const attachment = file("D:/Host/Attachments/Exact Case.html", {
    client: scoped, origin: "chat", sessionId: "main", agentId: "main", hostAttachment: true,
  });
  await act(async () => result.current.open(file("report.html", { directory: "/C:/project/sub" })));
  expect(client.readFile.mock.calls).toEqual([["dev", "/C:/project/sub/report.html"]]);
  expect(client.readFileFull.mock.calls).toEqual([["dev", "/C:/project/sub/report.html"]]);
  act(() => result.current.close());
  await act(async () => result.current.open(attachment));
  expect(scoped.readFile.mock.calls).toEqual([["dev", attachment.path]]);
  expect(scoped.readFileFull.mock.calls).toEqual([["dev", attachment.path]]);
  for (const reader of [client, scoped]) {
    expect(reader.resolveFileOpenTarget).not.toHaveBeenCalled();
    expect(reader.openPluginView).not.toHaveBeenCalled();
    expect(reader.createHtmlPreview).not.toHaveBeenCalled();
  }
});

test("full reads and downloads stay anchored to the captured directory, and closing aborts the active download", async () => {
  const { result, file, client } = setup({ canUsePlugins: false });
  const pending = deferred<void>();
  client.downloadFile.mockReturnValueOnce(pending.promise);
  await act(async () => result.current.open(file("a.md", { directory: "/work/sub" })));
  await act(async () => result.current.readFile("full"));
  expect(client.readFileFull.mock.calls).toEqual([["dev", "sub/a.md", { workspaceRelative: true }]]);
  expect(client.resolveFileOpenTarget).not.toHaveBeenCalled();
  const id = result.current.preview!.id;
  let downloading!: Promise<void>;
  act(() => { downloading = result.current.download(); });
  const [alias, path, progress, signal, options] = client.downloadFile.mock.calls[0];
  expect([alias, path, options]).toEqual(["dev", "sub/a.md", { workspaceRelative: true }]);
  act(() => progress!({ downloadedBytes: 12, totalBytes: 50 }));
  expect(result.current.preview).toMatchObject({ id, download: { downloadedBytes: 12 } });
  act(() => result.current.close());
  expect(signal!.aborted).toBe(true);
  await act(async () => result.current.open(file("b.md")));
  await act(async () => {
    progress!({ downloadedBytes: 50, totalBytes: 50 });
    pending.reject(new Error("cancelled"));
    await downloading;
  });
  expect(result.current.preview?.path).toBe("/work/b.md");
  expect(result.current.preview?.download).toBeUndefined();
  expect(result.current.notice).toBe("");
});
