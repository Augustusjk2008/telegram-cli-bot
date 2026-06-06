import { useState } from "react";
import { Check, X } from "lucide-react";
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

export function NativeAgentTranscript({
  entries,
  resultText,
  state,
  onReplyPermission,
  onFileLinkClick,
}: Props) {
  const [replyingPermissionId, setReplyingPermissionId] = useState("");

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

  return (
    <div data-testid="native-agent-transcript" className="min-w-0 text-sm text-[var(--text)]">
      {entries.map((entry) => {
        if (entry.kind === "process" || entry.kind === "error" || entry.kind === "cancelled") {
          return (
            <div key={entry.id} className="border-t border-[var(--workbench-hairline)] py-1">
              <div className={entry.kind === "error" ? "whitespace-pre-wrap break-words text-red-700" : "whitespace-pre-wrap break-words text-[var(--text)]"}>
                {compact(entry.summary, entry.label)}
              </div>
            </div>
          );
        }

        if (entry.kind === "permission") {
          const pending = Boolean(entry.pending && entry.permissionId);
          return (
            <div key={entry.id} data-testid="native-agent-permission" className="border-t border-[var(--workbench-hairline)] py-1">
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
          <details key={entry.id} className="border-t border-[var(--workbench-hairline)] py-1" open={!entry.collapsedByDefault}>
            <summary className="cursor-pointer truncate text-[var(--muted)] marker:text-[var(--muted)]">
              <span className="font-medium text-[var(--text)]">{entry.label}</span>
              {entry.summary ? <span className="ml-2">{entry.summary}</span> : null}
            </summary>
            <EntryBody entry={entry} />
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
    </div>
  );
}
