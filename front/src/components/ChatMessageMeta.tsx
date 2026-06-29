import type { ReactNode } from "react";
import type { ChatMessageContextUsage } from "../services/types";
import { ChatContextUsageBadge, clampPercent, formatCompactionCount, formatTokenNumber } from "./ChatContextUsageBadge";

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
      {contextVariant === "text" ? (
        <ChatContextUsageBadge contextUsage={contextUsage} testId="chat-message-context-usage-text" />
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
