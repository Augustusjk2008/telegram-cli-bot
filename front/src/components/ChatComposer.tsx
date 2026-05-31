import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, LoaderCircle, Paperclip, Plus, Settings, Trash2, X } from "lucide-react";
import { toolbarButtonClass } from "./ToolbarButton";
import type { AgentMention, AgentSummary, PromptPreset } from "../services/types";

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
  globalPromptPresets?: PromptPreset[];
  botPromptPresets?: PromptPreset[];
  promptPresets?: PromptPreset[];
  canManagePromptPresets?: boolean;
  onSaveGlobalPromptPresets?: (presets: PromptPreset[]) => Promise<void> | void;
  onSaveBotPromptPresets?: (presets: PromptPreset[]) => Promise<void> | void;
  onSavePromptPresets?: (presets: PromptPreset[]) => Promise<void> | void;
};

type PresetScope = "global" | "bot";

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

function clonePromptPresetList(presets: PromptPreset[] = []) {
  return presets.map((preset) => ({ ...preset }));
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
  globalPromptPresets,
  botPromptPresets,
  promptPresets = [],
  canManagePromptPresets = false,
  onSaveGlobalPromptPresets,
  onSaveBotPromptPresets,
  onSavePromptPresets,
}: Props) {
  const shellClassName = compact
    ? "chat-composer-delight border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-2"
    : "chat-composer-delight border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-3";
  const formClassName = compact
    ? "flex items-end gap-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-2 shadow-[var(--shadow-soft)]"
    : "flex items-end gap-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-2 shadow-[var(--shadow-soft)]";
  const inputDisabled = disabled || uploadingAttachments;
  const [message, setMessage] = useState("");
  const [presetMenuOpen, setPresetMenuOpen] = useState(false);
  const [presetEditorOpen, setPresetEditorOpen] = useState(false);
  const [editingPresetScope, setEditingPresetScope] = useState<PresetScope>("bot");
  const [draftPresetsByScope, setDraftPresetsByScope] = useState<Record<PresetScope, PromptPreset[]>>({
    global: [],
    bot: [],
  });
  const [presetSaving, setPresetSaving] = useState(false);
  const [presetError, setPresetError] = useState("");
  const [mentionQuery, setMentionQuery] = useState<MentionQuery | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const presetIdCounterRef = useRef(1);
  const resolvedGlobalPromptPresets = globalPromptPresets ?? [];
  const resolvedBotPromptPresets = botPromptPresets ?? promptPresets;
  const resolvedSaveBotPromptPresets = onSaveBotPromptPresets ?? onSavePromptPresets;
  const draftPresets = draftPresetsByScope[editingPresetScope];
  const showAnyPromptPresets = resolvedGlobalPromptPresets.length > 0 || resolvedBotPromptPresets.length > 0;
  const editingPresetScopeLabel = editingPresetScope === "global" ? "全局" : "当前 Bot";
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
  const showPromptPresetControls = showAnyPromptPresets || canManagePromptPresets;

  function updateMessage(next: string, cursor: number) {
    setMessage(next);
    setMentionQuery(clusterMode ? getMentionQuery(next, cursor) : null);
  }

  useEffect(() => {
    if (inputDisabled) {
      setPresetMenuOpen(false);
    }
  }, [inputDisabled]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, 288);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 288 ? "auto" : "hidden";
  }, [message, inputDisabled]);

  function focusTextarea(cursor: number) {
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(cursor, cursor);
    });
  }

  function insertTextAtCursor(content: string) {
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? message.length;
    const end = textarea?.selectionEnd ?? start;
    const next = `${message.slice(0, start)}${content}${message.slice(end)}`;
    const cursor = start + content.length;
    updateMessage(next, cursor);
    setPresetMenuOpen(false);
    focusTextarea(cursor);
  }

  function openPresetEditor(scope: PresetScope = "bot") {
    setEditingPresetScope(scope);
    setDraftPresetsByScope({
      global: clonePromptPresetList(resolvedGlobalPromptPresets),
      bot: clonePromptPresetList(resolvedBotPromptPresets),
    });
    setPresetError("");
    setPresetMenuOpen(false);
    setPresetEditorOpen(true);
  }

  function updateDraftPreset(index: number, patch: Partial<PromptPreset>) {
    setDraftPresetsByScope((current) => ({
      ...current,
      [editingPresetScope]: current[editingPresetScope].map((preset, itemIndex) => (
        itemIndex === index ? { ...preset, ...patch } : preset
      )),
    }));
  }

  function addDraftPreset() {
    const id = `preset-${Date.now().toString(36)}-${presetIdCounterRef.current}`;
    presetIdCounterRef.current += 1;
    setDraftPresetsByScope((current) => {
      if (current[editingPresetScope].length >= 50) {
        return current;
      }
      return {
        ...current,
        [editingPresetScope]: [...current[editingPresetScope], { id, title: "", content: "" }],
      };
    });
  }

  function removeDraftPreset(index: number) {
    setDraftPresetsByScope((current) => ({
      ...current,
      [editingPresetScope]: current[editingPresetScope].filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  async function saveDraftPresets() {
    const normalized = draftPresets.map((preset) => ({
      id: preset.id.trim() || `preset-${Date.now().toString(36)}`,
      title: preset.title.trim(),
      content: preset.content,
    }));
    if (normalized.some((preset) => !preset.title || !preset.content.trim())) {
      setPresetError("标题和内容不能为空");
      return;
    }
    setPresetSaving(true);
    setPresetError("");
    try {
      if (editingPresetScope === "global") {
        await onSaveGlobalPromptPresets?.(normalized);
      } else {
        await resolvedSaveBotPromptPresets?.(normalized);
      }
      setPresetEditorOpen(false);
    } catch (err) {
      setPresetError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setPresetSaving(false);
    }
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
    focusTextarea((range ? range.start : current.length + prefix.length) + token.length);
  }

  function renderPresetSection(title: string, presets: PromptPreset[]) {
    if (presets.length === 0) {
      return null;
    }
    return (
      <div>
        <div className="px-3 py-2 text-xs font-medium text-[var(--muted)]">{title}</div>
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            role="option"
            aria-selected={false}
            title={preset.content}
            onClick={() => insertTextAtCursor(preset.content)}
            className="block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
          >
            <span className="block truncate font-medium text-[var(--text)]">{preset.title}</span>
            <span className="mt-0.5 block truncate text-xs text-[var(--muted)]">{preset.content}</span>
          </button>
        ))}
      </div>
    );
  }

  return (
    <div data-testid="chat-composer-root" data-pulse={pulse ? "true" : "false"} className={shellClassName}>
      {attachments.length > 0 || uploadingAttachments ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 py-2">
          {attachments.map((attachment) => (
            <span
              key={attachment.id}
              title={attachment.savedPath}
              className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2.5 py-1 text-xs text-[var(--text)]"
            >
              <Paperclip className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" />
              <span className="truncate">{attachment.filename}</span>
              <button
                type="button"
                aria-label={`移除附件 ${attachment.filename}`}
                onClick={() => onRemoveAttachment(attachment.id)}
                disabled={inputDisabled}
                className="inline-flex h-4 w-4 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] disabled:opacity-50"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {uploadingAttachments ? (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-700">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
              正在上传附件
            </span>
          ) : null}
        </div>
      ) : null}

      {clusterMode && clusterAgents.length > 0 ? (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2 py-2 text-xs">
          <span className="font-medium text-[var(--accent)]">智能体集群</span>
          {clusterAgents.map((agent) => (
            <button
              key={agent.id}
              type="button"
              aria-label={`@${agent.id} ${agent.name}`}
              onClick={() => insertMention(agent)}
              disabled={inputDisabled}
              className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface)] px-2.5 py-1 text-[var(--text)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
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
        <label className="relative inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--accent)]">
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
            className={`max-h-72 w-full resize-none rounded-md border border-transparent bg-transparent p-2 ${showPromptPresetControls ? "pr-11" : ""} text-[var(--text)] outline-none placeholder:text-[var(--muted)] focus:border-[var(--workbench-hover-border)] focus:bg-[var(--workbench-panel-elevated-bg)] disabled:opacity-60`}
          />
          {showPromptPresetControls ? (
            <button
              type="button"
              aria-label="打开提示词预设"
              aria-expanded={presetMenuOpen}
              title="提示词预设"
              disabled={inputDisabled}
              onClick={() => setPresetMenuOpen((value) => !value)}
              className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--accent)] disabled:opacity-50"
            >
              <ChevronDown className="h-4 w-4" />
            </button>
          ) : null}
          {presetMenuOpen ? (
            <div
              role="listbox"
              aria-label="提示词预设"
              className="absolute bottom-full right-0 z-40 mb-2 w-64 overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-1 shadow-[var(--shadow-card)]"
            >
              {showAnyPromptPresets ? (
                <div className="max-h-64 overflow-y-auto">
                  {renderPresetSection("全局预设", resolvedGlobalPromptPresets)}
                  {resolvedGlobalPromptPresets.length > 0 && resolvedBotPromptPresets.length > 0 ? (
                    <div className="mx-2 my-1 border-t border-[var(--border)]" />
                  ) : null}
                  {renderPresetSection("当前 Bot", resolvedBotPromptPresets)}
                </div>
              ) : (
                <div className="px-3 py-2 text-sm text-[var(--muted)]">暂无预设</div>
              )}
              {canManagePromptPresets ? (
                <button
                  type="button"
                  onClick={() => openPresetEditor("bot")}
                  className="mt-1 flex w-full items-center gap-2 rounded-md border-t border-[var(--border)] px-3 py-2 text-left text-sm text-[var(--text)] hover:bg-[var(--surface-strong)]"
                >
                  <Settings className="h-4 w-4 text-[var(--muted)]" />
                  配置预设
                </button>
              ) : null}
            </div>
          ) : null}
          {mentionOptions.length > 0 ? (
            <div
              role="listbox"
              aria-label="智能体集群列表"
              className="absolute bottom-full left-0 z-30 mb-2 max-h-56 w-full overflow-y-auto rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-1 shadow-[var(--shadow-card)]"
            >
              {mentionOptions.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  role="option"
                  aria-label={`@${agent.id} ${agent.name}`}
                  aria-selected={false}
                  onClick={() => insertMention(agent)}
                  className="flex w-full items-center gap-2 rounded-md border border-transparent px-3 py-2 text-left text-sm hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]"
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
          className={toolbarButtonClass("primary", "md", compact ? "h-10 px-3.5" : "h-10 px-4")}
        >
          {uploadingAttachments ? "上传中..." : "发送"}
        </button>
      </form>
      {presetEditorOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4 py-6">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="配置提示词预设"
            className="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-card)]"
          >
            <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">提示词预设</h2>
                <p className="mt-0.5 text-xs text-[var(--muted)]">{editingPresetScopeLabel} · {draftPresets.length}/50</p>
                <div className="mt-2 inline-flex rounded-lg border border-[var(--border)] bg-[var(--surface-strong)] p-1">
                  <button
                    type="button"
                    onClick={() => setEditingPresetScope("global")}
                    disabled={presetSaving}
                    className={editingPresetScope === "global"
                      ? "rounded-md bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)] shadow-sm"
                      : "rounded-md px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)]"}
                  >
                    全局
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingPresetScope("bot")}
                    disabled={presetSaving}
                    className={editingPresetScope === "bot"
                      ? "rounded-md bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)] shadow-sm"
                      : "rounded-md px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)]"}
                  >
                    当前 Bot
                  </button>
                </div>
              </div>
              <button
                type="button"
                aria-label="关闭提示词预设配置"
                onClick={() => setPresetEditorOpen(false)}
                disabled={presetSaving}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)] disabled:opacity-50"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
              {draftPresets.length === 0 ? (
                <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-8 text-center text-sm text-[var(--muted)]">
                  暂无预设
                </div>
              ) : null}
              {draftPresets.map((preset, index) => (
                <div key={preset.id || index} className="rounded-lg border border-[var(--border)] bg-[var(--surface-strong)] p-3">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1 space-y-2">
                      <label className="block text-sm font-medium text-[var(--text)]">
                        {`预设标题 ${index + 1}`}
                        <input
                          value={preset.title}
                          maxLength={80}
                          onChange={(event) => updateDraftPreset(index, { title: event.currentTarget.value })}
                          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-normal text-[var(--text)] focus:border-[var(--accent)] focus:outline-none"
                        />
                      </label>
                      <label className="block text-sm font-medium text-[var(--text)]">
                        {`预设内容 ${index + 1}`}
                        <textarea
                          value={preset.content}
                          maxLength={12000}
                          rows={4}
                          onChange={(event) => updateDraftPreset(index, { content: event.currentTarget.value })}
                          className="mt-1 max-h-56 w-full resize-y rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-normal text-[var(--text)] focus:border-[var(--accent)] focus:outline-none"
                        />
                      </label>
                    </div>
                    <button
                      type="button"
                      aria-label={`删除预设 ${preset.title || index + 1}`}
                      onClick={() => removeDraftPreset(index)}
                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
            {presetError ? (
              <div className="border-t border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700">{presetError}</div>
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] px-4 py-3">
              <button
                type="button"
                onClick={addDraftPreset}
                disabled={presetSaving || draftPresets.length >= 50}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
                新增预设
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPresetEditorOpen(false)}
                  disabled={presetSaving}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-50"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => void saveDraftPresets()}
                  disabled={presetSaving}
                  className="rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-[var(--accent-foreground)] disabled:opacity-50"
                >
                  {presetSaving ? "保存中..." : "保存预设"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
