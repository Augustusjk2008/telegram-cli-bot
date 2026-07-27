import { BookOpenText } from "lucide-react";
import type { FileReadResult } from "../services/types";
import { FilePreviewSurface } from "./FilePreviewSurface";

type Props = {
  title: string;
  result: FileReadResult | null;
  botAlias?: string;
  loading?: boolean;
  statusText?: string;
  error?: string;
  onLoadFull?: () => void;
  onFileLinkClick?: (href: string) => void;
};

export function FilePreviewPane({
  title,
  result,
  botAlias = "",
  loading = false,
  statusText = "",
  error = "",
  onLoadFull,
  onFileLinkClick,
}: Props) {
  return (
    <div
      data-testid="desktop-inline-file-preview"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--editor-bg)]"
    >
      <div className="min-h-0 flex-1 overflow-hidden p-3">
        {error && !result ? (
          <div className="flex h-full items-center justify-center px-6 text-sm text-red-600">{error}</div>
        ) : (
          <FilePreviewSurface
            title={title}
            result={result}
            loading={loading}
            botAlias={botAlias}
            desktop
            onFileLinkClick={onFileLinkClick}
          />
        )}
      </div>

      <footer className="flex min-h-10 shrink-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--workbench-hairline)] px-3 py-1.5">
        <div
          className={error ? "min-w-0 flex-1 truncate text-xs text-red-600" : "min-w-0 flex-1 truncate text-xs text-[var(--muted)]"}
          role={statusText || error ? "status" : undefined}
        >
          {error || statusText}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {result?.mode !== "cat" && onLoadFull ? (
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
