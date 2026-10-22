import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import * as appearanceRuntime from "../theme/appearanceRuntime";
import type { ResolvedAppearance } from "../theme/types";
import type { WebBotClient } from "../services/webBotClient";

const terminalState = vi.hoisted(() => ({
  onData: null as ((data: string) => void) | null,
  csiCHandler: null as ((params: (number | number[])[]) => boolean | Promise<boolean>) | null,
  deferWriteCompletion: false,
  writeCallbacks: [] as Array<() => void>,
  writes: [] as string[],
  instances: [] as Array<{
    options: Record<string, unknown>;
    output: string[];
    reset: ReturnType<typeof vi.fn>;
    clear: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class MockTerminal {
    cols = 120;
    rows = 40;
    options: Record<string, unknown> = {};
    output: string[] = [];
    constructor(options: Record<string, unknown>) {
      this.options = { ...options };
      terminalState.instances.push(this);
    }
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
      this.output.push(text);
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
    reset = vi.fn(() => { this.output.length = 0; });
    clear = vi.fn(() => { this.output.length = 0; });
    focus() {}
    dispose = vi.fn();
    onWriteParsed() { return { dispose: vi.fn() }; }
    onScroll() { return { dispose: vi.fn() }; }
    scrollToBottom() {}

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
import { TerminalScreen } from "../screens/TerminalScreen";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";

const initialAppearance = appearanceRuntime.getCurrentAppearance();

function terminalAppearance(revision: string, foreground: string): ResolvedAppearance {
  return {
    ...initialAppearance, themeId: "theme_personal", revision,
    colors: { ...initialAppearance.colors, "terminal.foreground": foreground, "terminal.background": "#182028FF" },
  };
}

describe("terminal session", () => {
  afterEach(() => {
    cleanup();
    appearanceRuntime.applyResolvedAppearance(initialAppearance);
    terminalState.instances.length = 0;
    sockets.length = 0;
    terminalState.onData = null;
    terminalState.csiCHandler = null;
    terminalState.deferWriteCompletion = false;
    terminalState.writeCallbacks.length = 0;
    terminalState.writes.length = 0;
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("uses the current snapshot for new terminals and accepts explicit palettes and legacy calls", () => {
    const snapshot = terminalAppearance("terminal-1", "#E0E1E2FF");
    appearanceRuntime.applyResolvedAppearance(snapshot);
    const session = createTerminalSession(document.createElement("div"), { token: "", ownerId: "one", themeName: "paper-daylight" });
    expect(session.term.options.theme).toEqual(appearanceRuntime.resolvedTerminalTheme(snapshot));
    expect(session.term.options.theme.foreground).toBe("#E0E1E2FF");
    const explicit = { background: "#111213", foreground: "#AABBCC", red: "#CC2211" };
    const second = createTerminalSession(document.createElement("div"), { token: "", ownerId: "two", theme: explicit });
    expect(second.term.options.theme).toEqual(explicit);
    const next = terminalAppearance("terminal-2", "#B0C0D0FF");
    second.setTheme(next);
    expect(second.term.options.theme).toEqual(appearanceRuntime.resolvedTerminalTheme(next));
    second.setTheme(explicit);
    expect(second.term.options.theme).toEqual(explicit);
    appearanceRuntime.applyResolvedAppearance(next);
    session.setTheme("theme_personal");
    expect(session.term.options.theme).toEqual(appearanceRuntime.resolvedTerminalTheme(next));
    session.dispose();
    second.dispose();
  });

  it("an open screen applies same-ID color revisions without recreating its terminal, socket or output buffer", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket);
    appearanceRuntime.applyResolvedAppearance(terminalAppearance("screen-1", "#E0E1E2FF"));
    const client = {
      getTerminalSession: vi.fn(async () => ({ started: true, closed: false, cwd: "C:/workspace", ptyMode: true, connectionText: "运行中", lastSeq: 0 })),
      getTerminalActionsConfig: vi.fn(async () => ({ actions: [], errors: [], runtimePlatform: "windows" })),
      closeTerminalSession: vi.fn(),
    } as unknown as WebBotClient;
    const screen = (isVisible: boolean) => createElement(PersistentTerminalProvider, {
      client,
      children: createElement(TerminalScreen, { authToken: "", botAlias: "main", client, isVisible, themeName: "theme_personal" }),
    });
    const { rerender } = render(screen(true));
    await waitFor(() => expect(terminalState.instances).toHaveLength(1));
    const term = terminalState.instances[0];
    const socket = sockets[0];
    const owner = new URL(socket.url).searchParams.get("owner_id");
    await act(async () => {
      socket.open();
      socket.receive(JSON.stringify({ protocol_version: 2, stream_id: "stream-theme", pty_mode: true }));
      socket.receive(frame(1n, "retained terminal output\r\n"));
    });
    await waitFor(() => expect(term.output).toEqual(["retained terminal output\r\n"]));
    const next = terminalAppearance("screen-2", "#A0B0C0FF");
    await act(async () => { appearanceRuntime.applyResolvedAppearance(next); });
    expect(term.options.theme).toEqual(appearanceRuntime.resolvedTerminalTheme(next));
    expect(term.options.theme).toMatchObject({ foreground: "#A0B0C0FF" });
    rerender(screen(false));
    const hidden = terminalAppearance("screen-3", "#B0C0D0FF");
    await act(async () => { appearanceRuntime.applyResolvedAppearance(hidden); });
    expect(term.options.theme).toEqual(appearanceRuntime.resolvedTerminalTheme(hidden));
    expect(terminalState.instances).toHaveLength(1);
    expect(sockets).toEqual([socket]);
    expect(new URL(socket.url).searchParams.get("owner_id")).toBe(owner);
    expect(socket.readyState).toBe(MockWebSocket.OPEN);
    expect(term.output).toEqual(["retained terminal output\r\n"]);
    expect(term.reset).not.toHaveBeenCalled();
    expect(term.clear).not.toHaveBeenCalled();
    expect(term.dispose).not.toHaveBeenCalled();
    expect(client.closeTerminalSession).not.toHaveBeenCalled();
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
