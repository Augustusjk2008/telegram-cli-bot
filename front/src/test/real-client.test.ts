import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { EventType } from "../services/agUiProtocol";
import { RealWebBotClient } from "../services/realWebBotClient";
import { buildFileDownloadUrl } from "../utils/fileLinks";

describe("RealWebBotClient", () => {
  const fetchMock = vi.fn();

  function jsonOk(data: unknown) {
    return {
      ok: true,
      json: async () => ({ ok: true, data }),
    };
  }

  function streamOk(...frames: string[]) {
    const encoder = new TextEncoder();
    return {
      ok: true,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          frames.forEach((frame) => controller.enqueue(encoder.encode(frame)));
          controller.close();
        },
      }),
      json: async () => ({ ok: true, data: {} }),
    };
  }

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    vi.stubGlobal("__PUBLIC_ENV__", {});
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  test("uses the active public base path for auth requests and download links", async () => {
    window.history.replaceState(null, "", "/node/nanjing-laptop/");
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/nanjing-laptop" });
    fetchMock.mockResolvedValue(jsonOk({ user_id: 1001 }));

    const session = await new RealWebBotClient().login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/node/nanjing-laptop/api/auth/me",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ Authorization: "Bearer secret-token" }),
      }),
    );
    expect(buildFileDownloadUrl("main", "docs/readme.md")).toBe(
      "/node/nanjing-laptop/api/bots/main/files/download?filename=docs%2Freadme.md",
    );
    expect(session).toMatchObject({ isLoggedIn: true, token: "" });
  });

  test("ignores a stale configured public base path when served from root", async () => {
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/local" });
    fetchMock.mockResolvedValue(jsonOk({ user_id: 1001 }));

    await new RealWebBotClient().login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/me", expect.any(Object));
  });

  test("maps Transfer Admin routes but never re-exposes provider keys from status", async () => {
    const status = {
      enabled: true,
      configured: true,
      running: true,
      status: "running",
      local_url: "http://127.0.0.1:8080",
      bridge_page_url: "/api/transfer/page",
      responses_base_url: "http://127.0.0.1:8080/v1",
      chat_completions_base_url: "http://127.0.0.1:8080/v1",
      provider_api_key: "sk-leaked-top-level",
      provider_api_key_set: true,
      routes: [{
        id: "route-1",
        name: "默认",
        endpoint_mode: "responses",
        litellm_model: "openai/gpt-5",
        model_alias: "gpt-5",
        provider_base_url: "https://provider.example/v1",
        provider_api_key: "sk-leaked-route",
        provider_api_key_set: true,
        configured: true,
      }],
      request_count: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_bytes_in: 0,
      total_bytes_out: 0,
    };
    fetchMock
      .mockResolvedValueOnce(jsonOk(status))
      .mockResolvedValueOnce(jsonOk(status));

    const client = new RealWebBotClient();
    const loaded = await client.getTransferAdminStatus();
    await client.updateTransferBridgeConfig({
      enabled: true,
      routes: [{
        id: "route-1",
        name: "默认",
        endpointMode: "responses",
        litellmModel: "openai/gpt-5",
        modelAlias: "gpt-5",
        providerBaseUrl: "https://provider.example/v1",
        extraLitellmParams: { rpm: 60 },
        providerApiKeySet: true,
        providerApiKey: "sk-new-route-key",
      }],
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/admin/transfer/status",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/transfer/config",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          enabled: true,
          routes: [{
            id: "route-1",
            name: "默认",
            endpoint_mode: "responses",
            litellm_model: "openai/gpt-5",
            model_alias: "gpt-5",
            provider_base_url: "https://provider.example/v1",
            extra_litellm_params: { rpm: 60 },
            provider_api_key: "sk-new-route-key",
          }],
        }),
      }),
    );
    expect(loaded).toMatchObject({ providerApiKeySet: true, routes: [{ providerApiKeySet: true }] });
    expect(loaded).not.toHaveProperty("providerApiKey");
    expect(loaded.routes?.[0]).not.toHaveProperty("providerApiKey");
    expect(JSON.stringify(loaded)).not.toContain("sk-leaked");
  });

  test("maps valid Codex rate limit samples and filters invalid samples", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      rate_limit_samples: [
        {
          sampled_at: "2026-08-11T12:57:53+08:00",
          used_percent: 8,
          window_minutes: 10080,
          resets_at: "2026-08-18T08:01:25+08:00",
          plan_type: "pro",
        },
        {
          sampled_at: "2026-08-11T13:00:00+08:00",
          used_percent: 100,
          window_minutes: 60,
          resets_at: "1970-01-01T00:00:00Z",
        },
        { sampled_at: "invalid", used_percent: 8, window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:01:00+08:00", used_percent: -1, window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:02:00+08:00", used_percent: 101, window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:03:00+08:00", used_percent: "8", window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:04:00+08:00", used_percent: 8, window_minutes: 0, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:05:00+08:00", used_percent: 8, window_minutes: 1.5, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:06:00+08:00", used_percent: 8, window_minutes: 60, resets_at: "invalid" },
        { sampled_at: "2026-08-11T13:07:00+08:00", used_percent: 8, window_minutes: 60, resets_at: "1969-12-31T23:59:59Z" },
      ],
    }));

    const stats = await new RealWebBotClient().getCodexUsageStats();

    expect(fetchMock).toHaveBeenCalledWith("/api/admin/codex-usage/stats", expect.objectContaining({ cache: "no-store" }));
    expect(stats.rateLimitSamples).toEqual([
      {
        sampledAt: "2026-08-11T12:57:53+08:00",
        usedPercent: 8,
        windowMinutes: 10080,
        resetsAt: "2026-08-18T08:01:25+08:00",
        planType: "pro",
      },
      {
        sampledAt: "2026-08-11T13:00:00+08:00",
        usedPercent: 100,
        windowMinutes: 60,
        resetsAt: "1970-01-01T00:00:00Z",
        planType: null,
      },
    ]);
  });

  test("omits cluster task output only when requested", async () => {
    const status = {
      tasks: [],
      queued_count: 0,
      running_count: 0,
      completed_count: 0,
      failed_count: 0,
      pending_count: 0,
    };
    fetchMock.mockResolvedValue(jsonOk(status));
    const client = new RealWebBotClient();

    await client.getClusterTaskStatus("main", "run-1", { includeOutput: false });
    await client.getClusterTaskStatus("main", "run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/bots/main/cluster/runs/run-1/tasks?include_output=0",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/cluster/runs/run-1/tasks?include_output=1",
      expect.any(Object),
    );
  });

  test.each(["meta", "status", "trace", "done"] as const)(
    "preserves top-level turn binding from legacy %s frames",
    async (eventType) => {
      const turnId = `turn-${eventType}`;
      const assistantMessageId = `assistant-${eventType}`;
      const bindingFrame = eventType === "meta"
        ? `event: meta\ndata: {"type":"meta","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}"}\n\n`
        : eventType === "status"
          ? `event: status\ndata: {"type":"status","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}","preview_text":"处理中"}\n\n`
          : eventType === "trace"
            ? `event: trace\ndata: {"type":"trace","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}","event":{"kind":"tool_call","summary":"dir","tool_name":"shell_command"}}\n\n`
            : `event: done\ndata: {"type":"done","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}","output":"完成"}\n\n`;
      const terminalFrame = eventType === "done"
        ? undefined
        : "event: done\ndata: {\"type\":\"done\",\"output\":\"完成\"}\n\n";
      fetchMock.mockResolvedValue(streamOk(...[bindingFrame, terminalFrame].filter((frame): frame is string => Boolean(frame))));

      const statuses: Array<{ turnId?: string; assistantMessageId?: string }> = [];
      const traces: string[] = [];
      const message = await new RealWebBotClient().sendMessage(
        "main",
        "hello",
        () => undefined,
        (status) => statuses.push(status),
        (trace) => traces.push(`${trace.kind}:${trace.summary}`),
      );

      expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
        message: "hello",
        stream_protocol_version: 2,
      });
      expect(message).toMatchObject({ id: assistantMessageId, turnId, text: "完成", state: "done" });
      if (eventType === "meta" || eventType === "status") {
        expect(statuses).toContainEqual(expect.objectContaining({ turnId, assistantMessageId }));
      }
      if (eventType === "trace") {
        expect(traces).toEqual(["tool_call:dir"]);
      }
    },
  );

  test("maps compact CLI v1 and v2 terminal frames to identical final messages", async () => {
    const persistedMessage = {
      id: "assistant-compact-cli",
      turn_id: "turn-compact-cli",
      role: "assistant",
      content: "CLI 最终答复",
      created_at: "2026-08-08T00:00:00Z",
      state: "done",
    };
    const terminalEvents = [
      {
        type: "done",
        turn_id: "turn-compact-cli",
        assistant_message_id: "assistant-compact-cli",
        output: "CLI 最终答复",
        message: persistedMessage,
      },
      {
        type: "done",
        turn_id: "turn-compact-cli",
        assistant_message_id: "assistant-compact-cli",
        message: persistedMessage,
      },
    ];
    const messages = [];
    for (const doneEvent of terminalEvents) {
      fetchMock.mockResolvedValueOnce(streamOk(`event: done\ndata: ${JSON.stringify(doneEvent)}\n\n`));
      messages.push(await new RealWebBotClient().sendMessage("main", "hello", () => undefined));
    }

    expect(messages[0]).toEqual(messages[1]);
    expect(messages[0]).toMatchObject({
      id: "assistant-compact-cli",
      turnId: "turn-compact-cli",
      text: "CLI 最终答复",
      state: "done",
    });
    for (const request of fetchMock.mock.calls) {
      expect(JSON.parse(String(request[1].body))).toMatchObject({ stream_protocol_version: 2 });
    }
  });

  test("uses minimal plugin install, update, and uninstall routes with a trusted dev source path", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({ id: "dev-plugin" }))
      .mockResolvedValueOnce(jsonOk({ id: "dev-plugin", enabled: false }))
      .mockResolvedValueOnce(jsonOk({}));
    const client = new RealWebBotClient();

    await client.installPlugin({
      sourcePath: "C:\\plugins\\dev-plugin",
      force: true,
      allowDevSourcePath: true,
    });
    await client.updatePlugin("dev-plugin", { enabled: false });
    await client.uninstallPlugin("dev-plugin");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/plugins/install", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        sourcePath: "C:\\plugins\\dev-plugin",
        force: true,
        allowDevSourcePath: true,
      }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/plugins/dev-plugin", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ enabled: false }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/plugins/dev-plugin", expect.objectContaining({ method: "DELETE" }));
  });

  test("uses AG-UI for native requests and keeps native trace out of legacy callbacks", async () => {
    fetchMock.mockResolvedValue(streamOk(
      "event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n",
      "event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"activity-1\",\"activityType\":\"TCB_NATIVE_AGENT_TRACE\",\"replace\":true,\"content\":{\"id\":\"activity-1\",\"source\":\"native_agent\",\"rawKind\":\"commentary\",\"summary\":\"检查目录\"}}\n\n",
      "event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"原生完成\"},\"outcome\":{\"type\":\"success\"}}\n\n",
    ));

    const legacyTraces: string[] = [];
    const agUiEvents: string[] = [];
    const message = await new RealWebBotClient().sendMessage(
      "main",
      "hello",
      () => undefined,
      undefined,
      (trace) => legacyTraces.push(trace.summary),
      { executionMode: "native_agent" },
      (event) => agUiEvents.push(event.type),
    );

    const request = fetchMock.mock.calls[0];
    expect(request[0]).toBe("/api/bots/main/chat/stream?protocol=ag-ui");
    expect(JSON.parse(String(request[1].body))).toMatchObject({
      execution_mode: "native_agent",
      protocol: "ag-ui",
      stream_protocol_version: 2,
    });
    expect(agUiEvents).toEqual([EventType.RUN_STARTED, EventType.ACTIVITY_SNAPSHOT, EventType.RUN_FINISHED]);
    expect(legacyTraces).toEqual([]);
    expect(message).toMatchObject({ text: "原生完成", state: "done" });
    expect(message.meta).toMatchObject({ tracePresentation: "native_agent_flat", traceCount: 1 });
  });

  test("maps compact AG-UI v1 and v2 terminal frames to identical final messages", async () => {
    const persistedMessage = {
      id: "assistant-compact-native",
      turn_id: "turn-compact-native",
      role: "assistant",
      content: "原生最终答复",
      created_at: "2026-08-08T00:00:00Z",
      state: "done",
    };
    const results = [
      { content: "原生最终答复", message: persistedMessage },
      { message: persistedMessage },
    ];
    const messages = [];
    for (const result of results) {
      fetchMock.mockResolvedValueOnce(streamOk(
        `event: message\ndata: ${JSON.stringify({
          type: EventType.RUN_FINISHED,
          threadId: "thread-compact-native",
          runId: "run-compact-native",
          result: {
            ...result,
            completion_state: "completed",
            turn_id: "turn-compact-native",
            assistant_message_id: "assistant-compact-native",
          },
          outcome: { type: "success" },
        })}\n\n`,
      ));
      messages.push(await new RealWebBotClient().sendMessage(
        "main",
        "hello",
        () => undefined,
        undefined,
        undefined,
        { executionMode: "native_agent" },
      ));
    }

    expect(messages[0]).toEqual(messages[1]);
    expect(messages[0]).toMatchObject({
      id: "assistant-compact-native",
      turnId: "turn-compact-native",
      text: "原生最终答复",
      state: "done",
    });
  });

  test("drains an unterminated done frame at EOF", async () => {
    fetchMock.mockResolvedValue(streamOk('event: done\ndata: {"type":"done","output":"尾帧最终答复"}'));

    const message = await new RealWebBotClient().sendMessage("main", "hi", () => undefined);

    expect(message).toMatchObject({ text: "尾帧最终答复", state: "done" });
  });

  test("reports incomplete EOF with the server turn binding", async () => {
    fetchMock.mockResolvedValue(streamOk(
      'event: meta\ndata: {"type":"meta","turn_id":"turn-incomplete","assistant_message_id":"assistant-incomplete"}\n\n',
      'event: status\ndata: {"type":"status","preview_text":"仍在处理中"}\n\n',
    ));

    await expect(new RealWebBotClient().sendMessage("main", "hi", () => undefined)).rejects.toMatchObject({
      name: "ChatStreamIncompleteError",
      turnId: "turn-incomplete",
      assistantMessageId: "assistant-incomplete",
      partialMessage: expect.objectContaining({ id: "assistant-incomplete", state: "streaming" }),
    });
  });

  test("deduplicates replayed SSE frames by stream sequence", async () => {
    const frame = "event: trace\nid: 17\ndata: {\"event\":{\"kind\":\"commentary\",\"summary\":\"一次过程\",\"source\":\"codex\"}}\n\n";
    fetchMock.mockResolvedValue(streamOk(frame, frame, "event: done\ndata: {\"output\":\"ok\"}\n\n"));

    const traces: string[] = [];
    const message = await new RealWebBotClient().sendMessage("main", "hi", () => undefined, undefined, (trace) => {
      traces.push(trace.summary);
    });

    expect(traces).toEqual(["一次过程"]);
    expect(message.meta?.trace).toHaveLength(1);
  });

  test("scopes agent history and conversations by agent and execution mode", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({ items: [] }))
      .mockResolvedValueOnce(jsonOk({
        active_conversation_id: "conv-1",
        items: [{
          id: "conv-1",
          title: "审查",
          last_message_preview: "完成",
          message_count: 2,
          pinned: false,
          active: true,
          status: "active",
          bot_alias: "main",
          cli_type: "codex",
          working_dir: "C:\\repo",
          agent_id: "reviewer",
          native_provider: "codex",
          native_session_id: "thread-1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:01:00Z",
        }],
      }));

    const client = new RealWebBotClient();
    const history = await client.listMessages("main", { agentId: "reviewer", executionMode: "native_agent" });
    const conversations = await client.listConversations("main", "", {
      agentId: "reviewer",
      executionMode: "native_agent",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/bots/main/history?agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/conversations?limit=80&agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(conversations.items[0]).toMatchObject({
      agentId: "reviewer",
      nativeSource: { sessionId: "thread-1" },
    });
    expect(history).toEqual({ items: [] });
  });

  test.each([
    [{ items: [], current_revision: 7 }, 7],
    [{ items: [], revision: 0 }, 0],
    [{ items: [] }, undefined],
  ])("maps history snapshot revision from compatible response fields", async (payload, revision) => {
    fetchMock.mockResolvedValueOnce(jsonOk(payload));

    const snapshot = await new RealWebBotClient().listMessages("main");

    expect(snapshot.items).toEqual([]);
    expect(snapshot.revision).toBe(revision);
  });
  test("getCliParams maps the account-aware Codex model catalog", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      cli_type: "codex",
      params: { model: "gpt-5.6-sol", reasoning_effort: "ultra" },
      defaults: { model: "none", reasoning_effort: "medium" },
      schema: {
        model: { type: "string", enum: ["gpt-5.6-sol", "none"] },
        reasoning_effort: { type: "string", enum: ["medium", "ultra"] },
      },
      model_catalog: {
        source: "codex_cli",
        error: "",
        items: [{
          id: "gpt-5.6-sol",
          label: "GPT-5.6-Sol",
          reasoning_efforts: ["medium", "ultra"],
          default_reasoning_effort: "medium",
        }],
      },
    }));

    const result = await new RealWebBotClient().getCliParams("main");

    expect(result.modelCatalog).toEqual({
      source: "codex_cli",
      items: [{
        id: "gpt-5.6-sol",
        label: "GPT-5.6-Sol",
        reasoningEfforts: ["medium", "ultra"],
        defaultReasoningEffort: "medium",
      }],
      error: undefined,
    });
  });

});
