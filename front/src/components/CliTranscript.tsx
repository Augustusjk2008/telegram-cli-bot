import type { ReactNode } from "react";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, LoaderCircle, } from "lucide-react";
import { ChatMarkdownMessage } from "./ChatMarkdownMessage";
import { ChatPlainTextMessage } from "./ChatPlainTextMessage";
import type { ChatMessage, ChatMessageContextUsage } from "../services/types";

import type { CliTranscriptEntry } from "../utils/cliTranscript";
import { ChatFinalAnswerActions } from "./ChatFinalAnswerActions";

type Props = {
  entries: CliTranscriptEntry[];
  resultText: string;
  originalResultText?: string;
  translationControl?: ReactNode;
  state?: ChatMessage["state"];
  traceCount?: number;
  toolCallCount?: number;
  processCount?: number;
  traceLoaded?: boolean;
  isTraceLoading?: boolean;
  traceLoadError?: string;
  onLoadTrace?: () => void;

  onFileLinkClick?: (href: string) => void;
  onCopyFinalAnswer?: () => boolean | void | Promise<boolean | void>;
  onContinue?: () => void;
  onFastForward?: () => void;
  onToggleFavorite?: () => void;
  favorite?: boolean;
  canContinue?: boolean;
  contextUsage?: ChatMessageContextUsage;
  endlessContinueCount?: number;
  endlessActive?: boolean;
  endlessRetryAtMs?: number | null;
  mobileLayout?: boolean;
};

export function EndlessTypingLabel({ retryAtMs }: { retryAtMs?: number | null } = {}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!retryAtMs) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [retryAtMs]);
  const retryRemainingSeconds = retryAtMs ? Math.max(0, Math.ceil((retryAtMs - now) / 1000)) : null;
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1">
    <span aria-label="ENDLESS..." className="inline-flex items-baseline font-semibold tracking-[0.18em]">
      {"ENDLESS".split("").map((letter, index) => (
        <span
          key={`${letter}-${index}`}
          aria-hidden="true"
          className="endless-typing-letter inline-block"
          style={{ animationDelay: `${index * 100}ms` }}
        >
          {letter}
        </span>
      ))}
      <span aria-hidden="true" className="ml-0.5 tracking-normal">...</span>
    </span>
      {typeof retryRemainingSeconds === "number" && retryRemainingSeconds > 0 ? (
        <span className="text-xs font-normal tabular-nums">
          （{retryRemainingSeconds}秒后重试）
        </span>
      ) : null}
    </span>
  );
}

function compact(value: string, fallback: string) {
  const text = value.trim();
  return text || fallback;
}

function EntryBody({ entry }: { entry: CliTranscriptEntry }) {
  const body = (entry.body || "").trim();
  if (!body) {
    return null;
  }
  return (
    <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--workbench-panel-bg)] px-2 py-1.5 text-xs leading-5 text-[var(--text)]">
      {body}
    </pre>
  );
}

function shouldRenderEntrySummaryAsMarkdown(entry: CliTranscriptEntry) {
  return entry.kind === "process" && entry.trace?.kind === "commentary";
}

function stripThinkingBlocks(value: string) {
  return value
    .replace(/<thinking\b[^>]*>[\s\S]*?<\/thinking>/gi, "")
    .replace(/<thinking\b[^>]*>[\s\S]*$/gi, "")
    .replace(/<\/thinking>/gi, "")
    .trim();
}

type TranscriptRenderItem =
  | { kind: "entry"; entry: CliTranscriptEntry }
  | { kind: "group"; groupIndex: number; entries: CliTranscriptEntry[] }
  | { kind: "retry"; retryGroupIndex: number; attempt: number; entries: CliTranscriptEntry[] };

function isEndlessTranscriptEntry(entry: CliTranscriptEntry) {
  return entry.kind === "endless_error" || entry.kind === "endless_continue";
}

function cutsTranscriptGroup(entry: CliTranscriptEntry) {
  return (
    entry.kind === "process"
    || ["error", "cancelled", "endless_error", "endless_continue"].includes(entry.kind)
  );
}

function isToolResultEntry(entry: CliTranscriptEntry) {
  return entry.trace?.kind === "tool_result" || entry.label === "工具结果";
}

function shouldWrapTranscriptGroup(entries: CliTranscriptEntry[]) {
  if (entries.length <= 1) {
    return false;
  }
  return entries.some((entry) => entry.kind === "tool" || isToolResultEntry(entry));
}

function groupTranscriptEntries(entries: CliTranscriptEntry[]): TranscriptRenderItem[] {
  const grouped: TranscriptRenderItem[] = [];
  let current: CliTranscriptEntry[] = [];
  let groupIndex = 0;
  let retryGroupIndex = 0;

  const flushCurrent = () => {
    if (current.length === 0) {
      return;
    }
    if (shouldWrapTranscriptGroup(current)) {
      groupIndex += 1;
      grouped.push({ kind: "group", groupIndex, entries: current });
    } else {
      grouped.push(...current.map((entry) => ({ kind: "entry" as const, entry })));
    }
    current = [];
  };

  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    if (isEndlessTranscriptEntry(entry)) {
      flushCurrent();
      const attempt = typeof entry.attempt === "number" && entry.attempt > 0 ? entry.attempt : 0;
      const retryEntries = [entry];
      while (index + 1 < entries.length && isEndlessTranscriptEntry(entries[index + 1])) {
        index += 1;
        retryEntries.push(entries[index]);
      }
      retryGroupIndex += 1;
      grouped.push({ kind: "retry", retryGroupIndex, attempt, entries: retryEntries });
      continue;
    }
    if (cutsTranscriptGroup(entry)) {
      flushCurrent();
      grouped.push({ kind: "entry", entry });
      continue;
    }
    current.push(entry);
  }

  flushCurrent();
  return grouped;
}

function describeTranscriptGroup(entries: CliTranscriptEntry[]) {
  const toolCount = entries.filter((entry) => entry.kind === "tool").length;
  return `${entries.length} 条事件${toolCount > 0 ? ` · ${toolCount} 次工具` : ""}`;
}

function retryAttempts(item: Extract<TranscriptRenderItem, { kind: "retry" }>) {
  return new Set(
    item.entries
      .map((entry) => entry.attempt)
      .filter((attempt): attempt is number => typeof attempt === "number" && attempt > 0),
  );
}

function describeRetryGroup(item: Extract<TranscriptRenderItem, { kind: "retry" }>) {
  const errorCount = item.entries.filter((entry) => entry.kind === "endless_error").length;
  const continueCount = item.entries.filter((entry) => entry.kind === "endless_continue").length;
  const attempts = retryAttempts(item);
  const attemptText = attempts.size > 1
    ? `连续 ${attempts.size} 次`
    : item.attempt > 0 ? `第 ${item.attempt} 次` : "本次";
  return `${attemptText}重试 · ${errorCount} 条错误 · ${continueCount} 次 Continue`;
}

function countEndlessRetries(entries: CliTranscriptEntry[]) {
  const attempts = new Set<number>();
  let unknownErrors = 0;
  let unknownContinues = 0;
  for (const entry of entries) {
    if (!isEndlessTranscriptEntry(entry)) {
      continue;
    }
    if (typeof entry.attempt === "number" && entry.attempt > 0) {
      attempts.add(entry.attempt);
    } else if (entry.kind === "endless_error") {
      unknownErrors += 1;
    } else {
      unknownContinues += 1;
    }
  }
  return attempts.size > 0 ? attempts.size : Math.max(unknownErrors, unknownContinues);
}

function countProcessEntries(items: TranscriptRenderItem[]) {
  const allEntries = items.flatMap((item) => item.kind === "entry" ? [item.entry] : item.entries);
  return allEntries.filter((entry) => {
    if (isEndlessTranscriptEntry(entry)) {
      return false;
    }
    const traceKind = String(entry.trace?.kind || "").trim();
    return traceKind !== "tool_call" && traceKind !== "tool_result";
  }).length;
}

function entryCopyLabel(entry: CliTranscriptEntry) {
  if (entry.kind === "process") return entry.trace?.kind === "reasoning" ? "思考" : "过程";
  if (entry.kind === "tool") return `工具: ${entry.label}`;

  if (entry.kind === "error") return "错误";
  if (entry.kind === "cancelled") return "已取消";
  if (entry.kind === "endless_error") return "无尽错误";
  if (entry.kind === "endless_continue") return "Continue";
  return entry.label || "事件";
}

function formatTranscriptEntryForCopy(entry: CliTranscriptEntry) {
  const summary = stripThinkingBlocks(compact(entry.summary, entry.label));
  const body = (entry.body || "").trim();
  const bodyText = body && body !== summary ? `\n${body}` : "";
  const parts = [
    `[${entryCopyLabel(entry)}] ${summary}`.trim(),
    bodyText,
  ].filter(Boolean);
  return parts.join("");
}

function normalizedCopyText(value: string) {
  return stripThinkingBlocks(value)
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function normalizedDisplayText(value: string) {
  return value
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function isDuplicateFinalProcess(entry: CliTranscriptEntry, finalText: string) {
  if (entry.kind !== "process" || !finalText) {
    return false;
  }
  const kind = String(entry.trace?.kind || "").trim();
  if (kind && kind !== "commentary" && kind !== "reasoning") {
    return false;
  }
  return normalizedCopyText(entry.summary || "") === finalText;
}

function isDuplicateFinalError(entry: CliTranscriptEntry, finalText: string) {
  if (entry.kind !== "error" || !finalText) {
    return false;
  }
  const summary = normalizedDisplayText(entry.summary || "");
  if (summary === finalText) {
    return true;
  }
  return /^命令退出码\s+\d+\n/.test(summary) && normalizedDisplayText(summary.replace(/^命令退出码\s+\d+\n/, "")) === finalText;
}

function formatTranscriptFullAnswer(renderItems: TranscriptRenderItem[], resultText: string, originalResultText = resultText) {
  const blocks: string[] = [];
  const finalText = normalizedCopyText(resultText);
  const originalText = normalizedCopyText(originalResultText);
  for (const item of renderItems) {
    if (item.kind === "entry") {
      if (isDuplicateFinalProcess(item.entry, originalText) || isDuplicateFinalError(item.entry, originalText)) {
        continue;
      }
      const text = formatTranscriptEntryForCopy(item.entry);
      if (text) {
        blocks.push(text);
      }
      continue;
    }
    const groupEntries = item.entries
      .filter((entry) => !isDuplicateFinalProcess(entry, originalText) && !isDuplicateFinalError(entry, originalText))
      .map(formatTranscriptEntryForCopy)
      .filter(Boolean)
      .join("\n\n");
    if (groupEntries) {
      if (item.kind === "group") {
        blocks.push(`[过程 ${item.groupIndex}]\n${groupEntries}`);
      } else {
        const attempts = retryAttempts(item);
        const retryLabel = attempts.size > 1
          ? `连续重试（${attempts.size} 次）`
          : `重试 ${item.attempt > 0 ? item.attempt : item.retryGroupIndex}`;
        blocks.push(`[${retryLabel}]\n${groupEntries}`);
      }
    }
  }
  if (finalText) {
    blocks.push(`[最终回答]\n${finalText}`);
  }
  return blocks.join("\n\n");
}

function filterDuplicateFinalProcessItems(renderItems: TranscriptRenderItem[], resultText: string): TranscriptRenderItem[] {
  const finalText = normalizedCopyText(resultText);
  if (!finalText) {
    return renderItems;
  }
  const filtered: TranscriptRenderItem[] = [];
  for (const item of renderItems) {
    if (item.kind === "entry") {
      if (!isDuplicateFinalProcess(item.entry, finalText)) {
        filtered.push(item);
      }
      continue;
    }
    const entries = item.entries.filter((entry) => !isDuplicateFinalProcess(entry, finalText));
    if (entries.length > 0) {
      filtered.push({ ...item, entries });
    }
  }
  return filtered;
}

function filterDuplicateFinalErrorItems(renderItems: TranscriptRenderItem[], resultText: string): TranscriptRenderItem[] {
  const finalText = normalizedDisplayText(resultText);
  if (!finalText) {
    return renderItems;
  }
  const filtered: TranscriptRenderItem[] = [];
  for (const item of renderItems) {
    if (item.kind === "entry") {
      if (!isDuplicateFinalError(item.entry, finalText)) {
        filtered.push(item);
      }
      continue;
    }
    const entries = item.entries.filter((entry) => !isDuplicateFinalError(entry, finalText));
    if (entries.length > 0) {
      filtered.push({ ...item, entries });
    }
  }
  return filtered;
}

const TranscriptEntryRow = memo(function TranscriptEntryRow({
  entry,
  nested = false,

  onFileLinkClick,
}: {
  entry: CliTranscriptEntry;
  nested?: boolean;

  onFileLinkClick?: (href: string) => void;
}) {
  const rowClassName = nested ? "py-1" : "border-t border-[var(--workbench-hairline)] py-1";
  if (
    entry.kind === "process"
    || entry.kind === "error"
    || entry.kind === "cancelled"
    || entry.kind === "endless_error"
    || entry.kind === "endless_continue"
  ) {
    const summary = stripThinkingBlocks(compact(entry.summary, entry.label));
    if (!summary) {
      return null;
    }
    return (
      <div data-transcript-entry-id={entry.id} className={rowClassName}>
        {shouldRenderEntrySummaryAsMarkdown(entry) ? (
          <ChatMarkdownMessage content={summary} onFileLinkClick={onFileLinkClick} />
        ) : (
          <div className={entry.kind === "error" || entry.kind === "endless_error"
            ? "whitespace-pre-wrap break-words text-[var(--feedback-error-text-deep)]"
            : entry.kind === "endless_continue"
              ? "whitespace-pre-wrap break-words text-[var(--status-success)]"
              : "whitespace-pre-wrap break-words text-[var(--text)]"}>
            {summary}
          </div>
        )}
      </div>
    );
  }

  return <ToolTranscriptEntryRow entry={entry} rowClassName={rowClassName} />;
});

const ToolTranscriptEntryRow = memo(function ToolTranscriptEntryRow({
  entry,
  rowClassName,
}: {
  entry: CliTranscriptEntry;
  rowClassName: string;
}) {
  const [expanded, setExpanded] = useState(!entry.collapsedByDefault);
  return (
    <details
      className={rowClassName}
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary
        data-chat-scroll-lock-on-expand="true"
        className="cursor-pointer truncate text-[var(--muted)] marker:text-[var(--muted)]"
      >
        <span className="font-medium text-[var(--text)]">{entry.label}</span>
        {entry.summary ? <span className="ml-2">{entry.summary}</span> : null}
      </summary>
      {expanded ? <EntryBody entry={entry} /> : null}
    </details>
  );
});

const TranscriptGroupRow = memo(function TranscriptGroupRow({
  item,

  onFileLinkClick,
}: {
  item: Extract<TranscriptRenderItem, { kind: "group" }>;

  onFileLinkClick?: (href: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const renderGroupEntry = useCallback((entry: CliTranscriptEntry) => (
    <TranscriptEntryRow
      entry={entry}
      nested

      onFileLinkClick={onFileLinkClick}
    />
  ), [onFileLinkClick,  ]);
  return (
    <details
      data-testid="cli-event-group"
      className="group border-t border-[var(--workbench-hairline)] py-1"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary
        data-chat-scroll-lock-on-expand="true"
        className="flex cursor-pointer list-none items-center gap-2 py-1 text-[var(--muted)] marker:hidden [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted)] transition-transform group-open:rotate-90" aria-hidden="true" />
        <span className="shrink-0 text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--accent)]">过程 {item.groupIndex}</span>
        <span className="min-w-0 truncate text-[11px] text-[var(--muted)]">{describeTranscriptGroup(item.entries)}</span>
      </summary>
      {expanded ? (
        <div className="border-l-2 border-[var(--accent-outline)] pl-3">
          <div className="divide-y divide-[var(--workbench-hairline)]">
            {item.entries.map((entry) => (
              <div key={entry.id}>{renderGroupEntry(entry)}</div>
            ))}
          </div>
        </div>
      ) : null}
    </details>
  );
});

const RetryGroupRow = memo(function RetryGroupRow({
  item,

  onFileLinkClick,
}: {
  item: Extract<TranscriptRenderItem, { kind: "retry" }>;

  onFileLinkClick?: (href: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const renderRetryEntry = useCallback((entry: CliTranscriptEntry) => (
    <TranscriptEntryRow
      entry={entry}
      nested

      onFileLinkClick={onFileLinkClick}
    />
  ), [onFileLinkClick,  ]);
  return (
    <details
      data-testid="cli-retry-group"
      className="group border-t border-[var(--workbench-hairline)] py-1"
      open={expanded}
    >
      <summary
        data-chat-scroll-lock-on-expand="true"
        className="flex cursor-pointer list-none items-center gap-2 py-1 text-[var(--muted)] marker:hidden [&::-webkit-details-marker]:hidden"
        onClick={(event) => {
          event.preventDefault();
          setExpanded((value) => !value);
        }}
      >
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted)] transition-transform group-open:rotate-90" aria-hidden="true" />
        <span className="shrink-0 text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--accent)]">
          {retryAttempts(item).size > 1 ? "连续重试" : `重试记录 ${item.attempt > 0 ? item.attempt : item.retryGroupIndex}`}
        </span>
        <span className="min-w-0 truncate text-[11px] text-[var(--muted)]">{describeRetryGroup(item)}</span>
      </summary>
      {expanded ? (
        <div className="border-l-2 border-[var(--accent-outline)] pl-3">
          <div className="divide-y divide-[var(--workbench-hairline)]">
            {item.entries.map((entry) => (
              <div key={entry.id}>{renderRetryEntry(entry)}</div>
            ))}
          </div>
        </div>
      ) : null}
    </details>
  );
});

export function CliTranscript({
  entries,
  resultText,
  originalResultText = resultText,
  translationControl,
  state,
  traceCount,
  toolCallCount,
  processCount,
  traceLoaded,
  isTraceLoading = false,
  traceLoadError = "",
  onLoadTrace,

  onFileLinkClick,
  onCopyFinalAnswer,
  onContinue,
  onFastForward,
  onToggleFavorite,
  favorite = false,
  canContinue = false,
  contextUsage,
  endlessContinueCount,
  endlessActive = false,
  endlessRetryAtMs,
  mobileLayout = false,
}: Props) {

  const [traceExpanded, setTraceExpanded] = useState(false);
  const collapseProcess = mobileLayout || endlessActive;
  const totalTraceCount = typeof traceCount === "number" ? traceCount : entries.length;
  const hasCompleteTrace = totalTraceCount <= 0
    || traceLoaded === true
    || (typeof traceLoaded === "undefined" && entries.length >= totalTraceCount);
  const shouldLazyLoadTrace = totalTraceCount > 0 && !hasCompleteTrace;
  const traceToolCount = toolCallCount ?? entries.filter((entry) => entry.kind === "tool").length;

  useEffect(() => {
    if (!shouldLazyLoadTrace || !traceExpanded || isTraceLoading || traceLoadError || !onLoadTrace) {
      return;
    }
    onLoadTrace();
  }, [isTraceLoading, onLoadTrace, shouldLazyLoadTrace, totalTraceCount, traceExpanded, traceLoadError]);

  const renderItems = useMemo(() => groupTranscriptEntries(entries), [entries]);
  const shouldFilterDuplicateFinal = state !== "streaming" && Boolean(normalizedDisplayText(originalResultText));
  const displayRenderItems = useMemo(() => (
    shouldFilterDuplicateFinal
      ? filterDuplicateFinalErrorItems(filterDuplicateFinalProcessItems(renderItems, originalResultText), originalResultText)
      : renderItems
  ), [renderItems, originalResultText, shouldFilterDuplicateFinal]);
  const visibleProcessCount = countProcessEntries(displayRenderItems);
  const traceSummaryProcessCount = hasCompleteTrace || typeof processCount !== "number"
    ? visibleProcessCount
    : processCount;
  const endlessRetryCount = countEndlessRetries(entries);
  const traceSummaryLabel = [
    traceSummaryProcessCount > 0
      ? `${traceSummaryProcessCount} 条过程${traceToolCount > 0 ? ` · ${traceToolCount} 次工具` : ""}`
      : "",
    endlessRetryCount > 0 ? `${endlessRetryCount} 次重试` : "",
  ].filter(Boolean).join(" · ");
  const alwaysVisibleRenderItems = useMemo(() => (
    collapseProcess
      ? displayRenderItems.filter((item) => (
          item.kind === "entry"
          && (endlessActive ? [] : ["error", "cancelled"]).includes(item.entry.kind)
        ))
      : []
  ), [displayRenderItems, collapseProcess, endlessActive]);
  const traceDetailRenderItems = useMemo(() => (
    collapseProcess
      ? displayRenderItems.filter((item) => !(
          item.kind === "entry"
          && (endlessActive ? [] : ["error", "cancelled"]).includes(item.entry.kind)
        ))
      : displayRenderItems
  ), [displayRenderItems, collapseProcess, endlessActive]);
  const hasEndlessDetails = entries.some((entry) => (
    entry.kind === "endless_error" || entry.kind === "endless_continue"
  ));
  const endlessStreaming = state === "streaming" && (endlessActive || hasEndlessDetails);
  const shouldShowTraceDisclosure = shouldLazyLoadTrace
    || hasEndlessDetails
    || (collapseProcess && traceDetailRenderItems.length > 0);

  const renderTranscriptItem = useCallback((item: TranscriptRenderItem) => (
    item.kind === "entry" ? (
      <TranscriptEntryRow
        entry={item.entry}

        onFileLinkClick={onFileLinkClick}
      />
    ) : item.kind === "group" ? (
      <TranscriptGroupRow
        item={item}

        onFileLinkClick={onFileLinkClick}
      />
    ) : (
      <RetryGroupRow
        item={item}

        onFileLinkClick={onFileLinkClick}
      />
    )
  ), [ onFileLinkClick,  ]);

  const renderTranscriptItems = (items: TranscriptRenderItem[]) => (
    items.map((item) => (
      <div key={item.kind === "entry"
        ? item.entry.id
        : item.kind === "group"
          ? `group-${item.groupIndex}-${item.entries[0]?.id || "empty"}`
          : `retry-${item.retryGroupIndex}-${item.entries[0]?.id || "empty"}`}>
        {renderTranscriptItem(item)}
      </div>
    ))
  );

  const visibleResultText = stripThinkingBlocks(resultText);
  const latestProgress = [...entries].reverse().find((entry) => (
    ["process", "tool", "event"].includes(entry.kind) && stripThinkingBlocks(entry.summary).trim()
  ));
  const progressPreview = stripThinkingBlocks(latestProgress?.summary || visibleResultText).trim();
  const progressStatus = entries.some((entry) => false)
    ? "等待授权"
    : latestProgress?.kind === "tool" ? `执行工具：${latestProgress.label}` : "执行中";
  const showFinalResult = state !== "streaming" && Boolean(visibleResultText);
  const showCopyFinalAnswer = state !== "streaming" && Boolean(visibleResultText.trim()) && Boolean(onCopyFinalAnswer);
  const showFinalActions = state !== "streaming" && (
    showCopyFinalAnswer
    || Boolean(contextUsage)
    || typeof endlessContinueCount === "number"
    || (canContinue && Boolean(onContinue || onFastForward))
  );

  return (
    <div data-testid="cli-transcript" className="min-w-0 text-sm text-[var(--text)]">
      {mobileLayout && state === "streaming" ? (
        <div data-testid="cli-streaming-status" role="status" className="flex min-w-0 items-start gap-1.5 py-1 text-xs text-[var(--muted)]">
          {endlessStreaming ? <EndlessTypingLabel retryAtMs={endlessRetryAtMs} /> : (
            <>
              <LoaderCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-[var(--accent)]" />
              <div className="min-w-0">
                <div className="truncate font-medium">{progressStatus}</div>
                {!traceExpanded && progressPreview ? <p className="line-clamp-2 break-words">{progressPreview}</p> : null}
              </div>
            </>
          )}
        </div>
      ) : null}
      {shouldShowTraceDisclosure ? (
        <section data-testid="cli-trace-summary" className={`border-b border-[var(--workbench-hairline)] ${mobileLayout ? "pb-1" : "pb-2"}`}>
          <button
            type="button"
            data-chat-scroll-lock-on-expand="true"
            aria-label={`${traceExpanded ? "收起" : "展开"}过程详情`}
            aria-expanded={traceExpanded}
            onClick={() => setTraceExpanded((value) => !value)}
            className={`flex w-full min-w-0 items-center gap-2 text-left text-[var(--muted)] ${mobileLayout ? "py-0.5" : "py-1"}`}
          >
            <ChevronRight className={`h-3.5 w-3.5 shrink-0 transition-transform ${traceExpanded ? "rotate-90" : ""}`} />
            <span className="min-w-0 truncate text-xs font-medium text-[var(--text)]">过程详情</span>
            <span className="min-w-0 truncate text-[11px] text-[var(--muted)]">{traceSummaryLabel}</span>
          </button>
          {traceExpanded && traceDetailRenderItems.length > 0
            ? renderTranscriptItems(traceDetailRenderItems)
            : null}
          {traceExpanded && isTraceLoading ? (
            <div className="flex items-center gap-2 py-2 text-xs text-[var(--muted)]">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              <span>正在加载过程详情...</span>
            </div>
          ) : null}
          {traceExpanded && !isTraceLoading && traceLoadError ? (
            <div className="py-2 text-xs text-[var(--feedback-error-text-deep)]">
              <div>{traceLoadError}</div>
              {onLoadTrace ? (
                <button
                  type="button"
                  onClick={onLoadTrace}
                  className="mt-2 inline-flex rounded-md border border-[var(--feedback-error-border-light)] px-2 py-1 text-xs text-[var(--feedback-error-text-deep)] hover:bg-[var(--feedback-error-background-subtle)]"
                >
                  重试
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : renderTranscriptItems(traceDetailRenderItems)}
      {alwaysVisibleRenderItems.length > 0 ? renderTranscriptItems(alwaysVisibleRenderItems) : null}

      {showFinalResult || showFinalActions ? (
        <div data-testid="cli-final-result" className="chat-final-answer-compact border-t border-[var(--workbench-hairline)] pt-2">
          {showFinalResult && (state === "done" ? (
            <ChatMarkdownMessage content={visibleResultText} onFileLinkClick={onFileLinkClick} />
          ) : (
            <ChatPlainTextMessage content={visibleResultText} className={state === "error" ? "text-[var(--feedback-error-text-deep)]" : "text-[var(--text)]"} />
          ))}
          {showFinalActions ? (
            <ChatFinalAnswerActions
              translationControl={translationControl}
              canContinue={canContinue}
              contextUsage={contextUsage}
              endlessContinueCount={endlessContinueCount}
              favorite={favorite}
              buildFullAnswerText={showCopyFinalAnswer ? () => formatTranscriptFullAnswer(renderItems, resultText, originalResultText) : undefined}
              onContinue={onContinue}
              onFastForward={onFastForward}
              onCopyFinalAnswer={onCopyFinalAnswer}
              onToggleFavorite={onToggleFavorite}
            />
          ) : null}
        </div>
      ) : null}
      {!mobileLayout && state === "streaming" ? (
        <div
          data-testid="cli-streaming-status"
          role="status"
          className="flex items-center gap-2 border-t border-[var(--workbench-hairline)] py-2 text-sm text-[var(--muted)]"
        >
          {endlessStreaming ? <EndlessTypingLabel retryAtMs={endlessRetryAtMs} /> : (
            <>
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--accent)]" />
              <span>正在输出...</span>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
