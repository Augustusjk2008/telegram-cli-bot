import { afterEach, describe, expect, it, vi } from "vitest";
import appShell from "../../index.html?raw";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import { CLI_TYPES, WebApiClientError } from "../services/types";
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
      ["GET", "/cli-params?cli_type=antigravity", (c) => c.getCliParams("bot", "antigravity")],
      ["PATCH", "/cli-params", (c) => c.updateCliParam("bot", "effort", "low", "antigravity")],
      ["PATCH", "/cli-params", (c) => c.updateDeepSeekSelection("bot", { provider: "p", model: "m", reasoningEffort: "high" })],
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

  it("resolves model discovery and both settings mutations through the selected named chat", async () => {
    const alias = "team/qa";
    const base = "/api/bots/team%2Fqa";
    const catalog = { enabled: true, cli_options: [], items: [
      { id: "review", title: "Review", selected_cli_type: "antigravity", effective_cli_type: "antigravity" },
      { id: "models", title: "Models", selected_cli_type: "deepseek", effective_cli_type: "deepseek" },
    ] };
    const selection = { provider: "p", model: "pinned-model", reasoningEffort: "high" };
    const fetchMock = vi.fn(async (url: string, _init: RequestInit) => {
      if (url.endsWith("/sessions")) return ok(catalog);
      if (url.includes("/sessions/models/")) return ok({
        cli_type: "deepseek", params: selection, provider_changed: true,
        provider_options: [{ id: "p", label: "Pinned provider" }],
      });
      return ok({
        cli_type: "antigravity", cli_path: "/private/agy",
        params: { model: "m", extra_args: ["private"] }, defaults: { effort: "low", sandbox: true },
        schema: { model: { type: "string", enum: ["m"] }, sandbox: { type: "boolean" } },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const root = new RealWebBotClient();
    await root.listChatSessions(alias);
    const review = root.forChatSession(alias, "review");
    const payload = await review.getCliParams(alias, "antigravity");
    expect(payload).toEqual({
      cliType: "antigravity", params: { model: "m" }, defaults: { effort: "low" },
      schema: { model: { type: "string", enum: ["m"] } },
    });
    expect(await review.updateCliParam(alias, "effort", "low", "antigravity")).toEqual(payload);
    const deepseek = root.forChatSession(alias, "models");
    expect(await deepseek.updateDeepSeekSelection(alias, selection)).toMatchObject({
      cliType: "deepseek", providerChanged: true, providerOptions: [{ id: "p", label: "Pinned provider" }],
    });
    expect(await root.getCliParams(alias)).toMatchObject({ cliPath: "/private/agy", params: { extra_args: ["private"] } });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      base + "/sessions", base + "/sessions/review/cli-params?cli_type=antigravity",
      base + "/sessions/review/cli-params", base + "/sessions/models/cli-params", base + "/cli-params",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[2][1].body))).toEqual({ cli_type: "antigravity", key: "effort", value: "low" });
    expect(JSON.parse(String(fetchMock.mock.calls[3][1].body))).toEqual({
      cli_type: "deepseek", selection: { provider: "p", model: "pinned-model", reasoning_effort: "high" },
    });
  });

  it("uses legacy controls only for sessions identified by a phase-one host", async () => {
    const legacy = { enabled: true, items: [{ id: "legacy", title: "Legacy" }] };
    const newItem = { id: "new", title: "New" };
    const payload = { cli_type: "claude", params: {}, defaults: {}, schema: {}, diagnostic: "/private/path" };
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith("/sessions")) return ok(init.method === "POST" ? newItem : legacy);
      return ok(payload);
    });
    vi.stubGlobal("fetch", fetchMock);
    const root = new RealWebBotClient();
    const named = root.forChatSession("bot", "legacy");
    await root.listChatSessions("bot");
    expect(await named.getCliParams("bot", "claude")).not.toHaveProperty("diagnostic");
    await named.updateCliParam("bot", "model", "m", "claude");
    let finishRefresh!: (response: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRefresh = resolve; }));
    const refreshing = root.listChatSessions("bot");
    await root.createChatSession("bot", newItem.title);
    finishRefresh(ok(legacy));
    await refreshing;
    await root.forChatSession("bot", newItem.id).getCliParams("bot");
    await root.forChatSession("bot", "unlisted").getCliParams("bot");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/bots/bot/sessions", "/api/bots/bot/cli-params?cli_type=claude", "/api/bots/bot/cli-params",
      "/api/bots/bot/sessions", "/api/bots/bot/sessions", "/api/bots/bot/cli-params", "/api/bots/bot/sessions/unlisted/cli-params",
    ]);

    fetchMock.mockResolvedValueOnce(ok({ ...legacy, cli_options: [{ cli_type: "claude", available: true }] }));
    await root.listChatSessions("bot");
    await root.listChatSessions("bot"); // A late phase-one catalog cannot reopen the legacy mutation path.
    fetchMock.mockResolvedValueOnce(Response.json({ ok: false, error: { code: "forbidden" } }, { status: 403 }));
    await expect(named.updateCliParam("bot", "model", "m", "claude")).rejects.toMatchObject({ code: "forbidden" });
    expect(fetchMock.mock.calls.slice(7).map(([url]) => url)).toEqual([
      "/api/bots/bot/sessions", "/api/bots/bot/sessions", "/api/bots/bot/sessions/legacy/cli-params",
    ]);
  });

  it("binds mock chat controls to the effective tool and saves changes in the shared backend namespace", async () => {
    const root = new MockWebBotClient();
    const pinned = await root.createChatSession("main", "Review", "claude");
    const view = root.forChatSession("main", pinned.id);
    const saved = await view.updateCliParam("main", "effort", "low");
    expect(saved).toMatchObject({ cliType: "claude", params: { effort: "low" } });
    expect(saved.schema).not.toHaveProperty("extra_args");
    expect(await root.getCliParams("main", "claude")).toMatchObject({ params: { effort: "low" }, schema: { extra_args: {} } });
    await expect(view.getCliParams("main", "codex")).rejects.toMatchObject({ code: "session_cli_mismatch" });
    await expect(view.updateDeepSeekSelection("main", { provider: "p", model: "m", reasoningEffort: null }))
      .rejects.toMatchObject({ code: "session_cli_mismatch" });
    await expect(view.updateCliParam("main", "extra_args", []))
      .rejects.toMatchObject({ code: "invalid_chat_cli_param" });
  });

  it("maps only public tool metadata and reads the effective CLI from the bound overview", async () => {
    const raw = {
      id: "ses_review", title: "Review", selected_cli_type: "claude", effective_cli_type: "claude",
      cli_path: "/private/cli", cli_params: { extra_args: ["private"] },
    };
    const item = { id: raw.id, title: raw.title, selectedCliType: "claude", effectiveCliType: "claude" };
    const overview = {
      bot: {
        alias: "bot", cli_type: "codex_server", cli_path: "/bot/default", voice: { enabled: true },
        cluster: { tier_configs: { high: { cli_path: "/private/child" } } },
      },
      session: { cli_type: "claude", cli_path: raw.cli_path },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(ok({
        enabled: true, items: [
          raw, { id: "damaged", title: "Old record", selected_cli_type: "unknown", effective_cli_type: "unknown" },
        ],
        cli_options: CLI_TYPES.map((cli_type) => ({ cli_type, available: cli_type !== "deepseek", cli_path: raw.cli_path })),
      }))
      .mockResolvedValueOnce(ok(raw))
      .mockResolvedValueOnce(ok(overview))
      .mockResolvedValueOnce(ok(overview));
    vi.stubGlobal("fetch", fetchMock);
    const root = new RealWebBotClient();
    expect(await root.listChatSessions("bot")).toEqual({
      enabled: true, items: [
        item, { id: "damaged", title: "Old record", selectedCliType: "unknown", effectiveCliType: "unknown" },
      ],
      cliOptions: CLI_TYPES.map((cliType) => ({ cliType, available: cliType !== "deepseek" })),
    });
    expect(await root.createChatSession("bot", "Review", "claude")).toEqual(item);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ title: "Review", cli_type: "claude" });
    const scoped = await root.forChatSession("bot", raw.id).getBotOverview("bot");
    expect(scoped).toMatchObject({ cliType: "claude", voice: { enabled: false } });
    expect(scoped).not.toHaveProperty("cliPath");
    expect(scoped).not.toHaveProperty("cluster");
    expect(await root.getBotOverview("bot")).toMatchObject({ cliType: "codex_server", cliPath: "/bot/default" });
  });

  it("keeps an explicit create failure and never retries the request with just the title", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
      ok: false, error: { code: "cli_unavailable", message: "此工具不可用" },
    }, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(new RealWebBotClient().createChatSession("bot", "Review", "claude"))
      .rejects.toMatchObject({ code: "cli_unavailable" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ title: "Review", cli_type: "claude" });
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

  it("keeps all five pinned mock tools across a default change, while title-only chats follow it", async () => {
    const root = new MockWebBotClient();
    const inherited = await root.createChatSession("main", "Inherit");
    const pinned = await Promise.all(CLI_TYPES.map((type) => root.createChatSession("main", type, type)));
    const views = pinned.map((item) => root.forChatSession("main", item.id));
    await root.updateBotCli("main", "antigravity", "/private/agy");
    const catalog = await root.listChatSessions("main");
    expect(catalog.cliOptions).toEqual(CLI_TYPES.map((cliType) => ({ cliType, available: true })));
    expect(catalog.items.slice(0, 2)).toEqual(["main", inherited.id].map((id) => ({
      id, title: id === "main" ? "主会话" : "Inherit", selectedCliType: null, effectiveCliType: "antigravity", isProcessing: false,
    })));
    expect(await root.forChatSession("main", inherited.id).getBotOverview("main")).toMatchObject({ cliType: "antigravity" });
    for (const [index, cliType] of CLI_TYPES.entries()) {
      expect(catalog.items[index + 2]).toEqual({ ...pinned[index], selectedCliType: cliType, effectiveCliType: cliType });
      const view = views[index];
      expect(await view.getBotOverview("main")).toMatchObject({ cliType, voice: { enabled: false } });
      expect((await view.createConversation("main")).conversation.cliType).toBe(cliType);
    }
  });
});
