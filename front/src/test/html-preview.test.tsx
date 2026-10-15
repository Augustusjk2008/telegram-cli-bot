import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { FilePreviewSurface } from "../components/FilePreviewSurface";
import { useFilePreviewLoader } from "../hooks/useFilePreviewLoader";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { HtmlPreviewSession } from "../services/types";
import { loadFilePreview } from "../utils/filePreview";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function session(sessionId = "ticket"): HtmlPreviewSession {
  return { sessionId, entryUrl: `${window.location.origin}/api/file-previews/${sessionId}/index.html`, entryPath: "index.html", expiresAt: new Date(Date.now() + 60000).toISOString() };
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

test.each(["", "/node/laptop"])("session management retains agent scope and server URL prefix %s", async (prefix) => {
  window.history.replaceState(null, "", `${prefix}/`);
  vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: prefix });
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: { session_id: "ticket", entry_url: `${prefix}/api/file-previews/ticket/index.html`, entry_path: "index.html", expires_at: "2099-01-01T00:00:00Z" } }) });
  vi.stubGlobal("fetch", fetch);
  const client = new RealWebBotClient();
  const value = await client.createHtmlPreview("main", "index.html", { agentId: "worker" });
  expect(value.entryUrl).toBe(`${window.location.origin}${prefix}/api/file-previews/ticket/index.html`);
  expect(fetch).toHaveBeenLastCalledWith(`${prefix}/api/bots/main/files/html-preview?agent_id=worker`, expect.objectContaining({ method: "POST", body: JSON.stringify({ filename: "index.html" }) }));
  await client.closeHtmlPreview("main", value.sessionId, { agentId: "worker" });
  expect(fetch).toHaveBeenLastCalledWith(`${prefix}/api/bots/main/files/html-preview/ticket?agent_id=worker`, expect.objectContaining({ method: "DELETE" }));
});

test("local HTML creates a session without reading source; remote HTML remains static and loads full source", async () => {
  const client = new MockWebBotClient();
  const create = vi.spyOn(client, "createHtmlPreview").mockResolvedValue(session());
  const close = vi.spyOn(client, "closeHtmlPreview");
  const read = vi.spyOn(client, "readFile").mockResolvedValue({ content: "<html>", mode: "head", isFullContent: false, fileSizeBytes: 100 });
  const full = vi.spyOn(client, "readFileFull").mockResolvedValue({ content: "<html><script>run()</script></html>", mode: "cat" });
  const local = await loadFilePreview(client, "main", "index.html", { remote: false, agentId: "worker" });
  expect(local.result).toBeNull();
  expect(await local.htmlPreview!.acquire()).toMatchObject({ sessionId: "ticket" });
  expect(read).not.toHaveBeenCalled();
  expect(full).not.toHaveBeenCalled();
  expect(create).toHaveBeenCalledWith("main", "index.html", { agentId: "worker" });
  local.htmlPreview!.dispose();
  expect(close).toHaveBeenCalledTimes(1);
  const remote = await loadFilePreview(client, "main", "index.html", { remote: true });
  expect(remote.htmlPreview).toBeNull();
  expect(full).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledTimes(1);
  render(<FilePreviewSurface title="index.html" {...remote} />);
  expect(screen.getByTitle("index.html")).toHaveAttribute("sandbox", "");
  expect(screen.getByTitle("index.html")).toHaveAttribute("srcdoc", "<html><script>run()</script></html>");
});

test("unknown workspace must resolve overview before choosing local HTML", async () => {
  const client = new MockWebBotClient();
  const overview = await client.getBotOverview("main");
  const getOverview = vi.spyOn(client, "getBotOverview").mockResolvedValue({ ...overview, remoteWorkspace: { connectionId: "ssh", root: "/srv/site", platform: "posix", host: "example.test", port: 22, username: "user", hostKeyFingerprint: "key" } });
  const create = vi.spyOn(client, "createHtmlPreview");
  vi.spyOn(client, "readFile").mockResolvedValue({ content: "remote", mode: "cat" });
  const data = await loadFilePreview(client, "main", "index.html", { agentId: "worker" });
  expect(getOverview).toHaveBeenCalledWith("main", { agentId: "worker" });
  expect(data.result?.previewKind).toBe("html");
  expect(create).not.toHaveBeenCalled();
  getOverview.mockRejectedValue(new Error("offline"));
  await expect(loadFilePreview(client, "main", "index.html")).rejects.toThrow("offline");
  expect(create).not.toHaveBeenCalled();
});

test("iframe validates bridge messages, refreshes current page and returns to the entry", async () => {
  const client = new MockWebBotClient();
  const value = session();
  vi.spyOn(client, "createHtmlPreview").mockResolvedValue(value);
  const close = vi.spyOn(client, "closeHtmlPreview");
  const data = await loadFilePreview(client, "main", "index.html", { remote: false });
  const { unmount } = render(<FilePreviewSurface title="index.html" {...data} />);
  const frame = await screen.findByTitle<HTMLIFrameElement>("index.html");
  await act(async () => {});
  expect(frame).toHaveAttribute("src", value.entryUrl);
  expect(frame).not.toHaveAttribute("srcdoc");
  expect(frame).toHaveAttribute("sandbox", "allow-scripts allow-forms allow-downloads");
  expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
  const message = { type: "orbit-html-preview", sessionId: value.sessionId, event: "ready", path: "pages/next.html?q=1#/route" };
  fireEvent(window, new MessageEvent("message", { source: window, data: message }));
  fireEvent(window, new MessageEvent("message", { source: frame.contentWindow, data: { ...message, sessionId: "wrong" } }));
  expect(screen.getByRole("button", { name: "刷新" })).toBeDisabled();
  fireEvent(window, new MessageEvent("message", { source: frame.contentWindow, data: message }));
  expect(screen.getByText(message.path)).toBeInTheDocument();
  const post = vi.spyOn(frame.contentWindow!, "postMessage");
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  expect(post).toHaveBeenCalledWith({ type: "orbit-html-preview", sessionId: value.sessionId, command: "refresh" }, "*");
  expect(screen.getByTitle("index.html")).toBe(frame);
  fireEvent(window, new MessageEvent("message", { source: frame.contentWindow, data: message }));
  fireEvent.click(screen.getByRole("button", { name: "返回入口" }));
  expect(screen.getByTitle("index.html")).not.toBe(frame);
  expect(screen.getByTitle("index.html")).toHaveAttribute("src", value.entryUrl);
  expect(screen.getByText("index.html")).toBeInTheDocument();
  unmount();
  data.htmlPreview!.dispose();
  expect(close).toHaveBeenCalledTimes(1);
});

test("failed creation can retry, and a bridge error rebuilds without closing the new session", async () => {
  const client = new MockWebBotClient();
  const create = vi.spyOn(client, "createHtmlPreview").mockRejectedValueOnce(new Error("创建失败")).mockResolvedValueOnce(session("one")).mockResolvedValueOnce(session("two"));
  const close = vi.spyOn(client, "closeHtmlPreview");
  const data = await loadFilePreview(client, "main", "index.html", { remote: false });
  const { unmount } = render(<FilePreviewSurface title="index.html" {...data} />);
  expect(await screen.findByText("创建失败")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  const frame = await screen.findByTitle<HTMLIFrameElement>("index.html");
  fireEvent(window, new MessageEvent("message", { source: frame.contentWindow, data: { type: "orbit-html-preview", sessionId: "one", event: "error", message: "资源不可用" } }));
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await waitFor(() => expect(screen.getByTitle("index.html")).toHaveAttribute("src", session("two").entryUrl));
  expect(create).toHaveBeenCalledTimes(3);
  expect(close.mock.calls).toEqual([["main", "one", undefined]]);
  unmount();
  expect(close.mock.calls).toEqual([["main", "one", undefined], ["main", "two", undefined]]);
});

test("expired session is revoked and retry creates a fresh ticket", async () => {
  vi.useFakeTimers();
  const client = new MockWebBotClient();
  vi.spyOn(client, "createHtmlPreview").mockResolvedValueOnce({ ...session("old"), expiresAt: new Date(Date.now() + 1000).toISOString() }).mockResolvedValueOnce(session("new"));
  const close = vi.spyOn(client, "closeHtmlPreview");
  const data = await loadFilePreview(client, "main", "index.html", { remote: false });
  const { unmount } = render(<FilePreviewSurface title="index.html" {...data} />);
  await act(async () => {});
  await act(async () => { vi.advanceTimersByTime(1001); });
  expect(screen.getByText("预览已过期")).toBeInTheDocument();
  expect(screen.queryByTitle("index.html")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  await act(async () => {});
  expect(screen.getByTitle("index.html")).toHaveAttribute("src", session("new").entryUrl);
  expect(close.mock.calls).toEqual([["main", "old", undefined]]);
  unmount();
});

test.each(["close", "scope", "unmount"])("%s discards pending results and closes late sessions", async (action) => {
  const client = new MockWebBotClient();
  const late = deferred<HtmlPreviewSession>();
  vi.spyOn(client, "createHtmlPreview").mockReturnValue(late.promise);
  const close = vi.spyOn(client, "closeHtmlPreview");
  const hook = renderHook(({ scope }) => useFilePreviewLoader(client, "main", scope), { initialProps: { scope: "workspace:agent-1" } });
  const data = await hook.result.current.load("index.html", { remote: false });
  if (action === "close") hook.result.current.cancel("index.html");
  if (action === "scope") hook.rerender({ scope: "workspace:agent-2" });
  if (action === "unmount") hook.unmount();
  await act(async () => { late.resolve(session("late")); });
  expect(close.mock.calls).toEqual([["main", "late", undefined]]);
  await expect(data!.htmlPreview!.acquire()).rejects.toThrow("预览已关闭");
});

test("scope change while overview is pending discards the result and revokes any created session", async () => {
  const client = new MockWebBotClient();
  const overview = await client.getBotOverview("main");
  const late = deferred<typeof overview>();
  vi.spyOn(client, "getBotOverview").mockReturnValue(late.promise);
  vi.spyOn(client, "createHtmlPreview").mockResolvedValue(session("late"));
  const close = vi.spyOn(client, "closeHtmlPreview");
  const hook = renderHook(({ scope }) => useFilePreviewLoader(client, "main", scope), { initialProps: { scope: "a" } });
  const pending = hook.result.current.load("index.html");
  hook.rerender({ scope: "b" });
  late.resolve(overview);
  expect(await pending).toBeNull();
  expect(close).toHaveBeenCalledWith("main", "late", undefined);
});
