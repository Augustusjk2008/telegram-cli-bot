import { memo, useCallback, useMemo, useState } from "react";
import { Check, ChevronRight, LoaderCircle, X } from "lucide-react";
import { ChatMarkdownMessage } from "./ChatMarkdownMessage";
import { ChatPlainTextMessage } from "./ChatPlainTextMessage";
import type { ChatMessage, ChatMessageContextUsage } from "../services/types";
import type { AgUiPermissionRequest, NativeAgentPermissionReply, NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";
import { ChatFinalAnswerActions } from "./ChatFinalAnswerActions";
import { DynamicVirtualList } from "./virtual/DynamicVirtualList";

type Props = {
  entries: NativeAgentTranscriptEntry[];
  resultText: string;
  state?: ChatMessage["state"];
  mode?: "native" | "cli";
  onReplyPermission?: (reply: NativeAgentPermissionReply) => Promise<void>;
  onFileLinkClick?: (href: string) => void;
  onCopyFinalAnswer?: () => boolean | void | Promise<boolean | void>;
  onContinue?: () => void;
  onToggleFavorite?: () => void;
  favorite?: boolean;
  canContinue?: boolean;
  contextUsage?: ChatMessageContextUsage;
};

function compact(value: string, fallback: string) {
  const text = value.trim();
  return text || fallback;
}

function EntryBody({ entry }: { entry: NativeAgentTranscriptEntry }) {
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

function shouldRenderEntrySummaryAsMarkdown(entry: NativeAgentTranscriptEntry) {
  return entry.kind === "process" && entry.trace?.kind === "commentary";
}

function stripThinkingBlocks(value: string) {
  return value
    .replace(/<thinking\b[^>]*>[\s\S]*?<\/thinking>/gi, "")
    .replace(/<thinking\b[^>]*>[\s\S]*$/gi, "")
    .replace(/<\/thinking>/gi, "")
    .trim();
}

function stringValue(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function permissionKind(permission?: AgUiPermissionRequest) {
  return stringValue(permission?.uiKind).trim().toLowerCase() || "confirm";
}

function permissionOptions(permission?: AgUiPermissionRequest) {
  return (permission?.options || []).map((option) => {
    if (typeof option === "string" || typeof option === "number" || typeof option === "boolean") {
      const value = String(option);
      return { label: value, value };
    }
    if (option && typeof option === "object") {
      const record = option as Record<string, unknown>;
      const value = stringValue(record.value || record.id || record.label || record.name);
      const label = stringValue(record.label || record.name || record.title || record.value || record.id) || value;
      return { label, value };
    }
    return { label: "", value: "" };
  }).filter((option) => option.value || option.label);
}

function PermissionEntry({
  entry,
  rowClassName,
  replyingPermissionId,
  onReply,
}: {
  entry: NativeAgentTranscriptEntry;
  rowClassName: string;
  replyingPermissionId: string;
  onReply?: (reply: NativeAgentPermissionReply) => Promise<void>;
}) {
  const permission = entry.permission;
  const permissionId = entry.permissionId || permission?.permissionId || "";
  const pending = Boolean(entry.pending && permissionId);
  const kind = permissionKind(permission);
  const options = permissionOptions(permission);
  const initialValue = stringValue(permission?.defaultValue) || stringValue(permission?.value) || options[0]?.value || "";
  const [value, setValue] = useState(initialValue);
  const disabled = Boolean(replyingPermissionId) || !pending;
  const submit = (accepted: boolean, nextValue?: unknown) => {
    if (!onReply || !permissionId || disabled) {
      return;
    }
    void onReply({
      requestId: permissionId,
      accepted,
      ...(typeof nextValue !== "undefined" ? { value: nextValue } : {}),
    });
  };

  return (
    <div key={entry.id} data-testid="native-agent-permission" className={rowClassName}>
      <div className="whitespace-pre-wrap break-words text-[var(--text)]">{compact(entry.summary, "权限请求")}</div>
      {pending && onReply ? (
        kind === "select" || kind === "input" || kind === "editor" ? (
          <div className="mt-2 flex flex-col gap-2">
            {kind === "select" ? (
              <select
                aria-label="权限选项"
                value={value}
                disabled={disabled}
                onChange={(event) => setValue(event.target.value)}
                className="h-8 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 text-xs text-[var(--text)] disabled:opacity-60"
              >
                {options.map((option) => (
                  <option key={option.value || option.label} value={option.value}>{option.label || option.value}</option>
                ))}
              </select>
            ) : kind === "editor" ? (
              <textarea
                aria-label="权限输入"
                value={value}
                disabled={disabled}
                placeholder={permission?.placeholder}
                onChange={(event) => setValue(event.target.value)}
                className="min-h-24 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 py-1.5 text-xs text-[var(--text)] disabled:opacity-60"
              />
            ) : (
              <input
                aria-label="权限输入"
                value={value}
                disabled={disabled}
                placeholder={permission?.placeholder}
                onChange={(event) => setValue(event.target.value)}
                className="h-8 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 text-xs text-[var(--text)] disabled:opacity-60"
              />
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={disabled}
                onClick={() => submit(true, value)}
                className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--accent-outline)] px-2 text-xs text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Check className="h-3.5 w-3.5" />
                提交
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => submit(false)}
                className="inline-flex h-7 items-center gap-1 rounded-md border border-red-200 px-2 text-xs text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <X className="h-3.5 w-3.5" />
                取消
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-1 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={disabled}
              onClick={() => submit(true)}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--accent-outline)] px-2 text-xs text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Check className="h-3.5 w-3.5" />
              允许一次
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => submit(false)}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-red-200 px-2 text-xs text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <X className="h-3.5 w-3.5" />
              拒绝
            </button>
          </div>
        )
      ) : null}
    </div>
  );
}

type TranscriptRenderItem =
  | { kind: "entry"; entry: NativeAgentTranscriptEntry }
  | { kind: "group"; groupIndex: number; entries: NativeAgentTranscriptEntry[] };

const LARGE_TRANSCRIPT_GROUP_THRESHOLD = 100;

function cutsTranscriptGroup(entry: NativeAgentTranscriptEntry) {
  return (
    entry.trace?.kind === "commentary"
    || ["permission", "error", "cancelled"].includes(entry.kind)
  );
}

function isToolResultEntry(entry: NativeAgentTranscriptEntry) {
  return entry.trace?.kind === "tool_result" || entry.label === "工具结果";
}

function shouldWrapTranscriptGroup(entries: NativeAgentTranscriptEntry[]) {
  if (entries.length <= 1) {
    return false;
  }
  return entries.some((entry) => entry.kind === "tool" || isToolResultEntry(entry));
}

function groupTranscriptEntries(entries: NativeAgentTranscriptEntry[]): TranscriptRenderItem[] {
  const grouped: TranscriptRenderItem[] = [];
  let current: NativeAgentTranscriptEntry[] = [];
  let groupIndex = 0;

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

  for (const entry of entries) {
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

function describeTranscriptGroup(entries: NativeAgentTranscriptEntry[]) {
  const toolCount = entries.filter((entry) => entry.kind === "tool").length;
  return `${entries.length} 条事件${toolCount > 0 ? ` · ${toolCount} 次工具` : ""}`;
}

function entryCopyLabel(entry: NativeAgentTranscriptEntry) {
  if (entry.kind === "process") return entry.trace?.kind === "reasoning" ? "思考" : "过程";
  if (entry.kind === "tool") return `工具: ${entry.label}`;
  if (entry.kind === "permission") return "权限";
  if (entry.kind === "error") return "错误";
  if (entry.kind === "cancelled") return "已取消";
  return entry.label || "事件";
}

function formatTranscriptEntryForCopy(entry: NativeAgentTranscriptEntry) {
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

function isDuplicateFinalProcess(entry: NativeAgentTranscriptEntry, finalText: string) {
  if (entry.kind !== "process" || !finalText) {
    return false;
  }
  const kind = String(entry.trace?.kind || "").trim();
  if (kind && kind !== "commentary" && kind !== "reasoning") {
    return false;
  }
  return normalizedCopyText(entry.summary || "") === finalText;
}

function isDuplicateFinalError(entry: NativeAgentTranscriptEntry, finalText: string) {
  if (entry.kind !== "error" || !finalText) {
    return false;
  }
  const summary = normalizedDisplayText(entry.summary || "");
  if (summary === finalText) {
    return true;
  }
  return /^命令退出码\s+\d+\n/.test(summary) && normalizedDisplayText(summary.replace(/^命令退出码\s+\d+\n/, "")) === finalText;
}

function formatTranscriptFullAnswer(renderItems: TranscriptRenderItem[], resultText: string) {
  const blocks: string[] = [];
  const finalText = normalizedCopyText(resultText);
  for (const item of renderItems) {
    if (item.kind === "entry") {
      if (isDuplicateFinalProcess(item.entry, finalText) || isDuplicateFinalError(item.entry, finalText)) {
        continue;
      }
      const text = formatTranscriptEntryForCopy(item.entry);
      if (text) {
        blocks.push(text);
      }
      continue;
    }
    const groupEntries = item.entries
      .filter((entry) => !isDuplicateFinalProcess(entry, finalText) && !isDuplicateFinalError(entry, finalText))
      .map(formatTranscriptEntryForCopy)
      .filter(Boolean)
      .join("\n\n");
    if (groupEntries) {
      blocks.push(`[过程 ${item.groupIndex}]\n${groupEntries}`);
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
  replyingPermissionId,
  onReplyPermission,
  onFileLinkClick,
}: {
  entry: NativeAgentTranscriptEntry;
  nested?: boolean;
  replyingPermissionId: string;
  onReplyPermission?: (reply: NativeAgentPermissionReply) => Promise<void>;
  onFileLinkClick?: (href: string) => void;
}) {
  const rowClassName = nested ? "py-1" : "border-t border-[var(--workbench-hairline)] py-1";
  if (entry.kind === "process" || entry.kind === "error" || entry.kind === "cancelled") {
    const summary = stripThinkingBlocks(compact(entry.summary, entry.label));
    if (!summary) {
      return null;
    }
    return (
      <div data-transcript-entry-id={entry.id} className={rowClassName}>
        {shouldRenderEntrySummaryAsMarkdown(entry) ? (
          <ChatMarkdownMessage content={summary} onFileLinkClick={onFileLinkClick} />
        ) : (
          <div className={entry.kind === "error" ? "whitespace-pre-wrap break-words text-red-700" : "whitespace-pre-wrap break-words text-[var(--text)]"}>
            {summary}
          </div>
        )}
      </div>
    );
  }
  if (entry.kind === "permission") {
    return (
      <PermissionEntry
        entry={entry}
        rowClassName={rowClassName}
        replyingPermissionId={replyingPermissionId}
        onReply={onReplyPermission}
      />
    );
  }
  return (
    <details className={rowClassName} open={!entry.collapsedByDefault}>
      <summary className="cursor-pointer truncate text-[var(--muted)] marker:text-[var(--muted)]">
        <span className="font-medium text-[var(--text)]">{entry.label}</span>
        {entry.summary ? <span className="ml-2">{entry.summary}</span> : null}
      </summary>
      <EntryBody entry={entry} />
    </details>
  );
});

const TranscriptGroupRow = memo(function TranscriptGroupRow({
  item,
  replyingPermissionId,
  onReplyPermission,
  onFileLinkClick,
}: {
  item: Extract<TranscriptRenderItem, { kind: "group" }>;
  replyingPermissionId: string;
  onReplyPermission?: (reply: NativeAgentPermissionReply) => Promise<void>;
  onFileLinkClick?: (href: string) => void;
}) {
  const deferContents = item.entries.length > LARGE_TRANSCRIPT_GROUP_THRESHOLD;
  const [expanded, setExpanded] = useState(false);
  const renderGroupEntry = useCallback((entry: NativeAgentTranscriptEntry) => (
    <TranscriptEntryRow
      entry={entry}
      nested
      replyingPermissionId={replyingPermissionId}
      onReplyPermission={onReplyPermission}
      onFileLinkClick={onFileLinkClick}
    />
  ), [onFileLinkClick, onReplyPermission, replyingPermissionId]);
  return (
    <details
      data-testid="native-agent-event-group"
      className="group border-t border-[var(--workbench-hairline)] py-1"
      onToggle={deferContents ? (event) => setExpanded(event.currentTarget.open) : undefined}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 py-1 text-[var(--muted)] marker:hidden [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted)] transition-transform group-open:rotate-90" aria-hidden="true" />
        <span className="shrink-0 text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--accent)]">过程 {item.groupIndex}</span>
        <span className="min-w-0 truncate text-[11px] text-[var(--muted)]">{describeTranscriptGroup(item.entries)}</span>
      </summary>
      {!deferContents || expanded ? (
        <div className="border-l-2 border-[var(--accent-outline)] pl-3">
          {deferContents ? (
            <DynamicVirtualList
              items={item.entries}
              getKey={(entry) => entry.id}
              renderItem={renderGroupEntry}
              estimateHeight={56}
              overscan={3}
              dataTestId="virtualized-native-agent-group"
              className="max-h-[50vh] min-h-[240px] overflow-auto"
            />
          ) : (
            <div className="divide-y divide-[var(--workbench-hairline)]">
              {item.entries.map((entry) => (
                <div key={entry.id}>{renderGroupEntry(entry)}</div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </details>
  );
});

export function NativeAgentTranscript({
  entries,
  resultText,
  state,
  mode = "native",
  onReplyPermission,
  onFileLinkClick,
  onCopyFinalAnswer,
  onContinue,
  onToggleFavorite,
  favorite = false,
  canContinue = false,
  contextUsage,
}: Props) {
  const [replyingPermissionId, setReplyingPermissionId] = useState("");
  const renderItems = useMemo(() => groupTranscriptEntries(entries), [entries]);
  const shouldFilterDuplicateFinal = state !== "streaming" && Boolean(normalizedDisplayText(resultText));
  const displayRenderItems = useMemo(() => (
    shouldFilterDuplicateFinal
      ? filterDuplicateFinalErrorItems(filterDuplicateFinalProcessItems(renderItems, resultText), resultText)
      : renderItems
  ), [renderItems, resultText, shouldFilterDuplicateFinal]);
  const allowPermissionReply = mode === "native";
  const fullAnswerText = useMemo(
    () => formatTranscriptFullAnswer(renderItems, resultText),
    [renderItems, resultText],
  );

  const replyPermission = useCallback(async (reply: NativeAgentPermissionReply) => {
    if (!onReplyPermission || !reply.requestId || replyingPermissionId) {
      return;
    }
    setReplyingPermissionId(reply.requestId);
    try {
      await onReplyPermission(reply);
    } finally {
      setReplyingPermissionId("");
    }
  }, [onReplyPermission, replyingPermissionId]);

  const renderTranscriptItem = useCallback((item: TranscriptRenderItem) => (
    item.kind === "entry" ? (
      <TranscriptEntryRow
        entry={item.entry}
        replyingPermissionId={replyingPermissionId}
        onReplyPermission={allowPermissionReply ? replyPermission : undefined}
        onFileLinkClick={onFileLinkClick}
      />
    ) : (
      <TranscriptGroupRow
        item={item}
        replyingPermissionId={replyingPermissionId}
        onReplyPermission={allowPermissionReply ? replyPermission : undefined}
        onFileLinkClick={onFileLinkClick}
      />
    )
  ), [allowPermissionReply, onFileLinkClick, replyPermission, replyingPermissionId]);

  const visibleResultText = stripThinkingBlocks(resultText);
  const showFinalResult = Boolean(visibleResultText) && !(mode === "cli" && state === "streaming");
  const showCopyFinalAnswer = state !== "streaming" && Boolean(visibleResultText.trim()) && Boolean(onCopyFinalAnswer);

  return (
    <div data-testid="native-agent-transcript" className="min-w-0 text-sm text-[var(--text)]">
      {displayRenderItems.length > 100 ? (
        <DynamicVirtualList
          items={displayRenderItems}
          getKey={(item) => item.kind === "entry"
            ? item.entry.id
            : `group-${item.groupIndex}-${item.entries[0]?.id || "empty"}`}
          renderItem={renderTranscriptItem}
          estimateHeight={72}
          overscan={1}
          dataTestId="virtualized-native-agent-transcript"
          className="max-h-[60vh] min-h-[240px] overflow-auto"
        />
      ) : displayRenderItems.map((item) => (
        <div key={item.kind === "entry" ? item.entry.id : `group-${item.groupIndex}-${item.entries[0]?.id || "empty"}`}>
          {renderTranscriptItem(item)}
        </div>
      ))}

      {showFinalResult ? (
        <div data-testid="native-agent-final-result" className="border-t border-[var(--workbench-hairline)] pt-2">
          {state === "done" ? (
            <ChatMarkdownMessage content={visibleResultText} onFileLinkClick={onFileLinkClick} />
          ) : (
            <ChatPlainTextMessage content={visibleResultText} className={state === "error" ? "text-red-700" : "text-[var(--text)]"} />
          )}
          {showCopyFinalAnswer ? (
            <ChatFinalAnswerActions
              canContinue={canContinue}
              contextUsage={contextUsage}
              favorite={favorite}
              fullAnswerText={fullAnswerText}
              onContinue={onContinue}
              onCopyFinalAnswer={onCopyFinalAnswer}
              onToggleFavorite={onToggleFavorite}
            />
          ) : null}
        </div>
      ) : null}
      {state === "streaming" ? (
        <div
          data-testid="native-agent-streaming-status"
          className="flex items-center gap-2 border-t border-[var(--workbench-hairline)] py-2 text-sm text-[var(--muted)]"
        >
          <LoaderCircle className="h-4 w-4 animate-spin text-[var(--accent)]" />
          <span>正在输出...</span>
        </div>
      ) : null}
    </div>
  );
}
