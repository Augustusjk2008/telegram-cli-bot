import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { CodexVoiceBar } from "../components/CodexVoiceBar";
import { useCodexVoiceSession } from "../workbench/useCodexVoiceSession";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { CodexVoiceConnection, CodexVoiceMessage } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function Harness({ client, enabled = true, busy = false, scopeKey = "main" }: { client: WebBotClient; enabled?: boolean; busy?: boolean; scopeKey?: string }) {
  const voice = useCodexVoiceSession({ client, botAlias: "main", agentId: "main", scopeKey, enabled, busy });
  return (
    <>
      <CodexVoiceBar session={voice} busy={busy} />
      <output data-testid="voice-error">{voice.error}</output>
      <output data-testid="voice-caption">{voice.captions.map((caption) => `${caption.role}:${caption.text}`).join("|")}</output>
    </>
  );
}

function clientWithVoice(connection: CodexVoiceConnection) {
  return {
    connectCodexVoice: vi.fn(() => connection),
  } as unknown as WebBotClient;
}

class FakePeer {
  static last: FakePeer | undefined;
  iceGatheringState = "complete";
  connectionState = "new";
  localDescription: RTCSessionDescriptionInit | null = null;
  ontrack: ((event: RTCTrackEvent) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  createOffer = vi.fn(async () => ({ type: "offer" as const, sdp: "v=0\r\n" }));
  setLocalDescription = vi.fn(async (description: RTCSessionDescriptionInit) => { this.localDescription = description; });
  setRemoteDescription = vi.fn(async () => undefined);
  addTrack = vi.fn();
  readonly channel = { readyState: "connecting", close: vi.fn(), onopen: null, onclose: null, onerror: null, onmessage: null } as unknown as RTCDataChannel;
  constructor() { FakePeer.last = this; }
  createDataChannel = vi.fn(() => this.channel);
  getStats = vi.fn(async () => new Map());
  close = vi.fn(() => { this.connectionState = "closed"; });
}

function fakeMic() {
  const track = { enabled: true, stop: vi.fn(), onended: null } as unknown as MediaStreamTrack;
  return {
    track,
    stream: {
      getTracks: () => [track],
      getAudioTracks: () => [track],
    } as unknown as MediaStream,
  };
}

async function startVoiceHarness() {
  let onMessage!: (message: CodexVoiceMessage) => void;
  const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
  const client = clientWithVoice(connection);
  (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: typeof onMessage }) => {
    onMessage = options.onMessage;
    return connection;
  });
  const { stream } = fakeMic();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
  vi.stubGlobal("RTCPeerConnection", FakePeer);
  render(<StrictMode><Harness client={client} /></StrictMode>);
  fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
  await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
  const peer = FakePeer.last!;
  return { peer, connection, control: onMessage, media: (data: Record<string, unknown>) => {
    peer.channel.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  } };
}

beforeEach(() => {
  FakePeer.last = undefined;
  window.localStorage.clear();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
  window.history.replaceState(null, "", "/");
});

describe("useCodexVoiceSession", () => {
  test("renders V3 transcription immediately and keeps RTC turn IDs out of task bindings", async () => {
    const { media, control } = await startVoiceHarness();
    await act(async () => {
      control({ type: "voice.state", seq: 1, state: "active", codex_turn_id: "native-turn-1" });
      media({ type: "session.started", session: { status: "active" } });
      media({ type: "input_transcript.added", item: { id: "input-1", type: "input_transcript", text: "你" } });
    });
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:你");
    await act(async () => {
      media({ type: "turn.created", turn: { id: "rtc-user-1", role: "user", transcript: "你" } });
      media({ type: "turn.delta", turn_id: "rtc-user-1", delta: "好" });
      media({ type: "input_transcript.added", item: { id: "input-2", type: "input_transcript", text: "好" } });
      media({ type: "input_transcript.added", item: { id: "input-2", type: "input_transcript", text: "好" } });
    });
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:你好");
    await act(async () => {
      media({ type: "turn.done", turn: { id: "rtc-user-1", role: "user", transcript: "你好呀" } });
      media({ type: "output_transcript.added", item: { id: "output-1", type: "output_transcript", text: "你好" } });
      media({ type: "turn.created", turn: { id: "rtc-assistant-1", role: "assistant", transcript: "你好" } });
      media({ type: "turn.delta", turn_id: "rtc-assistant-1", delta: "！" });
      media({ type: "turn.done", turn: { id: "rtc-assistant-1", role: "assistant", transcript: "你好！" } });
    });
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:你好呀|assistant:你好！");
    expect(screen.getByTestId("codex-voice-details")).toHaveTextContent("Codex turn：native-turn-1");
    expect(screen.getByText("任务：空闲")).toBeInTheDocument();
  });

  test.each(["media", "control"])("uses the first transcript stream without duplicating repeated utterances (%s first)", async (first) => {
    const { media, control } = await startVoiceHarness();
    let seq = 0;
    for (let turn = 0; turn < 2; turn += 1) {
      const native = () => {
        control({ type: "voice.event", seq: ++seq, name: "thread/realtime/item/completed", data: {
          item: { id: `native-${turn}`, type: "transcriptSegment", role: "user", text: "你好" },
        } });
        control({ type: "voice.event", seq: ++seq, name: "thread/realtime/transcript/done", data: { role: "user", text: "你好" } });
      };
      const direct = () => {
        media({ type: "input_transcript.added", item: { id: `chunk-${turn}`, type: "input_transcript", text: "你好" } });
        media({ type: "turn.created", turn: { id: `rtc-${turn}`, role: "user", transcript: "你好" } });
        media({ type: "turn.done", turn: { id: `rtc-${turn}`, role: "user", transcript: "你好" } });
      };
      await act(async () => { if (first === "media") { direct(); native(); } else { native(); direct(); } });
      expect(screen.getByTestId("voice-caption").textContent).toBe(Array(turn + 1).fill("user:你好").join("|"));
    }
  });

  test("keeps a new pending caption bound when an earlier RTC turn completes again", async () => {
    const { media } = await startVoiceHarness();
    await act(async () => {
      media({ type: "turn.created", turn: { id: "first", role: "user", transcript: "first" } });
      media({ type: "turn.done", turn: { id: "first", role: "user", transcript: "first" } });
      media({ type: "input_transcript.added", item: { id: "second-chunk", text: "second" } });
      media({ type: "turn.done", turn: { id: "first", role: "user", transcript: "first" } });
      media({ type: "turn.created", turn: { id: "second", role: "user", transcript: "second" } });
      media({ type: "turn.done", turn: { id: "second", role: "user", transcript: "second" } });
    });
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:first|user:second");
  });

  test("removes a V3 partial caption when the explicit final transcript is empty", async () => {
    const { media } = await startVoiceHarness();
    await act(async () => media({ type: "turn.created", turn: { id: "withdrawn", role: "user", transcript: "partial" } }));
    expect(screen.getByTestId("voice-caption")).toHaveTextContent("partial");
    await act(async () => media({ type: "turn.done", turn: { id: "withdrawn", role: "user", transcript: "" } }));
    expect(screen.getByTestId("voice-caption")).toBeEmptyDOMElement();
  });

  test("waits for V3 media, data channel and session readiness before displaying connected", async () => {
    const { media, control, peer } = await startVoiceHarness();
    await act(async () => {
      control({ type: "voice.event", seq: 1, name: "thread/realtime/started", data: { version: "v3" } });
      control({ type: "voice.state", seq: 2, state: "active" });
    });
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("准备语音中");
    act(() => { peer.connectionState = "connected"; peer.onconnectionstatechange?.(); });
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("准备语音中");
    act(() => {
      Object.defineProperty(peer.channel, "readyState", { value: "open", configurable: true });
      peer.channel.onopen?.(new Event("open"));
    });
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("准备语音中");
    await act(async () => media({ type: "session.started", session: { status: "active" } }));
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("已连接");
  });

  test("resumes suppressed V3 audio only for a new assistant turn and keeps the audio tail playing", async () => {
    const { media, control, peer } = await startVoiceHarness();
    await act(async () => {
      control({ type: "voice.state", seq: 1, state: "active" });
      peer.ontrack?.({ track: { stop: vi.fn() }, streams: [{ getTracks: () => [] }] } as unknown as RTCTrackEvent);
      media({ type: "turn.created", turn: { id: "assistant-1", role: "assistant", transcript: "你好" } });
    });
    fireEvent.click(screen.getByRole("button", { name: "停止当前播报" }));
    const pauses = vi.mocked(HTMLMediaElement.prototype.pause).mock.calls.length;
    await act(async () => {
      media({ type: "turn.created", turn: { id: "assistant-1", role: "assistant", transcript: "你好" } });
      media({ type: "turn.created", turn: { id: "user-1", role: "user", transcript: "再说一次" } });
      media({ type: "turn.done", turn: { id: "assistant-1", role: "assistant", transcript: "你好" } });
    });
    expect(screen.getByText(/播放：本地暂停/)).toBeInTheDocument();
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(pauses);
    await act(async () => media({ type: "turn.created", turn: { id: "assistant-2", role: "assistant", transcript: "你好" } }));
    expect(screen.getByText(/播放：播放中/)).toBeInTheDocument();
  });

  test("reports microphone authorization failures and releases the session", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new Error("Permission denied")) },
    });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    const connect = vi.fn(() => ({ ready: Promise.resolve(), send: vi.fn(), close: vi.fn() }));
    render(<Harness client={{ connectCodexVoice: connect } as unknown as WebBotClient} />);
    // The failed authorization happens only after the user starts the session.
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(screen.getByTestId("voice-error")).toHaveTextContent("Permission denied"));
    expect(connect).not.toHaveBeenCalled();
  });

  test("remembers the selected physical microphone and uses it instead of the default input", async () => {
    const { stream, track } = fakeMic();
    Object.defineProperty(track, "label", { value: "麦克风 (Realtek(R) Audio)" });
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia,
        enumerateDevices: vi.fn().mockResolvedValue([
          { kind: "audioinput", deviceId: "steam", label: "Steam Streaming Microphone" },
          { kind: "audioinput", deviceId: "realtek", label: "麦克风 (Realtek(R) Audio)" },
          { kind: "audiooutput", deviceId: "speaker", label: "Realtek Speaker" },
        ]),
      },
    });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    const view = render(<Harness client={client} />);
    await screen.findByRole("option", { name: "麦克风 (Realtek(R) Audio)" });
    expect(screen.queryByRole("option", { name: "Realtek Speaker" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "麦克风设备" }), { target: { value: "realtek" } });
    view.unmount();
    render(<Harness client={client} />);
    await screen.findByRole("option", { name: "麦克风 (Realtek(R) Audio)" });
    expect(screen.getByRole("combobox", { name: "麦克风设备" })).toHaveValue("realtek");
    expect(getUserMedia).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: "realtek" } } });
    expect(FakePeer.last?.addTrack).toHaveBeenCalledWith(track, stream);
    expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("麦克风 (Realtek(R) Audio)");
    expect(screen.getByRole("combobox", { name: "麦克风设备" })).toBeDisabled();
  });

  test.each(["NotFoundError", "OverconstrainedError"])("requires a new selection when the chosen microphone is unavailable (%s)", async (errorName) => {
    const { stream } = fakeMic();
    const getUserMedia = vi.fn().mockRejectedValueOnce(new DOMException("Device unavailable", errorName)).mockResolvedValue(stream);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue([
        { kind: "audioinput", deviceId: "realtek", label: "Realtek Microphone" },
      ]) },
    });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    render(<Harness client={client} />);
    await screen.findByRole("option", { name: "Realtek Microphone" });
    fireEvent.change(screen.getByRole("combobox", { name: "麦克风设备" }), { target: { value: "realtek" } });
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("所选麦克风不可用"));
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(client.connectCodexVoice).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "麦克风设备" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    expect(getUserMedia).toHaveBeenLastCalledWith({ audio: true });
  });

  test("blocks voice start while a normal text task is active", () => {
    const connect = vi.fn();
    render(<Harness client={{ connectCodexVoice: connect } as unknown as WebBotClient} busy />);
    expect(screen.getByText("当前有活动任务，语音任务/混合输入将在 M2 支持")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始语音" })).toBeDisabled();
    expect(connect).not.toHaveBeenCalled();
  });

  test("deduplicates runtime events and keeps unknown task state visible", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = {
      ready: Promise.resolve(),
      send: vi.fn(),
      close: vi.fn(),
    };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    await act(async () => {
      messages[0]({ type: "voice.state", seq: 1, state: "active" });
      messages[0]({ type: "voice.event", seq: 2, event_id: "event-1", name: "response.audio_transcript.delta", item_id: "item-1", data: { delta: "hello", role: "assistant" } });
      messages[0]({ type: "voice.event", seq: 3, event_id: "event-1", name: "response.audio_transcript.delta", item_id: "item-1", data: { delta: "duplicate", role: "assistant" } });
      messages[0]({ type: "voice.event", seq: 4, name: "turn/completed", data: { status: "unknown" } });
    });
    expect(screen.getByTestId("voice-caption")).toHaveTextContent("hello");
    expect(screen.getByTestId("voice-caption")).not.toHaveTextContent("duplicate");
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("已连接");
  });

  test("coalesces item and flat transcript events while keeping consecutive repeats", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));

    const emitSegment = (seq: number, itemId: string) => {
      messages[0]({ type: "voice.event", seq, name: "thread/realtime/item/started", item_id: itemId,
        data: { item: { id: itemId, type: "transcriptSegment", role: "user", text: "" } } });
      messages[0]({ type: "voice.event", seq: seq + 1, name: "thread/realtime/item/transcript/delta", item_id: itemId,
        data: { itemId, delta: "你好" } });
      messages[0]({ type: "voice.event", seq: seq + 2, name: "thread/realtime/transcript/delta",
        data: { role: "user", delta: "你好" } });
      messages[0]({ type: "voice.event", seq: seq + 3, name: "thread/realtime/item/completed", item_id: itemId,
        data: { item: { id: itemId, type: "transcriptSegment", role: "user", text: "你好" } } });
      messages[0]({ type: "voice.event", seq: seq + 4, name: "thread/realtime/transcript/done",
        data: { role: "user", text: "你好" } });
    };
    await act(async () => {
      emitSegment(1, "item-1");
      emitSegment(6, "item-2");
    });

    expect(screen.getByTestId("voice-caption")).toHaveTextContent("user:你好|user:你好");
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:你好|user:你好");
  });

  test.each([false, true])("keeps flat transcript text when item text is delayed or absent (delayed: %s)", async (delayedItemText) => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<StrictMode><Harness client={client} /></StrictMode>);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalled());
    let seq = 0;
    const emit = (name: string, data: Record<string, unknown>) => messages[0]({ type: "voice.event", seq: ++seq, name, data });
    for (const role of ["user", "assistant"]) {
      await act(async () => {
        emit("thread/realtime/item/started", { item: { id: role, type: "transcriptSegment", role, text: "" } });
        emit("thread/realtime/transcript/delta", { role, delta: "你好" });
      });
      expect(screen.getByTestId("voice-caption")).toHaveTextContent(`${role}:你好`);
      await act(async () => {
        if (delayedItemText) emit("thread/realtime/item/transcript/delta", { itemId: role, delta: "你好" });
        emit("thread/realtime/transcript/delta", { role, delta: "世界" });
      });
      expect(screen.getByTestId("voice-caption")).toHaveTextContent(`${role}:你好世界`);
      await act(async () => {
        if (delayedItemText) emit("thread/realtime/item/transcript/delta", { itemId: role, delta: "世界" });
        emit("thread/realtime/item/completed", { item: { id: role, type: "transcriptSegment", role } });
        emit("thread/realtime/transcript/done", { role });
      });
    }
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:你好世界|assistant:你好世界");
  });

  test("preserves a corrected final transcript when later flat events omit the full text", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalled());
    const item = { id: "item-1", type: "transcriptSegment", role: "user" };
    await act(async () => {
      messages[0]({ type: "voice.event", seq: 1, name: "thread/realtime/item/started", data: { item: { ...item, text: "" } } });
      messages[0]({ type: "voice.event", seq: 2, name: "thread/realtime/transcript/delta", data: { role: "user", delta: "hello world" } });
      messages[0]({ type: "voice.event", seq: 3, name: "thread/realtime/item/completed", data: { item: { ...item, text: "hello" } } });
    });
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:hello");
    await act(async () => {
      messages[0]({ type: "voice.event", seq: 4, name: "thread/realtime/transcript/delta", data: { role: "user", delta: "!" } });
      messages[0]({ type: "voice.event", seq: 5, name: "thread/realtime/transcript/done", data: { role: "user" } });
    });
    expect(screen.getByTestId("voice-caption").textContent).toBe("user:hello");
  });

  test("reports microphone input and outgoing audio separately from received packets", async () => {
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const { stream, track } = fakeMic();
    Object.defineProperty(track, "label", { value: "Test microphone" });
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    vi.useFakeTimers();
    try {
      render(<Harness client={clientWithVoice(connection)} />);
      await act(async () => fireEvent.click(screen.getByRole("button", { name: "开始语音" })));
      expect(connection.send).toHaveBeenCalled();
      const peer = FakePeer.last!;
      peer.getStats.mockResolvedValue(new Map([
        ["incoming", { type: "inbound-rtp", kind: "audio", packetsReceived: 487, bytesReceived: 1461 }],
        ["outgoing", { type: "outbound-rtp", kind: "audio", packetsSent: 400, bytesSent: 1200 }],
        ["microphone", { type: "media-source", kind: "audio", audioLevel: 0, totalAudioEnergy: 0 }],
      ]));
      await act(async () => { vi.advanceTimersByTime(5000); });
      expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("Test microphone");
      expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("未检测到声音");
      expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("发送 400 包 / 1200 字节");
      peer.getStats.mockResolvedValue(new Map([
        ["outgoing", { type: "outbound-rtp", kind: "audio", packetsSent: 450, bytesSent: 9500 }],
        ["microphone", { type: "media-source", kind: "audio", audioLevel: 0.2, totalAudioEnergy: 0.1 }],
      ]));
      await act(async () => { vi.advanceTimersByTime(5000); });
      expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("已检测到声音");
      expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("20%");
      expect(screen.getByTestId("codex-voice-input")).toHaveTextContent("发送 450 包 / 9500 字节");
    } finally {
      vi.useRealTimers();
    }
  });

  test("does not show an unbound turn as a voice task", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));

    await act(async () => messages[0]({
      type: "voice.event", seq: 1, name: "turn/started", data: { turn: { id: "text-turn" } },
    }));
    expect(screen.getByText("任务：空闲")).toBeInTheDocument();
  });

  test("binds voice tasks, shows transcript persistence, and preserves unknown", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));

    await act(async () => {
      messages[0]({
        type: "voice.task",
        seq: 1,
        tcb_turn_id: "tcb-turn-1",
        assistant_message_id: "assistant-1",
        codex_turn_id: "codex-turn-1",
        conversation_id: "conversation-1",
        state: "active",
        transcript_state: "syncing",
      });
      messages[0]({
        type: "voice.event",
        seq: 3,
        name: "response.audio_transcript.delta",
        item_id: "assistant-item-1",
        data: { delta: "实时回答", role: "assistant" },
      });
    });
    expect(screen.getByText("任务：运行中")).toBeInTheDocument();
    expect(screen.getByText("字幕同步中")).toBeInTheDocument();

    await act(async () => {
      messages[0]({
        type: "voice.task",
        seq: 4,
        tcb_turn_id: "tcb-turn-1",
        assistant_message_id: "assistant-1",
        codex_turn_id: "codex-turn-1",
        conversation_id: "conversation-1",
        state: "unknown",
        transcript_state: {
          user: { persisted: true },
          assistant: { persisted: true },
          user_final: true,
          assistant_final: true,
        },
      });
      messages[0]({ type: "voice.event", seq: 5, name: "turn/completed", data: { status: "completed" } });
    });
    expect(screen.getByText("任务：结果待确认")).toBeInTheDocument();
    expect(screen.getByText("字幕已保存")).toBeInTheDocument();
  });

  test("accepts a new voice task after a terminal task and ignores an old task event", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));

    await act(async () => {
      messages[0]({ type: "voice.task", seq: 1, tcb_turn_id: "tcb-1", codex_turn_id: "codex-1", state: "active", transcript_state: "syncing" });
      messages[0]({ type: "voice.task", seq: 2, tcb_turn_id: "tcb-1", codex_turn_id: "codex-1", state: "completed", transcript_state: "syncing" });
      messages[0]({ type: "voice.task", seq: 3, tcb_turn_id: "tcb-2", codex_turn_id: "codex-2", state: "active", transcript_state: "syncing" });
      messages[0]({ type: "voice.task", seq: 4, tcb_turn_id: "tcb-1", codex_turn_id: "codex-1", state: "failed", transcript_state: "syncing" });
    });

    expect(screen.getByText("任务：运行中")).toBeInTheDocument();
  });

  test("keeps the voice session open when its own task makes the chat busy", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = {
      ready: Promise.resolve(),
      send: vi.fn(),
      close: vi.fn(),
    };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    const view = render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));

    await act(async () => {
      messages[0]({ type: "voice.state", seq: 1, state: "active" });
      messages[0]({
        type: "voice.task",
        seq: 2,
        tcb_turn_id: "tcb-turn-1",
        state: "active",
        transcript_state: "syncing",
      });
    });
    view.rerender(<Harness client={client} busy />);

    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("已连接");
    expect(screen.getByText("任务：运行中")).toBeInTheDocument();
    expect(screen.queryByText("当前有活动任务，语音任务/混合输入将在 M2 支持")).not.toBeInTheDocument();
    expect(connection.send).not.toHaveBeenLastCalledWith({ op: "stop_voice" });
    expect(connection.close).not.toHaveBeenCalled();

    await act(async () => messages[0]({
      type: "voice.task", seq: 3, tcb_turn_id: "tcb-turn-1", state: "completed", transcript_state: "syncing",
    }));
    view.rerender(<Harness client={client} busy />);
    expect(screen.queryByText("当前有活动任务，语音任务/混合输入将在 M2 支持")).not.toBeInTheDocument();
  });

  test.each(["", "/tcb-hub/node/lenovo-y7000p-laptop"])("starts a fresh voice connection at %s and receives server recovery credentials", async (basePath) => {
    class FakeWebSocket extends EventTarget {
      static OPEN = 1;
      static last: FakeWebSocket | undefined;
      readyState = 0;
      send = vi.fn();
      close = vi.fn(() => { this.readyState = 3; });
      constructor(readonly url: string) {
        super();
        FakeWebSocket.last = this;
      }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);
    window.history.replaceState(null, "", `${basePath}/`);
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: basePath });
    const client = new RealWebBotClient();
    vi.spyOn(client, "getBotOverview").mockResolvedValue({
      activeConversationId: "conversation-1", sessionEpoch: 0,
    } as Awaited<ReturnType<WebBotClient["getBotOverview"]>>);
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} scopeKey={JSON.stringify(["account", "cli", "conversation-1", 0])} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(FakeWebSocket.last).toBeDefined());
    const socket = FakeWebSocket.last!;
    const url = new URL(socket.url);
    expect(url.pathname).toBe(`${basePath}/api/bots/main/chat/voice`);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      agent_id: "main", execution_mode: "cli", protocol_version: "1",
      conversation_id: "conversation-1", session_epoch: "0",
    });
    expect(screen.getByText(/恢复令牌：未生成/)).toBeInTheDocument();

    await act(async () => {
      socket.readyState = FakeWebSocket.OPEN;
      socket.dispatchEvent(new Event("open"));
      socket.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
        type: "voice.state", seq: 1, state: "negotiating",
        recovery_token: "server-recovery-1", client_generation: "generation-1",
      }) }));
    });
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({ op: "start", sdp: "v=0\r\n" });
    await act(async () => socket.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
      type: "voice.sdp", seq: 2, sdp: "v=0 answer",
    }) })));
    expect(FakePeer.last?.setRemoteDescription).toHaveBeenCalledWith({ type: "answer", sdp: "v=0 answer" });
    await act(async () => socket.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({
      type: "voice.state", seq: 3, state: "active",
    }) })));
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("已连接");
    expect(screen.getByText(/clientGeneration：generation-1/)).toBeInTheDocument();
    expect(screen.getByText(/恢复令牌：已保存/)).toBeInTheDocument();
  });

  test("recovers an unexpected control disconnect without repeating start", async () => {
    const connections: CodexVoiceConnection[] = [];
    const optionsList: Array<{
      onMessage: (message: CodexVoiceMessage) => void;
      onClose: () => void;
      recoveryToken?: string;
      clientGeneration?: string;
      threadId?: string;
      codexTurnId?: string;
      tcbTurnId?: string;
      conversationId?: string;
      sessionEpoch?: number;
    }> = [];
    const connect = vi.fn((_alias: string, options: typeof optionsList[number]) => {
      optionsList.push(options);
      const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
      connections.push(connection);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={{ connectCodexVoice: connect } as unknown as WebBotClient} scopeKey={JSON.stringify(["account", "cli", "conversation-1", 7])} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connections[0]?.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));

    await act(async () => optionsList[0].onMessage({
      type: "voice.state",
      seq: 1,
      state: "active",
      recovery_token: "server-recovery-1",
      client_generation: "generation-1",
      thread_id: "thread-1",
      codex_turn_id: "codex-turn-1",
      tcb_turn_id: "tcb-turn-1",
    }));

    vi.useFakeTimers();
    try {
      act(() => optionsList[0].onClose());
      expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("连接中断");

      await act(async () => {
        vi.advanceTimersByTime(250);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(connect).toHaveBeenCalledTimes(2);
      expect(optionsList[1]).toMatchObject({
        agentId: "main",
        conversationId: "conversation-1",
        sessionEpoch: 7,
        recoveryToken: "server-recovery-1",
        clientGeneration: "generation-1",
        threadId: "thread-1",
        codexTurnId: "codex-turn-1",
        tcbTurnId: "tcb-turn-1",
      });
      expect(connections[1].send).toHaveBeenCalledWith({ op: "summary" });
      expect(connections[1].send).not.toHaveBeenCalledWith(expect.objectContaining({ op: "start" }));
      expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("已继续当前会话");
    } finally {
      vi.useRealTimers();
    }
  });

  test("shows occupied errors without retrying or taking over", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    const connect = client.connectCodexVoice as ReturnType<typeof vi.fn>;
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    await act(async () => messages[0]({ type: "voice.error", code: "voice_connection_occupied", message: "已有连接" }));
    expect(screen.getByRole("alert")).toHaveTextContent("当前会话已在其他标签页使用语音");
    expect(screen.getByRole("button", { name: "开始语音" })).toBeEnabled();
    expect(connect).toHaveBeenCalledTimes(1);
    expect(connection.close).toHaveBeenCalledTimes(1);
  });

  test("releases resources immediately for an unknown result and ignores late events", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    let onClose: (() => void) | undefined;
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void; onClose: () => void }) => {
      messages.push(options.onMessage);
      onClose = options.onClose;
      return connection;
    });
    const { stream, track } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    const peer = FakePeer.last!;
    const remoteTrack = { stop: vi.fn() } as unknown as MediaStreamTrack;
    act(() => peer.ontrack?.({ track: remoteTrack, streams: [{ getTracks: () => [remoteTrack] }] } as unknown as RTCTrackEvent));
    await act(async () => messages[0]({ type: "voice.error", outcome: "unknown", code: "unknown_result", message: "无法确认" }));
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
    expect(screen.getByRole("alert")).toHaveTextContent("unknown_result: 无法确认");
    expect(screen.getByRole("button", { name: "开始语音" })).toBeEnabled();
    expect(screen.queryByText(/麦克风：/)).not.toBeInTheDocument();
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(remoteTrack.stop).toHaveBeenCalledTimes(1);
    expect(peer.channel.close).toHaveBeenCalledTimes(1);
    expect(peer.close).toHaveBeenCalledTimes(1);
    expect(connection.close).toHaveBeenCalledTimes(1);
    expect(connection.send).toHaveBeenCalledTimes(1);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    await act(async () => {
      messages[0]({ type: "voice.state", seq: 1, state: "closed" });
      messages[0]({ type: "voice.error", code: "late_error", message: "晚到错误" });
      onClose?.();
    });
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
    expect(connection.close).toHaveBeenCalledTimes(1);
    expect(peer.close).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("unknown_result: 无法确认");
  });

  test("releases resources when voice state becomes unknown", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream, track } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    await act(async () => messages[0]({ type: "voice.state", seq: 1, state: "unknown", message: "无法确认" }));
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
    expect(screen.queryByText(/麦克风：/)).not.toBeInTheDocument();
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(FakePeer.last!.channel.close).toHaveBeenCalledTimes(1);
    expect(FakePeer.last!.close).toHaveBeenCalledTimes(1);
    expect(connection.close).toHaveBeenCalledTimes(1);
    expect(connection.send).toHaveBeenCalledTimes(1);
  });

  test("waits through transient peer disconnection before failing", async () => {
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    vi.useFakeTimers();
    try {
      await act(async () => messages[0]({ type: "voice.state", seq: 1, state: "active" }));
      const peer = FakePeer.last!;
      act(() => { peer.connectionState = "disconnected"; peer.onconnectionstatechange?.(); });
      expect(connection.close).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(5000); });
      expect(connection.close).not.toHaveBeenCalled();
      act(() => { peer.connectionState = "connected"; peer.onconnectionstatechange?.(); });
      act(() => { vi.advanceTimersByTime(10000); });
      expect(connection.close).not.toHaveBeenCalled();
      act(() => { peer.connectionState = "failed"; peer.onconnectionstatechange?.(); });
      expect(connection.close).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
    } finally {
      vi.useRealTimers();
    }
  });

  test("releases the connection when explicit stop times out", async () => {
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    const { stream, track } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByRole("button", { name: "结束语音" }));
      expect(connection.send).toHaveBeenCalledTimes(2);
      expect(connection.send).toHaveBeenLastCalledWith({ op: "stop_voice" });
      expect(track.stop).toHaveBeenCalledTimes(1);
      expect(FakePeer.last!.channel.close).toHaveBeenCalledTimes(1);
      expect(FakePeer.last!.close).toHaveBeenCalledTimes(1);
      expect(connection.close).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(10000); });
      expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
      expect(screen.getByRole("alert")).toHaveTextContent("结束语音结果待确认，设备已释放");
      expect(screen.getByRole("button", { name: "开始语音" })).toBeEnabled();
      expect(connection.close).toHaveBeenCalledTimes(1);
      expect(connection.send).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  test("stops only local playback until an explicit resume or a new response", async () => {
    const messages: Array<(message: CodexVoiceMessage) => void> = [];
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    (client.connectCodexVoice as ReturnType<typeof vi.fn>).mockImplementation((_alias: string, options: { onMessage: (message: CodexVoiceMessage) => void }) => {
      messages.push(options.onMessage);
      return connection;
    });
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    await act(async () => messages[0]({ type: "voice.state", seq: 1, state: "active" }));
    act(() => FakePeer.last!.ontrack?.({ track: { stop: vi.fn() }, streams: [{ getTracks: () => [] }] } as unknown as RTCTrackEvent));
    await waitFor(() => expect(screen.getByText(/播放：播放中/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "停止当前播报" }));
    expect(screen.getByText(/播放：本地暂停/)).toBeInTheDocument();
    expect(connection.send).toHaveBeenCalledTimes(1);
    act(() => FakePeer.last!.channel.onmessage?.({ data: JSON.stringify({ type: "output_audio_buffer.started" }) } as MessageEvent));
    expect(screen.getByText(/播放：本地暂停/)).toBeInTheDocument();
    act(() => FakePeer.last!.channel.onmessage?.({ data: JSON.stringify({ type: "response.created" }) } as MessageEvent));
    await waitFor(() => expect(screen.getByText(/播放：播放中/)).toBeInTheDocument());
    await act(async () => messages[0]({ type: "voice.event", seq: 2, name: "output_audio_buffer.stopped", data: {} }));
    expect(screen.getByText(/播放：等待音频/)).toBeInTheDocument();
  });

  test("releases the old connection when the chat scope changes", async () => {
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const client = clientWithVoice(connection);
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    const view = render(<Harness client={client} scopeKey="scope-1" />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connection.send).toHaveBeenCalledWith(expect.objectContaining({ op: "start" })));
    view.rerender(<Harness client={client} scopeKey="scope-2" />);
    expect(connection.close).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("未连接");
  });
});
