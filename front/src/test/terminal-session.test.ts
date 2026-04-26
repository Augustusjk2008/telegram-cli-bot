import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createTerminalSession } from "../services/terminalSession";
import { getTerminalTheme } from "../theme";

const terminalState = vi.hoisted(() => ({
  instances: [] as Array<{
    cols: number;
    rows: number;
    options: { theme?: unknown };
  }>,
  fitCalls: 0,
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    cols = 132;
    rows = 40;
    options: { theme?: unknown };
    textarea = document.createElement("textarea");

    constructor(options: { theme?: unknown }) {
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

  open() {
    this.readyState = MockSocket.OPEN;
    this.dispatch("open", new Event("open"));
  }

  private dispatch(type: string, event: Event) {
    for (const handler of this.listeners.get(type) ?? []) {
      handler(event);
    }
  }
}

beforeEach(() => {
  terminalState.instances = [];
  terminalState.fitCalls = 0;
  socketState.instances = [];
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

test("setTheme updates the live xterm theme in place", () => {
  const container = document.createElement("div");
  const session = createTerminalSession(container, {
    token: "abc",
    ownerId: "owner-1",
    themeName: "deep-space",
  });

  session.setTheme("classic");

  expect(terminalState.instances[0]?.options.theme).toEqual(getTerminalTheme("classic"));
});
