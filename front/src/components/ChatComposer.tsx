import { LoaderCircle, Paperclip, X } from "lucide-react";

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
  uploadingAttachments?: boolean;
};

export function ChatComposer({
  onSend,
  onAttachFiles,
  onRemoveAttachment,
  attachments,
  disabled,
  compact = false,
  uploadingAttachments = false,
}: Props) {
  const shellClassName = compact
    ? "border-t border-[var(--border)] bg-[var(--surface-strong)] px-2 py-2"
    : "border-t border-[var(--border)] bg-[var(--surface-strong)] px-3 py-3";
  const formClassName = compact ? "flex items-end gap-2" : "flex items-end gap-2";
  const inputDisabled = disabled || uploadingAttachments;

  return (
    <div className={shellClassName}>
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

      <form
        className={formClassName}
        onSubmit={(event) => {
          event.preventDefault();
          const formData = new FormData(event.currentTarget);
          const text = String(formData.get("message") || "").trim();
          if (!text && attachments.length === 0) return;
          onSend(text);
          event.currentTarget.reset();
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
        <textarea
          name="message"
          placeholder="输入消息"
          rows={1}
          disabled={inputDisabled}
          onKeyDown={(event) => {
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
          className="flex-1 resize-none rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2 text-[var(--text)] focus:border-[var(--accent)] focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={inputDisabled}
          className={compact
            ? "px-3.5 py-2 bg-[var(--accent)] text-white rounded-lg disabled:opacity-50"
            : "px-4 py-2 bg-[var(--accent)] text-white rounded-lg disabled:opacity-50"}
        >
          {uploadingAttachments ? "上传中..." : "发送"}
        </button>
      </form>
    </div>
  );
}
