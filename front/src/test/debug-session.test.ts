import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createDebugSession } from "../services/debugSession";
import { RealWebBotClient } from "../services/realWebBotClient";

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    headers: {
      get: () => "application/json",
    },
    clone() {
      return {
        text: async () => JSON.stringify({ ok: true, data }),
      };
    },
    json: async () => ({
      ok: true,
      data,
    }),
  };
}

const fetchMock = vi.fn();
const socketState = {
  instances: [] as MockSocket[],
};

class MockSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readonly url: string;
  readyState = MockSocket.CONNECTING;
  sent: string[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    socketState.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = MockSocket.CLOSED;
    this.onclose?.(new CloseEvent("close"));
  }

  open() {
    this.readyState = MockSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  message(payload: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
}

beforeEach(() => {
  fetchMock.mockReset();
  socketState.instances = [];
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("WebSocket", MockSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("real web bot client maps debug profile and state payloads", async () => {
  fetchMock
    .mockResolvedValueOnce(jsonResponse({
      config_name: "(gdb) Remote Debug",
      program: "H:/Resources/RTLinux/Demos/MB_DDF/build/aarch64/Debug/MB_DDF",
      cwd: "H:/Resources/RTLinux/Demos/MB_DDF",
      mi_debugger_path: "D:/Toolchain/aarch64-none-linux-gnu-gdb.exe",
      compile_commands: "H:/Resources/RTLinux/Demos/MB_DDF/.vscode/compile_commands.json",
      prepare_command: ".\\debug.bat",
      stop_at_entry: true,
      setup_commands: ["set sysroot H:/Resources/RTLinux/Demos/MB_DDF/build/aarch64/sysroot"],
      remote_host: "192.168.1.29",
      remote_user: "root",
      remote_dir: "/home/sast8/tmp",
      remote_port: 1234,
    }))
    .mockResolvedValueOnce(jsonResponse({
      phase: "paused",
      message: "命中断点",
      breakpoints: [{ source: "src/main.cpp", line: 42, verified: true }],
      frames: [{ id: "frame-0", name: "main", source: "H:/Resources/RTLinux/Demos/MB_DDF/src/main.cpp", line: 42 }],
      current_frame_id: "frame-0",
      scopes: [{ name: "Locals", variablesReference: "frame-0:locals" }],
      variables: {
        "frame-0:locals": [
          { name: "ctx", value: "{...}", type: "Context", variablesReference: "var-1" },
        ],
      },
    }));

  const client = new RealWebBotClient();
  const profile = await client.getDebugProfile("main");
  const state = await client.getDebugState("main");

  expect(profile?.configName).toBe("(gdb) Remote Debug");
  expect(profile?.prepareCommand).toBe(".\\debug.bat");
  expect(profile?.remoteHost).toBe("192.168.1.29");
  expect(profile?.remotePort).toBe(1234);
  expect(state.phase).toBe("paused");
  expect(state.currentFrameId).toBe("frame-0");
  expect(state.variables["frame-0:locals"]?.[0]?.variablesReference).toBe("var-1");
});

test("createDebugSession connects with token query and relays JSON events", async () => {
  const events: Array<{ type: string }> = [];
  const session = createDebugSession({
    token: "abc123",
    botAlias: "main",
    onEvent: (event) => {
      events.push({ type: event.type });
    },
  });

  const connectPromise = session.connect();
  const socket = socketState.instances[0];
  expect(socket.url).toBe(
    `${window.location.origin.replace(/^http/, "ws")}/debug/ws?token=abc123&alias=main`,
  );

  socket.open();
  await expect(connectPromise).resolves.toBe(true);

  expect(session.send({ type: "continue" })).toBe(true);
  expect(socket.sent).toEqual([JSON.stringify({ type: "continue" })]);

  socket.message({ type: "state", payload: { phase: "idle" } });
  expect(events).toEqual([{ type: "state" }]);

  session.dispose();
});
