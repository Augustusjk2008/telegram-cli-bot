import { Mic, MicOff, Phone, Square, Volume2, VolumeX } from "lucide-react";
import { VOICE_BUSY_REASON, type CodexVoiceSession } from "../workbench/useCodexVoiceSession";

type Props = {
  session: CodexVoiceSession;
  disabled?: boolean;
  busy?: boolean;
};

const stateLabels: Record<string, string> = {
  idle: "未连接",
  negotiating: "连接中",
  active: "已连接",
  stopping: "结束中",
  closed: "已结束",
  error: "连接错误",
  unknown: "结果待确认",
};

const taskLabels: Record<string, string> = {
  idle: "空闲",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  unknown: "结果待确认",
};

export function CodexVoiceBar({ session, disabled = false, busy = false }: Props) {
  const active = session.connected;
  const blockedByBusy = !active && busy && session.taskBinding?.state !== "active";
  const hasCaption = session.captions.length > 0;
  const primaryState = session.state === "unknown"
    ? stateLabels[session.state]
    : session.continuity === "interrupted"
    ? "连接中断"
    : session.continuity === "recovering"
      ? "正在尝试继续当前会话"
      : session.continuity === "resumed"
        ? "已继续当前会话"
        : session.continuity === "ended"
          ? "语音已结束"
          : stateLabels[session.state] || session.state;
  const details = session.details;
  return (
    <section
      data-testid="codex-voice-bar"
      aria-label="Codex 语音控制"
      className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-[var(--text)]">语音</span>
        <span data-testid="codex-voice-state" className="font-medium text-[var(--text)]">{primaryState}</span>
        {session.mic !== "off" ? <span className="text-[var(--muted)]">麦克风：{session.mic === "muted" ? "已静音" : session.mic === "requesting" ? "授权中" : "开启"}</span> : null}
        <span className="text-[var(--muted)]">{session.activity}</span>
        <span className="text-[var(--muted)]">任务：{taskLabels[session.task] || session.task}</span>
        {!active ? (
          <button
            type="button"
            aria-label="开始语音"
            onClick={() => void session.start()}
            disabled={disabled || busy}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--accent-outline)] px-2 font-medium text-[var(--accent)] hover:bg-[var(--workbench-hover-bg)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Phone className="h-3.5 w-3.5" />开始语音
          </button>
        ) : (
          <>
            <button
              type="button"
              aria-label={session.mic === "muted" ? "取消静音" : "静音"}
              aria-pressed={session.mic === "muted"}
              onClick={session.toggleMute}
              disabled={session.mic !== "on" && session.mic !== "muted"}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--workbench-hairline)] px-2 text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
            >
              {session.mic === "muted" ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
              {session.mic === "muted" ? "取消静音" : "静音"}
            </button>
            <button
              type="button"
              aria-label={session.playback === "suppressed" ? "恢复播报" : "停止当前播报"}
              onClick={session.playback === "suppressed" ? session.resumePlayback : session.stopPlayback}
              disabled={session.state === "stopping" || session.playback === "idle"}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--workbench-hairline)] px-2 text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
            >
              {session.playback === "suppressed" ? <Volume2 className="h-3.5 w-3.5" /> : <VolumeX className="h-3.5 w-3.5" />}
              {session.playback === "suppressed" ? "恢复播报" : "停止播报"}
            </button>
            <button
              type="button"
              aria-label="结束语音"
              onClick={session.end}
              disabled={session.state === "stopping"}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--status-danger-border)] px-2 text-[var(--status-danger)] hover:bg-[var(--status-danger-bg)] disabled:opacity-50"
            >
              <Square className="h-3.5 w-3.5" />结束语音
            </button>
          </>
        )}
      </div>
      {blockedByBusy ? <p className="mt-1 text-[var(--status-warning)]">{VOICE_BUSY_REASON}</p> : null}
      {session.playback === "blocked" ? <button type="button" onClick={session.resumePlayback} className="mt-1 text-[var(--accent)]">允许播放音频</button> : null}
      {session.continuity === "ended" ? <p data-testid="codex-voice-ended" className="mt-1 text-[var(--muted)]">语音已结束，已保存的内容仍在对话中</p> : null}
      {session.error ? <p role="alert" className="mt-1 text-[var(--status-danger)]">{session.error}</p> : null}
      <details className="mt-1 text-[var(--muted)]">
        <summary className="cursor-pointer select-none">连接详情</summary>
        <div data-testid="codex-voice-details" className="mt-1 space-y-0.5 pl-3">
          <p>会话：{details.conversationId || "未绑定"} · epoch：{details.sessionEpoch ?? "未绑定"} · agent：{details.agentId || "main"}</p>
          <p>线程：{details.threadId || "未同步"} · Codex turn：{details.codexTurnId || "未同步"} · TCB turn：{details.tcbTurnId || "未同步"}</p>
          <p>clientGeneration：{details.clientGeneration || "未同步"} · 恢复令牌：{details.recoveryToken ? "已保存" : "未生成"}</p>
          <p>控制连接：{stateLabels[session.state] || session.state} · 恢复尝试：{details.reconnectAttempt || 0} · 最新序号：{details.lastSeq ?? "未同步"}</p>
          {active ? <p>媒体：{session.peer} · 播放：{{ idle: "等待音频", playing: "播放中", blocked: "等待播放授权", suppressed: "本地暂停，下一次响应恢复" }[session.playback]} · 接收 {session.receivedPackets} 包 / {session.receivedBytes} 字节</p> : null}
        </div>
      </details>
      {hasCaption ? (
        <div data-testid="codex-voice-captions" className="mt-2 max-h-24 space-y-1 overflow-y-auto rounded-md bg-[var(--workbench-panel-bg)] px-2 py-1.5">
          {session.captions.map((caption) => (
            <p key={caption.id} className="whitespace-pre-wrap text-[var(--text)]">
              <span className="mr-1 text-[var(--muted)]">{caption.role === "user" ? "你" : caption.role === "assistant" ? "Codex" : "转写"}</span>
              {caption.text}
              {!caption.done ? <span className="ml-1 text-[var(--muted)]">…</span> : null}
            </p>
          ))}
          <span className="text-[var(--muted)]">
            {session.taskBinding?.transcriptState === "saved"
              ? "字幕已保存"
              : session.taskBinding?.transcriptState === "syncing"
                ? "字幕同步中"
                : "实时字幕"}
          </span>
        </div>
      ) : null}
      {session.receivedPackets > 0 ? <span className="sr-only">已接收远端音频 {session.receivedPackets} 个数据包</span> : null}
    </section>
  );
}
