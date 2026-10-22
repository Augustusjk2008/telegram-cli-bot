import { isFilePreviewFullyLoaded, type HtmlPreviewHandle } from "../utils/filePreview";
import { BookOpenText } from "lucide-react";
import type { FileReadResult, RemoteWorkspace } from "../services/types";
import { FilePreviewSurface } from "./FilePreviewSurface";

type Props = {
  title: string;
  result: FileReadResult | null;
  htmlPreview?: HtmlPreviewHandle | null;
  botAlias?: string;
  remotePlatform?: RemoteWorkspace["platform"];
  loading?: boolean;
  statusText?: string;
  error?: string;
  onRetry?: () => void;
  onLoadFull?: () => void;
  onFileLinkClick?: (href: string) => void;
};

export function FilePreviewPane({
  title,
  result,
  htmlPreview,
  botAlias = "",
  remotePlatform,
  loading = false,
  statusText = "",
  error = "",
  onRetry,
  onLoadFull,
  onFileLinkClick,
}: Props) {
  return (
    <div
      data-testid="desktop-inline-file-preview"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--editor-bg)]"
    >
      <div className="min-h-0 flex-1 overflow-hidden p-3">
        <FilePreviewSurface
          title={title}
          result={result}
          htmlPreview={htmlPreview}
          loading={loading}
          error={error}
          onRetry={onRetry}
          botAlias={botAlias}
          remotePlatform={remotePlatform}
          desktop
          onFileLinkClick={onFileLinkClick}
        />
      </div>

      <footer className="flex min-h-10 shrink-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--workbench-hairline)] px-3 py-1.5">
        <div
          className={error ? "min-w-0 flex-1 truncate text-xs text-[var(--feedback-error-text-strong)]" : "min-w-0 flex-1 truncate text-xs text-[var(--muted)]"}
          role={statusText || error ? "status" : undefined}
        >
          {error || statusText}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {!htmlPreview && !isFilePreviewFullyLoaded(result) && onLoadFull ? (
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
        </div>
      </footer>
    </div>
  );
}
