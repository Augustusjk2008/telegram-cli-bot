import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createTerminalSession } from "../services/terminalSession";
import { getTerminalTheme } from "../theme";

const terminalState = vi.hoisted(() => ({
  instances: [] as Array<{
    cols: number;
    rows: number;
    options: { theme?: unknown; minimumContrastRatio?: unknown };
    writes: unknown[];
    emitData: (data: string) => void;
  }>,
  fitCalls: 0,
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    cols = 132;
    rows = 40;
    options: { theme?: unknown; minimumContrastRatio?: unknown };
    textarea = document.createElement("textarea");
    writes: unknown[] = [];
    private readonly dataHandlers = new Set<(data: string) => void>();

    constructor(options: { theme?: unknown; minimumContrastRatio?: unknown }) {
      this.options = { ...options };
      terminalState.instances.push(this);
    }

    loadAddon() {}

    open() {}

    focus() {}

    write(data: unknown) {
      this.writes.push(data);
    }

    onData(handler: (data: string) => void) {
      this.dataHandlers.add(handler);
      return { dispose: () => this.dataHandlers.delete(handler) };
    }

    emitData(data: string) {
      for (const handler of this.dataHandlers) {
        handler(data);
      }
    }

    dispose() {}

    scrollToBottom() {}
  },
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class MockFitAddon {
    fit() {
      terminalState.fitCalls += 1;
    }
  },
}));

vi.mock("@xterm/addon-attach", () => ({
  AttachAddon: class MockAttachAddon {
    dispose() {}
  },
}));

const socketState = {
  instances: [] as MockSocket[],
};

const fetchState = {
  requests: [] as Array<{ url: string; init?: RequestInit }>,
  inputBodies: [] as unknown[],
};

function createPendingFetch() {
  return vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    fetchState.requests.push({ url: String(url), init });
    if (init?.body) {
      try {
        fetchState.inputBodies.push(JSON.parse(String(init.body)));
      } catch {
        fetchState.inputBodies.push(init.body);
      }
    }
    return new Promise<Response>(() => {});
  });
}

function createSseResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  }), {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
    },
  });
}

class MockSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockSocket.CONNECTING;
  binaryType = "blob";
  sent: string[] = [];
  private readonly listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(public readonly url: string) {
    socketState.instances.push(this);
  }

  addEventListener(type: string, handler: (event: Event) => void) {
    const handlers = this.listeners.get(type) ?? new Set<(event: Event) => void>();
    handlers.add(handler);
    this.listeners.set(type, handlers);
  }

  removeEventListener(type: string, handler: (event: Event) => void) {
    this.listeners.get(type)?.delete(handler);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = MockSocket.CLOSED;
    this.dispatch("close", new CloseEvent("close"));
  }

  closeWith(code: number, reason = "") {
    this.readyState = MockSocket.CLOSED;
    this.dispatch("close", new CloseEvent("close", { code, reason }));
  }

  open() {
    this.readyState = MockSocket.OPEN;
    this.dispatch("open", new Event("open"));
  }

  emitError() {
    this.dispatch("error", new Event("error"));
  }

  emitMessage(data: string | ArrayBuffer | Blob) {
    this.dispatch("message", new MessageEvent("message", { data }));
  }

  private dispatch(type: string, event: Event) {
    for (const handler of this.listeners.get(type) ?? []) {
      handler(event);
    }
  }
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  delete window.__TCB_PUBLIC_ENV__;
  terminalState.instances = [];
  terminalState.fitCalls = 0;
  socketState.instances = [];
  fetchState.requests = [];
  fetchState.inputBodies = [];
  vi.stubGlobal("__PUBLIC_ENV__", {});
  vi.stubGlobal("WebSocket", MockSocket as unknown as typeof WebSocket);
  vi.stubGlobal("fetch", createPendingFetch());
});

afterEach(() => {
  delete window.__TCB_PUBLIC_ENV__;
  vi.unstubAllGlobals();
});

test("connect sends initial geometry and fit sends resize payload", () => {
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    fromSeq: 12,
  });

  session.connect();
  const socket = socketState.instances[0];
  expect(socket?.url).toContain("/terminal/ws?token=abc&owner_id=owner-1");
  socket.open();

  expect(JSON.parse(socket.sent[0] ?? "{}")).toEqual({
    owner_id: "owner-1",
    from_seq: 12,
    cols: 132,
    rows: 40,
  });

  session.fit();

  expect(JSON.parse(socket.sent[1] ?? "{}")).toEqual({
    type: "resize",
    cols: 132,
    rows: 40,
  });
});

test("connect applies node base path to websocket url", () => {
  window.history.replaceState(null, "", "/node/nanjing-laptop/");
  vi.stubGlobal("__PUBLIC_ENV__", {
    VITE_API_BASE_URL: "/node/nanjing-laptop",
  });
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
  });

  session.connect();
  const socket = socketState.instances[0];

  expect(new URL(socket.url).pathname).toBe("/node/nanjing-laptop/terminal/ws");
});

test("connect uses runtime base path before stale build base path", () => {
  window.history.replaceState(null, "", "/node/nanjing-laptop/");
  vi.stubGlobal("__PUBLIC_ENV__", {
    VITE_API_BASE_URL: "/node/local",
  });
  window.__TCB_PUBLIC_ENV__ = {
    VITE_API_BASE_URL: "/node/nanjing-laptop",
  };
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
  });

  session.connect();
  const socket = socketState.instances[0];

  expect(new URL(socket.url).pathname).toBe("/node/nanjing-laptop/terminal/ws");
});

test("connect ignores node base path when page is served from root", () => {
  vi.stubGlobal("__PUBLIC_ENV__", {
    VITE_API_BASE_URL: "/node/local",
  });
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
  });

  session.connect();
  const socket = socketState.instances[0];

  expect(new URL(socket.url).pathname).toBe("/terminal/ws");
});

test("reports backend terminal websocket error before attach", () => {
  const errors: string[] = [];
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    onError: (message) => errors.push(message),
  });

  session.connect();
  socketState.instances[0].emitMessage(JSON.stringify({ error: "终端未启动" }));

  expect(errors).toEqual(["终端 WebSocket 连接被后端拒绝：终端未启动"]);
});

test("reports websocket close code and path when connection fails", () => {
  const errors: string[] = [];
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    onError: (message) => errors.push(message),
  });

  session.connect();
  socketState.instances[0].closeWith(1006);

  expect(errors[0]).toContain("终端已启动，但 WebSocket 连接失败");
  expect(errors[0]).toContain("路径 /terminal/ws?...");
  expect(errors[0]).toContain("页面 /");
  expect(errors[0]).toContain("base /（配置 /，来源 build）");
  expect(errors[0]).toContain("code 1006");
});

test("falls back to http terminal stream when websocket fails before attach", async () => {
  const errors: string[] = [];
  const opened: string[] = [];
  const closed: string[] = [];
  let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
  const encoder = new TextEncoder();
  vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const requestUrl = String(url);
    fetchState.requests.push({ url: requestUrl, init });
    if (init?.body) {
      fetchState.inputBodies.push(JSON.parse(String(init.body)));
      return Promise.resolve(new Response(JSON.stringify({ ok: true, data: { accepted: true } }), { status: 200 }));
    }
    if (new URL(requestUrl).pathname === "/terminal/ws-probe") {
      return Promise.resolve(new Response(JSON.stringify({
        ok: true,
        data: {
          path: "/terminal/ws-probe",
          configured_base_path: "",
          auth_status: "ok",
          origin_allowed: true,
        },
      }), { status: 200 }));
    }
    return Promise.resolve(new Response(new ReadableStream({
      start(controller) {
        streamController = controller;
        controller.enqueue(encoder.encode("event: ready\ndata: {\"pty_mode\":true,\"connection_text\":\"运行中\"}\n\n"));
        controller.enqueue(encoder.encode("event: output\ndata: {\"data\":\"aGVsbG8K\",\"encoding\":\"base64\"}\n\n"));
      },
    }), {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
      },
    }));
  }));
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    fromSeq: 7,
    onOpen: () => opened.push("open"),
    onClose: () => closed.push("close"),
    onError: (message) => errors.push(message),
  });

  session.connect();
  socketState.instances[0].emitError();
  await vi.waitFor(() => expect(fetchState.requests.length).toBeGreaterThanOrEqual(2));
  await vi.waitFor(() => expect(opened).toEqual(["open"]));
  session.sendText("pwd\n");

  expect(errors[0]).toContain("已切换到 HTTP 终端流");
  await vi.waitFor(() => expect(errors.some((message) => message.includes("HTTP 探针已到达后端且鉴权通过"))).toBe(true));
  const streamRequest = fetchState.requests.find((request) => new URL(request.url).pathname === "/api/terminal/session/stream");
  const probeRequest = fetchState.requests.find((request) => new URL(request.url).pathname === "/terminal/ws-probe");
  expect(streamRequest).toBeDefined();
  expect(probeRequest).toBeDefined();
  expect(new URL(streamRequest!.url).searchParams.get("owner_id")).toBe("owner-1");
  expect(new URL(streamRequest!.url).searchParams.get("from_seq")).toBe("7");
  expect(streamRequest!.init?.headers).toEqual(expect.objectContaining({ Authorization: "Bearer abc" }));
  expect(probeRequest!.init?.headers).toEqual(expect.objectContaining({ Authorization: "Bearer abc" }));
  expect(terminalState.instances[0].writes).toHaveLength(1);
  await vi.waitFor(() => expect(fetchState.inputBodies).toEqual([{ owner_id: "owner-1", data: "pwd\n" }]));
  streamController?.close();
  await vi.waitFor(() => expect(closed).toEqual(["close"]));
});

test("websocket fallback probe uses runtime base path", async () => {
  const errors: string[] = [];
  window.history.replaceState(null, "", "/node/local/");
  window.__TCB_PUBLIC_ENV__ = {
    VITE_API_BASE_URL: "/node/local",
  };
  vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const requestUrl = String(url);
    fetchState.requests.push({ url: requestUrl, init });
    if (new URL(requestUrl).pathname === "/node/local/terminal/ws-probe") {
      return Promise.resolve(new Response(JSON.stringify({
        ok: true,
        data: {
          path: "/node/local/terminal/ws-probe",
          configured_base_path: "/node/local",
          auth_status: "ok",
          origin_allowed: false,
          forwarded_host: "proxy.example.test",
          forwarded_proto: "https",
        },
      }), { status: 200 }));
    }
    return Promise.resolve(createSseResponse([
      "event: ready\ndata: {\"pty_mode\":true,\"connection_text\":\"运行中\"}\n\n",
    ]));
  }));
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    onError: (message) => errors.push(message),
  });

  session.connect();
  socketState.instances[0].emitError();

  await vi.waitFor(() => expect(fetchState.requests.some((request) => new URL(request.url).pathname === "/node/local/terminal/ws-probe")).toBe(true));
  await vi.waitFor(() => expect(errors.some((message) => message.includes("Origin/代理头不匹配"))).toBe(true));
});

test("reports websocket error with path context", () => {
  const errors: string[] = [];
  window.history.replaceState(null, "", "/node/local/");
  window.__TCB_PUBLIC_ENV__ = {
    VITE_API_BASE_URL: "/node/local",
  };
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    onError: (message) => errors.push(message),
  });

  session.connect();
  socketState.instances[0].emitError();

  expect(errors[0]).toContain("终端已启动，但 WebSocket 连接失败");
  expect(errors[0]).toContain("路径 /node/local/terminal/ws?...");
  expect(errors[0]).toContain("页面 /node/local/");
  expect(errors[0]).toContain("base /node/local（配置 /node/local，来源 runtime:VITE_API_BASE_URL）");
});
