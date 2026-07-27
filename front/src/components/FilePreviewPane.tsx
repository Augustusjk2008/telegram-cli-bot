import { BookOpenText, Download, Pencil, X } from "lucide-react";
import type { FilePreviewKind } from "../services/types";
import { FilePreviewSurface } from "./FilePreviewSurface";

type Props = {
  title: string;
  content: string;
  mode: "preview" | "full";
  botAlias?: string;
  previewKind?: FilePreviewKind;
  contentType?: string;
  contentBase64?: string;
  loading?: boolean;
  statusText?: string;
  downloadProgressText?: string;
  downloadPercent?: number;
  onClose: () => void;
  onLoadFull?: () => void;
  onEdit?: () => void;
  onDownload?: () => void;
  onFileLinkClick?: (href: string) => void;
};

export function FilePreviewPane({
  title,
  content,
  mode,
  botAlias = "",
  previewKind,
  contentType,
  contentBase64,
  loading = false,
  statusText = "",
  downloadProgressText = "",
  downloadPercent,
  onClose,
  onLoadFull,
  onEdit,
  onDownload,
  onFileLinkClick,
}: Props) {
  const isDownloading = Boolean(downloadProgressText);

  return (
    <div
      data-testid="desktop-inline-file-preview"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--editor-bg)]"
    >
      <header className="editor-tab-strip flex h-[34px] shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--workbench-panel-elevated-bg)]">
        <div className="flex min-w-0 flex-1 items-center gap-2 px-3">
          <h2 className="truncate text-[13px] font-medium text-[var(--text)]" title={title}>{title}</h2>
          <span className="shrink-0 text-[10px] text-[var(--muted)]">预览</span>
        </div>
        <button
          type="button"
          aria-label={`关闭 ${title} 预览`}
          title="关闭预览"
          onClick={onClose}
          className="mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden p-3">
        <FilePreviewSurface
          title={title}
          result={{ content, mode: mode === "full" ? "cat" : "head", previewKind, contentType, contentBase64 }}
          loading={loading}
          botAlias={botAlias}
          desktop
          onFileLinkClick={onFileLinkClick}
        />
      </div>

      <footer className="flex min-h-10 shrink-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--workbench-hairline)] px-3 py-1.5">
        <div className="min-w-0 flex-1 truncate text-xs text-[var(--muted)]" role={statusText ? "status" : undefined}>
          {downloadProgressText || statusText}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {isDownloading ? (
            <div
              role="progressbar"
              aria-label={`${title} 下载进度`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={typeof downloadPercent === "number" ? downloadPercent : undefined}
              className="h-1.5 w-24 overflow-hidden rounded-full bg-[var(--surface-strong)]"
            >
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-[width]"
                style={{ width: `${typeof downloadPercent === "number" ? downloadPercent : 100}%` }}
              />
            </div>
          ) : null}
          {mode !== "full" && onLoadFull ? (
            <button
              type="button"
              onClick={onLoadFull}
              disabled={loading}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[var(--border)] px-2 text-xs text-[var(--text)] hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
            >
              <BookOpenText className="h-3.5 w-3.5" />
              {loading ? "读取中..." : "全文读取"}
            </button>
          ) : null}
          {onEdit ? (
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[var(--border)] px-2 text-xs text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
            >
              <Pencil className="h-3.5 w-3.5" />
              编辑
            </button>
          ) : null}
          {onDownload ? (
            <button
              type="button"
              onClick={onDownload}
              disabled={isDownloading}
              className="inline-flex h-7 items-center gap-1.5 rounded-md bg-[var(--accent)] px-2 text-xs text-[var(--accent-foreground)] disabled:opacity-60"
            >
              <Download className="h-3.5 w-3.5" />
              {isDownloading ? "下载中..." : "下载"}
            </button>
          ) : null}
        </div>
      </footer>
    </div>
  );
}
