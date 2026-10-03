import { useCallback, useEffect, useRef, useState } from "react";
import type { CodexVoiceConnection, CodexVoiceMessage, CodexVoiceState } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

export const VOICE_BUSY_REASON = "当前有活动任务，语音任务/混合输入将在 M2 支持";

type Caption = { id: string; role: string; text: string; done: boolean };
type VoiceView = {
  state: CodexVoiceState;
  mic: "off" | "requesting" | "on" | "muted";
  peer: RTCPeerConnectionState;
  playback: "idle" | "playing" | "blocked" | "suppressed";
  activity: string;
  task: "idle" | "running" | "completed" | "failed" | "interrupted" | "unknown";
  receivedBytes: number;
  receivedPackets: number;
  captions: Caption[];
  error: string;
};
const initialView: VoiceView = {
  state: "idle", mic: "off", peer: "new", playback: "idle", activity: "等待连接", task: "idle",
  receivedBytes: 0, receivedPackets: 0, captions: [], error: "",
};
type Session = {
  connection?: CodexVoiceConnection;
  peer?: RTCPeerConnection;
  audio?: HTMLAudioElement;
  channel?: RTCDataChannel;
  mic?: MediaStream;
  tracks: Set<MediaStreamTrack>;
  abort: AbortController;
  seen: Set<string>;
  seq: number;
  started: boolean;
  stopping: boolean;
  applyingSdp: boolean;
  suppressed: boolean;
  statsTimer?: number;
  deadline?: number;
};

function releaseMedia(session: Session) {
  session.abort.abort();
  window.clearInterval(session.statsTimer);
  window.clearTimeout(session.deadline);
  session.mic?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
  session.tracks.forEach((track) => track.stop());
  if (session.channel) {
    session.channel.onmessage = null;
    session.channel.onclose = null;
    session.channel.onerror = null;
    session.channel.close();
  }
  if (session.peer) {
    session.peer.ontrack = null;
    session.peer.onconnectionstatechange = null;
    session.peer.close();
  }
  if (session.audio) {
    session.audio.pause();
    session.audio.srcObject = null;
    session.audio.removeAttribute("src");
  }
}

function gatherIce(peer: RTCPeerConnection, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(new Error("语音连接已取消"));
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const finish = (error?: Error) => {
      window.clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", check);
      signal.removeEventListener("abort", cancel);
      if (error) reject(error); else resolve();
    };
    const check = () => { if (peer.iceGatheringState === "complete") finish(); };
    const cancel = () => finish(new Error("语音连接已取消"));
    const timer = window.setTimeout(() => finish(new Error("ICE 收集超时，请重新开始语音")), 15000);
    peer.addEventListener("icegatheringstatechange", check);
    signal.addEventListener("abort", cancel, { once: true });
    check();
  });
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function updateCaptions(captions: Caption[], name: string, data: Record<string, unknown>, itemId?: string): Caption[] {
  const item = record(data.item);
  const native = /^thread\/realtime\/(?:transcript\/(?:delta|done)|item\/(?:started|completed|transcript\/delta)|itemStarted|itemCompleted|itemTranscriptDelta)$/.test(name);
  const standard = /^(?:conversation\.item\.input_audio_transcription\.(?:delta|completed)|response\.(?:audio_transcript|output_audio_transcript|output_text)\.(?:delta|done))$/.test(name);
  if ((!native && !standard) || (item.type && item.type !== "transcriptSegment")) return captions;
  const role = String(item.role || data.role || (name.startsWith("conversation.") ? "user" : standard ? "assistant" : "unknown"));
  const stableId = item.id || data.itemId || data.item_id || itemId || data.response_id;
  const previous = stableId
    ? captions.find((caption) => caption.id === String(stableId))
    : [...captions].reverse().find((caption) => caption.role === role && !caption.done);
  const fullText = item.text ?? data.text ?? data.transcript;
  const text = typeof fullText === "string" ? fullText
    : (previous?.text || "") + (!previous?.done && typeof data.delta === "string" ? data.delta : "");
  if (!text) return captions;
  const caption: Caption = {
    id: previous?.id || String(stableId || crypto.randomUUID()),
    role: role === "unknown" ? previous?.role || role : role,
    text: text.slice(-4000),
    done: Boolean(previous?.done || /(?:done|completed|itemCompleted)$/.test(name)),
  };
  return (previous ? captions.map((row) => row.id === caption.id ? caption : row) : [...captions, caption]).slice(-30);
}

export function useCodexVoiceSession({ client, botAlias, agentId, scopeKey, enabled, busy = false }: {
  client: WebBotClient;
  botAlias: string;
  agentId: string;
  scopeKey: string;
  enabled: boolean;
  busy?: boolean;
}) {
  const [view, setView] = useState<VoiceView>(initialView);
  const current = useRef<Session | null>(null);
  const scopeInitialized = useRef(false);

  const dispose = useCallback(() => {
    const session = current.current;
    current.current = null;
    if (!session) return;
    if (session.started && !session.stopping) {
      try { session.connection?.send({ op: "stop_voice" }); } catch { /* Disconnect also releases the server lease. */ }
    }
    releaseMedia(session);
    session.connection?.close();
  }, []);

  useEffect(() => {
    if (scopeInitialized.current) setView(initialView);
    scopeInitialized.current = true;
    const leave = () => { dispose(); setView(initialView); };
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); dispose(); };
  }, [client, botAlias, agentId, scopeKey, enabled, dispose]);

  const finish = useCallback((session: Session, state: CodexVoiceState, error = "") => {
    if (current.current !== session) return;
    dispose();
    setView((value) => ({ ...value, state, mic: "off", peer: "closed", playback: "idle", error,
      activity: state === "closed" ? "语音已结束" : "设备已释放",
      task: state === "unknown" && value.task === "running" ? "unknown" : value.task,
    }));
  }, [dispose]);

  const play = useCallback(async (session: Session) => {
    if (!session.audio || session.stopping) return;
    try {
      await session.audio.play();
      if (current.current === session && !session.stopping) setView((value) => ({ ...value, playback: session.suppressed ? "suppressed" : "playing" }));
    } catch {
      if (current.current === session && !session.stopping) setView((value) => ({ ...value, playback: "blocked" }));
    }
  }, []);

  const start = useCallback(async () => {
    if (!enabled || current.current) return;
    if (busy) { setView((value) => ({ ...value, error: VOICE_BUSY_REASON })); return; }
    const session: Session = {
      abort: new AbortController(), tracks: new Set(), seen: new Set(), seq: -1,
      started: false, stopping: false, applyingSdp: false, suppressed: false,
    };
    current.current = session;
    const live = () => current.current === session && !session.stopping;
    const fail = (message: string) => finish(session, session.started ? "unknown" : "error", message);
    setView({ ...initialView, state: "negotiating", mic: "requesting", activity: "等待麦克风授权" });
    const runtimeEvent = (name: string, raw: Record<string, unknown>, eventId?: string, itemId?: string) => {
      if (!live()) return;
      const outer = record(raw.params || raw);
      const nested = record(outer.event);
      const data = typeof nested.type === "string" ? nested : outer;
      if (typeof nested.type === "string") name = nested.type;
      const id = typeof data.event_id === "string" ? data.event_id : eventId;
      if (id && session.seen.has(id)) return;
      if (id) {
        session.seen.add(id);
        if (session.seen.size > 500) session.seen.delete(session.seen.values().next().value!);
      }
      if (name === "thread/realtime/error") { fail(String(data.message || "语音运行时错误")); return; }
      if (name === "runtime/error" || name === "runtime/closed") { fail("语音运行时连接中断，结果待确认"); return; }
      if (name === "thread/realtime/closed") { session.stopping = true; finish(session, "closed"); return; }
      setView((value) => {
        let task = value.task;
        if (name === "turn/started") task = "running";
        if (name === "turn/completed") {
          const status = record(data.turn).status || data.status;
          task = status === "completed" || status === "failed" || status === "interrupted" ? status : "unknown";
        }
        const activity = name === "input_audio_buffer.speech_started" ? "正在聆听"
          : name === "output_audio_buffer.started" ? "正在播报"
          : name === "output_audio_buffer.stopped" || name === "thread/realtime/started" ? "等待语音" : value.activity;
        return { ...value, task, activity, captions: updateCaptions(value.captions, name, data, itemId) };
      });
    };
    const onMessage = (message: CodexVoiceMessage) => {
      if (current.current !== session) return;
      if (typeof message.seq === "number") {
        if (message.seq <= session.seq) return;
        session.seq = message.seq;
      }
      if (message.type === "voice.state") {
        if (["closed", "error", "unknown"].includes(message.state)) {
          session.stopping = true;
          finish(session, message.state);
        } else if (!session.stopping && message.state !== "idle") setView((value) => ({ ...value, state: message.state }));
      } else if (message.type === "voice.sdp" && live() && session.peer && !session.applyingSdp) {
        session.applyingSdp = true;
        void session.peer.setRemoteDescription({ type: "answer", sdp: message.sdp }).then(() => {
          if (live()) window.clearTimeout(session.deadline);
        }).catch(() => fail("远端 SDP 协商失败，设备已释放"));
      } else if (message.type === "voice.event") {
        runtimeEvent(message.name, record(message.data), message.event_id, message.item_id);
      } else if (message.type === "error" || message.type === "voice.error") {
        finish(session, message.state === "unknown" || message.outcome === "unknown" ? "unknown" : "error",
          message.message || message.error?.message || message.code || "语音连接失败");
      }
    };
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") throw new Error("当前浏览器不支持语音，请使用安全连接并允许麦克风访问");
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!live()) { mic.getTracks().forEach((track) => track.stop()); return; }
      session.mic = mic;
      session.audio = new Audio();
      session.audio.autoplay = true;
      const peer = session.peer = new RTCPeerConnection({ iceServers: [] });
      mic.getTracks().forEach((track) => {
        peer.addTrack(track, mic);
        track.onended = () => fail("麦克风已停止，设备已释放");
      });
      setView((value) => ({ ...value, mic: "on", activity: "正在协商" }));
      peer.ontrack = ({ track, streams }) => {
        if (!live()) { track.stop(); return; }
        session.tracks.add(track);
        const stream = streams[0] || new MediaStream([track]);
        stream.getTracks().forEach((remoteTrack) => session.tracks.add(remoteTrack));
        session.audio!.srcObject = stream;
        void play(session);
      };
      peer.onconnectionstatechange = () => {
        if (!live()) return;
        setView((value) => ({ ...value, peer: peer.connectionState }));
        if (["failed", "disconnected", "closed"].includes(peer.connectionState)) fail("媒体连接中断，语音结果待确认");
      };
      const channel = session.channel = peer.createDataChannel("oai-events");
      channel.onclose = () => fail("语音事件通道已关闭");
      channel.onerror = () => fail("语音事件通道错误");
      channel.onmessage = ({ data: raw }) => {
        if (!live()) return;
        let data: Record<string, unknown>;
        try { data = record(JSON.parse(raw)); } catch { return; }
        const name = typeof data.type === "string" ? data.type : "";
        runtimeEvent(name, data);
        if (session.suppressed && ["response.created", "output_audio_buffer.started"].includes(name)) {
          session.suppressed = false;
          session.audio!.muted = false;
          void play(session);
        }
      };
      const offer = await peer.createOffer();
      if (!live()) return;
      await peer.setLocalDescription(offer);
      if (!live()) return;
      await gatherIce(peer, session.abort.signal);
      if (!live()) return;
      if (!peer.localDescription?.sdp) throw new Error("未生成本地 SDP");
      session.connection = client.connectCodexVoice(botAlias, {
        agentId, onMessage, onClose: () => fail("语音控制连接中断，未自动重连"),
      });
      await session.connection.ready;
      if (!live()) return;
      session.connection.send({ op: "start", sdp: peer.localDescription.sdp });
      session.started = true;
      session.deadline = window.setTimeout(() => fail("等待远端 SDP 超时，语音结果待确认"), 70000);
      session.statsTimer = window.setInterval(() => {
        void peer.getStats().then((reports) => {
          if (!live()) return;
          let receivedBytes = 0, receivedPackets = 0;
          reports.forEach((report) => {
            if (report.type === "inbound-rtp" && (report.kind === "audio" || report.mediaType === "audio")) {
              receivedBytes += Number(report.bytesReceived) || 0;
              receivedPackets += Number(report.packetsReceived) || 0;
            }
          });
          setView((value) => ({ ...value, receivedBytes, receivedPackets }));
        }).catch(() => { /* Statistics are diagnostic; media may still be live. */ });
      }, 5000);
    } catch (error) {
      if (live()) fail(error instanceof Error ? error.message : "语音启动失败");
    }
  }, [enabled, busy, client, botAlias, agentId, finish, play]);

  const end = useCallback(() => {
    const session = current.current;
    if (!session || session.stopping) return;
    session.stopping = true;
    releaseMedia(session);
    if (!session.started) { finish(session, "closed"); return; }
    setView((value) => ({ ...value, state: "stopping", mic: "off", peer: "closed", playback: "idle" }));
    try {
      session.connection?.send({ op: "stop_voice" });
      session.deadline = window.setTimeout(() => finish(session, "unknown", "结束语音结果待确认，设备已释放"), 10000);
    } catch { finish(session, "unknown", "结束语音结果待确认，设备已释放"); }
  }, [finish]);

  useEffect(() => { if (busy) end(); }, [busy, end]);

  const toggleMute = useCallback(() => {
    const session = current.current;
    if (!session?.mic || session.stopping) return;
    const enabled = !session.mic.getAudioTracks().some((track) => track.enabled);
    session.mic.getAudioTracks().forEach((track) => { track.enabled = enabled; });
    setView((value) => ({ ...value, mic: enabled ? "on" : "muted" }));
  }, []);
  const stopPlayback = useCallback(() => {
    const session = current.current;
    if (!session?.audio || session.stopping) return;
    session.suppressed = true;
    session.audio.muted = true;
    setView((value) => ({ ...value, playback: "suppressed" }));
  }, []);
  const resumePlayback = useCallback(() => {
    const session = current.current;
    if (!session?.audio || session.stopping) return;
    session.suppressed = false;
    session.audio.muted = false;
    void play(session);
  }, [play]);

  return { ...view, start, end, toggleMute, stopPlayback, resumePlayback,
    connected: ["negotiating", "active", "stopping"].includes(view.state),
  };
}

export type CodexVoiceSession = ReturnType<typeof useCodexVoiceSession>;
