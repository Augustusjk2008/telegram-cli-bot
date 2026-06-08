import { useState } from "react";
import { Check, LoaderCircle, X } from "lucide-react";
import { ChatMarkdownMessage } from "./ChatMarkdownMessage";
import { ChatPlainTextMessage } from "./ChatPlainTextMessage";
import type { ChatMessage } from "../services/types";
import type { NativeAgentTranscriptEntry } from "../utils/agUiRunReducer";

type Props = {
  entries: NativeAgentTranscriptEntry[];
  resultText: string;
  state?: ChatMessage["state"];
  onReplyPermission?: (permissionId: string, approved: boolean) => Promise<void>;
  onFileLinkClick?: (href: string) => void;
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

type TranscriptRenderItem =
  | { kind: "entry"; entry: NativeAgentTranscriptEntry }
  | { kind: "group"; groupIndex: number; entries: NativeAgentTranscriptEntry[] };

function startsTranscriptGroup(entry: NativeAgentTranscriptEntry) {
  return entry.kind === "process";
}

function cutsTranscriptGroup(entry: NativeAgentTranscriptEntry) {
  return ["permission", "error", "cancelled"].includes(entry.kind);
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
    if (startsTranscriptGroup(entry) && current.length > 0) {
      flushCurrent();
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

export function NativeAgentTranscript({
  entries,
  resultText,
  state,
  onReplyPermission,
  onFileLinkClick,
}: Props) {
  const [replyingPermissionId, setReplyingPermissionId] = useState("");
  const renderItems = groupTranscriptEntries(entries);

  const replyPermission = async (permissionId: string, approved: boolean) => {
    if (!onReplyPermission || !permissionId || replyingPermissionId) {
      return;
    }
    setReplyingPermissionId(permissionId);
    try {
      await onReplyPermission(permissionId, approved);
    } finally {
      setReplyingPermissionId("");
    }
  };

  const renderEntry = (entry: NativeAgentTranscriptEntry, nested = false) => {
    const rowClassName = nested
      ? "py-1"
      : "border-t border-[var(--workbench-hairline)] py-1";

    if (entry.kind === "process" || entry.kind === "error" || entry.kind === "cancelled") {
      return (
        <div key={entry.id} className={rowClassName}>
          <div className={entry.kind === "error" ? "whitespace-pre-wrap break-words text-red-700" : "whitespace-pre-wrap break-words text-[var(--text)]"}>
            {compact(entry.summary, entry.label)}
          </div>
        </div>
      );
    }

    if (entry.kind === "permission") {
      const pending = Boolean(entry.pending && entry.permissionId);
      return (
        <div key={entry.id} data-testid="native-agent-permission" className={rowClassName}>
          <div className="whitespace-pre-wrap break-words text-[var(--text)]">{compact(entry.summary, "权限请求")}</div>
          {pending && onReplyPermission ? (
            <div className="mt-1 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={Boolean(replyingPermissionId)}
                onClick={() => void replyPermission(entry.permissionId || "", true)}
                className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--accent-outline)] px-2 text-xs text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <Check className="h-3.5 w-3.5" />
                允许一次
              </button>
              <button
                type="button"
                disabled={Boolean(replyingPermissionId)}
                onClick={() => void replyPermission(entry.permissionId || "", false)}
                className="inline-flex h-7 items-center gap-1 rounded-md border border-red-200 px-2 text-xs text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <X className="h-3.5 w-3.5" />
                拒绝
              </button>
            </div>
          ) : null}
        </div>
      );
    }

    return (
      <details key={entry.id} className={rowClassName} open={!entry.collapsedByDefault}>
        <summary className="cursor-pointer truncate text-[var(--muted)] marker:text-[var(--muted)]">
          <span className="font-medium text-[var(--text)]">{entry.label}</span>
          {entry.summary ? <span className="ml-2">{entry.summary}</span> : null}
        </summary>
        <EntryBody entry={entry} />
      </details>
    );
  };

  return (
    <div data-testid="native-agent-transcript" className="min-w-0 text-sm text-[var(--text)]">
      {renderItems.map((item) => {
        if (item.kind === "entry") {
          return renderEntry(item.entry);
        }
        return (
          <details
            key={`native-agent-event-group-${item.groupIndex}-${item.entries[0]?.id || "empty"}`}
            data-testid="native-agent-event-group"
            className="border-t border-[var(--workbench-hairline)] py-1"
          >
            <summary className="cursor-pointer marker:text-[var(--muted)]">
              <span className="inline-flex w-full flex-wrap items-center justify-between gap-2 py-1">
                <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--accent)]">
                  阶段 {item.groupIndex}
                </span>
                <span className="rounded-md border border-[var(--workbench-hairline)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
                  {describeTranscriptGroup(item.entries)}
                </span>
              </span>
            </summary>
            <div className="border-l-2 border-[var(--accent-outline)] pl-3">
              <div className="divide-y divide-[var(--workbench-hairline)]">
                {item.entries.map((entry) => renderEntry(entry, true))}
              </div>
            </div>
          </details>
        );
      })}

      {resultText.trim() ? (
        <div data-testid="native-agent-final-result" className="border-t border-[var(--workbench-hairline)] pt-2">
          {state === "done" ? (
            <ChatMarkdownMessage content={resultText} onFileLinkClick={onFileLinkClick} />
          ) : (
            <ChatPlainTextMessage content={resultText} className={state === "error" ? "text-red-700" : "text-[var(--text)]"} />
          )}
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
