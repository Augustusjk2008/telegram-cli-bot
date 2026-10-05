import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import { ChatScreen } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { HtmlPreviewSession } from "../services/types";
import { SoloWorkbench } from "../workbench/SoloWorkbench";

function session(sessionId: string): HtmlPreviewSession {
  return { sessionId, entryUrl: `${window.location.origin}/api/file-previews/${sessionId}/index.html`, entryPath: "index.html", expiresAt: new Date(Date.now() + 60000).toISOString() };
}

test("mobile files close a pending HTML session without reopening the dialog or reading source", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: "C:/site", entries: [{ name: "index.html", isDir: false }] });
  let resolve!: (value: HtmlPreviewSession) => void;
  vi.spyOn(client, "createHtmlPreview").mockReturnValue(new Promise((done) => { resolve = done; }));
  const read = vi.spyOn(client, "readFile");
  const close = vi.spyOn(client, "closeHtmlPreview");
  render(<FilesScreen botAlias="main" client={client} />);
  fireEvent.click(await screen.findByRole("button", { name: "打开 index.html" }));
  const dialog = await screen.findByRole("dialog", { name: "index.html" });
  await waitFor(() => expect(client.createHtmlPreview).toHaveBeenCalledTimes(1));
  expect(within(dialog).queryByRole("button", { name: "全文读取" })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
  await act(async () => { resolve(session("late")); });
  expect(screen.queryByRole("dialog", { name: "index.html" })).not.toBeInTheDocument();
  expect(read).not.toHaveBeenCalled();
  expect(close.mock.calls).toEqual([["main", "late", undefined]]);
});

test("Solo switches away from HTML and recreates a session on return; workspace change closes it", async () => {
  const client = new MockWebBotClient();
  const create = vi.spyOn(client, "createHtmlPreview").mockResolvedValueOnce(session("one")).mockResolvedValueOnce(session("two"));
  const close = vi.spyOn(client, "closeHtmlPreview");
  const props = {
    botAlias: "main", client, workspaceName: "C:/site", viewMode: "desktop" as const, sessionSnapshot: null,
    onViewModeChange: vi.fn(), onOpenBotSwitcher: vi.fn(), onLogout: vi.fn(),
    chatPaneContent: ({ requestPreview }: { requestPreview: (path: string) => void }) => <button onClick={() => requestPreview("index.html")}>打开 HTML</button>,
  };
  const { rerender } = render(<SoloWorkbench {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "打开 HTML" }));
  await waitFor(() => expect(document.querySelector('iframe[title="index.html"]')).toHaveAttribute("src", session("one").entryUrl));
  fireEvent.click(screen.getByRole("tab", { name: "会话信息" }));
  expect(close.mock.calls).toEqual([["main", "one", undefined]]);
  fireEvent.click(screen.getByRole("tab", { name: "index.html" }));
  await waitFor(() => expect(document.querySelector('iframe[title="index.html"]')).toHaveAttribute("src", session("two").entryUrl));
  expect(create).toHaveBeenCalledTimes(2);
  expect(close).toHaveBeenCalledTimes(1);
  rerender(<SoloWorkbench {...props} workspaceName="C:/another-site" />);
  expect(screen.queryByRole("tab", { name: "index.html" })).not.toBeInTheDocument();
  expect(close.mock.calls).toEqual([["main", "one", undefined], ["main", "two", undefined]]);
});

test.each(["bot", "hidden"])("chat HTML links close their scoped iframe on %s switch", async (change) => {
  const client = new MockWebBotClient();
  const overview = await client.getBotOverview("main");
  vi.spyOn(client, "getBotOverview").mockResolvedValue({ ...overview, workingDir: "C:/site" });
  vi.spyOn(client, "listMessages").mockResolvedValue({ items: [{ id: "html-link", role: "assistant", text: "[查看页面](index.html)", state: "done", createdAt: "2026-10-04T00:00:00Z" }] });
  const create = vi.spyOn(client, "createHtmlPreview").mockResolvedValue(session("chat"));
  const close = vi.spyOn(client, "closeHtmlPreview");
  const read = vi.spyOn(client, "readFile");
  const { rerender } = render(<ChatScreen botAlias="main" client={client} />);
  fireEvent.click(await screen.findByRole("link", { name: "查看页面" }));
  await waitFor(() => expect(document.querySelector("iframe")).toHaveAttribute("src", session("chat").entryUrl));
  expect(create).toHaveBeenCalledWith("main", expect.stringMatching(/index\.html$/), { agentId: "main" });
  expect(read).not.toHaveBeenCalled();
  rerender(<ChatScreen botAlias={change === "bot" ? "another" : "main"} client={client} isVisible={change !== "hidden"} />);
  expect(document.querySelector("iframe")).toBeNull();
  expect(close.mock.calls).toEqual([["main", "chat", { agentId: "main" }]]);
});
