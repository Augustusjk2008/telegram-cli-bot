import { afterEach, describe, expect, it, vi } from "vitest";

const terminalState = vi.hoisted(() => ({
  onData: null as ((data: string) => void) | null,
  csiCHandler: null as ((params: (number | number[])[]) => boolean | Promise<boolean>) | null,
  deferWriteCompletion: false,
  writeCallbacks: [] as Array<() => void>,
  writes: [] as string[],
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    cols = 120;
    rows = 40;
    options: Record<string, unknown> = {};
    textarea = { focus: vi.fn() };
    parser = {
      registerCsiHandler: (
        _id: { final: string },
        callback: (params: (number | number[])[]) => boolean | Promise<boolean>,
      ) => {
        terminalState.csiCHandler = callback;
        return {
          dispose: () => {
            if (terminalState.csiCHandler === callback) {
              terminalState.csiCHandler = null;
            }
          },
        };
      },
    };

    loadAddon() {}
    open() {}
    write(data: string | Uint8Array, callback?: () => void) {
      const text = typeof data === "string" ? data : new TextDecoder().decode(data);
      terminalState.writes.push(text);
      const handled = text === "\u001b[c" && terminalState.csiCHandler?.([]) === true;
      if (text === "\u001b[c" && !handled) {
        terminalState.onData?.("\u001b[?1;2c");
      }
      if (callback && terminalState.deferWriteCompletion) {
        terminalState.writeCallbacks.push(callback);
      } else {
        callback?.();
      }
    }
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

function frame(sequence: bigint, payload: string) {
  const bytes = new TextEncoder().encode(payload);
  const buffer = new ArrayBuffer(14 + bytes.length);
  const view = new DataView(buffer);
  [0x54, 0x43, 0x42, 0x32].forEach((value, index) => view.setUint8(index, value));
  view.setUint8(4, 2);
  view.setUint8(5, 0);
  view.setBigUint64(6, sequence, false);
  new Uint8Array(buffer, 14).set(bytes);
  return buffer;
}

import { createTerminalSession } from "../services/terminalSession";

describe("terminal session", () => {
  afterEach(() => {
    sockets.length = 0;
    terminalState.onData = null;
    terminalState.csiCHandler = null;
    terminalState.deferWriteCompletion = false;
    terminalState.writeCallbacks.length = 0;
    terminalState.writes.length = 0;
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
  });

  it("keeps the active node base and tab owner in the terminal WebSocket URL", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/nanjing-laptop" });
    window.history.replaceState(null, "", "/node/nanjing-laptop/terminal");

    const session = createTerminalSession(document.createElement("div"), {
      token: "session-secret",
      ownerId: "terminal-tab-42",
    });
    session.connect();

    const socketUrl = new URL(sockets[0].url);
    expect(socketUrl.pathname).toBe("/node/nanjing-laptop/terminal/ws");
    expect(socketUrl.searchParams.get("owner_id")).toBe("terminal-tab-42");
    session.dispose();
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

  it("does not resend terminal replies while restoring output already rendered by this tab", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    const container = document.createElement("div");
    const options = {
      token: "",
      ownerId: "main",
      previousRecoveryState: {
        streamId: "stream-1",
        lastAppliedSequence: 1,
      },
    };
    const session = createTerminalSession(container, options);

    session.connect();
    const socket = sockets[0];
    socket.open();
    socket.receive(JSON.stringify({
      protocol_version: 2,
      stream_id: "stream-1",
      last_seq: 1,
      pty_mode: true,
    }));

    terminalState.deferWriteCompletion = true;
    socket.receive(frame(1n, "\u001b[c"));
    await vi.waitFor(() => expect(terminalState.writes).toEqual(["\u001b[c"]));
    expect(socket.sent).not.toContain("\u001b[?1;2c");
    terminalState.onData?.("dir\r");
    expect(socket.sent.at(-1)).toBe("dir\r");
    terminalState.writeCallbacks.shift()?.();
    terminalState.deferWriteCompletion = false;

    socket.receive(frame(2n, "\u001b[c"));
    await vi.waitFor(() => expect(terminalState.writes).toEqual(["\u001b[c", "\u001b[c"]));
    expect(socket.sent.filter((data) => data === "\u001b[?1;2c")).toHaveLength(1);

    session.dispose();
  });
});
