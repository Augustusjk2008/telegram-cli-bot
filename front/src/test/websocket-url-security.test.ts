import { afterEach, describe, expect, it, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";

const urls: string[] = [];

class CapturedWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readyState = CapturedWebSocket.CONNECTING;

  constructor(url: string) {
    super();
    urls.push(url);
  }

  close() {
    this.readyState = CapturedWebSocket.CLOSED;
  }

  send() {}
}

describe("WebSocket URL security", () => {
  afterEach(() => {
    urls.length = 0;
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
  });

  it("keeps notification and LAN socket secrets out of query strings", () => {
    vi.stubGlobal("WebSocket", CapturedWebSocket);
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/nanjing-laptop" });
    window.history.replaceState(null, "", "/node/nanjing-laptop/");
    const client = new RealWebBotClient();
    (client as unknown as { token: string }).token = "session-secret";

    const notifications = client.subscribeNotifications(vi.fn());
    const closeLanSocket = client.openLanChatSocket(vi.fn());
    const socketUrls = urls.map((value) => new URL(value));

    expect(socketUrls.map((url) => url.pathname)).toEqual([
      "/node/nanjing-laptop/api/notifications/ws",
      "/node/nanjing-laptop/lan-chat/ws",
    ]);
    socketUrls.forEach((url) => {
      expect(url.searchParams.has("token")).toBe(false);
      expect(url.search).toBe("");
    });

    notifications.close();
    closeLanSocket();
  });
});
