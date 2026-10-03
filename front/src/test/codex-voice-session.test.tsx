import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { CodexVoiceBar } from "../components/CodexVoiceBar";
import { useCodexVoiceSession } from "../workbench/useCodexVoiceSession";
import type { CodexVoiceConnection, CodexVoiceMessage } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function Harness({ client, enabled = true, busy = false, scopeKey = "main" }: { client: WebBotClient; enabled?: boolean; busy?: boolean; scopeKey?: string }) {
  const voice = useCodexVoiceSession({ client, botAlias: "main", agentId: "main", scopeKey, enabled, busy });
  return (
    <>
      <CodexVoiceBar session={voice} busy={busy} />
      <output data-testid="voice-error">{voice.error}</output>
      <output data-testid="voice-caption">{voice.captions.map((caption) => caption.text).join("|")}</output>
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
  readonly channel = { close: vi.fn(), onclose: null, onerror: null, onmessage: null } as unknown as RTCDataChannel;
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

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("useCodexVoiceSession", () => {
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

  test("passes the current voice scope to the connection", async () => {
    const connection: CodexVoiceConnection = { ready: Promise.resolve(), send: vi.fn(), close: vi.fn() };
    const connect = vi.fn(() => connection);
    const { stream } = fakeMic();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
    vi.stubGlobal("RTCPeerConnection", FakePeer);
    render(<Harness client={{ connectCodexVoice: connect } as unknown as WebBotClient} scopeKey={JSON.stringify(["account", "cli", "conversation-1", 7])} />);
    fireEvent.click(screen.getByRole("button", { name: "开始语音" }));
    await waitFor(() => expect(connect).toHaveBeenCalled());
    expect(connect).toHaveBeenCalledWith("main", expect.objectContaining({
      agentId: "main",
      conversationId: "conversation-1",
      sessionEpoch: 7,
      protocolVersion: 1,
    }));
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

  test("keeps unknown results until a terminal event and does not auto recover playback", async () => {
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
    await act(async () => messages[0]({ type: "voice.error", outcome: "unknown", code: "unknown_result", message: "无法确认" }));
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
    expect(screen.getByRole("alert")).toHaveTextContent("unknown_result: 无法确认");
    expect(connection.close).not.toHaveBeenCalled();
    await act(async () => messages[0]({ type: "voice.state", seq: 1, state: "active" }));
    expect(screen.getByTestId("codex-voice-state")).toHaveTextContent("结果待确认");
    await act(async () => messages[0]({ type: "voice.state", seq: 2, state: "closed" }));
    expect(connection.close).toHaveBeenCalledTimes(1);
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
