import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { MarkdownPreview } from "./MarkdownPreview";

type DesktopAnchorRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type Props = {
  title: string;
  content: string;
  mode: "preview" | "full";
  variant?: "mobile" | "desktop";
  desktopAnchorRect?: DesktopAnchorRect | null;
  loading?: boolean;
  statusText?: string;
  onClose: () => void;
  onLoadFull?: () => void;
  onEdit?: () => void;
  onDownload?: () => void;
  onFileLinkClick?: (href: string) => void;
};

const DESKTOP_DIALOG_MARGIN_PX = 12;
const MIN_DESKTOP_DIALOG_WIDTH_PX = 420;
const MIN_DESKTOP_DIALOG_HEIGHT_PX = 280;

function clamp(value: number, min: number, max: number) {
  if (min > max) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

export function FilePreviewDialog({
  title,
  content,
  mode,
  variant = "mobile",
  desktopAnchorRect = null,
  loading = false,
  statusText = "",
  onClose,
  onLoadFull,
  onEdit,
  onDownload,
  onFileLinkClick,
}: Props) {
  const isMarkdownPreview = /\.(md|markdown)$/i.test(title);
  const [desktopOffset, setDesktopOffset] = useState({ x: 0, y: 0 });
  const dragStateRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    startOffsetX: number;
    startOffsetY: number;
  } | null>(null);

  useEffect(() => {
    if (variant === "desktop") {
      setDesktopOffset({ x: 0, y: 0 });
    }
  }, [title, variant]);

  useEffect(() => {
    if (variant !== "desktop") {
      return undefined;
    }

    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState || event.pointerId !== dragState.pointerId) {
        return;
      }
      event.preventDefault();
      setDesktopOffset({
        x: dragState.startOffsetX + event.clientX - dragState.startX,
        y: dragState.startOffsetY + event.clientY - dragState.startY,
      });
    };

    const stopDragging = (event: PointerEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState || event.pointerId !== dragState.pointerId) {
        return;
      }
      dragStateRef.current = null;
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [variant]);

  const desktopFrame = useMemo(() => {
    if (variant !== "desktop") {
      return null;
    }

    const fallbackBounds = desktopAnchorRect || {
      left: DESKTOP_DIALOG_MARGIN_PX,
      top: DESKTOP_DIALOG_MARGIN_PX,
      width: typeof window === "undefined" ? 960 : window.innerWidth - DESKTOP_DIALOG_MARGIN_PX * 2,
      height: typeof window === "undefined" ? 720 : window.innerHeight - DESKTOP_DIALOG_MARGIN_PX * 2,
    };
    const viewportWidth = typeof window === "undefined" ? fallbackBounds.left + fallbackBounds.width : window.innerWidth;
    const viewportHeight = typeof window === "undefined" ? fallbackBounds.top + fallbackBounds.height : window.innerHeight;
    const width = clamp(
      viewportWidth - DESKTOP_DIALOG_MARGIN_PX * 2,
      MIN_DESKTOP_DIALOG_WIDTH_PX,
      Math.max(MIN_DESKTOP_DIALOG_WIDTH_PX, viewportWidth - DESKTOP_DIALOG_MARGIN_PX * 2),
    );
    const height = clamp(
      viewportHeight - DESKTOP_DIALOG_MARGIN_PX * 2,
      MIN_DESKTOP_DIALOG_HEIGHT_PX,
      Math.max(MIN_DESKTOP_DIALOG_HEIGHT_PX, viewportHeight - DESKTOP_DIALOG_MARGIN_PX * 2),
    );
    const rawLeft = DESKTOP_DIALOG_MARGIN_PX + desktopOffset.x;
    const rawTop = DESKTOP_DIALOG_MARGIN_PX + desktopOffset.y;
    const maxLeft = viewportWidth - width - DESKTOP_DIALOG_MARGIN_PX;
    const maxTop = viewportHeight - height - DESKTOP_DIALOG_MARGIN_PX;

    return {
      left: clamp(rawLeft, DESKTOP_DIALOG_MARGIN_PX, maxLeft),
      top: clamp(rawTop, DESKTOP_DIALOG_MARGIN_PX, maxTop),
      width,
      height,
    };
  }, [desktopAnchorRect, desktopOffset.x, desktopOffset.y, variant]);

  function handleDesktopDragStart(event: ReactPointerEvent<HTMLDivElement>) {
    if (variant !== "desktop" || event.button !== 0) {
      return;
    }
    if (event.target instanceof Element && event.target.closest("button")) {
      return;
    }

    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startOffsetX: desktopOffset.x,
      startOffsetY: desktopOffset.y,
    };
    event.preventDefault();
  }

  if (variant === "desktop" && desktopFrame) {
    return (
      <div
        data-testid="desktop-workbench-preview"
        className="fixed inset-0 z-50 bg-black/35 pointer-events-none"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div
          data-testid="desktop-workbench-preview-window"
          className="pointer-events-auto fixed flex min-h-0 flex-col overflow-hidden rounded-2xl border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-card)]"
          style={{
            left: `${desktopFrame.left}px`,
            top: `${desktopFrame.top}px`,
            width: `${desktopFrame.width}px`,
            height: `${desktopFrame.height}px`,
          }}
        >
          <div
            data-testid="desktop-preview-drag-handle"
            onPointerDown={handleDesktopDragStart}
            className="flex cursor-move items-center justify-between gap-4 border-b border-[var(--workbench-hairline)] px-5 py-4 touch-none select-none"
          >
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold text-[var(--text)]">{title}</h2>
              <p className="mt-1 text-xs text-[var(--muted)]">桌面预览默认最大化显示</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[var(--border)] px-3 py-1 text-sm hover:bg-[var(--surface-strong)]"
            >
              关闭
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden px-5 py-4">
            {isMarkdownPreview ? (
              <MarkdownPreview content={content} variant="desktop-preview" onFileLinkClick={onFileLinkClick} />
            ) : (
              <pre className="h-full overflow-auto rounded-xl bg-[var(--surface-strong)] p-4 text-sm whitespace-pre-wrap break-all">
                {content}
              </pre>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-[var(--workbench-hairline)] px-5 py-4">
            <div className="min-h-[1.25rem] text-sm text-[var(--muted)]">
              {statusText}
            </div>
            <div className="flex justify-end gap-2">
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
              {onEdit ? (
                <button
                  type="button"
                  onClick={onEdit}
                  className="rounded-lg border border-[var(--border)] px-4 py-2 hover:bg-[var(--surface-strong)]"
                >
                  在编辑器中打开
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
      </div>
    );
  }

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
        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="min-h-[1.25rem] text-sm text-[var(--muted)]">
            {statusText}
          </div>
          <div className="flex justify-end gap-2">
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
            {onEdit ? (
              <button
                type="button"
                onClick={onEdit}
                className="rounded-lg border border-[var(--border)] px-4 py-2 hover:bg-[var(--surface-strong)]"
              >
                在编辑器中打开
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
    </div>
  );
}
