import { useEffect, useRef, useState } from "react";
import { Download, FileText, Folder, MoreHorizontal, Pencil, SquarePen, Trash2 } from "lucide-react";
import { toolbarButtonClass } from "./ToolbarButton";
import { FileEntry } from "../services/types";

type Props = {
  files: FileEntry[];
  onDirClick: (name: string) => void;
  onFileClick: (name: string) => void;
  onEdit?: (file: FileEntry) => void;
  onRename?: (file: FileEntry) => void;
  onDownload?: (file: FileEntry) => void;
  onDelete?: (file: FileEntry) => void;
  allowDelete?: boolean;
};

export function FileList({ files, onDirClick, onFileClick, onEdit, onRename, onDownload, onDelete, allowDelete = true }: Props) {
  const [openActionsFor, setOpenActionsFor] = useState<string | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);

  useEffect(() => {
    if (!openActionsFor) {
      return;
    }

    const closeOnPointerDown = (event: PointerEvent) => {
      if (!listRef.current?.contains(event.target as Node)) {
        setOpenActionsFor(null);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenActionsFor(null);
      }
    };

    window.addEventListener("pointerdown", closeOnPointerDown);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnPointerDown);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [openActionsFor]);

  if (files.length === 0) {
    return <div className="text-center text-[var(--muted)] py-8">目录为空</div>;
  }

  return (
    <ul ref={listRef} className="divide-y divide-[var(--workbench-hairline)] rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-surface)]">
      {files.map((file) => {
        const actionsOpen = openActionsFor === file.name;
        const canEdit = !file.isDir && Boolean(onEdit);
        const canRename = Boolean(onRename);
        const canDownload = !file.isDir && Boolean(onDownload);
        const canDelete = allowDelete && Boolean(onDelete);
        const hasActions = canEdit || canRename || canDownload || canDelete;

        return <li key={file.name} className={`relative flex items-center gap-1 p-1 ${actionsOpen ? "z-20" : ""}`}>
          <button
            type="button"
            aria-label={`${file.isDir ? "进入" : "打开"} ${file.name}`}
            onClick={() => file.isDir ? onDirClick(file.name) : onFileClick(file.name)}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-[var(--workbench-hover-bg)] active:bg-[var(--workbench-active-bg)]"
          >
            {file.isDir ? (
              <Folder className="h-4 w-4 shrink-0 text-blue-500" />
            ) : (
              <FileText className="h-4 w-4 shrink-0 text-gray-500" />
            )}
            <div className="min-w-0 flex-1 truncate">
              <span className="font-medium">{file.name}</span>
              {!file.isDir && file.size !== undefined && (
                <span className="ml-1.5 text-[11px] text-[var(--muted)]">
                  {(file.size / 1024).toFixed(1)} KB
                </span>
              )}
            </div>
            {file.updatedAt && (
              <span className="shrink-0 text-[11px] text-[var(--muted)]">
                {new Date(file.updatedAt).toLocaleDateString()}
              </span>
            )}
          </button>
          {hasActions ? (
            <div className="relative shrink-0">
              <button
                type="button"
                aria-label={`更多操作 ${file.name}`}
                title={`更多操作 ${file.name}`}
                aria-haspopup="menu"
                aria-expanded={actionsOpen}
                onClick={() => setOpenActionsFor((current) => current === file.name ? null : file.name)}
                className={toolbarButtonClass("plain", "icon", "h-7 w-7 text-[var(--accent)]")}
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
              {actionsOpen ? (
                <div
                  role="menu"
                  aria-label={`${file.name} 文件操作`}
                  className="absolute right-0 top-full z-30 mt-1 min-w-32 rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface-overlay)] p-1 shadow-[var(--shadow-card)]"
                >
                  {canEdit ? (
                    <button
                      type="button"
                      role="menuitem"
                      aria-label={`编辑 ${file.name}`}
                      onClick={() => {
                        setOpenActionsFor(null);
                        onEdit?.(file);
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
                    >
                      <SquarePen className="h-4 w-4 text-[var(--accent)]" />
                      编辑
                    </button>
                  ) : null}
                  {canRename ? (
                    <button
                      type="button"
                      role="menuitem"
                      aria-label={`重命名 ${file.name}`}
                      onClick={() => {
                        setOpenActionsFor(null);
                        onRename?.(file);
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
                    >
                      <Pencil className="h-4 w-4 text-[var(--accent)]" />
                      重命名
                    </button>
                  ) : null}
                  {canDownload ? (
                    <button
                      type="button"
                      role="menuitem"
                      aria-label={`下载 ${file.name}`}
                      onClick={() => {
                        setOpenActionsFor(null);
                        onDownload?.(file);
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
                    >
                      <Download className="h-4 w-4 text-[var(--accent)]" />
                      下载
                    </button>
                  ) : null}
                  {canDelete ? (
                    <button
                      type="button"
                      role="menuitem"
                      aria-label={`删除 ${file.name}`}
                      onClick={() => {
                        setOpenActionsFor(null);
                        onDelete?.(file);
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-[var(--danger)] hover:bg-[var(--workbench-hover-bg)]"
                    >
                      <Trash2 className="h-4 w-4" />
                      删除
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </li>;
      })}
    </ul>
  );
}
