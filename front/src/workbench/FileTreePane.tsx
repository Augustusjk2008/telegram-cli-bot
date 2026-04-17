import { FilePlus, FolderPlus, House } from "lucide-react";
import { useState } from "react";
import { FileList } from "../components/FileList";
import { FileNameDialog } from "../components/FileNameDialog";
import { type UseFileBrowserResult } from "./useFileBrowser";

type Props = {
  browser: UseFileBrowserResult;
  onOpenFile: (path: string) => void;
  onCreatedFile: (path: string, content: string, lastModifiedNs?: number) => void;
  onRenamedFile: (oldPath: string, nextPath: string) => void;
  onDeletedFile: (path: string) => void;
};

export function FileTreePane({
  browser,
  onOpenFile,
  onCreatedFile,
  onRenamedFile,
  onDeletedFile,
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
      const result = await browser.createFile(pendingFileName.trim(), "");
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
      const result = await browser.renameFile(renameTargetPath, renameValue.trim());
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

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-[var(--border)] px-3 py-3">
        <p className="truncate text-xs text-[var(--muted)]">{browser.currentPath}</p>
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            aria-label="回到工作目录"
            title="回到工作目录"
            onClick={() => void browser.goHome()}
            className="rounded-lg border border-[var(--border)] p-2 text-[var(--accent)] hover:bg-[var(--surface-strong)]"
          >
            <House className="h-4 w-4" />
          </button>
          {!browser.isVirtualRoot ? (
            <button
              type="button"
              aria-label="新建文件"
              title="新建文件"
              onClick={() => {
                setPendingFileName("");
                setCreateFileError("");
                setShowCreateFileDialog(true);
              }}
              className="rounded-lg border border-[var(--border)] p-2 text-[var(--accent)] hover:bg-[var(--surface-strong)]"
            >
              <FilePlus className="h-4 w-4" />
            </button>
          ) : null}
          {!browser.isVirtualRoot ? (
            <button
              type="button"
              aria-label="新建文件夹"
              title="新建文件夹"
              onClick={() => {
                const name = window.prompt("请输入新文件夹名称", "")?.trim();
                if (!name) {
                  return;
                }
                void browser.createDirectory(name);
              }}
              className="rounded-lg border border-[var(--border)] p-2 text-[var(--accent)] hover:bg-[var(--surface-strong)]"
            >
              <FolderPlus className="h-4 w-4" />
            </button>
          ) : null}
        </div>
        {browser.error ? (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {browser.error}
          </div>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {browser.loading ? (
          <div className="text-center text-sm text-[var(--muted)]">加载中...</div>
        ) : (
          <FileList
            files={browser.files}
            onDirClick={(name) => void browser.goToDirectory(name)}
            onFileClick={(name) => onOpenFile(name)}
            onRename={(file) => {
              setRenameTargetPath(file.name);
              setRenameValue(file.name);
              setRenameError("");
              setShowRenameDialog(true);
            }}
            onDownload={(file) => void browser.downloadEntry(file)}
            onDelete={(file) => {
              const message = file.isDir
                ? `确定删除文件夹 ${file.name} 吗？此操作会递归删除其中的所有内容。`
                : `确定删除文件 ${file.name} 吗？`;
              if (!window.confirm(message)) {
                return;
              }
              void browser.deleteEntry(file).then((deleted) => {
                if (deleted && !file.isDir) {
                  onDeletedFile(file.name);
                }
              });
            }}
            allowDelete={!browser.isVirtualRoot}
          />
        )}
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
