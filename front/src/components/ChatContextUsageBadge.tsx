import { ChevronsDownUp } from "lucide-react";
import type { ChatMessageContextUsage } from "../services/types";
import { mapEstimatedCost } from "../utils/contextUsage";
import { TouchHint } from "./TouchHint";

function normalizedCompactionCount(count?: number) {
  const value = Math.floor(Number(count || 0));
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function formatCompactionCount(count?: number) {
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

function formatTokenNumber(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "";
  }
  return Math.max(0, Math.floor(value)).toLocaleString("en-US");
}

function clampPercent(value: number) {
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
  const cost = mapEstimatedCost(contextUsage.estimatedCost, contextUsage.provider);
  const model = contextUsage.model || cost?.model;
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
    model ? `model: ${model}` : "",
    contextUsage.provider ? `provider: ${contextUsage.provider.replace(/原生 (?:agent|智能体)/gi, "native agent")}` : "",
    contextUsage.sessionId ? `session: ${contextUsage.sessionId}` : "",
    formatCompactionCount(contextUsage.compactionCount),
  ].filter(Boolean);
  if (cost) {
    const amount = cost.total.toLocaleString("en-US", {
      useGrouping: false,
      maximumSignificantDigits: 15,
    });
    rows.push(`Estimated cost: ${cost.currency} ${amount}`);
  }
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
    ? options.compact ? `ctx ${formatPercent(leftPercent)}%` : `${formatPercent(leftPercent)}% left`
    : "";
  const costText = mapEstimatedCost(contextUsage.estimatedCost, contextUsage.provider) ? "Estimated cost" : "";
  const statusText = (contextUsage.statusText || "").replace(/\bcontext left\b/gi, "left");
  if (options.compact) {
    const baseText = percent || statusText || costText;
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
  const baseText = options.preferLeft
    ? [percent, usage].filter(Boolean).join(" · ") || statusText || costText
    : statusText || [percent, usage].filter(Boolean).join(" · ") || costText;
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
    ? "inline-flex min-w-0 items-center rounded-md border border-red-200 bg-red-50 px-1.5 py-0.5"
    : "inline-flex min-w-0 items-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5";
  const textClassName = textContext.isLow ? "font-medium text-red-600" : "text-[var(--muted)]";
  return (
    <TouchHint content={textContext.title}>
      <button
        type="button"
        aria-label={`View context details: ${textContext.text}`}
        data-testid={testId}
        className={[baseClassName, className, "cursor-help text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]"].filter(Boolean).join(" ")}
      >
        <span className={["inline-flex min-w-0 items-center", textClassName].join(" ")}>
          {compactionCount > 0 ? (
            <>
              <span className="min-w-0 truncate pr-1">{textContext.text}</span>
              <span
                aria-label={formatCompactionCount(compactionCount)}
                className="inline-flex shrink-0 items-center gap-0.5 border-l border-current/20 pl-1"
                data-testid={testId ? `${testId}-compaction` : undefined}
              >
                <ChevronsDownUp aria-hidden="true" className="h-3 w-3" />
                <span aria-hidden="true">×{compactionCount}</span>
              </span>
            </>
          ) : textContext.text}
        </span>
      </button>
    </TouchHint>
  );
}
