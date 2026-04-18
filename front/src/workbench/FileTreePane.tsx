import { Download, FilePlus, FolderPlus, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { FileNameDialog } from "../components/FileNameDialog";
import { type FileTreeNode, type UseFileTreeResult } from "./useFileTree";

type Props = {
  tree: UseFileTreeResult;
  onOpenFile: (path: string) => void;
  onCreatedFile: (path: string, content: string, lastModifiedNs?: string) => void;
  onRenamedFile: (oldPath: string, nextPath: string) => void;
  onDeletedFile: (path: string) => void;
  onRequestSetWorkdir: (path: string) => void;
};

function branchLabel(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

export function FileTreePane({
  tree,
  onOpenFile,
  onCreatedFile,
  onRenamedFile,
  onDeletedFile,
  onRequestSetWorkdir,
}: Props) {
  const [showCreateFileDialog, setShowCreateFileDialog] = useState(false);
  const [pendingFileName, setPendingFileName] = useState("");
  const [createFileBusy, setCreateFileBusy] = useState(false);
  const [createFileError, setCreateFileError] = useState("");
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [renameTargetPath, setRenameTargetPath] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState("");

  async function handleCreateFile() {
    setCreateFileBusy(true);
    setCreateFileError("");
    try {
      const result = await tree.createFile(pendingFileName.trim(), "");
      setShowCreateFileDialog(false);
      setPendingFileName("");
      onCreatedFile(result.path, "", result.lastModifiedNs);
    } catch (error) {
      setCreateFileError(error instanceof Error ? error.message : "新建文件失败");
    } finally {
      setCreateFileBusy(false);
    }
  }

  async function handleRenameFile() {
    setRenameBusy(true);
    setRenameError("");
    try {
      const result = await tree.renameFile(renameTargetPath, renameValue.trim());
      setShowRenameDialog(false);
      setRenameTargetPath("");
      setRenameValue("");
      onRenamedFile(result.oldPath, result.path);
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "重命名失败");
    } finally {
      setRenameBusy(false);
    }
  }

  async function handleCreateDirectory() {
    const name = window.prompt("请输入新文件夹名称", "")?.trim();
    if (!name) {
      return;
    }
    try {
      await tree.createDirectory(name);
    } catch {
      // tree.error is surfaced by the hook state
    }
  }

  async function handleDelete(entry: FileTreeNode) {
    const message = entry.isDir
      ? `确定删除文件夹 ${entry.path} 吗？此操作会递归删除其中的所有内容。`
      : `确定删除文件 ${entry.path} 吗？`;
    if (!window.confirm(message)) {
      return;
    }

    await tree.deletePath(entry.path);
    if (!entry.isDir) {
      onDeletedFile(entry.path);
    }
  }

  function renderBranch(entries: FileTreeNode[], depth: number) {
    return (
      <ul className="space-y-0.5">
        {entries.map((entry) => {
          const expanded = tree.isExpanded(entry.path);
          const branch = tree.branches[entry.path];
          const dirLabel = branchLabel(entry.path);
          return (
            <li key={entry.path}>
              <div
                className="group flex min-w-0 items-center gap-1 rounded-md text-[12px]"
                style={{ paddingLeft: `${depth * 12}px` }}
              >
                {entry.isDir ? (
                  <button
                    type="button"
                    aria-label={`${expanded ? "收起" : "展开"} ${entry.path}`}
                    onClick={() => void tree.toggleDirectory(entry.path)}
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-[var(--surface-strong)]"
                  >
                    {expanded ? "▾" : "▸"}
                  </button>
                ) : (
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center text-[var(--muted)]">
                    ·
                  </span>
                )}

                {entry.isDir ? (
                  <button
                    type="button"
                    aria-label={`切换 ${entry.path}`}
                    onClick={() => void tree.toggleDirectory(entry.path)}
                    className="min-w-0 flex-1 truncate rounded px-2 py-1 text-left text-[var(--text)] hover:bg-[var(--surface-strong)]"
                  >
                    {dirLabel}
                  </button>
                ) : (
                  <button
                    type="button"
                    aria-label={`打开 ${entry.path}`}
                    onClick={() => onOpenFile(entry.path)}
                    className="min-w-0 flex-1 truncate rounded px-2 py-1 text-left text-[var(--text)] hover:bg-[var(--surface-strong)]"
                  >
                    {entry.name}
                  </button>
                )}

                {entry.isDir ? (
                  <button
                    type="button"
                    aria-label={`设 ${entry.path} 为工作目录`}
                    onClick={() => onRequestSetWorkdir(`${tree.rootPath.replace(/[\\/]+$/, "")}/${entry.path}`)}
                    className="shrink-0 rounded px-2 py-1 text-[11px] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
                  >
                    设为工作目录
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      aria-label={`重命名 ${entry.path}`}
                      title={`重命名 ${entry.path}`}
                      onClick={() => {
                        setRenameTargetPath(entry.path);
                        setRenameValue(entry.name);
                        setRenameError("");
                        setShowRenameDialog(true);
                      }}
                      className="shrink-0 rounded p-1 text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label={`下载 ${entry.path}`}
                      title={`下载 ${entry.path}`}
                      onClick={() => void tree.downloadFile(entry.path)}
                      className="shrink-0 rounded p-1 text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}

                <button
                  type="button"
                  aria-label={`删除 ${entry.path}`}
                  title={`删除 ${entry.path}`}
                  onClick={() => void handleDelete(entry)}
                  className="shrink-0 rounded p-1 text-red-600 hover:bg-red-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>

              {entry.isDir && expanded ? (
                <div className="space-y-1">
                  {branch?.loading ? (
                    <div className="px-2 py-1 text-[11px] text-[var(--muted)]" style={{ paddingLeft: `${(depth + 1) * 12 + 24}px` }}>
                      加载中...
                    </div>
                  ) : null}
                  {branch?.error ? (
                    <div className="px-2 py-1 text-[11px] text-red-700" style={{ paddingLeft: `${(depth + 1) * 12 + 24}px` }}>
                      {branch.error}
                    </div>
                  ) : null}
                  {branch?.entries?.length ? renderBranch(branch.entries, depth + 1) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-[var(--border)] px-3 py-2.5">
        <div className="truncate text-[11px] text-[var(--muted)]">{tree.rootPath}</div>
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            aria-label="刷新文件树"
            title="刷新文件树"
            onClick={() => void tree.refreshRoot()}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="新建文件"
            title="新建文件"
            onClick={() => {
              setPendingFileName("");
              setCreateFileError("");
              setShowCreateFileDialog(true);
            }}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
          >
            <FilePlus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="新建文件夹"
            title="新建文件夹"
            onClick={() => void handleCreateDirectory()}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
          >
            <FolderPlus className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div data-testid="desktop-file-tree-scroll" className="flex-1 overflow-y-auto px-2 py-2">
        {tree.loading ? (
          <div className="px-2 py-2 text-[12px] text-[var(--muted)]">加载中...</div>
        ) : null}
        {!tree.loading && tree.error ? (
          <div className="px-2 py-2 text-[12px] text-red-700">{tree.error}</div>
        ) : null}
        {!tree.loading && !tree.error ? renderBranch(tree.rootEntries, 0) : null}
      </div>

      {showCreateFileDialog ? (
        <FileNameDialog
          title="新建文件"
          label="文件名"
          value={pendingFileName}
          confirmText="创建"
          busy={createFileBusy}
          error={createFileError}
          onChange={setPendingFileName}
          onConfirm={() => void handleCreateFile()}
          onClose={() => {
            if (createFileBusy) {
              return;
            }
            setShowCreateFileDialog(false);
            setPendingFileName("");
            setCreateFileError("");
          }}
        />
      ) : null}

      {showRenameDialog ? (
        <FileNameDialog
          title="重命名文件"
          label="文件名"
          value={renameValue}
          confirmText="重命名"
          busy={renameBusy}
          error={renameError}
          onChange={setRenameValue}
          onConfirm={() => void handleRenameFile()}
          onClose={() => {
            if (renameBusy) {
              return;
            }
            setShowRenameDialog(false);
            setRenameTargetPath("");
            setRenameValue("");
            setRenameError("");
          }}
        />
      ) : null}
    </div>
  );
}
