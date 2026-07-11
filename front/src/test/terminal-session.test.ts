import { afterEach, describe, expect, it, vi } from "vitest";

const terminalState = vi.hoisted(() => ({
  onData: null as ((data: string) => void) | null,
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    cols = 120;
    rows = 40;
    options: Record<string, unknown> = {};
    textarea = { focus: vi.fn() };

    loadAddon() {}
    open() {}
    write() {}
    reset() {}
    clear() {}
    focus() {}
    dispose() {}

    onData(callback: (data: string) => void) {
      terminalState.onData = callback;
      return {
        dispose: () => {
          if (terminalState.onData === callback) {
            terminalState.onData = null;
          }
        },
      };
    }
  },
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class MockFitAddon {
    fit() {}
  },
}));

vi.mock("@xterm/addon-attach", () => ({
  AttachAddon: class MockAttachAddon {
    dispose() {}
  },
}));

class MockWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly sent: Array<string | ArrayBufferLike | Blob | ArrayBufferView> = [];
  readyState = MockWebSocket.CONNECTING;
  binaryType: BinaryType = "blob";

  constructor(readonly url: string) {
    super();
    sockets.push(this);
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView) {
    this.sent.push(data);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  receive(data: string | ArrayBuffer) {
    this.dispatchEvent(new MessageEvent("message", { data }));
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }
}

const sockets: MockWebSocket[] = [];

import { createTerminalSession } from "../services/terminalSession";

describe("terminal session", () => {
  afterEach(() => {
    sockets.length = 0;
    terminalState.onData = null;
    vi.unstubAllGlobals();
  });

  it("forwards xterm input after a v2 WebSocket handshake", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const container = document.createElement("div");
    const session = createTerminalSession(container, {
      token: "",
      ownerId: "main",
    });

    session.connect();
    const socket = sockets[0];
    socket.open();
    socket.receive(JSON.stringify({
      protocol_version: 2,
      stream_id: "stream-1",
      pty_mode: true,
    }));

    terminalState.onData?.("dir\r");

    expect(socket.sent.at(-1)).toBe("dir\r");
    session.dispose();
  });
});
