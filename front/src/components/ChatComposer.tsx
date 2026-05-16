import { useMemo, useRef, useState } from "react";
import { LoaderCircle, Paperclip, X } from "lucide-react";
import type { AgentMention, AgentSummary } from "../services/types";

type ComposerAttachment = {
  id: string;
  filename: string;
  savedPath: string;
};

type Props = {
  onSend: (text: string, mentions?: AgentMention[]) => void;
  onAttachFiles: (files: File[]) => void;
  onRemoveAttachment: (attachmentId: string) => void;
  attachments: ComposerAttachment[];
  agents?: AgentSummary[];
  clusterMode?: boolean;
  disabled?: boolean;
  compact?: boolean;
  pulse?: boolean;
  uploadingAttachments?: boolean;
  placeholder?: string;
};

function collectMentions(text: string, agents: AgentSummary[] = []): AgentMention[] {
  const result: AgentMention[] = [];
  for (const agent of agents) {
    const needle = `@${agent.id}`;
    let index = text.indexOf(needle);
    while (index >= 0) {
      result.push({ agentId: agent.id, label: agent.name, start: index, end: index + needle.length });
      index = text.indexOf(needle, index + needle.length);
    }
  }
  return result;
}

type MentionQuery = {
  query: string;
  start: number;
  end: number;
};

function getMentionQuery(text: string, cursor: number): MentionQuery | null {
  const beforeCursor = text.slice(0, cursor);
  const match = beforeCursor.match(/(?:^|\s)@([a-z0-9_-]*)$/i);
  if (!match) {
    return null;
  }
  const atIndex = beforeCursor.lastIndexOf("@");
  return { query: match[1].toLowerCase(), start: atIndex, end: cursor };
}

export function ChatComposer({
  onSend,
  onAttachFiles,
  onRemoveAttachment,
  attachments,
  agents = [],
  clusterMode = false,
  disabled,
  compact = false,
  pulse = false,
  uploadingAttachments = false,
  placeholder = "输入消息",
}: Props) {
  const shellClassName = compact
    ? "chat-composer-delight border-t border-[var(--border)] bg-[var(--surface-strong)] px-2 py-2"
    : "chat-composer-delight border-t border-[var(--border)] bg-[var(--surface-strong)] px-3 py-3";
  const formClassName = compact ? "flex items-end gap-2" : "flex items-end gap-2";
  const inputDisabled = disabled || uploadingAttachments;
  const [message, setMessage] = useState("");
  const [mentionQuery, setMentionQuery] = useState<MentionQuery | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const clusterAgents = useMemo(
    () => agents.filter((agent) => agent.enabled && !agent.isMain),
    [agents],
  );
  const mentionOptions = useMemo(() => {
    if (!clusterMode || !mentionQuery) {
      return [];
    }
    return clusterAgents.filter((agent) => {
      const query = mentionQuery.query;
      return agent.id.toLowerCase().includes(query) || agent.name.toLowerCase().includes(query);
    }).slice(0, 8);
  }, [clusterAgents, clusterMode, mentionQuery]);

  function updateMessage(next: string, cursor: number) {
    setMessage(next);
    setMentionQuery(clusterMode ? getMentionQuery(next, cursor) : null);
  }

  function insertMention(agent: AgentSummary) {
    const token = `@${agent.id} `;
    const current = message;
    const range = mentionQuery;
    const needsPrefix = current.length > 0 && !/\s$/.test(current);
    const prefix = needsPrefix ? " " : "";
    const next = range
      ? `${current.slice(0, range.start)}${token}${current.slice(range.end)}`
      : `${current}${prefix}${token}`;
    setMessage(next);
    setMentionQuery(null);
    requestAnimationFrame(() => {
      const cursor = (range ? range.start : current.length + prefix.length) + token.length;
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(cursor, cursor);
    });
  }

  return (
    <div data-testid="chat-composer-root" data-pulse={pulse ? "true" : "false"} className={shellClassName}>
      {attachments.length > 0 || uploadingAttachments ? (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {attachments.map((attachment) => (
            <span
              key={attachment.id}
              title={attachment.savedPath}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-xs text-[var(--text)]"
            >
              <Paperclip className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" />
              <span className="truncate">{attachment.filename}</span>
              <button
                type="button"
                aria-label={`移除附件 ${attachment.filename}`}
                onClick={() => onRemoveAttachment(attachment.id)}
                disabled={inputDisabled}
                className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[var(--muted)] hover:bg-[var(--border)] disabled:opacity-50"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {uploadingAttachments ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-700">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              正在上传附件
            </span>
          ) : null}
        </div>
      ) : null}

      {clusterMode && clusterAgents.length > 0 ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium text-emerald-700">智能体集群</span>
          {clusterAgents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              aria-label={`@${agent.id} ${agent.name}`}
              onClick={() => insertMention(agent)}
              disabled={inputDisabled}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 text-[var(--text)] hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-60"
            >
              <span className="font-medium">@{agent.id}</span>
              <span className="truncate text-[var(--muted)]">{agent.name}</span>
            </button>
          ))}
        </div>
      ) : null}

      <form
        className={formClassName}
        onSubmit={(event) => {
          event.preventDefault();
          const text = message.trim();
          if (!text && attachments.length === 0) return;
          onSend(text, clusterMode ? collectMentions(text, agents) : []);
          setMessage("");
          setMentionQuery(null);
        }}
      >
        <label className="relative inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] hover:border-[var(--accent)] hover:text-[var(--accent)]">
          <Paperclip className="h-4 w-4" />
          <span className="sr-only">上传附件</span>
          <input
            aria-label="上传附件"
            data-testid="chat-attachment-input"
            type="file"
            multiple
            disabled={inputDisabled}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
            onChange={(event) => {
              const nextFiles = Array.from(event.currentTarget.files || []);
              if (nextFiles.length > 0) {
                onAttachFiles(nextFiles);
              }
              event.currentTarget.value = "";
            }}
          />
        </label>
        <div className="relative flex-1">
          <textarea
            ref={textareaRef}
            name="message"
            value={message}
            placeholder={placeholder}
            rows={1}
            disabled={inputDisabled}
            onChange={(event) => updateMessage(event.currentTarget.value, event.currentTarget.selectionStart)}
            onSelect={(event) => {
              const target = event.currentTarget;
              setMentionQuery(clusterMode ? getMentionQuery(target.value, target.selectionStart) : null);
            }}
            onKeyDown={(event) => {
              if (mentionOptions.length > 0 && (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey))) {
                event.preventDefault();
                insertMention(mentionOptions[0]);
                return;
              }
              if (event.key !== "Enter" || !event.shiftKey || event.nativeEvent.isComposing) {
                return;
              }
              event.preventDefault();
              const form = event.currentTarget.form;
              if (!form) {
                return;
              }
              if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
                return;
              }
              form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
            }}
            className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2 text-[var(--text)] focus:border-[var(--accent)] focus:outline-none disabled:opacity-60"
          />
          {mentionOptions.length > 0 ? (
            <div
              role="listbox"
              aria-label="智能体集群列表"
              className="absolute bottom-full left-0 z-30 mb-2 max-h-56 w-full overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]"
            >
              {mentionOptions.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  role="option"
                  aria-label={`@${agent.id} ${agent.name}`}
                  aria-selected={false}
                  onClick={() => insertMention(agent)}
                  className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  <span className="font-medium text-[var(--text)]">@{agent.id}</span>
                  <span className="truncate text-[var(--muted)]">{agent.name}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <button
          type="submit"
          disabled={inputDisabled}
          className={compact
            ? "px-3.5 py-2 bg-[var(--accent)] text-[var(--accent-foreground)] rounded-lg disabled:opacity-50"
            : "px-4 py-2 bg-[var(--accent)] text-[var(--accent-foreground)] rounded-lg disabled:opacity-50"}
        >
          {uploadingAttachments ? "上传中..." : "发送"}
        </button>
      </form>
    </div>
  );
}
