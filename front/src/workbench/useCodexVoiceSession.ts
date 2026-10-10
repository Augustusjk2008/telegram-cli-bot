import { useCallback, useEffect, useRef, useState } from "react";
import type {
  CodexVoiceConnection,
  CodexVoiceMessage,
  CodexVoiceState,
  VoiceTaskBinding,
} from "../services/types";
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
  taskBinding: VoiceTaskBinding | null;
  receivedBytes: number;
  receivedPackets: number;
  captions: Caption[];
  error: string;
};
const initialView: VoiceView = {
  state: "idle", mic: "off", peer: "new", playback: "idle", activity: "等待连接", task: "idle",
  taskBinding: null, receivedBytes: 0, receivedPackets: 0, captions: [], error: "",
};

function taskLabelState(binding: VoiceTaskBinding | null): VoiceView["task"] {
  if (!binding) return "idle";
  return binding.state === "active" ? "running" : binding.state;
}

function initialViewForTask(binding?: VoiceTaskBinding | null): VoiceView {
  if (!binding) return initialView;
  return {
    ...initialView,
    task: taskLabelState(binding),
    taskBinding: binding,
    activity: binding.state === "active" ? "任务运行中" : "语音任务已同步",
  };
}

function isTerminalTaskState(state: VoiceTaskBinding["state"]) {
  return state !== "active";
}

function normalizeTranscriptState(value: unknown): {
  state: VoiceTaskBinding["transcriptState"];
  details?: Record<string, unknown>;
} {
  if (typeof value === "string") {
    return { state: value.trim().toLowerCase() === "saved" ? "saved" : "syncing" };
  }
  const details = value && typeof value === "object" ? value as Record<string, unknown> : undefined;
  const user = record(details?.user);
  const assistant = record(details?.assistant);
  const userPersisted = user.persisted === true || details?.user_persisted === true;
  const assistantPersisted = assistant.persisted === true || details?.assistant_persisted === true;
  return {
    state: userPersisted && assistantPersisted ? "saved" : "syncing",
    ...(details ? { details } : {}),
  };
}
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
  released: boolean;
  playbackGeneration: number;
  responseId?: string;
  suppressedResponseId?: string;
  statsTimer?: number;
  deadline?: number;
  disconnectTimer?: number;
};

function releaseMedia(session: Session) {
  if (!session.released) {
    session.released = true;
    session.abort.abort();
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
      session.audio.onended = null;
      session.audio.pause();
      session.audio.srcObject = null;
      session.audio.removeAttribute("src");
    }
  }
  window.clearInterval(session.statsTimer);
  session.statsTimer = undefined;
  window.clearTimeout(session.deadline);
  session.deadline = undefined;
  window.clearTimeout(session.disconnectTimer);
  session.disconnectTimer = undefined;
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

function optionalNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || (typeof value === "string" && !value.trim())) return undefined;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseVoiceScope(scopeKey: string): { conversationId?: string; sessionEpoch?: number } {
  try {
    const value: unknown = JSON.parse(scopeKey);
    if (Array.isArray(value)) {
      const conversationId = typeof value[2] === "string" ? value[2].trim() : "";
      const sessionEpoch = optionalNumber(value[3]);
      return {
        ...(conversationId ? { conversationId } : {}),
        ...(sessionEpoch !== undefined ? { sessionEpoch } : {}),
      };
    }
    const scope = record(value);
    const conversationId = String(scope.conversationId ?? scope.conversation_id ?? scope.activeConversationId ?? scope.active_conversation_id ?? "").trim();
    const sessionEpoch = optionalNumber(scope.sessionEpoch ?? scope.session_epoch);
    return {
      ...(conversationId ? { conversationId } : {}),
      ...(sessionEpoch !== undefined ? { sessionEpoch } : {}),
    };
  } catch {
    return {};
  }
}

function voiceErrorMessage(message: { code?: string; message?: string; error?: { code?: string; message?: string } }, fallback: string) {
  const code = String(message.code || message.error?.code || "").trim();
  const detail = String(message.message || message.error?.message || "").trim();
  if (code === "voice_connection_occupied") return "当前会话已在其他标签页使用语音";
  if (code && detail) return `${code}: ${detail}`;
  return detail || code || fallback;
}

function responseIdOf(data: Record<string, unknown>): string {
  const response = record(data.response);
  return String(data.response_id ?? data.responseId ?? response.id ?? data.id ?? "").trim();
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

export function useCodexVoiceSession({ client, botAlias, agentId, scopeKey, conversationId: requestedConversationId, sessionEpoch: requestedSessionEpoch, taskBinding: restoredTaskBinding, enabled, busy = false }: {
  client: WebBotClient;
  botAlias: string;
  agentId: string;
  scopeKey: string;
  conversationId?: string;
  sessionEpoch?: number;
  taskBinding?: VoiceTaskBinding | null;
  enabled: boolean;
  busy?: boolean;
}) {
  const [view, setView] = useState<VoiceView>(() => initialViewForTask(restoredTaskBinding));
  const current = useRef<Session | null>(null);
  const scopeInitialized = useRef(false);
  const restoredTaskBindingRef = useRef<VoiceTaskBinding | null | undefined>(restoredTaskBinding);
  restoredTaskBindingRef.current = restoredTaskBinding;

  const dispose = useCallback((sendStop = true) => {
    const session = current.current;
    if (!session) return;
    const shouldSendStop = sendStop && session.started && !session.stopping;
    current.current = null;
    session.stopping = true;
    if (shouldSendStop) {
      try { session.connection?.send({ op: "stop_voice" }); } catch { /* Disconnect also releases the server lease. */ }
    }
    releaseMedia(session);
    session.connection?.close();
  }, []);

  useEffect(() => {
    if (scopeInitialized.current) setView(initialViewForTask(restoredTaskBindingRef.current));
    scopeInitialized.current = true;
    const leave = () => { dispose(); setView(initialViewForTask(restoredTaskBindingRef.current)); };
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); dispose(); };
  }, [client, botAlias, agentId, scopeKey, enabled, dispose]);

  useEffect(() => {
    if (current.current || !restoredTaskBinding) {
      return;
    }
    setView((value) => {
      if (value.taskBinding?.state === "unknown" && restoredTaskBinding.state !== "unknown") {
        return value;
      }
      if (isTerminalTaskState(value.taskBinding?.state || "active")
        && value.taskBinding?.state !== restoredTaskBinding.state
        && value.taskBinding?.seq === undefined) {
        return value;
      }
      return {
        ...value,
        task: taskLabelState(restoredTaskBinding),
        taskBinding: restoredTaskBinding,
        activity: restoredTaskBinding.state === "active" ? "任务运行中" : "语音任务已同步",
      };
    });
  }, [restoredTaskBinding]);

  const finish = useCallback((session: Session, state: CodexVoiceState, error = "") => {
    if (current.current !== session) return;
    if (state === "unknown") {
      dispose(false);
      setView((value) => ({ ...value, state: "unknown", error: error || value.error,
        mic: "off", peer: "closed", playback: "idle",
        activity: "结果待确认",
        task: value.taskBinding?.state === "unknown" || value.task === "running" ? "unknown" : value.task,
      }));
      return;
    }
    dispose();
    setView((value) => ({ ...value, state, mic: "off", peer: "closed", playback: "idle", error,
      activity: state === "closed" ? "语音已结束" : "设备已释放",
      task: value.task,
    }));
  }, [dispose]);

  const play = useCallback(async (session: Session) => {
    if (!session.audio || session.stopping) return;
    const generation = session.playbackGeneration;
    try {
      await session.audio.play();
      if (current.current === session && !session.stopping && generation === session.playbackGeneration) {
        setView((value) => ({ ...value, playback: session.suppressed ? "suppressed" : "playing" }));
      }
    } catch {
      if (current.current === session && !session.stopping && generation === session.playbackGeneration) setView((value) => ({ ...value, playback: "blocked" }));
    }
  }, []);

  const start = useCallback(async () => {
    if (!enabled) return;
    if (current.current) return;
    if (busy) { setView((value) => ({ ...value, error: VOICE_BUSY_REASON })); return; }
    const session: Session = {
      abort: new AbortController(), tracks: new Set(), seen: new Set(), seq: -1,
      started: false, stopping: false, applyingSdp: false, suppressed: false, released: false,
      playbackGeneration: 0,
    };
    current.current = session;
    const live = () => current.current === session && !session.stopping;
    const fail = (message: string) => {
      finish(session, session.started ? "unknown" : "error", message);
    };
    setView({ ...initialView, state: "negotiating", mic: "requesting", activity: "等待麦克风授权" });
    const applyTaskBinding = (raw: Record<string, unknown>) => {
      const nested = record(raw.data);
      const payload = Object.keys(nested).length > 0 ? { ...nested, ...raw } : raw;
      const rawState = String(payload.state || "unknown").trim().toLowerCase();
      const transcript = normalizeTranscriptState(payload.transcript_state ?? payload.transcriptState);
      const sessionEpoch = optionalNumber(payload.session_epoch ?? payload.sessionEpoch);
      const binding: VoiceTaskBinding = {
        type: "voice.task",
        ...(typeof payload.seq === "number" && Number.isFinite(payload.seq) ? { seq: payload.seq } : {}),
        ...(payload.tcb_turn_id || payload.tcbTurnId ? { tcbTurnId: String(payload.tcb_turn_id || payload.tcbTurnId) } : {}),
        ...(payload.assistant_message_id || payload.assistantMessageId ? { assistantMessageId: String(payload.assistant_message_id || payload.assistantMessageId) } : {}),
        ...(payload.codex_turn_id || payload.codexTurnId ? { codexTurnId: String(payload.codex_turn_id || payload.codexTurnId) } : {}),
        ...(payload.realtime_session_id || payload.realtimeSessionId ? { realtimeSessionId: String(payload.realtime_session_id || payload.realtimeSessionId) } : {}),
        ...(payload.conversation_id || payload.conversationId ? { conversationId: String(payload.conversation_id || payload.conversationId) } : {}),
        state: ["active", "completed", "failed", "interrupted", "unknown"].includes(rawState)
          ? rawState as VoiceTaskBinding["state"]
          : "unknown",
        transcriptState: transcript.state,
        ...(transcript.details ? { transcriptDetails: transcript.details } : {}),
        ...(sessionEpoch !== undefined ? { sessionEpoch } : {}),
      };
      setView((value) => {
        if (value.taskBinding?.state === "unknown" && binding.state !== "unknown") {
          return value;
        }
        if (isTerminalTaskState(value.taskBinding?.state || "active") && binding.state === "active") {
          return value;
        }
        return {
          ...value,
          task: taskLabelState(binding),
          taskBinding: binding,
          activity: binding.state === "active" ? "任务运行中" : "语音任务已同步",
        };
      });
    };
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
      if (name === "response.created") {
        const previousResponseId = session.responseId;
        const responseId = responseIdOf(data);
        if (responseId) session.responseId = responseId;
        const newResponse = !previousResponseId || !responseId || previousResponseId !== responseId;
        if (newResponse && (!session.suppressed || session.suppressedResponseId !== responseId)) {
          session.suppressed = false;
          session.suppressedResponseId = undefined;
          if (session.audio) {
            session.audio.muted = false;
            void play(session);
          }
        }
      }
      if (name === "output_audio_buffer.stopped") {
        session.playbackGeneration += 1;
        session.audio?.pause();
      }
      setView((value) => {
        let task = value.task;
        if (name === "turn/started" && value.taskBinding?.state === "active") task = "running";
        if (name === "turn/completed" && value.taskBinding?.state === "active") {
          const status = record(data.turn).status || data.status;
          task = status === "completed" || status === "failed" || status === "interrupted" ? status : "unknown";
        }
        const activity = name === "input_audio_buffer.speech_started" ? "正在聆听"
          : name === "output_audio_buffer.started" ? "正在播报"
          : name === "output_audio_buffer.stopped" || name === "thread/realtime/started" ? "等待语音" : value.activity;
        return { ...value, task, activity,
          playback: name === "output_audio_buffer.stopped" ? "idle" : value.playback,
          captions: updateCaptions(value.captions, name, data, itemId),
        };
      });
    };
    const onMessage = (message: CodexVoiceMessage) => {
      if (current.current !== session) return;
      if (typeof message.seq === "number") {
        if (message.seq <= session.seq) return;
        session.seq = message.seq;
      }
      if (message.type === "voice.state") {
        if (message.state === "unknown") {
          finish(session, "unknown", voiceErrorMessage(message, "语音状态待确认"));
        } else if (message.state === "closed") {
          session.stopping = true;
          finish(session, message.state);
        } else if (message.state === "error") {
          session.stopping = true;
          finish(session, message.state, voiceErrorMessage(message, "语音连接失败"));
        } else if (!session.stopping && message.state !== "idle") setView((value) => ({ ...value, state: message.state }));
      } else if (message.type === "voice.task") {
        applyTaskBinding(record(message));
      } else if (message.type === "voice.sdp" && live() && session.peer && !session.applyingSdp) {
        session.applyingSdp = true;
        void session.peer.setRemoteDescription({ type: "answer", sdp: message.sdp }).then(() => {
          if (live()) window.clearTimeout(session.deadline);
        }).catch(() => fail("远端 SDP 协商失败，设备已释放"));
      } else if (message.type === "voice.event") {
        runtimeEvent(message.name, record(message.data), message.event_id, message.item_id);
      } else if (message.type === "error" || message.type === "voice.error") {
        const unknown = message.state === "unknown" || message.outcome === "unknown";
        if (unknown) finish(session, "unknown", voiceErrorMessage(message, "语音结果待确认"));
        else {
          session.stopping = true;
          finish(session, "error", voiceErrorMessage(message, "语音连接失败"));
        }
      }
    };
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") throw new Error("当前浏览器不支持语音，请使用安全连接并允许麦克风访问");
      const scoped = parseVoiceScope(scopeKey);
      let voiceConversationId = requestedConversationId?.trim() || scoped.conversationId;
      let voiceSessionEpoch = requestedSessionEpoch ?? scoped.sessionEpoch;
      if (typeof client.getBotOverview === "function") {
        const overview = await client.getBotOverview(botAlias, { agentId, executionMode: "cli" });
        if (!live()) return;
        const overviewConversationId = overview.activeConversationId
          || overview.agents?.find((agent) => agent.id === agentId)?.activeConversationId
          || "";
        if (voiceConversationId && overviewConversationId && voiceConversationId !== overviewConversationId) {
          throw new Error("当前聊天会话已切换，请重试语音连接");
        }
        voiceConversationId ||= overviewConversationId;
        if (voiceSessionEpoch === undefined) voiceSessionEpoch = overview.sessionEpoch;
        if (voiceSessionEpoch !== undefined && overview.sessionEpoch !== undefined && voiceSessionEpoch !== overview.sessionEpoch) {
          throw new Error("当前聊天会话已切换，请重试语音连接");
        }
      }
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!live()) { mic.getTracks().forEach((track) => track.stop()); return; }
      session.mic = mic;
      session.audio = new Audio();
      session.audio.autoplay = true;
      session.audio.onended = () => {
        if (current.current !== session) return;
        session.playbackGeneration += 1;
        setView((value) => ({ ...value, playback: "idle" }));
      };
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
        const connectionState = peer.connectionState;
        setView((value) => ({ ...value, peer: connectionState,
          ...(connectionState === "disconnected" ? { activity: "媒体连接暂时中断，等待恢复" } : {}) }));
        window.clearTimeout(session.disconnectTimer);
        session.disconnectTimer = undefined;
        if (connectionState === "disconnected") {
          session.disconnectTimer = window.setTimeout(() => {
            session.disconnectTimer = undefined;
            if (live() && ["disconnected", "failed"].includes(peer.connectionState)) {
              fail("媒体连接持续中断，语音结果待确认");
            }
          }, 10000);
        } else if (["failed", "closed"].includes(connectionState)) {
          fail("媒体连接中断，语音结果待确认");
        }
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
      };
      const offer = await peer.createOffer();
      if (!live()) return;
      await peer.setLocalDescription(offer);
      if (!live()) return;
      await gatherIce(peer, session.abort.signal);
      if (!live()) return;
      if (!peer.localDescription?.sdp) throw new Error("未生成本地 SDP");
      session.connection = client.connectCodexVoice(botAlias, {
        agentId,
        conversationId: voiceConversationId,
        sessionEpoch: voiceSessionEpoch,
        protocolVersion: 1,
        onMessage,
        onClose: () => fail("语音控制连接中断，未自动重连"),
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
  }, [enabled, busy, client, botAlias, agentId, scopeKey, requestedConversationId, requestedSessionEpoch, dispose, finish, play]);

  const end = useCallback(() => {
    const session = current.current;
    if (!session || session.stopping) return;
    session.stopping = true;
    releaseMedia(session);
    if (!session.started) { finish(session, "closed"); return; }
    setView((value) => ({ ...value, state: "stopping", mic: "off", peer: "closed", playback: "idle" }));
    try {
      session.connection?.send({ op: "stop_voice" });
      if (current.current === session) {
        session.deadline = window.setTimeout(() => finish(session, "unknown", "结束语音结果待确认，设备已释放"), 10000);
      }
    } catch { finish(session, "unknown", "结束语音结果待确认，设备已释放"); }
  }, [finish]);

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
    session.suppressedResponseId = session.responseId;
    session.playbackGeneration += 1;
    session.audio.muted = true;
    session.audio.pause();
    setView((value) => ({ ...value, playback: "suppressed" }));
  }, []);
  const resumePlayback = useCallback(() => {
    const session = current.current;
    if (!session?.audio || session.stopping) return;
    session.suppressed = false;
    session.suppressedResponseId = undefined;
    session.audio.muted = false;
    void play(session);
  }, [play]);

  return { ...view, start, end, toggleMute, stopPlayback, resumePlayback,
    connected: ["negotiating", "active", "stopping"].includes(view.state),
  };
}

export type CodexVoiceSession = ReturnType<typeof useCodexVoiceSession>;
