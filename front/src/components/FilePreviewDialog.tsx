import { MarkdownPreview } from "./MarkdownPreview";

type Props = {
  title: string;
  content: string;
  mode: "preview" | "full";
  loading?: boolean;
  onClose: () => void;
  onLoadFull?: () => void;
  onDownload?: () => void;
  onFileLinkClick?: (href: string) => void;
};

export function FilePreviewDialog({
  title,
  content,
  mode,
  loading = false,
  onClose,
  onLoadFull,
  onDownload,
  onFileLinkClick,
}: Props) {
  const isMarkdownPreview = /\.(md|markdown)$/i.test(title);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="w-full max-w-3xl rounded-2xl bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="truncate text-lg font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-3 py-1"
          >
            关闭
          </button>
        </div>
        {isMarkdownPreview ? (
          <MarkdownPreview content={content} onFileLinkClick={onFileLinkClick} />
        ) : (
          <pre className="max-h-[50vh] overflow-auto rounded-xl bg-[var(--surface-strong)] p-4 text-sm whitespace-pre-wrap break-all">
            {content}
          </pre>
        )}
        <div className="mt-4 flex justify-end gap-2">
          {mode !== "full" && onLoadFull ? (
            <button
              type="button"
              onClick={onLoadFull}
              disabled={loading}
              className="rounded-lg border border-[var(--border)] px-4 py-2 hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              {loading ? "读取中..." : "全文读取"}
            </button>
          ) : null}
          {onDownload ? (
            <button
              type="button"
              onClick={onDownload}
              className="rounded-lg bg-[var(--accent)] px-4 py-2 text-white"
            >
              下载
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
