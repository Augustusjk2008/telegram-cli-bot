import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";
import { EventType } from "../services/agUiProtocol";
import { buildFileDownloadUrl } from "../utils/fileLinks";
import {
  createClusterBundleDiff,
  createClusterStatus,
  createClusterTask,
  createClusterTaskStatus,
  createClusterTemplateBundle,
} from "./fixtures/cluster";

describe("RealWebBotClient", () => {
  const fetchMock = vi.fn();
  const socketState = {
    instances: [] as Array<{ url: string; readyState: number; close: () => void; addEventListener: (type: string, handler: (event: Event) => void) => void }>,
  };

  class MockSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    readyState = MockSocket.CONNECTING;
    private readonly listeners = new Map<string, Set<(event: Event) => void>>();

    constructor(public readonly url: string) {
      socketState.instances.push(this);
    }

    addEventListener(type: string, handler: (event: Event) => void) {
      const handlers = this.listeners.get(type) ?? new Set<(event: Event) => void>();
      handlers.add(handler);
      this.listeners.set(type, handlers);
    }

    close() {
      this.readyState = MockSocket.CLOSED;
    }
  }

  function jsonOk(data: unknown) {
    return {
      ok: true,
      json: async () => ({
        ok: true,
        data,
      }),
    };
  }

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    vi.stubGlobal("__PUBLIC_ENV__", {});
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("WebSocket", MockSocket as unknown as typeof WebSocket);
    socketState.instances = [];
  });

  afterEach(() => {
    vi.useRealTimers();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  test("login validates token through auth/me", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          user_id: 1001,
          token: "secret-token",
        },
      }),
    });

    const client = new RealWebBotClient();
    const session = await client.login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(session.isLoggedIn).toBe(true);
    expect(session.token).toBe("");
    expect(session.currentBotAlias).toBe("");
  });

  test("applies public base path to fetch calls", async () => {
    window.history.replaceState(null, "", "/node/nanjing-laptop/");
    vi.stubGlobal("__PUBLIC_ENV__", {
      VITE_API_BASE_URL: "/node/nanjing-laptop",
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          user_id: 1001,
        },
      }),
    });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/node/nanjing-laptop/api/auth/me",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("ignores configured base path when current page is served from root", async () => {
    vi.stubGlobal("__PUBLIC_ENV__", {
      VITE_API_BASE_URL: "/node/local",
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          user_id: 1001,
        },
      }),
    });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("applies public base path to generated file download links", () => {
    window.history.replaceState(null, "", "/node/nanjing-laptop/");
    vi.stubGlobal("__PUBLIC_ENV__", {
      VITE_API_BASE_URL: "/node/nanjing-laptop",
    });

    expect(buildFileDownloadUrl("main", "docs/readme.md")).toBe(
      "/node/nanjing-laptop/api/bots/main/files/download?filename=docs%2Freadme.md",
    );
  });

  test("applies public base path to listed avatar asset urls", async () => {
    window.history.replaceState(null, "", "/node/nanjing-laptop/");
    vi.stubGlobal("__PUBLIC_ENV__", {
      VITE_API_BASE_URL: "/node/nanjing-laptop",
    });
    fetchMock.mockResolvedValue(jsonOk({
      items: [{
        name: "avatar_01.png",
        url: "/assets/avatars/avatar_01.png",
      }],
    }));

    const client = new RealWebBotClient();
    const assets = await client.listAvatarAssets();

    expect(fetchMock).toHaveBeenCalledWith(
      "/node/nanjing-laptop/api/admin/assets/avatars",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(assets).toEqual([{
      name: "avatar_01.png",
      url: "/node/nanjing-laptop/assets/avatars/avatar_01.png",
    }]);
  });

  
  test("cluster setup endpoints map snake case responses", async () => {
    const statusData = createClusterStatus({
      mcp: {
        serverName: "tcb-cluster",
        activeCliType: "kimi",
        runtime: { state: "runtime_ready", message: "运行态可用" },
        codex: { state: "not_checked", message: "未使用" },
        claude: { state: "not_checked", message: "未使用" },
        kimi: { state: "installed", message: "已安装" },
      },
      modelTiers: { low: "fast-model", medium: "balanced-model", high: "strong-model" },
      agents: [{
        id: "reviewer",
        name: "代码审查",
        enabled: true,
        allowCluster: true,
        allowWrite: false,
        sessionPolicy: "ephemeral",
        timeoutSeconds: 180,
      }],
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          enabled: statusData.enabled,
          model_tiers: statusData.modelTiers,
          mcp: {
            server_name: statusData.mcp.serverName,
            active_cli_type: statusData.mcp.activeCliType,
            runtime: statusData.mcp.runtime,
            codex: statusData.mcp.codex,
            claude: statusData.mcp.claude,
            kimi: statusData.mcp.kimi,
          },
          agents: statusData.agents.map((agent) => ({
            id: agent.id,
            name: agent.name,
            enabled: agent.enabled,
            allow_cluster: agent.allowCluster,
            allow_write: agent.allowWrite,
            session_policy: agent.sessionPolicy,
            timeout_seconds: agent.timeoutSeconds,
          })),
        },
      }),
    });

    const client = new RealWebBotClient();
    const status = await client.getClusterStatus("main");

    expect(fetchMock).toHaveBeenCalledWith("/api/bots/main/cluster/status", expect.objectContaining({ cache: "no-store" }));
    expect(status.enabled).toBe(true);
    expect(status.mcp.serverName).toBe("tcb-cluster");
    expect(status.mcp.activeCliType).toBe("kimi");
    expect(status.mcp.runtime?.state).toBe("runtime_ready");
    expect(status.mcp.kimi.state).toBe("installed");
    expect(status.modelTiers.low).toBe("fast-model");
    expect(status.agents[0].allowWrite).toBe(false);
    expect(status.agents[0].sessionPolicy).toBe("ephemeral");
    expect(status.agents[0].timeoutSeconds).toBe(180);
  });

  test("getDebugProfile normalizes snake case launch schema fields", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      provider_id: "custom",
      provider_label: "Custom Debug",
      config_name: "custom",
      launch_schema: {},
    }));

    const client = new RealWebBotClient();
    const profile = await client.getDebugProfile("main");

    expect(fetchMock).toHaveBeenCalledWith("/api/bots/main/debug/profile", expect.objectContaining({ cache: "no-store" }));
    expect(profile?.providerId).toBe("custom");
    expect(profile?.launchSchema.fields).toEqual([]);
  });

  
  
  test("sendMessage includes cluster mention payload", async () => {
    const encoder = new TextEncoder();
    fetchMock.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              value: encoder.encode("data: {\"type\":\"done\",\"output\":\"ok\"}\n\n"),
              done: false,
            })
            .mockResolvedValueOnce({ value: undefined, done: true }),
          cancel: vi.fn().mockResolvedValue(undefined),
        }),
      },
    });

    const client = new RealWebBotClient();
    await client.sendMessage("main", "@reviewer 看一下", vi.fn(), undefined, undefined, {
      cluster: true,
      mentions: [{ agentId: "reviewer", label: "代码审查", start: 0, end: 9 }],
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/main/chat/stream");
    expect(body.protocol).toBeUndefined();
    expect(body.cluster).toBe(true);
    expect(body.mentions[0]).toMatchObject({ agent_id: "reviewer", label: "代码审查" });
  });

  test("sendMessage uses plain stream protocol for CLI messages", async () => {
    const encoder = new TextEncoder();
    fetchMock.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              value: encoder.encode("data: {\"type\":\"done\",\"output\":\"ok\"}\n\n"),
              done: false,
            })
            .mockResolvedValueOnce({ value: undefined, done: true }),
          cancel: vi.fn().mockResolvedValue(undefined),
        }),
      },
    });

    const client = new RealWebBotClient();
    const onAgUiEvent = vi.fn();
    const message = await client.sendMessage("main", "hi", vi.fn(), undefined, undefined, undefined, onAgUiEvent);

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/main/chat/stream");
    expect(body.protocol).toBeUndefined();
    expect(message.text).toBe("ok");
    expect(onAgUiEvent).not.toHaveBeenCalled();
  });

  test("sendMessage keeps task mode on plain stream protocol", async () => {
    const encoder = new TextEncoder();
    fetchMock.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              value: encoder.encode("data: {\"type\":\"done\",\"output\":\"ok\"}\n\n"),
              done: false,
            })
            .mockResolvedValueOnce({ value: undefined, done: true }),
          cancel: vi.fn().mockResolvedValue(undefined),
        }),
      },
    });

    const client = new RealWebBotClient();
    await client.sendMessage("main", "run plan", vi.fn(), undefined, undefined, {
      taskMode: "plan",
      taskPayload: { path: "docs/plan.md" },
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/main/chat/stream");
    expect(body.protocol).toBeUndefined();
    expect(body.task_mode).toBe("plan");
    expect(body.task_payload).toEqual({ path: "docs/plan.md" });
  });

  test("sendMessage includes native agent execution mode", async () => {
    const encoder = new TextEncoder();
    fetchMock.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              value: encoder.encode("data: {\"type\":\"done\",\"output\":\"ok\"}\n\n"),
              done: false,
            })
            .mockResolvedValueOnce({ value: undefined, done: true }),
          cancel: vi.fn().mockResolvedValue(undefined),
        }),
      },
    });

    const client = new RealWebBotClient();
    await client.sendMessage("main", "hi", vi.fn(), undefined, undefined, {
      executionMode: "native_agent",
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/main/chat/stream?protocol=ag-ui");
    expect(body.execution_mode).toBe("native_agent");
    expect(body.protocol).toBe("ag-ui");
  });

  test("sendMessage parses legacy CRLF SSE delta and done as completed", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("data: {\"type\":\"delta\",\"text\":\"he\"}\r\n\r\n"));
        controller.enqueue(encoder.encode("data: {\"type\":\"delta\",\"text\":\"llo\"}\r\n\r\n"));
        controller.enqueue(encoder.encode("data: {\"type\":\"done\",\"output\":\"hello\",\"elapsed_seconds\":2,\"message\":{\"id\":\"msg-final\",\"role\":\"assistant\",\"content\":\"hello\",\"state\":\"streaming\",\"created_at\":\"2026-06-06T00:00:00Z\"}}\r\n\r\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn());

    expect(message.text).toBe("hello");
    expect(message.state).toBe("done");
    expect(message.elapsedSeconds).toBe(2);
  });

  test("sendMessage parses ag-ui stream without legacy trace callbacks", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"msg-1\",\"activityType\":\"TCB_STATUS\",\"replace\":true,\"content\":{\"elapsedSeconds\":2,\"previewText\":\"处理中\",\"contextUsage\":{\"session_id\":\"thread-1\",\"status_text\":\"74% context left\"}}}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_START\",\"messageId\":\"msg-1\",\"role\":\"assistant\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_CONTENT\",\"messageId\":\"msg-1\",\"delta\":\"hello\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TOOL_CALL_START\",\"toolCallId\":\"call-1\",\"toolCallName\":\"shell_command\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TOOL_CALL_ARGS\",\"toolCallId\":\"call-1\",\"delta\":\"{\\\"command\\\":\\\"dir\\\"}\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TOOL_CALL_RESULT\",\"messageId\":\"msg-1\",\"toolCallId\":\"call-1\",\"content\":\"Exit code: 0\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"outcome\":{\"type\":\"success\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({
        ok: true,
        data: {},
      }),
    });

    const client = new RealWebBotClient();
    const chunks: string[] = [];
    const statuses: Array<{ previewText?: string; elapsedSeconds?: number }> = [];
    const traces: string[] = [];
    const agUiEvents: string[] = [];
    const message = await client.sendMessage(
      "main",
      "hello",
      (chunk) => chunks.push(chunk),
      (status) => statuses.push({ previewText: status.previewText, elapsedSeconds: status.elapsedSeconds }),
      (trace) => traces.push(`${trace.kind}:${trace.summary}`),
      undefined,
      (event) => agUiEvents.push(event.type),
    );

    expect(chunks).toEqual([]);
    expect(statuses).toEqual([]);
    expect(traces).toEqual([]);
    expect(agUiEvents).toEqual([
      EventType.RUN_STARTED,
      EventType.ACTIVITY_SNAPSHOT,
      EventType.TEXT_MESSAGE_START,
      EventType.TEXT_MESSAGE_CONTENT,
      EventType.TOOL_CALL_START,
      EventType.TOOL_CALL_ARGS,
      EventType.TOOL_CALL_RESULT,
      EventType.RUN_FINISHED,
    ]);
    expect(message.text).toBe("hello");
    expect(message.meta?.traceCount).toBe(3);
  });

  test("sendMessage keeps duplicate native process events in flat trace", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"trace-1\",\"activityType\":\"TCB_NATIVE_AGENT_TRACE\",\"replace\":true,\"content\":{\"summary\":\"重复过程\",\"rawKind\":\"commentary\",\"rawType\":\"message.text.reclassified\"}}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"trace-2\",\"activityType\":\"TCB_NATIVE_AGENT_TRACE\",\"replace\":true,\"content\":{\"summary\":\"重复过程\",\"rawKind\":\"commentary\",\"rawType\":\"message.text.reclassified\"}}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"ok\"},\"outcome\":{\"type\":\"success\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn());

    expect(message.text).toBe("ok");
    expect(message.meta?.tracePresentation).toBe("native_agent_flat");
    expect(message.meta?.trace).toEqual([
      expect.objectContaining({ kind: "commentary", summary: "重复过程", sequence: 1 }),
      expect.objectContaining({ kind: "commentary", summary: "重复过程", sequence: 2 }),
    ]);
  });

  test("sendMessage upserts ag-ui tool results by toolCallId", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TOOL_CALL_START\",\"toolCallId\":\"call-1\",\"toolCallName\":\"shell_command\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TOOL_CALL_RESULT\",\"messageId\":\"msg-1\",\"toolCallId\":\"call-1\",\"content\":\"partial\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TOOL_CALL_RESULT\",\"messageId\":\"msg-1\",\"toolCallId\":\"call-1\",\"content\":\"final\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"ok\"},\"outcome\":{\"type\":\"success\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn(), undefined, undefined, {
      executionMode: "native_agent",
    });

    expect(message.meta?.traceCount).toBe(2);
    expect(message.meta?.trace).toEqual([
      expect.objectContaining({ kind: "tool_call", callId: "call-1" }),
      expect.objectContaining({ kind: "tool_result", callId: "call-1", summary: "final" }),
    ]);
  });

  test("sendMessage does not mark non-native permission activity as native flat", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"perm-1\",\"activityType\":\"TCB_PERMISSION_REQUEST\",\"replace\":true,\"content\":{\"id\":\"perm-1\",\"permissionId\":\"perm-1\",\"summary\":\"CLI 请求确认\",\"source\":\"codex\"}}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"ok\"},\"outcome\":{\"type\":\"success\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn());

    expect(message.meta?.tracePresentation).toBeUndefined();
    expect(message.meta?.trace).toEqual([
      expect.objectContaining({ kind: "permission", source: "codex", summary: "CLI 请求确认" }),
    ]);
  });

  test("sendMessage does not mark session error as native flat without native mode", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_ERROR\",\"message\":\"OpenCode failed\",\"code\":\"session.error\"}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn());

    expect(message.state).toBe("error");
    expect(message.meta?.tracePresentation).toBeUndefined();
    expect(message.meta?.trace).toEqual([
      expect.objectContaining({ kind: "error", rawType: "session.error", summary: "OpenCode failed" }),
    ]);
  });

  test("sendMessage keeps session error native flat in native mode", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_ERROR\",\"message\":\"OpenCode failed\",\"code\":\"session.error\"}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn(), undefined, undefined, {
      executionMode: "native_agent",
    });

    expect(message.state).toBe("error");
    expect(message.meta?.tracePresentation).toBe("native_agent_flat");
    expect(message.meta?.trace).toEqual([
      expect.objectContaining({ kind: "error", rawType: "session.error", summary: "OpenCode failed" }),
    ]);
  });

  test("sendMessage preserves ag-ui native trace stable metadata", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"trace-1\",\"activityType\":\"TCB_NATIVE_AGENT_TRACE\",\"replace\":true,\"content\":{\"id\":\"trace-1\",\"ordinal\":7,\"sequence\":9,\"createdAt\":\"2026-06-06T00:00:00Z\",\"summary\":\"先检查目录。\",\"source\":\"native_agent\",\"rawKind\":\"commentary\",\"rawType\":\"message.text.reclassified\"}}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"ok\"},\"outcome\":{\"type\":\"success\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn());

    expect(message.meta?.trace).toEqual([
      expect.objectContaining({
        id: "trace-1",
        ordinal: 7,
        sequence: 9,
        createdAt: "2026-06-06T00:00:00Z",
        kind: "commentary",
        summary: "先检查目录。",
      }),
    ]);
  });

  test("sendMessage applies ag-ui message snapshot before final content", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_START\",\"messageId\":\"msg-1\",\"role\":\"assistant\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_CONTENT\",\"messageId\":\"msg-1\",\"delta\":\"先查一下...\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"MESSAGES_SNAPSHOT\",\"messages\":[{\"id\":\"msg-1\",\"role\":\"assistant\",\"content\":\"\"}]}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_CONTENT\",\"messageId\":\"msg-1\",\"delta\":\"最终答复\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"最终答复\"},\"outcome\":{\"type\":\"success\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const agUiTexts: string[] = [];
    const message = await client.sendMessage(
      "main",
      "hi",
      vi.fn(),
      undefined,
      undefined,
      undefined,
      (event) => {
        if (event.type === EventType.TEXT_MESSAGE_CONTENT) {
          agUiTexts.push(event.delta);
        }
        if (event.type === EventType.MESSAGES_SNAPSHOT) {
          const assistant = event.messages.find((item) => item.role === "assistant");
          agUiTexts.push(String(assistant?.content ?? ""));
        }
      },
    );

    expect(agUiTexts).toEqual(["先查一下...", "", "最终答复"]);
    expect(message.text).toBe("最终答复");
  });

  test("sendMessage maps ag-ui cancelled finish into message meta", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_START\",\"messageId\":\"msg-1\",\"role\":\"assistant\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_CONTENT\",\"messageId\":\"msg-1\",\"delta\":\"半截\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"半截\",\"completion_state\":\"cancelled\"},\"outcome\":{\"type\":\"interrupt\",\"interrupts\":[{\"id\":\"interrupt-1\",\"reason\":\"cancelled\"}]}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "hi", vi.fn());

    expect(message.state).toBe("error");
    expect(message.meta?.completionState).toBe("cancelled");
    expect(message.meta?.trace).toEqual([
      expect.objectContaining({ kind: "cancelled", summary: "用户终止输出" }),
    ]);
  });

  test("sendMessage prefers done content over live ag-ui text", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_START\",\"messageId\":\"msg-1\",\"role\":\"assistant\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"TEXT_MESSAGE_CONTENT\",\"messageId\":\"msg-1\",\"delta\":\"internal thinking\"}\n\n"));
        controller.enqueue(encoder.encode("event: message\ndata: {\"type\":\"done\",\"output\":\"ok\",\"message\":{\"id\":\"msg-final\",\"role\":\"assistant\",\"content\":\"ok\",\"state\":\"done\",\"created_at\":\"2026-06-06T00:00:00Z\",\"updated_at\":\"2026-06-06T00:00:01Z\"}}\n\n"));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue({
      ok: true,
      body: stream,
      json: async () => ({ ok: true, data: {} }),
    });

    const client = new RealWebBotClient();
    const message = await client.sendMessage("main", "回复 ok", vi.fn());

    expect(message.text).toBe("ok");
  });

  test("killTask includes scoped agent and execution mode", async () => {
    fetchMock.mockResolvedValue(jsonOk({ message: "已请求原生 agent 停止" }));

    const client = new RealWebBotClient();
    const message = await client.killTask("main", { agentId: "reviewer", executionMode: "native_agent" });

    expect(message).toBe("已请求原生 agent 停止");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/kill",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          agent_id: "reviewer",
          execution_mode: "native_agent",
        }),
      }),
    );
  });

  test("replyNativeAgentPermission posts scoped approval", async () => {
    fetchMock.mockResolvedValue(jsonOk({ permission_id: "perm-1", approved: true }));

    const client = new RealWebBotClient();
    const result = await client.replyNativeAgentPermission("main", "perm-1", {
      approved: true,
      message: "允许本次读取",
      executionMode: "native_agent",
    });

    expect(result).toEqual({ permissionId: "perm-1", approved: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/native-agent/permissions/perm-1/reply",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          execution_mode: "native_agent",
          approved: true,
          message: "允许本次读取",
        }),
      }),
    );
  });

  test("native agent config and model APIs map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        config: { provider: { jojocode_max: { models: {} } } },
        opencode_config_path: "C:\\Users\\me\\.config\\opencode\\opencode.json",
        backup_path: "C:\\Users\\me\\.tcb\\native_agent\\opencode.config.backup.json",
        models: [{
          id: "jojocode_max/gpt-5.4",
          provider: "jojocode_max",
          model: "gpt-5.4",
          name: "gpt-5.4",
          label: "jojocode_max / gpt-5.4",
          context_window: 1000000,
          output_limit: 128000,
          reasoning_efforts: ["low", "medium", "high"],
          default_reasoning_effort: "medium",
        }],
        needs_restart: false,
      }))
      .mockResolvedValueOnce(jsonOk({
        config: { provider: {} },
        opencode_config_path: "opencode.json",
        backup_path: "backup.json",
        models: [],
        needs_restart: true,
      }))
      .mockResolvedValueOnce(jsonOk({
        items: [{
          id: "jojocode_max/gpt-5.4",
          provider: "jojocode_max",
          model: "gpt-5.4",
          name: "gpt-5.4",
          label: "jojocode_max / gpt-5.4",
          context_window: 1000000,
          reasoning_efforts: ["low", "medium", "high"],
          default_reasoning_effort: "medium",
        }],
        selected_model: "jojocode_max/gpt-5.4",
        selected_reasoning_effort: "medium",
      }))
      .mockResolvedValueOnce(jsonOk({
        items: [],
        selected_model: "jojocode_max/gpt-5.5",
        selected_reasoning_effort: "high",
        bot: {
          alias: "main",
          cli_type: "codex",
          status: "running",
          working_dir: "C:\\workspace",
          native_agent: { model: "jojocode_max/gpt-5.5", reasoning_effort: "high" },
        },
      }));

    const client = new RealWebBotClient();
    const config = await client.getNativeAgentConfig();
    const saved = await client.updateNativeAgentConfig({ provider: {} });
    const models = await client.getNativeAgentModels("main");
    const updated = await client.updateNativeAgentModel("main", "jojocode_max/gpt-5.5", { reasoningEffort: "high" });

    expect(config.models[0]).toMatchObject({
      id: "jojocode_max/gpt-5.4",
      contextWindow: 1000000,
      outputLimit: 128000,
      reasoningEfforts: ["low", "medium", "high"],
      defaultReasoningEffort: "medium",
    });
    expect(saved.needsRestart).toBe(true);
    expect(models.selectedModel).toBe("jojocode_max/gpt-5.4");
    expect(models.selectedReasoningEffort).toBe("medium");
    expect(updated.selectedModel).toBe("jojocode_max/gpt-5.5");
    expect(updated.selectedReasoningEffort).toBe("high");
    expect(updated.bot?.nativeAgent?.model).toBe("jojocode_max/gpt-5.5");
    expect(updated.bot?.nativeAgent?.reasoningEffort).toBe("high");
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ config: { provider: {} } });
    expect(JSON.parse(String(fetchMock.mock.calls[3][1]?.body))).toEqual({
      model: "jojocode_max/gpt-5.5",
      reasoning_effort: "high",
    });
  });

  test("maps context_usage from history and stream done message", async () => {
    const encoder = new TextEncoder();
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        items: [{
          id: "assistant-history",
          role: "assistant",
          content: "历史回复",
          created_at: "2026-05-08T09:05:00+08:00",
          state: "done",
          meta: {
            context_usage: {
              provider: "codex",
              source: "codex_session_token_count",
              session_id: "thread-1",
              used_tokens: 76593,
              context_window: 258400,
              context_left_percent: 74,
              context_used: 76593,
              context_used_percent: 30,
              input_tokens: 1237,
              cache_read_tokens: 35328,
              cache_write_tokens: 0,
              output_tokens: 512,
              reasoning_tokens: 128,
              model: "jojocode/gpt-5.4",
              used_display: "76.6K",
              window_display: "258K",
              status_text: "74% context left · 76.6K / 258K",
              compaction_count: 2,
            },
          },
        }],
      }))
      .mockResolvedValueOnce({
        ok: true,
        body: {
          getReader: () => ({
            read: vi.fn()
              .mockResolvedValueOnce({
                value: encoder.encode(
                  "data: {\"type\":\"done\",\"message\":{\"id\":\"assistant-stream\",\"role\":\"assistant\",\"content\":\"流式回复\",\"created_at\":\"2026-05-08T09:06:00+08:00\",\"state\":\"done\",\"meta\":{\"context_usage\":{\"provider\":\"codex\",\"source\":\"codex_session_token_count\",\"session_id\":\"thread-2\",\"used_tokens\":76593,\"context_window\":258400,\"context_left_percent\":74,\"used_display\":\"76.6K\",\"window_display\":\"258K\",\"status_text\":\"74% context left · 76.6K / 258K\",\"compaction_count\":1}}}}\n\n",
                ),
                done: false,
              })
              .mockResolvedValueOnce({ value: undefined, done: true }),
            cancel: vi.fn().mockResolvedValue(undefined),
          }),
        },
      });

    const client = new RealWebBotClient();
    const history = await client.listMessages("main");
    const sent = await client.sendMessage("main", "hi", vi.fn());

    expect(history[0].meta?.contextUsage?.sessionId).toBe("thread-1");
    expect(history[0].meta?.contextUsage?.statusText).toBe("74% context left · 76.6K / 258K");
    expect(history[0].meta?.contextUsage?.compactionCount).toBe(2);
    expect(history[0].meta?.contextUsage).toEqual(expect.objectContaining({
      contextUsed: 76593,
      contextUsedPercent: 30,
      inputTokens: 1237,
      cacheReadTokens: 35328,
      cacheWriteTokens: 0,
      outputTokens: 512,
      reasoningTokens: 128,
      model: "jojocode/gpt-5.4",
    }));
    expect(sent.meta?.contextUsage?.sessionId).toBe("thread-2");
    expect(sent.meta?.contextUsage?.usedTokens).toBe(76593);
    expect(sent.meta?.contextUsage?.compactionCount).toBe(1);
  });

  test("preserves native history trace count when trace payload is not embedded", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      items: [{
        id: "assistant-history",
        role: "assistant",
        content: "历史回复",
        created_at: "2026-05-08T09:05:00+08:00",
        state: "done",
        meta: {
          trace_count: 3,
          tool_call_count: 1,
          process_count: 1,
          native_source: {
            provider: "native_agent",
            session_id: "native-1",
          },
        },
      }],
    }));

    const client = new RealWebBotClient();
    const history = await client.listMessages("main");

    expect(history[0].meta?.traceCount).toBe(3);
    expect(history[0].meta?.toolCallCount).toBe(1);
    expect(history[0].meta?.processCount).toBe(1);
    expect(history[0].meta?.tracePresentation).toBe("native_agent_flat");
    expect(history[0].meta?.nativeSource?.provider).toBe("原生 agent");
  });

  test("executePlan posts plan content and maps execution payload", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      plan_path: "docs/plan/2026-05-21-1010-plan-mode.md",
      conversation: {
        id: "conv-plan",
        title: "Plan Mode",
        last_message_preview: "",
        message_count: 0,
        pinned: false,
        active: true,
        status: "active",
        bot_alias: "main",
        bot_mode: "cli",
        cli_type: "codex",
        agent_id: "reviewer",
        working_dir: "C:\\workspace",
        created_at: "2026-05-21T10:10:00",
        updated_at: "2026-05-21T10:10:00",
      },
      messages: [],
      execution_message: "请按方案执行。方案文件：docs/plan/2026-05-21-1010-plan-mode.md",
    }));

    const client = new RealWebBotClient() as RealWebBotClient & {
      executePlan: (botAlias: string, input: {
        content: string;
        title?: string;
        agentId?: string;
        executionMode?: "cli" | "native_agent";
        cluster?: boolean;
        mentions?: Array<{ agentId: string; label: string; start: number; end: number }>;
      }) => Promise<{
        planPath: string;
        conversation: { id: string };
        executionMessage: string;
      }>;
    };
    const result = await client.executePlan("main", {
      content: "# 方案",
      title: "Plan Mode",
      agentId: "reviewer",
      executionMode: "native_agent",
      cluster: true,
      mentions: [{ agentId: "reviewer", label: "代码审查", start: 0, end: 9 }],
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/plans/execute",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          content: "# 方案",
          title: "Plan Mode",
          agent_id: "reviewer",
          execution_mode: "native_agent",
          cluster: true,
          mentions: [{ agent_id: "reviewer", label: "代码审查", start: 0, end: 9 }],
        }),
      }),
    );
    expect(result.planPath).toBe("docs/plan/2026-05-21-1010-plan-mode.md");
    expect(result.conversation.id).toBe("conv-plan");
    expect(result.executionMessage).toContain("请按方案执行");
  });

  test("login posts username/password and maps account session fields", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          token: "web_sess_123",
          username: "alice",
          role: "member",
          capabilities: ["chat_send", "view_file_tree"],
          current_bot_alias: "main",
          current_path: "C:\\workspace",
        },
      }),
    });

    const client = new RealWebBotClient();
    const session = await client.login({ username: "alice", password: "pw-123" });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          username: "alice",
          password: "pw-123",
        }),
      }),
    );
    expect(session).toEqual(expect.objectContaining({
      isLoggedIn: true,
      token: "web_sess_123",
      username: "alice",
      role: "member",
      capabilities: ["chat_send", "view_file_tree"],
      currentBotAlias: "main",
      currentPath: "C:\\workspace",
    }));
  });

  test("login does not reuse returned token for later authenticated requests", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            token: "web_sess_123",
            username: "alice",
            role: "member",
            capabilities: ["view_bots"],
          },
        }),
      })
      .mockResolvedValueOnce(jsonOk([]));

    const client = new RealWebBotClient();
    await client.login({ username: "alice", password: "pw-123" });
    await client.listBots();

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: expect.not.objectContaining({
          Authorization: expect.any(String),
        }),
      }),
    );
  });

  
  test("guest login and logout use auth guest/logout endpoints", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            token: "web_sess_guest",
            username: "guest",
            role: "guest",
            capabilities: ["view_file_tree"],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    const session = await client.loginGuest();
    await client.logout();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/guest",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/logout",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
    expect(session).toEqual(expect.objectContaining({
      token: "web_sess_guest",
      username: "guest",
      role: "guest",
      capabilities: ["view_file_tree"],
    }));
  });

  test("notification websocket url does not include token query", () => {
    const client = new RealWebBotClient();
    const subscription = client.subscribeNotifications(() => undefined);
    const socket = socketState.instances[0];

    expect(socket).toBeDefined();
    expect(socket.url).toContain("/api/notifications/ws");
    expect(socket.url).not.toContain("token=");

    subscription.close();
  });

  test("lan chat websocket url does not include token query", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          user_id: 1001,
        },
      }),
    });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const close = client.openLanChatSocket(() => undefined);
    const socket = socketState.instances[0];

    expect(socket).toBeDefined();
    expect(socket.url).toContain("/lan-chat/ws");
    expect(socket.url).not.toContain("token=");

    close();
  });

  
  
  
  test("listBots maps backend fields to frontend shape", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: [
            {
              alias: "main",
              cli_type: "codex",
              status: "running",
              is_processing: true,
              service_status: "online",
              activity_status: "busy",
              busy_agent_ids: ["reviewer"],
              busy_agent_names: ["代码审查"],
              busy_agent_count: 1,
              working_dir: "C:\\workspace\\demo",
            },
          ],
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bots = await client.listBots();

    expect(bots).toEqual([
      {
        alias: "main",
        cliType: "codex",
        status: "busy",
        serviceStatus: "online",
        activityStatus: "busy",
        busyAgentIds: ["reviewer"],
        busyAgentNames: ["代码审查"],
        busyAgentCount: 1,
        workingDir: "C:\\workspace\\demo",
        lastActiveText: "处理中",
        avatarName: "",
      },
    ]);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
  });

  test("updateBotExecutionConfig posts native agent config", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      bot: {
        alias: "main",
        cli_type: "codex",
        status: "running",
        service_status: "online",
        activity_status: "idle",
        working_dir: "C:\\workspace\\demo",
        supported_execution_modes: ["native_agent"],
        default_execution_mode: "native_agent",
        native_agent: {
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          opencode_agent: "reviewer",
          base_url: "https://cdn.codeflow.asia/v1",
          has_api_key: true,
          api_key_masked: "sk-****1234",
        },
      },
    }));

    const client = new RealWebBotClient();
    const bot = await client.updateBotExecutionConfig("main", {
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: {
        provider: "anthropic",
        model: "claude-sonnet-4-5",
        opencodeAgent: "reviewer",
        baseUrl: "https://cdn.codeflow.asia/v1",
        apiKey: "sk-route-1234",
      },
    });
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/bots/main/execution",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(body).toEqual({
      supported_execution_modes: ["native_agent"],
      default_execution_mode: "native_agent",
      native_agent: {
        opencode_agent: "reviewer",
      },
    });
    expect(bot.nativeAgent).toEqual({
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      opencodeAgent: "reviewer",
      baseUrl: "https://cdn.codeflow.asia/v1",
      hasApiKey: true,
      apiKeyMasked: "sk-****1234",
    });
  });

  test("addBot posts only bot-scoped native agent fields", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      bot: {
        alias: "native1",
        cli_type: "codex",
        bot_mode: "cli",
        status: "running",
        service_status: "online",
        activity_status: "idle",
        working_dir: "C:\\workspace\\native1",
        supported_execution_modes: ["native_agent"],
        default_execution_mode: "native_agent",
        native_agent: {
          provider: "codeflow",
          model: "gpt-5.1-codex",
          opencode_agent: "main",
          base_url: "https://cdn.codeflow.asia/v1",
          has_api_key: false,
          api_key_masked: "",
        },
      },
    }));

    const client = new RealWebBotClient();
    await client.addBot({
      alias: "native1",
      botMode: "cli",
      cliType: "codex",
      cliPath: "codex",
      workingDir: "C:\\workspace\\native1",
      avatarName: "",
      supportedExecutionModes: ["native_agent"],
      defaultExecutionMode: "native_agent",
      nativeAgent: {
        provider: "codeflow",
        model: "gpt-5.1-codex",
        opencodeAgent: "main",
        baseUrl: "https://cdn.codeflow.asia/v1",
        clearApiKey: true,
      },
    });
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/bots",
      expect.objectContaining({ method: "POST" }),
    );
    expect(body.native_agent).toEqual({
      opencode_agent: "main",
    });
  });

  
  
  
  test("listFiles maps snake_case directory entries to camelCase", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            working_dir: "C:\\workspace\\demo",
            entries: [
              {
                name: "src",
                is_dir: true,
              },
              {
                name: "package.json",
                is_dir: false,
                size: 1024,
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const listing = await client.listFiles("main");

    expect(listing).toEqual({
      workingDir: "C:\\workspace\\demo",
      entries: [
        {
          name: "src",
          isDir: true,
        },
        {
          name: "package.json",
          isDir: false,
          size: 1024,
        },
      ],
    });
  });

  
  
  
  test("getBotOverview maps running reply snapshot", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            bot: {
              alias: "main",
              cli_type: "codex",
              status: "running",
              working_dir: "C:\\workspace\\profile",
              supported_execution_modes: ["cli", "native_agent"],
              default_execution_mode: "native_agent",
              execution_mode: "native_agent",
              native_agent: {
                provider: "anthropic",
                model: "claude-sonnet-4-5",
                opencode_agent: "reviewer",
                base_url: "https://cdn.codeflow.asia/v1",
                has_api_key: true,
                api_key_masked: "sk-****abcd",
              },
              assistant_runtime: {
                pending_count: 2,
                queued_count: 1,
                active: {
                  run_id: "run_active",
                  source: "cron",
                  status: "running",
                  task_mode: "dream",
                  interactive: false,
                  job_id: "daily_dream",
                  job_title: "每日自整理",
                  visible_text: "dream prompt",
                  enqueued_at: "2026-04-09T10:39:59",
                },
                queue: [
                  {
                    run_id: "run_queued",
                    source: "web",
                    status: "queued",
                    task_mode: "standard",
                    interactive: true,
                    visible_text: "帮我总结今天进度",
                    enqueued_at: "2026-04-09T10:40:01",
                  },
                ],
              },
            },
            session: {
              working_dir: "C:\\workspace\\session",
              message_count: 3,
              history_count: 2,
              is_processing: true,
              running_reply: {
                preview_text: "处理中预览",
                started_at: "2026-04-09T10:40:00",
                updated_at: "2026-04-09T10:40:05",
              },
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const overview = await client.getBotOverview("main");

    expect(overview.workingDir).toBe("C:\\workspace\\session");
    expect(overview.status).toBe("busy");
    expect(overview.supportedExecutionModes).toEqual(["cli", "native_agent"]);
    expect(overview.defaultExecutionMode).toBe("native_agent");
    expect(overview.executionMode).toBe("native_agent");
    expect(overview.nativeAgent).toEqual({
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      opencodeAgent: "reviewer",
      baseUrl: "https://cdn.codeflow.asia/v1",
      hasApiKey: true,
      apiKeyMasked: "sk-****abcd",
    });
    expect(overview.runningReply).toEqual({
      previewText: "处理中预览",
      startedAt: "2026-04-09T10:40:00",
      updatedAt: "2026-04-09T10:40:05",
    });
    expect(overview.assistantRuntime).toEqual({
      pendingCount: 2,
      queuedCount: 1,
      active: {
        runId: "run_active",
        source: "cron",
        status: "running",
        taskMode: "dream",
        interactive: false,
        jobId: "daily_dream",
        jobTitle: "每日自整理",
        visibleText: "dream prompt",
        enqueuedAt: "2026-04-09T10:39:59",
      },
      queue: [
        {
          runId: "run_queued",
          source: "web",
          status: "queued",
          taskMode: "standard",
          interactive: true,
          visibleText: "帮我总结今天进度",
          enqueuedAt: "2026-04-09T10:40:01",
        },
      ],
    });
  });

  
  test("agent endpoints and scoped chat requests use agent_id", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [{
              id: "reviewer",
              name: "代码审查",
              system_prompt: "先列风险",
              enabled: true,
              is_main: false,
            }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            agent: {
              id: "writer",
              name: "文档",
              system_prompt: "写文档",
              enabled: true,
              is_main: false,
            },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            bot: {
              alias: "main",
              cli_type: "codex",
              status: "running",
              working_dir: "C:\\workspace",
            },
            session: {
              working_dir: "C:\\workspace",
              message_count: 0,
              history_count: 0,
              is_processing: false,
            },
            agents: [],
            active_agent_id: "reviewer",
            busy_agent_ids: [],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: { items: [] },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            active_conversation_id: "",
            items: [],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            conversation: {
              id: "conv-1",
              title: "审查",
              last_message_preview: "",
              message_count: 0,
              pinned: false,
              active: true,
              status: "active",
              bot_alias: "main",
              bot_mode: "cli",
              cli_type: "codex",
              working_dir: "C:\\workspace",
              agent_id: "reviewer",
              created_at: "2026-05-04T00:00:00Z",
              updated_at: "2026-05-04T00:00:00Z",
            },
            messages: [],
          },
        }),
      });

    const client = new RealWebBotClient();
    const agents = await client.listAgents("main");
    const created = await client.createAgent("main", {
      id: "writer",
      name: "文档",
      systemPrompt: "写文档",
      enabled: true,
    });
    await client.getBotOverview("main", { agentId: "reviewer", executionMode: "native_agent" });
    await client.listMessages("main", { agentId: "reviewer", executionMode: "native_agent" });
    await client.listConversations("main", "", { agentId: "reviewer", executionMode: "native_agent" });
    await client.createConversation("main", "审查", { agentId: "reviewer", executionMode: "native_agent" });

    expect(agents.items[0]).toEqual(expect.objectContaining({
      id: "reviewer",
      name: "代码审查",
      systemPrompt: "先列风险",
    }));
    expect(created.agent).toEqual(expect.objectContaining({
      id: "writer",
      systemPrompt: "写文档",
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/bots/main/agents",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/bots/main/agents",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          id: "writer",
          name: "文档",
          system_prompt: "写文档",
          enabled: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/bots/main?agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/bots/main/history?agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/bots/main/conversations?limit=80&agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/bots/main/conversations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "审查",
          agent_id: "reviewer",
          execution_mode: "native_agent",
        }),
      }),
    );
  });

  
  
  test("listConversations maps native session metadata", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          active_conversation_id: "conv-1",
          items: [{
            id: "conv-1",
            title: "修复 diff",
            last_message_preview: "完成",
            message_count: 2,
            pinned: false,
            active: true,
            status: "active",
            bot_alias: "main",
            bot_mode: "cli",
            cli_type: "codex",
            working_dir: "C:\\repo",
            native_provider: "codex",
            native_session_id: "thread-1",
            created_at: "2026-05-03T00:00:00Z",
            updated_at: "2026-05-03T00:01:00Z",
          }],
        },
      }),
    });

    const client = new RealWebBotClient();
    const data = await client.listConversations("main");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/conversations?limit=80",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(data.activeConversationId).toBe("conv-1");
    expect(data.items[0].title).toBe("修复 diff");
    expect(data.items[0].nativeSource?.sessionId).toBe("thread-1");
  });

  test("deleteAllConversations calls collection delete and maps result", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      deleted_count: 3,
      active_conversation_id: "",
      native_session_cleared: true,
      items: [],
      messages: [],
    }));

    const client = new RealWebBotClient();
    const data = await client.deleteAllConversations("main", { deleteNativeSession: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/conversations?delete_native_session=true",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(data.deletedCount).toBe(3);
    expect(data.messages).toEqual([]);
    expect(data.nativeSessionCleared).toBe(true);
  });

  test("deleteAllConversations forwards scoped params", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      deleted_count: 1,
      active_conversation_id: "",
      native_session_cleared: true,
      items: [],
      messages: [],
    }));

    const client = new RealWebBotClient();
    await client.deleteAllConversations("main", {
      agentId: "reviewer",
      executionMode: "native_agent",
      deleteNativeSession: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/conversations?agent_id=reviewer&execution_mode=native_agent&delete_native_session=true",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  
  
  test("getMessageTrace maps rich native trace payload for one history message", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            message_id: "codex-thread-1-0",
            trace_count: 3,
            tool_call_count: 1,
            process_count: 1,
            trace: [
              {
                id: "trace-1",
                ordinal: 1,
                created_at: "2026-06-06T00:00:00Z",
                kind: "commentary",
                source: "native",
                raw_type: "agent_message",
                summary: "我先检查目录结构。",
              },
              {
                kind: "tool_call",
                source: "native",
                raw_type: "function_call",
                title: "shell_command",
                tool_name: "shell_command",
                call_id: "call_1",
                summary: "Get-ChildItem -Force",
                payload: {
                  arguments: {
                    command: "Get-ChildItem -Force",
                  },
                },
              },
              {
                kind: "tool_result",
                source: "native",
                raw_type: "function_call_output",
                call_id: "call_1",
                summary: "bot/web/api_service.py",
                payload: {
                  output: "bot/web/api_service.py",
                },
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const traceDetails = await client.getMessageTrace("main", "codex-thread-1-0");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/history/codex-thread-1-0/trace",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
    expect(traceDetails).toEqual({
      traceCount: 3,
      toolCallCount: 1,
      processCount: 1,
      trace: [
        {
          id: "trace-1",
          ordinal: 1,
          createdAt: "2026-06-06T00:00:00Z",
          kind: "commentary",
          rawType: "agent_message",
          summary: "我先检查目录结构。",
          source: "native",
        },
        {
          kind: "tool_call",
          rawType: "function_call",
          title: "shell_command",
          toolName: "shell_command",
          callId: "call_1",
          summary: "Get-ChildItem -Force",
          source: "native",
          payload: {
            arguments: {
              command: "Get-ChildItem -Force",
            },
          },
        },
        {
          kind: "tool_result",
          rawType: "function_call_output",
          callId: "call_1",
          summary: "bot/web/api_service.py",
          source: "native",
          payload: {
            output: "bot/web/api_service.py",
          },
        },
      ],
    });
  });

  test("getMessageTrace folds duplicate tool results and keeps commentary in trace order", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            trace_count: 5,
            tool_call_count: 1,
            process_count: 2,
            trace: [
              {
                kind: "tool_call",
                ordinal: 2,
                tool_name: "shell_command",
                call_id: "call_1",
                summary: "Get-ChildItem",
                payload: { arguments: "Get-ChildItem" },
              },
              {
                kind: "tool_result",
                ordinal: 3,
                call_id: "call_1",
                summary: "partial",
                payload: { output: "partial" },
              },
              {
                kind: "commentary",
                ordinal: 4,
                raw_type: "message.text.reclassified",
                summary: "我先检查目录结构。",
              },
              {
                kind: "tool_result",
                ordinal: 5,
                call_id: "call_1",
                summary: "final",
                payload: { output: "final" },
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const traceDetails = await client.getMessageTrace("main", "assistant-1");

    expect(traceDetails.traceCount).toBe(3);
    expect(traceDetails.toolCallCount).toBe(1);
    expect(traceDetails.processCount).toBe(1);
    expect(traceDetails.trace.map((item) => item.kind)).toEqual([
      "tool_call",
      "tool_result",
      "commentary",
    ]);
    expect(traceDetails.trace[1]).toEqual(expect.objectContaining({
      callId: "call_1",
      summary: "final",
    }));
  });

  
  
  
  test("getUpdateStatus maps backend update payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { user_id: 1001 } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_version: "1.0.0",
            current_package_kind: "installer",
            update_enabled: true,
            update_channel: "release",
            last_checked_at: "2026-04-15T10:00:00+08:00",
            last_available_version: "1.0.1",
            last_available_release_url: "https://github.com/owner/repo/releases/tag/v1.0.1",
            last_available_notes: "Bugfixes",
            pending_update_version: "",
            pending_update_path: "",
            pending_update_notes: "",
            pending_update_platform: "",
            pending_update_package_kind: "installer",
            update_last_error: "",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const status = await client.getUpdateStatus();

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/update",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
    expect(status.currentVersion).toBe("1.0.0");
    expect(status.currentPackageKind).toBe("installer");
    expect(status.latestVersion).toBe("1.0.1");
    expect(status.pendingUpdatePackageKind).toBe("installer");
  });

  test("downloadUpdateStream forwards progress events and returns the final update status", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            "event: progress\ndata: {\"phase\":\"downloading\",\"downloaded_bytes\":512,\"total_bytes\":1024,\"percent\":50}\n\n",
          ),
        );
        controller.enqueue(
          encoder.encode(
            "event: done\ndata: {\"status\":{\"current_version\":\"1.0.0\",\"current_package_kind\":\"installer\",\"update_enabled\":true,\"update_channel\":\"release\",\"last_checked_at\":\"2026-04-15T10:00:00+08:00\",\"last_available_version\":\"1.0.1\",\"last_available_release_url\":\"https://github.com/owner/repo/releases/tag/v1.0.1\",\"last_available_notes\":\"Bugfixes\",\"pending_update_version\":\"1.0.1\",\"pending_update_path\":\".updates/cli-bridge-windows-x64-installer.zip\",\"pending_update_notes\":\"Bugfixes\",\"pending_update_platform\":\"windows-x64-installer\",\"pending_update_package_kind\":\"installer\",\"update_last_error\":\"\"}}\n\n",
          ),
        );
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient() as RealWebBotClient & {
      downloadUpdateStream: (
        onProgress: (event: { phase: string; downloadedBytes: number; totalBytes?: number; percent?: number }) => void,
      ) => Promise<{
        pendingUpdateVersion: string;
        pendingUpdatePath: string;
        pendingUpdatePackageKind: string;
      }>;
    };
    await client.login("secret-token");

    const progressEvents: Array<{ phase: string; downloadedBytes: number; totalBytes?: number; percent?: number }> = [];
    const status = await client.downloadUpdateStream((event) => {
      progressEvents.push(event);
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/update/download/stream",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({}),
      }),
    );
    expect(progressEvents).toEqual([
      {
        phase: "downloading",
        downloadedBytes: 512,
        totalBytes: 1024,
        percent: 50,
      },
    ]);
    expect(status.pendingUpdateVersion).toBe("1.0.1");
    expect(status.pendingUpdatePath).toBe(".updates/cli-bridge-windows-x64-installer.zip");
    expect(status.pendingUpdatePackageKind).toBe("installer");
  });

  
  
  
  test("readFileFull uses cat mode endpoint", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            content: "full file content",
            mode: "cat",
            file_size_bytes: 123,
            is_full_content: true,
            last_modified_ns: "1776420510390927700",
            encoding: "gb18030",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const content = await client.readFileFull("main", "README.md");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/files/read?filename=README.md&mode=cat&lines=0",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
    expect(content).toEqual({
      content: "full file content",
      mode: "cat",
      workingDir: "",
      fileSizeBytes: 123,
      isFullContent: true,
      lastModifiedNs: "1776420510390927700",
      encoding: "gb18030",
    });
  });

  
  
  test("installPlugin sends allowDevSourcePath for local source paths", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      id: "local-plugin",
      name: "Local Plugin",
      version: "1.0.0",
      description: "",
      enabled: true,
      views: [],
      actions: [],
      config: {},
    }));

    const client = new RealWebBotClient();
    await client.installPlugin({
      sourcePath: "C:\\plugins\\local-plugin",
      force: true,
      allowDevSourcePath: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/plugins/install",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          sourcePath: "C:\\plugins\\local-plugin",
          force: true,
          allowDevSourcePath: true,
        }),
      }),
    );
  });

  
  test("writeFile preserves string file versions in the request body", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            path: "README.md",
            file_size_bytes: 16,
            last_modified_ns: "1776420510390927700",
            encoding: "gb18030",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const result = await client.writeFile("main", "README.md", "updated content", "1776420510390927700", "gb18030");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/files/write",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          path: "README.md",
          content: "updated content",
          expected_mtime_ns: "1776420510390927700",
          encoding: "gb18030",
        }),
      }),
    );
    expect(result).toEqual({
      path: "README.md",
      fileSizeBytes: 16,
      lastModifiedNs: "1776420510390927700",
      encoding: "gb18030",
    });
  });

  
  
  
  test("git smart commit endpoints map snake case payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            job_id: "job-1",
            alias: "main",
            user_id: 1001,
            status: "running",
            phase: "generating",
            message: "",
            error: "",
            overview: {},
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            job_id: "job-1",
            alias: "main",
            user_id: 1001,
            status: "running",
            phase: "staging",
            message: "feat(git): add generated commit message flow",
            error: "",
            overview: null,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            job_id: "job-1",
            alias: "main",
            user_id: 1001,
            status: "succeeded",
            phase: "done",
            message: "feat(git): add generated commit message flow",
            error: "",
            overview: {
              repo_found: true,
              can_init: false,
              working_dir: "C:\\workspace\\repo",
              repo_path: "C:\\workspace\\repo",
              repo_name: "repo",
              current_branch: "main",
              is_clean: true,
              ahead_count: 1,
              behind_count: 0,
              changed_files: [],
              recent_commits: [
                {
                  hash: "abcdef012345",
                  short_hash: "abcdef0",
                  author_name: "Web Bot",
                  authored_at: "2026-04-09 21:00:00 +0800",
                  subject: "feat: initial commit",
                  message: "feat: initial commit\n\nadd first repo snapshot",
                },
              ],
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const started = await client.startGitSmartCommit("main");
    const active = await client.getActiveGitSmartCommit("main");
    const finished = await client.getGitSmartCommitJob("main", "job-1");

    expect(started).toEqual({
      jobId: "job-1",
      alias: "main",
      userId: 1001,
      status: "running",
      phase: "generating",
      message: "",
      error: "",
      overview: null,
    });
    expect(active?.phase).toBe("staging");
    expect(active?.message).toBe("feat(git): add generated commit message flow");
    expect(finished.overview?.isClean).toBe(true);
    expect(finished.overview?.recentCommits[0].shortHash).toBe("abcdef0");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/git/smart-commit",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/bots/main/git/smart-commit/active",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/bots/main/git/smart-commit/job-1",
      expect.any(Object),
    );
  });

  
  test("sendMessage maps legacy status events into callbacks and metadata", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: meta\ndata: {\"type\":\"meta\",\"cli_type\":\"codex\"}\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: {\"elapsed_seconds\":2,\"preview_text\":\"处理中预览\",\"context_usage\":{\"provider\":\"codex\",\"source\":\"codex_session_token_count\",\"session_id\":\"thread-1\",\"used_tokens\":76593,\"context_window\":258400,\"context_left_percent\":74,\"used_display\":\"76.6K\",\"window_display\":\"258K\",\"status_text\":\"74% context left · 76.6K / 258K\",\"compaction_count\":1}}\n\n"));
        controller.enqueue(encoder.encode("event: trace\ndata: {\"event\":{\"kind\":\"tool_call\",\"summary\":\"Get-ChildItem\",\"tool_name\":\"shell_command\",\"call_id\":\"call-1\"}}\n\n"));
        controller.enqueue(encoder.encode("event: done\ndata: {\"output\":\"最终结果\",\"elapsed_seconds\":4}\n\n"));
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    const statuses: Array<{ elapsedSeconds?: number; previewText?: string; contextUsage?: { sessionId?: string; statusText?: string; compactionCount?: number } }> = [];
    const traces: string[] = [];
    const agUiEvents: string[] = [];
    const message = await client.sendMessage("main", "hello", () => undefined, (status) => {
      statuses.push(status);
    }, (trace) => {
      traces.push(`${trace.kind}:${trace.summary}:${trace.toolName || ""}`);
    }, undefined, (event) => {
      agUiEvents.push(event.type);
    });

    expect(statuses).toEqual([
      expect.objectContaining({
        elapsedSeconds: 2,
        previewText: "处理中预览",
        contextUsage: expect.objectContaining({
          sessionId: "thread-1",
          statusText: "74% context left · 76.6K / 258K",
          compactionCount: 1,
        }),
      }),
    ]);
    expect(traces).toEqual(["tool_call:Get-ChildItem:shell_command"]);
    expect(agUiEvents).toEqual([]);
    expect(message.text).toBe("最终结果");
    expect(message.elapsedSeconds).toBe(4);
    expect(message.meta?.tracePresentation).toBeUndefined();
    expect(message.meta?.traceCount).toBe(1);
    expect(message.meta?.toolCallCount).toBe(1);
    expect(message.meta?.contextUsage).toEqual(expect.objectContaining({
      sessionId: "thread-1",
      statusText: "74% context left · 76.6K / 258K",
      compactionCount: 1,
    }));
  });

  
  
  
  
  test("getGitOverview maps git workspace payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            repo_found: true,
            can_init: false,
            working_dir: "C:\\workspace\\repo",
            repo_path: "C:\\workspace\\repo",
            repo_name: "repo",
            current_branch: "main",
            is_clean: false,
            ahead_count: 1,
            behind_count: 0,
            changed_files: [
              {
                path: "tracked.txt",
                status: "M ",
                staged: true,
                unstaged: false,
                untracked: false,
              },
            ],
            recent_commits: [
              {
                hash: "abcdef",
                short_hash: "abcdef",
                author_name: "Web Bot",
                authored_at: "2026-04-09 21:00:00 +0800",
                subject: "feat: initial commit",
                message: "feat: initial commit\n\nadd first repo snapshot",
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const overview = await client.getGitOverview("main");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/git",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
    expect(overview.repoFound).toBe(true);
    expect(overview.currentBranch).toBe("main");
    expect(overview.changedFiles[0].path).toBe("tracked.txt");
    expect(overview.recentCommits[0]).toMatchObject({
      subject: "feat: initial commit",
      message: "feat: initial commit\n\nadd first repo snapshot",
    });
  });

  test("getGitTreeStatus maps git tree payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            repo_found: true,
            working_dir: "C:\\workspace\\repo",
            repo_path: "C:\\workspace\\repo",
            items: {
              "src/app.ts": "modified",
              "new.ts": "added",
              "dist": "ignored",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const status = await client.getGitTreeStatus("main");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/git/tree-status",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
    expect(status).toEqual({
      repoFound: true,
      workingDir: "C:\\workspace\\repo",
      repoPath: "C:\\workspace\\repo",
      items: {
        "src/app.ts": "modified",
        "new.ts": "added",
        "dist": "ignored",
      },
    });
  });

  test("getGitCommitGraph maps snake case payload and query", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      repo_found: true,
      scope: "current",
      nodes: [
        {
          hash: "abcdef012345",
          short_hash: "abcdef0",
          parents: ["123456789abc"],
          author_name: "Web Bot",
          authored_at: "2026-04-09T21:00:00+08:00",
          subject: "feat: graph",
          refs: [
            { name: "HEAD", kind: "head", current: true },
            { name: "main", kind: "local_branch", current: true },
            { name: "origin/main", kind: "remote_branch", current: false },
          ],
          graph: {
            column: "bad",
            width: null,
            edges: [{ from: 1, to: 0, commit: "123456789abc" }, { from: "bad", to: null }],
          },
          can_reset: false,
        },
      ],
      has_more: true,
      next_cursor: "cursor-2",
    }));

    const client = new RealWebBotClient();
    const graph = await client.getGitCommitGraph("main", { scope: "current", limit: 25, cursor: "cursor-1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/git/graph?scope=current&limit=25&cursor=cursor-1",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(graph).toEqual({
      repoFound: true,
      scope: "current",
      nodes: [
        {
          hash: "abcdef012345",
          shortHash: "abcdef0",
          parents: ["123456789abc"],
          authorName: "Web Bot",
          authoredAt: "2026-04-09T21:00:00+08:00",
          subject: "feat: graph",
          refs: [
            { name: "HEAD", kind: "head", current: true },
            { name: "main", kind: "local_branch", current: true },
            { name: "origin/main", kind: "remote_branch", current: false },
          ],
          graph: {
            column: 0,
            width: 1,
            edges: [{ from: 1, to: 0, commit: "123456789abc" }, { from: 0, to: 0 }],
          },
          canReset: false,
        },
      ],
      hasMore: true,
      nextCursor: "cursor-2",
    });
  });

  test("createGitBranch sends start point in request body", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      current_branch: "main",
      branches: [
        {
          name: "feature/from-commit",
          current: false,
          upstream: "",
          short_hash: "abcdef0",
          subject: "feat: initial commit",
        },
      ],
    }));

    const client = new RealWebBotClient();
    const result = await client.createGitBranch("main", "feature/from-commit", "abcdef012345");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/git/branches",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "feature/from-commit", start_point: "abcdef012345" }),
      }),
    );
    expect(result.branches[0].shortHash).toBe("abcdef0");
  });

  test("resetGitBranch sends commit and mode then maps payload", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      message: "分支已重置",
      overview: {
        repo_found: true,
        can_init: false,
        working_dir: "C:\\workspace\\repo",
        repo_path: "C:\\workspace\\repo",
        repo_name: "repo",
        current_branch: "main",
        is_clean: true,
        ahead_count: 0,
        behind_count: 0,
        changed_files: [],
        recent_commits: [
          {
            hash: "abcdef012345",
            short_hash: "abcdef0",
            author_name: "Web Bot",
            authored_at: "2026-04-09 21:00:00 +0800",
            subject: "feat: initial commit",
          },
        ],
      },
      branches: [
        {
          name: "main",
          current: true,
          upstream: "origin/main",
          short_hash: "abcdef0",
          subject: "feat: initial commit",
        },
      ],
      current_branch: "main",
      head_commit: "abcdef012345",
    }));

    const client = new RealWebBotClient();
    const result = await client.resetGitBranch("main", "abcdef012345", "hard");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/git/branches/reset",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ commit: "abcdef012345", mode: "hard" }),
      }),
    );
    expect(result.currentBranch).toBe("main");
    expect(result.headCommit).toBe("abcdef012345");
    expect(result.overview.isClean).toBe(true);
    expect(result.branches[0].name).toBe("main");
  });

  
  
  test("assistant proposal endpoints map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                id: "pr_1",
                kind: "code",
                title: "补审计",
                body: "- body",
                status: "proposed",
                created_at: "2026-04-28T00:00:00Z",
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                alias: "target1",
                working_dir: "C:\\workspace\\target1",
                repo_root: "C:\\workspace\\target1",
                head: "deadbeef",
                dirty: false,
                dirty_paths: [],
                bot_mode: "cli",
                cli_type: "codex",
                cli_path: "codex",
                available: true,
                reason: "",
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            proposal: {
              id: "pr_1",
              kind: "code",
              title: "补审计",
              body: "- body",
              status: "approved",
              created_at: "2026-04-28T00:00:00Z",
            },
            diff: {
              available: true,
              source: "upgrades/pending/pr_1.patch",
              text: "diff --git",
            },
            apply: {
              available: false,
              applied: false,
              last_error: "",
              last_error_at: "",
              last_error_log_path: "",
            },
            upgrade: {
              state: "pending",
              target_alias: "target1",
              target_repo_root: "C:\\workspace\\target1",
              base_commit: "deadbeef",
              patch_source: "upgrades/pending/pr_1.patch",
              generation_status: "succeeded",
              sensitive_hits: [],
              can_generate: true,
              can_approve_patch: true,
              can_dry_run: false,
              can_apply: false,
            },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            id: "pr_1",
            proposal_id: "pr_1",
            state: "pending",
            target_alias: "target1",
            target_working_dir: "C:\\workspace\\target1",
            target_repo_root: "C:\\workspace\\target1",
            base_commit: "deadbeef",
            worktree_path: "C:\\workspace\\.assistant\\upgrades\\worktrees\\pr_1",
            patch_path: "upgrades/pending/pr_1.patch",
            generated_at: "2026-04-28T01:00:00Z",
            generated_by: "1001",
            generator: {
              cli_type: "codex",
              cli_path: "codex",
              status: "succeeded",
              elapsed_seconds: 3,
            },
            dry_run: {
              ok: false,
              checked_at: "",
              stderr: "",
            },
            sensitive_hits: [],
            changed_files: ["bot/x.py"],
            additions: 3,
            deletions: 1,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            id: "pr_1",
            proposal_id: "pr_1",
            state: "approved",
            target_alias: "target1",
            target_working_dir: "C:\\workspace\\target1",
            target_repo_root: "C:\\workspace\\target1",
            base_commit: "deadbeef",
            worktree_path: "C:\\workspace\\.assistant\\upgrades\\worktrees\\pr_1",
            patch_path: "upgrades/approved/pr_1.patch",
            generated_at: "2026-04-28T01:00:00Z",
            generated_by: "1001",
            approved_by: "1001",
            approved_at: "2026-04-28T01:10:00Z",
            generator: {
              cli_type: "codex",
              cli_path: "codex",
              status: "succeeded",
              elapsed_seconds: 3,
            },
            dry_run: {
              ok: false,
              checked_at: "",
              stderr: "",
            },
            sensitive_hits: [],
            changed_files: ["bot/x.py"],
            additions: 3,
            deletions: 1,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            proposal: {
              id: "pr_1",
              kind: "code",
              title: "补审计",
              body: "- body",
              status: "approved",
              created_at: "2026-04-28T00:00:00Z",
            },
            diff: {
              available: true,
              source: "upgrades/approved/pr_1.patch",
              text: "diff --git",
            },
            apply: {
              available: true,
              applied: false,
              last_error: "",
              last_error_at: "",
              last_error_log_path: "",
            },
            upgrade: {
              state: "approved",
              target_alias: "target1",
              target_repo_root: "C:\\workspace\\target1",
              base_commit: "deadbeef",
              patch_source: "upgrades/approved/pr_1.patch",
              generation_status: "succeeded",
              sensitive_hits: [],
              dry_run: {
                ok: true,
                checked_at: "2026-04-28T01:12:00Z",
                stdout: "Patch cleanly applies",
                stderr: "",
                patch_path: "upgrades/approved/pr_1.patch",
                repo_root: "C:\\workspace\\target1",
              },
              can_generate: true,
              can_approve_patch: false,
              can_dry_run: true,
              can_apply: true,
            },
            generation_log: {
              available: true,
              source: "upgrades/logs/pr_1.generate.jsonl",
              items: [
                {
                  event: "failed",
                  created_at: "2026-04-28T01:00:00Z",
                  code: "TimeoutExpired",
                  error: "timed out",
                },
              ],
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const proposals = await client.listAssistantProposals("assistant1", "proposed");
    const targets = await client.listAssistantUpgradeTargets("assistant1");
    const pendingDetail = await client.getAssistantProposal("assistant1", "pr_1");
    const pendingPatch = await client.generateAssistantProposalPatch("assistant1", "pr_1", {
      targetAlias: "target1",
      regenerate: true,
    });
    const approvedPatch = await client.approveAssistantProposalPatch("assistant1", "pr_1");
    const detail = await client.getAssistantProposal("assistant1", "pr_1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/bots/assistant1/assistant/proposals?status=proposed",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
        headers: {},
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/admin/bots/assistant1/assistant/upgrade-targets",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1/patch",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          target_alias: "target1",
          regenerate: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1/patch/approve",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1",
      expect.any(Object),
    );
    expect(proposals[0]).toEqual(expect.objectContaining({
      id: "pr_1",
      title: "补审计",
      status: "proposed",
    }));
    expect(targets[0]).toEqual(expect.objectContaining({
      alias: "target1",
      repoRoot: "C:\\workspace\\target1",
      available: true,
      dirtyPaths: [],
    }));
    expect(pendingDetail.upgrade.state).toBe("pending");
    expect(pendingPatch.targetAlias).toBe("target1");
    expect(approvedPatch.approvedBy).toBe("1001");
    expect(detail.diff.available).toBe(true);
    expect(detail.apply.available).toBe(true);
    expect(detail.upgrade.canDryRun).toBe(true);
    expect(detail.upgrade.dryRun.stdout).toBe("Patch cleanly applies");
    expect(detail.generationLog.items[0]).toEqual(expect.objectContaining({
      event: "failed",
      code: "TimeoutExpired",
      error: "timed out",
    }));
  });

  
  
  test("admin center user permission APIs map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [{
              account_id: "member_1",
              username: "alice",
              role: "member",
              disabled: false,
              created_at: "2026-05-12T00:00:00Z",
              allowed_bots: ["main"],
              owned_bots: ["team1"],
              owned_bot_count: 1,
              bot_create_limit: 3,
            }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            account_id: "member_1",
            allowed_bots: ["main", "sub1"],
          },
        }),
      });

    const client = new RealWebBotClient();
    const users = await client.listAdminUsers();
    const updated = await client.updateUserBotPermissions("member_1", ["main", "sub1"]);

    expect(users[0].allowedBots).toEqual(["main"]);
    expect(users[0].ownedBotCount).toBe(1);
    expect(users[0].botCreateLimit).toBe(3);
    expect(updated.allowedBots).toEqual(["main", "sub1"]);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/users/member_1/permissions",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  
  test("offline update APIs map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            artifacts_dir: ".release-local/artifacts",
            items: [{
              name: "offline.zip",
              path: "C:\\pkg\\offline.zip",
              version: "1.2.3",
              package_kind: "installer",
              size_bytes: 10,
              valid: true,
              error: "",
            }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_version: "1.0.0",
            current_package_kind: "installer",
            update_enabled: true,
            update_channel: "release",
            last_checked_at: "",
            latest_version: "1.2.3",
            latest_release_url: "",
            latest_notes: "",
            pending_update_version: "1.2.3",
            pending_update_path: "C:\\pkg\\offline.zip",
            pending_update_notes: "",
            pending_update_platform: "windows-x64-installer",
            pending_update_package_kind: "installer",
            last_error: "",
          },
        }),
      });

    const client = new RealWebBotClient();
    const packages = await client.listOfflineUpdatePackages();
    const status = await client.prepareOfflineUpdate("C:\\pkg\\offline.zip", "1.2.3");

    expect(packages.items[0].valid).toBe(true);
    expect(packages.items[0].sizeBytes).toBe(10);
    expect(status.pendingUpdateVersion).toBe("1.2.3");
    expect(status.pendingUpdatePath).toBe("C:\\pkg\\offline.zip");
  });

  
  });
