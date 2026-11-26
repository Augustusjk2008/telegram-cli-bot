import { afterEach, describe, expect, it, vi } from "vitest";
import appShell from "../../index.html?raw";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import { WebApiClientError } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

function ok(data: unknown) {
  return Response.json({ ok: true, data });
}

function html(body: string, status = 200) {
  return new Response(body, { status, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

describe("named Web chat client", () => {
  it("confirms the same Bot's authenticated overview before accepting an old host's SPA fallback", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(html(appShell))
      .mockResolvedValueOnce(ok({ bot: { alias: "bot" }, session: {} }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new RealWebBotClient();
    await expect(client.listChatSessions("Bot")).resolves.toEqual({
      enabled: false, items: [{ id: "main", title: "主会话" }],
    });
    expect(fetchMock.mock.calls).toEqual([
      ["/api/bots/Bot/sessions", expect.objectContaining({ credentials: "same-origin" })],
      ["/api/bots/Bot", expect.objectContaining({ credentials: "same-origin" })],
    ]);
  });

  it.each([
    ["503 HTML", () => html(appShell, 503)],
    ["a sign-in page", () => html("<html><title>Sign in</title><div id='root'></div></html>")],
    ["401 JSON", () => Response.json({ ok: false, error: { code: "unauthorized" } }, { status: 401 })],
    ["invalid JSON", () => new Response('{"ok":true,', { headers: { "Content-Type": "application/json" } })],
    ["invalid catalog data", () => ok({})],
  ] as const)("keeps the catalog error visible for %s", async (_label, response) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response());
    vi.stubGlobal("fetch", fetchMock);
    const catalog = new RealWebBotClient().listChatSessions("bot");
    await expect(catalog).rejects.toThrow();
    await expect(catalog).rejects.not.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("propagates a failed overview probe and a failed catalog fetch", async () => {
    const offline = new TypeError("Failed to fetch");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(html(appShell))
      .mockResolvedValueOnce(Response.json({ ok: false, error: { code: "forbidden" } }, { status: 403 }))
      .mockRejectedValue(offline);
    vi.stubGlobal("fetch", fetchMock);
    const client = new RealWebBotClient();
    await expect(client.listChatSessions("bot")).rejects.toMatchObject({ status: 403, code: "forbidden" });
    await expect(client.listChatSessions("bot")).rejects.toBe(offline);
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/bots/bot/sessions", "/api/bots/bot", "/api/bots/bot/sessions", "/api/bots/bot/sessions",
    ]);
  });

  it("keeps a missing Bot distinct from a confirmed missing catalog route", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(html(appShell))
      .mockResolvedValueOnce(Response.json({
        ok: false, error: { code: "bot_not_found", message: "Bot 不存在" },
      }, { status: 404 })));
    const catalog = new RealWebBotClient().listChatSessions("bot");
    await expect(catalog).rejects.toThrow("Bot 不存在");
    await expect(catalog).rejects.not.toMatchObject({ status: 404 });
  });

  it.each(["bot_chat_capacity", "session_busy"])("preserves %s from an HTTP 200 SSE error", async (code) => {
    const message = "此会话暂时无法接受新的任务";
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(
      `event: error\ndata: ${JSON.stringify({ type: "error", code, message })}\n\n`,
      { headers: { "Content-Type": "text/event-stream" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const client = new RealWebBotClient().forChatSession("bot", "review");
    const send = client.sendMessage("bot", "keep queued", vi.fn());
    await expect(send).rejects.toBeInstanceOf(WebApiClientError);
    await expect(send).rejects.toMatchObject({ code, message });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves the API status and error code when chat admission fails before streaming", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({
      ok: false, error: { code: "session_busy", message: "正在执行任务" },
    }, { status: 409 })));
    await expect(new RealWebBotClient().sendMessage("bot", "keep queued", vi.fn()))
      .rejects.toMatchObject({ name: "WebApiClientError", status: 409, code: "session_busy" });
  });

  it("lists and creates sessions without changing the active transport", async () => {
    window.history.replaceState(null, "", "/node/test-host/");
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/test-host" });
    const alias = "bot A";
    const base = "/node/test-host/api/bots/bot%20A";
    const item = { id: "session/one", title: "Reviews" };
    const list = { enabled: true, items: [{ id: "main", title: "主会话" }, item] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(ok(list))
      .mockResolvedValueOnce(ok(item))
      .mockResolvedValueOnce(ok({ items: [] }))
      .mockResolvedValueOnce(ok({ items: [] }))
      .mockResolvedValueOnce(ok({ working_dir: "/repo" }));
    vi.stubGlobal("fetch", fetchMock);
    const root = new RealWebBotClient();
    const named = root.forChatSession(alias, item.id);
    expect(await named.listChatSessions!(alias)).toEqual(list);
    expect(await named.createChatSession!(alias, "Reviews")).toEqual(item);
    expect(root.forChatSession(alias, item.id)).toBe(named);
    expect(named.forChatSession!(alias, "main")).toBe(root);
    expect(() => root.forChatSession(alias, "")).toThrow();
    await Promise.all([named.listMessages(alias), root.listMessages(alias), named.getCurrentPath(alias)]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      base + "/sessions", base + "/sessions", base + "/sessions/session%2Fone/history",
      base + "/history", base + "/pwd",
    ]);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Reviews" }),
    });
    await expect(named.killTask("another-bot")).rejects.toThrow();
    await expect(named.updateClusterConfig(alias, { enabled: true })).rejects.toMatchObject({ code: "chat_session_unsupported" });
    await expect(named.resetSession(alias)).rejects.toMatchObject({ code: "chat_session_unsupported" });
    expect(() => named.connectCodexVoice(alias, { onMessage: vi.fn(), onClose: vi.fn() })).toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("keeps every chat operation on the named route, including when the server rejects it", async () => {
    const fetchMock = vi.fn(async (_url: string, _options: RequestInit) => Response.json({
      ok: false, error: { code: "session_not_found", message: "unknown session" },
    }, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new RealWebBotClient().forChatSession("bot", "missing");
    const requests: Array<[string, string, (client: WebBotClient) => Promise<unknown>]> = [
      ["GET", "", (c) => c.getBotOverview("bot")],
      ["GET", "/history/delta?after_id=last&limit=5&revision=8", (c) => c.listMessageDelta("bot", "last", 5, { revision: 8 })],
      ["GET", "/history/m%2F1/trace?payload=compact", (c) => c.getMessageTrace("bot", "m/1")],
      ["GET", "/history/m%2F1/trace/event?id=t", (c) => c.getMessageTraceEvent!("bot", "m/1", { id: "t" })],
      ["POST", "/history/m%2F1/translation/retry", (c) => c.retryAnswerTranslation("bot", "m/1")],
      ["GET", "/conversations?limit=80&q=proposal", (c) => c.listConversations("bot", "proposal")],
      ["POST", "/conversations", (c) => c.createConversation("bot", "draft")],
      ["POST", "/conversations/c%2F1/select", (c) => c.selectConversation("bot", "c/1")],
      ["POST", "/conversations/c%2F1/archive", (c) => c.archiveConversation("bot", "c/1")],
      ["DELETE", "/conversations/c%2F1?delete_native_session=true", (c) => c.deleteConversation("bot", "c/1", { deleteNativeSession: true })],
      ["DELETE", "/conversations", (c) => c.deleteAllConversations("bot")],
      ["GET", "/favorites", (c) => c.listFavoriteAnswers("bot")],
      ["POST", "/favorites", (c) => c.favoriteAnswer("bot", { conversationId: "c", messageId: "m", messageKey: "k" })],
      ["DELETE", "/favorites/f%2F1", (c) => c.deleteFavoriteAnswer("bot", "f/1")],
      ["POST", "/chat/steer", (c) => c.steerMessage("bot", "change", "turn")],
      ["POST", "/plans/execute", (c) => c.executePlan("bot", { content: "plan" })],
      ["POST", "/kill", (c) => c.killTask("bot")],
    ];
    for (const [method, suffix, run] of requests) {
      await expect(run(client)).rejects.toMatchObject({ code: "session_not_found" });
      const [url, init] = fetchMock.mock.lastCall!;
      expect([init.method ?? "GET", url]).toEqual([method, "/api/bots/bot/sessions/missing" + suffix]);
      expect(init.credentials).toBe("same-origin");
    }
    expect(fetchMock).toHaveBeenCalledTimes(requests.length);
  });

  it("streams from the bound URL with the account's current authorization and SSE message identity", async () => {
    let finishRestore!: (response: Response) => void;
    const frame = { type: "done", turn_id: "t", assistant_message_id: "a", output: "done" };
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRestore = resolve; }))
      .mockResolvedValueOnce(new Response(`event: done\ndata: ${JSON.stringify(frame)}\n\n`))
      .mockResolvedValueOnce(ok({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const root = new RealWebBotClient();
    const named = root.forChatSession("bot", "review");
    const restoring = root.restoreSession("temporary-credential");
    const result = await named.sendMessage("bot", "review this", vi.fn());
    expect(result).toMatchObject({ id: "a", turnId: "t", text: "done" });
    expect(fetchMock.mock.calls[1]).toEqual(["/api/bots/bot/sessions/review/chat/stream", expect.objectContaining({
      credentials: "same-origin", method: "POST",
      headers: { Authorization: "Bearer temporary-credential", "Content-Type": "application/json" },
      body: JSON.stringify({ message: "review this", stream_protocol_version: 2, trace_payload: "compact" }),
    })]);
    finishRestore(ok({}));
    await restoring;
    await named.listMessages("bot");
    expect(fetchMock.mock.calls[2][1].headers).not.toHaveProperty("Authorization");
  });

  it("isolates mock turns, conversation selection and favorites across named sessions", async () => {
    const root = new MockWebBotClient();
    const [a, b] = await Promise.all(["Review", "Design"].map((title) => root.createChatSession("main", title)));
    expect((await root.listChatSessions("main")).items.map((item) => item.id)).toEqual(["main", a.id, b.id]);
    const review = root.forChatSession("main", a.id);
    const design = root.forChatSession("main", b.id);
    const baseline = (await root.listMessages("main")).items.slice();
    const first = await review.sendMessage("main", "Review the design", vi.fn(), undefined, undefined, { taskMode: "plan" });
    const initial = (await review.listConversations("main")).activeConversationId;
    await review.favoriteAnswer("main", { conversationId: initial, messageId: first.id, messageKey: first.id });
    await review.createConversation("main", "Follow-up");
    expect((await review.listMessages("main")).items).toEqual([]);
    await review.selectConversation("main", initial);
    expect((await review.listMessages("main")).items.at(-1)?.id).toBe(first.id);
    expect((await design.listMessages("main")).items).toEqual([]);
    expect((await design.listFavoriteAnswers("main")).items).toEqual([]);
    expect((await root.listMessages("main")).items).toEqual(baseline);
    expect(() => root.forChatSession("team2", a.id)).toThrow();
  });

  it("stops only the requested mock turn and honors the bot's parallel limit", async () => {
    vi.useFakeTimers();
    const root = new MockWebBotClient();
    await root.updateClusterConfig("main", { maxParallelAgents: 2 });
    const clients = await Promise.all(["a", "b", "c"].map(async (title) => {
      const session = await root.createChatSession("main", title);
      return root.forChatSession("main", session.id);
    }));
    const traceEvent = { id: "event-1", kind: "tool_call", summary: "List files" };
    vi.stubGlobal("__ORBIT_MOCK_CHAT_SCRIPT__", { chunks: ["finished"], trace: [traceEvent] });
    const cancelled = expect(clients[0].sendMessage("main", "a", vi.fn())).rejects.toMatchObject({ name: "AbortError" });
    const finished = clients[1].sendMessage("main", "b", vi.fn());
    await expect(clients[2].sendMessage("main", "c", vi.fn())).rejects.toMatchObject({ status: 409, code: "bot_chat_capacity" });
    expect((await clients[0].getBotOverview("main")).isProcessing).toBe(true);
    await clients[0].killTask("main");
    await vi.runAllTimersAsync();
    await cancelled;
    const answer = await finished;
    expect((await clients[1].listMessages("main")).items.at(-1)?.id).toBe(answer.id);
    expect(await clients[1].getMessageTraceEvent!("main", answer.id, { id: traceEvent.id })).toEqual(traceEvent);
    expect(await clients[0].getMessageTraceEvent!("main", answer.id, { id: traceEvent.id })).toBeNull();
    expect((await clients[0].listMessages("main")).items.some((item) => item.role === "assistant")).toBe(false);
    expect((await clients[0].getBotOverview("main")).isProcessing).toBe(false);
  });
});
