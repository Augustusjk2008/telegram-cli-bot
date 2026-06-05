import { expect, test, vi } from "vitest";
import { createDebugSession } from "../services/debugSession";

class MockSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockSocket.CONNECTING;
  private readonly listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(public readonly url: string) {}

  addEventListener(type: string, handler: (event: Event) => void) {
    const handlers = this.listeners.get(type) ?? new Set<(event: Event) => void>();
    handlers.add(handler);
    this.listeners.set(type, handlers);
  }

  close() {
    this.readyState = MockSocket.CLOSED;
  }
}

test("debug websocket url keeps alias and omits token query", async () => {
  const socketUrls: string[] = [];

  vi.stubGlobal("WebSocket", class extends MockSocket {
    constructor(url: string) {
      super(url);
      socketUrls.push(url);
    }
  } as unknown as typeof WebSocket);

  const session = createDebugSession({
    token: "legacy-token",
    botAlias: "main",
  });

  void session.connect();

  expect(socketUrls[0]).toContain("/debug/ws?alias=main");
  expect(socketUrls[0]).not.toContain("token=");

  vi.unstubAllGlobals();
});
