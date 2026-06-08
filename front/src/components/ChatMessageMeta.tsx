import type { ReactNode } from "react";
import type { ChatMessageContextUsage } from "../services/types";

type Props = {
  name: string;
  createdAt: string;
  align?: "left" | "right";
  avatar?: ReactNode;
  contextUsage?: ChatMessageContextUsage;
  contextVariant?: "text" | "ring";
};

function formatTime(createdAt: string) {
  const parsed = Date.parse(createdAt);
  if (Number.isNaN(parsed)) {
    return "--:--";
  }
  const createdDate = new Date(parsed);
  const timeText = createdDate.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const now = new Date();
  const isSameDay = createdDate.getFullYear() === now.getFullYear()
    && createdDate.getMonth() === now.getMonth()
    && createdDate.getDate() === now.getDate();
  if (isSameDay) {
    return timeText;
  }
  const dateText = createdDate.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return `${dateText} ${timeText}`;
}

function formatCompactionCount(count?: number) {
  const value = Math.floor(Number(count || 0));
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }
  if (value === 1) {
    return "compacted once";
  }
  if (value === 2) {
    return "compacted twice";
  }
  return `compacted ${value} times`;
}

function formatTokenNumber(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "";
  }
  return Math.max(0, Math.floor(value)).toLocaleString("zh-CN");
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function formatTextContextUsage(contextUsage?: ChatMessageContextUsage) {
  if (!contextUsage) {
    return null;
  }
  const percent = typeof contextUsage.contextLeftPercent === "number"
    ? `${contextUsage.contextLeftPercent}% left`
    : "";
  const usage = contextUsage.usedDisplay && contextUsage.windowDisplay
    ? `${contextUsage.usedDisplay} / ${contextUsage.windowDisplay}`
    : "";
  const baseText = (contextUsage.statusText || [percent, usage].filter(Boolean).join(" · "))
    .replace(/\bcontext left\b/g, "left");
  if (!baseText) {
    return null;
  }
  const compactionText = formatCompactionCount(contextUsage.compactionCount);
  const text = [baseText, compactionText ? `(${compactionText})` : ""].filter(Boolean).join(" ");
  if (!text) {
    return null;
  }
  const baseTitle = contextUsage.usedDisplay && contextUsage.windowDisplay
    ? `${contextUsage.usedDisplay} used / ${contextUsage.windowDisplay} window`
    : baseText;
  const title = compactionText ? `${baseTitle} (${compactionText})` : baseTitle;
  return {
    text,
    title,
    isLow: typeof contextUsage.contextLeftPercent === "number" && contextUsage.contextLeftPercent < 25,
  };
}

function formatRingContextUsage(contextUsage?: ChatMessageContextUsage) {
  if (!contextUsage) {
    return null;
  }
  const contextUsed = typeof contextUsage.contextUsed === "number"
    ? contextUsage.contextUsed
    : contextUsage.usedTokens;
  const contextWindow = contextUsage.contextWindow;
  const hasWindow = typeof contextWindow === "number" && contextWindow > 0;
  const usedPercent = typeof contextUsage.contextUsedPercent === "number"
    ? contextUsage.contextUsedPercent
    : hasWindow && typeof contextUsed === "number"
      ? (contextUsed / contextWindow) * 100
      : typeof contextUsage.contextLeftPercent === "number"
        ? 100 - contextUsage.contextLeftPercent
        : 0;
  const detailRows = [
    hasWindow ? `context window: ${formatTokenNumber(contextWindow)}` : "未配置 context window",
    typeof contextUsed === "number" ? `context used: ${formatTokenNumber(contextUsed)}` : "",
    typeof contextUsage.inputTokens === "number" ? `input: ${formatTokenNumber(contextUsage.inputTokens)}` : "",
    typeof contextUsage.cacheReadTokens === "number" ? `cache read: ${formatTokenNumber(contextUsage.cacheReadTokens)}` : "",
    typeof contextUsage.cacheWriteTokens === "number" ? `cache write: ${formatTokenNumber(contextUsage.cacheWriteTokens)}` : "",
    typeof contextUsage.outputTokens === "number" ? `output: ${formatTokenNumber(contextUsage.outputTokens)}` : "",
    typeof contextUsage.reasoningTokens === "number" ? `reasoning: ${formatTokenNumber(contextUsage.reasoningTokens)}` : "",
    contextUsage.model ? `model: ${contextUsage.model}` : "",
  ].filter(Boolean);
  const compactionText = formatCompactionCount(contextUsage.compactionCount);
  if (compactionText) {
    detailRows.push(compactionText);
  }
  return {
    percent: hasWindow ? clampPercent(usedPercent) : 0,
    title: detailRows.join("\n"),
    label: hasWindow ? `context 已用 ${Math.round(clampPercent(usedPercent))}%` : "未配置 context window",
  };
}

export function ChatMessageMeta({ name, createdAt, align = "left", avatar, contextUsage, contextVariant = "text" }: Props) {
  const textContext = contextVariant === "text" ? formatTextContextUsage(contextUsage) : null;
  const ringContext = contextVariant === "ring" ? formatRingContextUsage(contextUsage) : null;
  return (
    <div
      className={align === "right"
        ? "mb-1.5 flex min-w-0 items-center justify-end gap-2 text-xs"
        : "mb-1.5 flex min-w-0 items-center gap-2 text-xs"}
    >
      {align === "left" && avatar ? <span className="shrink-0">{avatar}</span> : null}
      <span className="min-w-0 max-w-[12rem] truncate font-medium text-[var(--text)]">{name}</span>
      <span className="shrink-0 text-[var(--muted)]">{formatTime(createdAt)}</span>
      {textContext ? (
        <span
          className={textContext.isLow
            ? "rounded-md border border-red-200 bg-red-50 px-1.5 py-0.5 font-medium text-red-600"
            : "rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5 text-[var(--muted)]"}
          data-testid="chat-message-context-usage-text"
          title={textContext.title}
        >
          {textContext.text}
        </span>
      ) : null}
      {ringContext ? (
        <span
          aria-label={ringContext.label}
          className="inline-flex h-4 w-4 shrink-0 items-center justify-center text-[var(--muted)]"
          data-testid="chat-message-context-usage"
          title={ringContext.title}
        >
          <svg viewBox="0 0 20 20" className="h-4 w-4" aria-hidden="true">
            <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
            <circle
              cx="10"
              cy="10"
              r="7"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeDasharray={43.98}
              strokeDashoffset={43.98 - (43.98 * ringContext.percent) / 100}
              strokeLinecap="round"
              transform="rotate(-90 10 10)"
            />
          </svg>
        </span>
      ) : null}
      {align === "right" && avatar ? <span className="shrink-0">{avatar}</span> : null}
    </div>
  );
}
