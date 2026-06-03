import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createTerminalSession } from "../services/terminalSession";
import { getTerminalTheme } from "../theme";

const terminalState = vi.hoisted(() => ({
  instances: [] as Array<{
    cols: number;
    rows: number;
    options: { theme?: unknown; minimumContrastRatio?: unknown };
  }>,
  fitCalls: 0,
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    cols = 132;
    rows = 40;
    options: { theme?: unknown; minimumContrastRatio?: unknown };
    textarea = document.createElement("textarea");

    constructor(options: { theme?: unknown; minimumContrastRatio?: unknown }) {
      this.options = { ...options };
      terminalState.instances.push(this);
    }

    loadAddon() {}

    open() {}

    focus() {}

    write() {}

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
  terminalState.instances = [];
  terminalState.fitCalls = 0;
  socketState.instances = [];
  vi.stubGlobal("__PUBLIC_ENV__", {});
  vi.stubGlobal("WebSocket", MockSocket as unknown as typeof WebSocket);
});

afterEach(() => {
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
  expect(errors[0]).toContain("code 1006");
});

test("reports websocket error with path context", () => {
  const errors: string[] = [];
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    onError: (message) => errors.push(message),
  });

  session.connect();
  socketState.instances[0].emitError();

  expect(errors[0]).toContain("终端已启动，但 WebSocket 连接失败");
  expect(errors[0]).toContain("路径 /terminal/ws?...");
});
