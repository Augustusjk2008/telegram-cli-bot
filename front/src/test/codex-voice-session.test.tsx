import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { CodexVoiceBar } from "../components/CodexVoiceBar";
import { useCodexVoiceSession } from "../workbench/useCodexVoiceSession";
import type { CodexVoiceConnection, CodexVoiceMessage } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

function Harness({ client, enabled = true, busy = false }: { client: WebBotClient; enabled?: boolean; busy?: boolean }) {
  const voice = useCodexVoiceSession({ client, botAlias: "main", agentId: "main", scopeKey: "main", enabled, busy });
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
  iceGatheringState = "complete";
  connectionState = "new";
  localDescription: RTCSessionDescriptionInit | null = null;
  createOffer = vi.fn(async () => ({ type: "offer" as const, sdp: "v=0\r\n" }));
  setLocalDescription = vi.fn(async (description: RTCSessionDescriptionInit) => { this.localDescription = description; });
  setRemoteDescription = vi.fn(async () => undefined);
  addTrack = vi.fn();
  createDataChannel = vi.fn(() => ({ close: vi.fn(), onclose: null, onerror: null, onmessage: null }));
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
});
