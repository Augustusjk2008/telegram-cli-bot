import { ChevronsDownUp } from "lucide-react";
import type { ChatMessageContextUsage } from "../services/types";

function normalizedCompactionCount(count?: number) {
  const value = Math.floor(Number(count || 0));
  return Number.isFinite(value) && value > 0 ? value : 0;
}

export function formatCompactionCount(count?: number) {
  const value = normalizedCompactionCount(count);
  if (value <= 0) {
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

export function formatTokenNumber(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "";
  }
  return Math.max(0, Math.floor(value)).toLocaleString("zh-CN");
}

export function clampPercent(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function formatPercent(value: number) {
  const rounded = Math.round(clampPercent(value) * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

export function contextLeftPercent(contextUsage?: ChatMessageContextUsage) {
  if (!contextUsage) {
    return undefined;
  }
  if (typeof contextUsage.contextLeftPercent === "number") {
    return clampPercent(contextUsage.contextLeftPercent);
  }
  if (typeof contextUsage.contextUsedPercent === "number") {
    return clampPercent(100 - contextUsage.contextUsedPercent);
  }
  const contextUsed = typeof contextUsage.contextUsed === "number"
    ? contextUsage.contextUsed
    : contextUsage.usedTokens;
  if (
    typeof contextUsed === "number"
    && typeof contextUsage.contextWindow === "number"
    && contextUsage.contextWindow > 0
  ) {
    return clampPercent(100 - (contextUsed / contextUsage.contextWindow) * 100);
  }
  return undefined;
}

export function formatContextUsageDetails(contextUsage?: ChatMessageContextUsage) {
  if (!contextUsage) {
    return "";
  }
  const contextUsed = typeof contextUsage.contextUsed === "number"
    ? contextUsage.contextUsed
    : contextUsage.usedTokens;
  const leftPercent = contextLeftPercent(contextUsage);
  const rows = [
    typeof leftPercent === "number" ? `context left: ${formatPercent(leftPercent)}%` : "",
    typeof contextUsage.contextWindow === "number" ? `context window: ${formatTokenNumber(contextUsage.contextWindow)}` : "",
    typeof contextUsed === "number" ? `context used: ${formatTokenNumber(contextUsed)}` : "",
    typeof contextUsage.inputTokens === "number" ? `input: ${formatTokenNumber(contextUsage.inputTokens)}` : "",
    typeof contextUsage.cacheReadTokens === "number" ? `cache read: ${formatTokenNumber(contextUsage.cacheReadTokens)}` : "",
    typeof contextUsage.cacheWriteTokens === "number" ? `cache write: ${formatTokenNumber(contextUsage.cacheWriteTokens)}` : "",
    typeof contextUsage.outputTokens === "number" ? `output: ${formatTokenNumber(contextUsage.outputTokens)}` : "",
    typeof contextUsage.reasoningTokens === "number" ? `reasoning: ${formatTokenNumber(contextUsage.reasoningTokens)}` : "",
    contextUsage.usedDisplay && contextUsage.windowDisplay ? `display: ${contextUsage.usedDisplay} / ${contextUsage.windowDisplay}` : "",
    contextUsage.model ? `model: ${contextUsage.model}` : "",
    contextUsage.provider ? `provider: ${contextUsage.provider}` : "",
    contextUsage.sessionId ? `session: ${contextUsage.sessionId}` : "",
    formatCompactionCount(contextUsage.compactionCount),
  ].filter(Boolean);
  return rows.join("\n");
}

export function formatTextContextUsage(
  contextUsage?: ChatMessageContextUsage,
  options: { compact?: boolean; preferLeft?: boolean } = {},
) {
  if (!contextUsage) {
    return null;
  }
  const leftPercent = contextLeftPercent(contextUsage);
  const percent = typeof leftPercent === "number"
    ? options.compact
      ? `ctx ${formatPercent(leftPercent)}%`
      : `${formatPercent(leftPercent)}% left`
    : "";
  if (options.compact) {
    const statusText = (contextUsage.statusText || "").replace(/\bcontext left\b/g, "left");
    const baseText = percent || statusText;
    if (!baseText) {
      return null;
    }
    const details = formatContextUsageDetails(contextUsage);
    return {
      text: baseText,
      title: details || baseText,
      isLow: typeof leftPercent === "number" && leftPercent < 25,
    };
  }
  const usage = contextUsage.usedDisplay && contextUsage.windowDisplay
    ? `${contextUsage.usedDisplay} / ${contextUsage.windowDisplay}`
    : "";
  const statusText = (contextUsage.statusText || "").replace(/\bcontext left\b/g, "left");
  const baseText = options.preferLeft
    ? [percent, usage].filter(Boolean).join(" · ") || statusText
    : statusText || [percent, usage].filter(Boolean).join(" · ");
  if (!baseText) {
    return null;
  }
  const compactionText = formatCompactionCount(contextUsage.compactionCount);
  const text = [baseText, compactionText ? `(${compactionText})` : ""].filter(Boolean).join(" ");
  if (!text) {
    return null;
  }
  const details = formatContextUsageDetails(contextUsage);
  const title = details || baseText;
  return {
    text,
    title,
    isLow: typeof leftPercent === "number" && leftPercent < 25,
  };
}

type Props = {
  contextUsage?: ChatMessageContextUsage;
  className?: string;
  compact?: boolean;
  testId?: string;
  preferLeft?: boolean;
};

export function ChatContextUsageBadge({ contextUsage, className = "", compact = false, testId, preferLeft = false }: Props) {
  const textContext = formatTextContextUsage(contextUsage, { compact, preferLeft });
  if (!textContext) {
    return null;
  }
  const compactionCount = compact ? normalizedCompactionCount(contextUsage?.compactionCount) : 0;
  const baseClassName = textContext.isLow
    ? "inline-flex min-w-0 items-center rounded-md border border-red-200 bg-red-50 px-1.5 py-0.5 font-medium text-red-600"
    : "inline-flex min-w-0 items-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5 text-[var(--muted)]";
  return (
    <span
      className={[baseClassName, className].filter(Boolean).join(" ")}
      data-testid={testId}
      title={textContext.title}
    >
      {compactionCount > 0 ? (
        <>
          <span className="min-w-0 truncate pr-1">{textContext.text}</span>
          <span
            aria-label={`已 compact ${compactionCount} 次`}
            className="inline-flex shrink-0 items-center gap-0.5 border-l border-current/20 pl-1"
            data-testid={testId ? `${testId}-compaction` : undefined}
          >
            <ChevronsDownUp aria-hidden="true" className="h-3 w-3" />
            <span aria-hidden="true">×{compactionCount}</span>
          </span>
        </>
      ) : textContext.text}
    </span>
  );
}
