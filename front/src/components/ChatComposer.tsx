import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, LoaderCircle, Paperclip, Plus, Send, Settings, Trash2, X } from "lucide-react";
import type { PromptPreset } from "../services/types";

export type ChatComposerModelOption = {
  value: string;
  label: string;
  title?: string;
};

type ComposerAttachment = {
  id: string;
  filename: string;
  savedPath: string;
};

type Props = {
  onSend: (text: string) => void;
  onAttachFiles: (files: File[]) => void;
  onRemoveAttachment: (attachmentId: string) => void;
  attachments: ComposerAttachment[];
  disabled?: boolean;
  compact?: boolean;
  enterToSend?: boolean;
  pulse?: boolean;
  uploadingAttachments?: boolean;
  placeholder?: string;
  modelOptions?: ChatComposerModelOption[];
  selectedModel?: string;
  modelDisabled?: boolean;
  onModelChange?: (model: string) => void;
  reasoningEffortOptions?: string[];
  selectedReasoningEffort?: string;
  reasoningEffortDisabled?: boolean;
  onReasoningEffortChange?: (effort: string) => void;
  globalPromptPresets?: PromptPreset[];
  botPromptPresets?: PromptPreset[];
  promptPresets?: PromptPreset[];
  canManagePromptPresets?: boolean;
  onSaveGlobalPromptPresets?: (presets: PromptPreset[]) => Promise<void> | void;
  onSaveBotPromptPresets?: (presets: PromptPreset[]) => Promise<void> | void;
  onSavePromptPresets?: (presets: PromptPreset[]) => Promise<void> | void;
};

type PresetScope = "global" | "bot";

function clonePromptPresetList(presets: PromptPreset[] = []) {
  return presets.map((preset) => ({ ...preset }));
}

export function ChatComposer({
  onSend,
  onAttachFiles,
  onRemoveAttachment,
  attachments,
  disabled,
  compact = false,
  enterToSend = true,
  pulse = false,
  uploadingAttachments = false,
  placeholder = "输入消息",
  modelOptions = [],
  selectedModel = "",
  modelDisabled = false,
  onModelChange,
  reasoningEffortOptions = [],
  selectedReasoningEffort = "",
  reasoningEffortDisabled = false,
  onReasoningEffortChange,
  globalPromptPresets,
  botPromptPresets,
  promptPresets = [],
  canManagePromptPresets = false,
  onSaveGlobalPromptPresets,
  onSaveBotPromptPresets,
  onSavePromptPresets,
}: Props) {
  const shellClassName = compact
    ? "chat-composer-delight border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-1.5"
    : "chat-composer-delight border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2";
  const formClassName = "relative";
  const inputBarClassName = "relative flex min-w-0 flex-col p-1 transition-colors focus-within:bg-[var(--workbench-hover-bg)]";
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const measureTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const presetIdCounterRef = useRef(1);
  const resolvedGlobalPromptPresets = globalPromptPresets ?? [];
  const resolvedBotPromptPresets = botPromptPresets ?? promptPresets;
  const resolvedSaveBotPromptPresets = onSaveBotPromptPresets ?? onSavePromptPresets;
  const draftPresets = draftPresetsByScope[editingPresetScope];
  const showAnyPromptPresets = resolvedGlobalPromptPresets.length > 0 || resolvedBotPromptPresets.length > 0;
  const editingPresetScopeLabel = editingPresetScope === "global" ? "全局" : "当前 Bot";
  const showPromptPresetControls = showAnyPromptPresets || canManagePromptPresets;
  const selectedModelOption = modelOptions.find((model) => model.value === selectedModel);
  const composerTextareaBaseClassName = "max-h-72 min-h-8 w-full resize-none border border-transparent bg-transparent px-1.5 py-1.5 leading-5 text-[var(--text)] outline-none placeholder:text-[var(--muted)] disabled:opacity-60";
  const inputTextareaClassName = composerTextareaBaseClassName;
  const measureTextareaClassName = `${composerTextareaBaseClassName} pointer-events-none absolute inset-0 h-auto overflow-hidden opacity-0`;
  const attachmentButtonClassName = "relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--accent)]";
  const actionGroupClassName = "ml-auto flex shrink-0 items-center gap-1";
  const actionButtonClassName = "inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50";
  const compactSelectClassName = "h-8 w-full appearance-none rounded-md border-0 bg-transparent py-0 pl-1.5 pr-4 text-xs font-medium text-[var(--text)] hover:bg-[var(--workbench-hover-bg)] focus:outline-none focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50";
  const presetMenuClassName = "absolute bottom-full right-10 z-40 mb-2 w-64 overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-1 shadow-[var(--shadow-card)]";

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
    const measureTextarea = measureTextareaRef.current;
    if (measureTextarea) {
      measureTextarea.style.height = "auto";
    }
    textarea.style.height = "auto";
    const measuredHeight = measureTextarea?.scrollHeight || textarea.scrollHeight;
    const nextHeight = Math.max(32, Math.min(measuredHeight, 288));
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = measuredHeight > 288 ? "auto" : "hidden";
  }, [inputDisabled, message]);

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
    setMessage(next);
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

  const presetEditorDialog = presetEditorOpen ? (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-[var(--overlay-backdrop-40)] px-4 py-6"
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        if (event.target === event.currentTarget && !presetSaving) {
          setPresetEditorOpen(false);
        }
      }}
    >
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
  ) : null;

  return (
    <div data-testid="chat-composer-root" data-pulse={pulse ? "true" : "false"} className={shellClassName}>
      {attachments.length > 0 || uploadingAttachments ? (
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 py-1.5">
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

      <form
        className={formClassName}
        onSubmit={(event) => {
          event.preventDefault();
          const text = message.trim();
          if (!text && attachments.length === 0) return;
          onSend(text);
          setMessage("");
        }}
      >
        <div data-testid="chat-composer-input-surface" className={inputBarClassName}>
          <div className="relative min-h-8 w-full min-w-0">
            <textarea
              ref={measureTextareaRef}
              aria-hidden="true"
              tabIndex={-1}
              readOnly
              value={message || " "}
              rows={1}
              className={measureTextareaClassName}
            />
            <textarea
              ref={textareaRef}
              name="message"
              value={message}
              placeholder={placeholder}
              rows={1}
              disabled={inputDisabled}
              onChange={(event) => setMessage(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) {
                  return;
                }
                if (event.key !== "Enter" || event.shiftKey || !enterToSend) {
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
              className={inputTextareaClassName}
            />
          </div>
          <div data-testid="chat-composer-toolbar" className="flex min-w-0 items-center gap-0.5">
            <label
              className={attachmentButtonClassName}
              title="上传附件"
            >
              <Plus className="h-4 w-4" />
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
            {modelOptions.length > 0 ? (
              <div className="relative min-w-[4.25rem] max-w-[8.5rem] flex-[0_1_8.5rem]">
                <select
                  aria-label="模型"
                  title={selectedModelOption?.title || selectedModelOption?.label || "模型"}
                  value={selectedModel}
                  disabled={inputDisabled || modelDisabled || !onModelChange}
                  onChange={(event) => onModelChange?.(event.target.value)}
                  className={compactSelectClassName}
                >
                  {modelOptions.map((model) => (
                    <option key={model.value} value={model.value} title={model.title}>
                      {model.label}
                    </option>
                  ))}
                </select>
                <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-0.5 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--muted)]" />
              </div>
            ) : null}
            {reasoningEffortOptions.length > 0 ? (
              <div className="relative min-w-[3.75rem] max-w-[6.5rem] flex-[0_1_6.5rem]">
                <select
                  aria-label="思考深度"
                  title={selectedReasoningEffort || "思考深度"}
                  value={selectedReasoningEffort}
                  disabled={inputDisabled || reasoningEffortDisabled || !onReasoningEffortChange}
                  onChange={(event) => onReasoningEffortChange?.(event.target.value)}
                  className={compactSelectClassName}
                >
                  {reasoningEffortOptions.map((effort) => (
                    <option key={effort} value={effort}>{effort}</option>
                  ))}
                </select>
                <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-0.5 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--muted)]" />
              </div>
            ) : null}
            <div className={actionGroupClassName}>
              {showPromptPresetControls ? (
                <button
                  type="button"
                  aria-label="打开提示词预设"
                  aria-expanded={presetMenuOpen}
                  title="提示词预设"
                  disabled={inputDisabled}
                  onClick={() => setPresetMenuOpen((value) => !value)}
                  className={actionButtonClassName}
                >
                  <ChevronDown className="h-4 w-4" />
                </button>
              ) : null}
              <button
                type="submit"
                aria-label="发送"
                title={uploadingAttachments ? "上传中..." : "发送"}
                disabled={inputDisabled}
                className={actionButtonClassName}
              >
                {uploadingAttachments ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>
          {presetMenuOpen ? (
            <div
              role="listbox"
              aria-label="提示词预设"
              className={presetMenuClassName}
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
        </div>
      </form>
      {presetEditorDialog ? createPortal(presetEditorDialog, document.body) : null}
    </div>
  );
}
