import { useEffect, useRef, useState } from "react";
import { ChevronLeft, FilePlus, FolderOpen, FolderPlus, House, Upload } from "lucide-react";
import { BotIdentity } from "../components/BotIdentity";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { FileList } from "../components/FileList";
import { FileNameDialog } from "../components/FileNameDialog";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileDownloadProgress, FileEntry, FileReadResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  getFilePreviewStatusText,
  isFilePreviewFullyLoaded,
  isFilePreviewTooLarge,
  shouldAutoLoadFullHtmlPreview,
  withDetectedPreviewKind,
} from "../utils/filePreview";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  structureOnly?: boolean;
  canWriteFiles?: boolean;
  canOpenSystemFolder?: boolean;
};

function joinBrowserPath(basePath: string, name: string) {
  if (!basePath || basePath === "/") {
    return `/${name}`;
  }
  if (/^[A-Za-z]:[\\/]?$/.test(basePath)) {
    return `${basePath.replace(/[\\/]+$/, "\\")}${name}`;
  }
  const separator = basePath.includes("\\") ? "\\" : "/";
  return `${basePath.replace(/[\\/]+$/, "")}${separator}${name}`;
}

function getParentBrowserPath(path: string) {
  const normalized = path.replace(/[\\/]+$/, "");
  if (!normalized || normalized === "/") {
    return normalized || "/";
  }
  const parts = normalized.split(/[\\/]+/);
  if (parts.length <= 1) {
    return normalized;
  }
  if (/^[A-Za-z]:$/.test(parts[0])) {
    return parts.length <= 2 ? `${parts[0]}\\` : `${parts[0]}\\${parts.slice(1, -1).join("\\")}`;
  }
  if (normalized.startsWith("/")) {
    return `/${parts.slice(1, -1).join("/")}` || "/";
  }
  return parts.slice(0, -1).join("/");
}

type ActiveDownload = FileDownloadProgress & {
  filename: string;
};

function formatBytes(value: number) {
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function formatDownloadDetail(progress: ActiveDownload) {
  if (typeof progress.totalBytes === "number" && progress.totalBytes > 0) {
    return `${formatBytes(progress.downloadedBytes)} / ${formatBytes(progress.totalBytes)}`;
  }
  return formatBytes(progress.downloadedBytes);
}

export function FilesScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  structureOnly = false,
  canWriteFiles = true,
  canOpenSystemFolder = false,
}: Props) {
  const [currentPath, setCurrentPath] = useState("");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [isVirtualRoot, setIsVirtualRoot] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewMode, setPreviewMode] = useState<"preview" | "full">("preview");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState<FileReadResult | null>(null);
  const [editorPath, setEditorPath] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [editorLoading, setEditorLoading] = useState(false);
  const [editorSaving, setEditorSaving] = useState(false);
  const [editorError, setEditorError] = useState("");
  const [editorStatusText, setEditorStatusText] = useState("");
  const [editorLastModifiedNs, setEditorLastModifiedNs] = useState<string | undefined>(undefined);
  const [editorEncoding, setEditorEncoding] = useState<string | undefined>(undefined);
  const [showCreateFileDialog, setShowCreateFileDialog] = useState(false);
  const [pendingFileName, setPendingFileName] = useState("");
  const [createFileBusy, setCreateFileBusy] = useState(false);
  const [createFileError, setCreateFileError] = useState("");
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [renameTargetPath, setRenameTargetPath] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameError, setRenameError] = useState("");
  const [downloadProgress, setDownloadProgress] = useState<ActiveDownload | null>(null);
  const [statusText, setStatusText] = useState("");
  const listingRequestSeqRef = useRef(0);
  const previewRequestSeqRef = useRef(0);
  const canPreviewFiles = !structureOnly;
  const canMutateFiles = canPreviewFiles && canWriteFiles;

  async function loadListing(targetPath?: string) {
    const requestSeq = listingRequestSeqRef.current + 1;
    listingRequestSeqRef.current = requestSeq;
    setLoading(true);
    setError("");
    setStatusText("");
    try {
      const listing = structureOnly
        ? await client.listFiles(botAlias, targetPath || currentPath || await client.getCurrentPath(botAlias))
        : await client.listFiles(botAlias);
      if (requestSeq !== listingRequestSeqRef.current) {
        return;
      }
      setCurrentPath(listing.workingDir);
      setFiles(listing.entries);
      setIsVirtualRoot(Boolean(listing.isVirtualRoot));
    } catch (err) {
      if (requestSeq === listingRequestSeqRef.current) {
        setError(err instanceof Error ? err.message : "加载目录失败");
      }
    } finally {
      if (requestSeq === listingRequestSeqRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    void loadListing();
  }, [botAlias, client, structureOnly]);

  const isEditorOpen = Boolean(editorPath);
  const isDirty = isEditorOpen && editorContent !== savedContent;

  const handleDirClick = async (name: string) => {
    try {
      if (structureOnly) {
        await loadListing(joinBrowserPath(currentPath, name));
        return;
      }
      await client.changeDirectory(botAlias, name);
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换目录失败");
      setStatusText("");
    }
  };

  const handleBack = async () => {
    try {
      if (structureOnly) {
        await loadListing(getParentBrowserPath(currentPath));
        return;
      }
      await client.changeDirectory(botAlias, "..");
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "返回上级目录失败");
      setStatusText("");
    }
  };

  const handleHome = async () => {
    try {
      setError("");
      setStatusText("");
      const workingDir = await client.getCurrentPath(botAlias);
      if (structureOnly) {
        await loadListing(workingDir);
        return;
      }
      await client.changeDirectory(botAlias, workingDir);
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "返回工作目录失败");
      setStatusText("");
    }
  };

  const handleCreateDirectory = async () => {
    if (!canMutateFiles) {
      setError("无文件写入权限");
      setStatusText("");
      return;
    }
    const name = window.prompt("请输入新文件夹名称", "")?.trim();
    if (!name) {
      return;
    }

    setError("");
    setStatusText("");
    try {
      await client.createDirectory(botAlias, name);
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新建文件夹失败");
      setStatusText("");
    }
  };

  const handleDeleteEntry = async (file: FileEntry) => {
    if (!canMutateFiles) {
      setError("无文件写入权限");
      setStatusText("");
      return;
    }
    const message = file.isDir
      ? `确定删除文件夹 ${file.name} 吗？此操作会递归删除其中的所有内容。`
      : `确定删除文件 ${file.name} 吗？`;
    if (!window.confirm(message)) {
      return;
    }

    setError("");
    setStatusText("");
    try {
      await client.deletePath(botAlias, file.name);
      if (previewName === file.name) {
        setPreviewName("");
        setPreviewContent("");
        setPreviewResult(null);
      }
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : file.isDir ? "删除文件夹失败" : "删除文件失败");
      setStatusText("");
    }
  };

  const handleDownloadEntry = async (file: FileEntry) => {
    if (!canPreviewFiles) {
      return;
    }
    try {
      setError("");
      setStatusText("");
      setDownloadProgress({
        filename: file.name,
        downloadedBytes: 0,
        ...(typeof file.size === "number" ? { totalBytes: file.size, percent: 0 } : {}),
      });
      await client.downloadFile(botAlias, file.name, (progress) => {
        setDownloadProgress({
          filename: file.name,
          ...progress,
        });
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "下载文件失败");
      setStatusText("");
    } finally {
      setDownloadProgress(null);
    }
  };

  const loadPreview = async (name: string, mode: "preview" | "full") => {
    if (!canPreviewFiles) {
      return;
    }
    const requestSeq = previewRequestSeqRef.current + 1;
    previewRequestSeqRef.current = requestSeq;
    setPreviewLoading(true);
    try {
      let result = mode === "full"
        ? await client.readFileFull(botAlias, name)
        : await client.readFile(botAlias, name);
      if (mode === "preview" && shouldAutoLoadFullHtmlPreview(name, result)) {
        result = await client.readFileFull(botAlias, name);
      }
      if (requestSeq !== previewRequestSeqRef.current) {
        return;
      }
      result = withDetectedPreviewKind(name, result);
      setPreviewName(name);
      setPreviewMode(result.mode === "cat" ? "full" : "preview");
      setPreviewResult(result);
      setPreviewContent(result.previewKind === "image" ? "" : result.content || "文件为空");
    } catch (err) {
      if (requestSeq === previewRequestSeqRef.current) {
        setError(err instanceof Error ? err.message : mode === "full" ? "读取全文失败" : "预览文件失败");
        setStatusText("");
      }
    } finally {
      if (requestSeq === previewRequestSeqRef.current) {
        setPreviewLoading(false);
      }
    }
  };

  const previewStatusText = getFilePreviewStatusText(previewResult);
  const canLoadFull = canPreviewFiles && !isFilePreviewFullyLoaded(previewResult) && !isFilePreviewTooLarge(previewResult);
  const canEditPreview = canMutateFiles && previewResult?.previewKind !== "image";
  const previewDownloadProgress = downloadProgress?.filename === previewName ? downloadProgress : null;

  const handleFileClick = async (name: string) => {
    if (!canPreviewFiles) {
      return;
    }
    await loadPreview(name, "preview");
  };

  const handleOpenWorkdir = async () => {
    setError("");
    setStatusText("");
    try {
      await client.openBotWorkdir(botAlias);
      setStatusText("已请求系统打开工作目录");
    } catch (err) {
      setError(err instanceof Error ? err.message : "系统文件夹打开失败");
    }
  };

  const clearEditor = () => {
    setEditorPath("");
    setEditorContent("");
    setSavedContent("");
    setEditorLoading(false);
    setEditorSaving(false);
    setEditorError("");
    setEditorStatusText("");
    setEditorLastModifiedNs(undefined);
    setEditorEncoding(undefined);
  };

  const handleOpenEditor = async (name: string) => {
    if (!canMutateFiles) {
      setError("无文件写入权限");
      setStatusText("");
      return;
    }
    setError("");
    setStatusText("");
    setEditorError("");
    setEditorStatusText("");
    setEditorLoading(true);
    try {
      const result = await client.readFileFull(botAlias, name);
      setPreviewName("");
      setPreviewContent("");
      setPreviewResult(null);
      setEditorPath(name);
      setEditorContent(result.content || "");
      setSavedContent(result.content || "");
      setEditorLastModifiedNs(result.lastModifiedNs);
      setEditorEncoding(result.encoding);
    } catch (err) {
      const message = err instanceof Error ? err.message : "读取文件失败";
      setEditorError(message);
      setError(message);
      setStatusText("");
      if (previewName === name) {
        setPreviewName("");
        setPreviewContent("");
        setPreviewResult(null);
      }
    } finally {
      setEditorLoading(false);
    }
  };

  const handleEditorChange = (value: string) => {
    if (!canMutateFiles) {
      return;
    }
    setEditorContent(value);
    setEditorStatusText("");
  };

  const handleCloseEditor = () => {
    if (isDirty && !window.confirm("文件尚未保存，确定放弃修改吗？")) {
      return;
    }
    clearEditor();
  };

  const handleSaveEditor = async () => {
    if (!editorPath) {
      return;
    }
    if (!canMutateFiles) {
      setEditorError("无文件写入权限");
      setEditorSaving(false);
      return;
    }

    setEditorSaving(true);
    setEditorError("");
    try {
      const result = await client.writeFile(botAlias, editorPath, editorContent, editorLastModifiedNs, editorEncoding);
      setSavedContent(editorContent);
      setEditorLastModifiedNs(result.lastModifiedNs);
      setEditorEncoding(result.encoding || editorEncoding);
      setEditorStatusText("已保存");
      if (previewName === editorPath) {
        setPreviewContent(editorContent || "文件为空");
        setPreviewResult((current) => current
          ? {
              ...current,
              content: editorContent,
              mode: "cat",
              isFullContent: true,
              fileSizeBytes: result.fileSizeBytes,
              lastModifiedNs: result.lastModifiedNs,
            }
          : current);
      }
      await loadListing();
    } catch (err) {
      setEditorError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setEditorSaving(false);
    }
  };

  const handleOpenCreateFileDialog = () => {
    if (!canMutateFiles) {
      setError("无文件写入权限");
      setStatusText("");
      return;
    }
    setPendingFileName("");
    setCreateFileError("");
    setShowCreateFileDialog(true);
  };

  const handleCloseCreateFileDialog = () => {
    if (createFileBusy) {
      return;
    }
    setShowCreateFileDialog(false);
    setPendingFileName("");
    setCreateFileError("");
  };

  const handleCreateFile = async () => {
    if (!canMutateFiles) {
      setCreateFileError("无文件写入权限");
      return;
    }
    setCreateFileBusy(true);
    setCreateFileError("");
    try {
      const result = await client.createTextFile(botAlias, pendingFileName.trim(), "");
      setShowCreateFileDialog(false);
      setPendingFileName("");
      setEditorPath(result.path);
      setEditorContent("");
      setSavedContent("");
      setEditorError("");
      setEditorStatusText("");
      setEditorLastModifiedNs(result.lastModifiedNs);
      await loadListing();
    } catch (err) {
      setCreateFileError(err instanceof Error ? err.message : "新建文件失败");
    } finally {
      setCreateFileBusy(false);
    }
  };

  const handleOpenRenameDialog = (path: string) => {
    if (!canMutateFiles) {
      setError("无文件写入权限");
      setStatusText("");
      return;
    }
    setRenameTargetPath(path);
    setRenameValue(path);
    setRenameError("");
    setShowRenameDialog(true);
  };

  const handleCloseRenameDialog = () => {
    if (renameBusy) {
      return;
    }
    setShowRenameDialog(false);
    setRenameTargetPath("");
    setRenameValue("");
    setRenameError("");
  };

  const handleRenameFile = async () => {
    if (!canMutateFiles) {
      setRenameError("无文件写入权限");
      return;
    }
    setRenameBusy(true);
    setRenameError("");
    try {
      const result = await client.renamePath(botAlias, renameTargetPath, renameValue.trim());
      setShowRenameDialog(false);
      setRenameTargetPath("");
      setRenameValue("");
      if (previewName === result.oldPath) {
        setPreviewName(result.path);
      }
      if (editorPath === result.oldPath) {
        setEditorPath(result.path);
      }
      await loadListing();
    } catch (err) {
      setRenameError(err instanceof Error ? err.message : "重命名失败");
    } finally {
      setRenameBusy(false);
    }
  };

  return (
    <main className="flex flex-col h-full bg-[var(--bg)]">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)] flex items-center justify-between">
        <div className="flex items-center gap-2 overflow-hidden">
          {currentPath !== "/" && currentPath !== "." && !isVirtualRoot && !isEditorOpen ? (
            <button onClick={() => void handleBack()} className="p-1 rounded-md hover:bg-[var(--border)]">
              <ChevronLeft className="w-5 h-5" />
            </button>
          ) : null}
          <div className="min-w-0">
            {botAvatarName ? (
              <BotIdentity
                alias={botAlias}
                avatarName={botAvatarName}
                size={28}
                className="flex min-w-0 items-center gap-2"
                nameClassName="truncate text-lg font-semibold text-[var(--text)]"
              />
            ) : (
              <h1 className="text-lg font-semibold truncate">{botAlias}</h1>
            )}
            <p className="truncate text-xs text-[var(--muted)]">{currentPath || "加载中..."}</p>
          </div>
        </div>
        {!isEditorOpen ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Home"
              title="回到工作目录"
              onClick={() => void handleHome()}
              className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)]"
            >
              <House className="w-5 h-5" />
            </button>
            {canMutateFiles && canOpenSystemFolder ? (
              <button
                type="button"
                aria-label="在系统文件夹中打开"
                title="在系统文件夹中打开"
                onClick={() => void handleOpenWorkdir()}
                className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)]"
              >
                <FolderOpen className="w-5 h-5" />
              </button>
            ) : null}
            {canMutateFiles && !isVirtualRoot ? (
              <button
                type="button"
                aria-label="新建文件"
                title="新建文件"
                onClick={() => void handleOpenCreateFileDialog()}
                className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)]"
              >
                <FilePlus className="w-5 h-5" />
              </button>
            ) : null}
            {canMutateFiles && !isVirtualRoot ? (
              <button
                type="button"
                aria-label="新建文件夹"
                title="新建文件夹"
                onClick={() => void handleCreateDirectory()}
                className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)]"
              >
                <FolderPlus className="w-5 h-5" />
              </button>
            ) : null}
            {canMutateFiles && !isVirtualRoot ? (
              <label className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)] cursor-pointer">
                <Upload className="w-5 h-5" />
                <input
                  type="file"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    if (!canMutateFiles) return;
                    void client.uploadFile(botAlias, file)
                      .then(() => loadListing())
                      .catch((err: Error) => setError(err.message || "上传失败"));
                  }}
                />
              </label>
            ) : null}
          </div>
        ) : null}
      </header>

      {isEditorOpen ? (
        <FileEditorSurface
          path={editorPath}
          value={editorContent}
          loading={editorLoading}
          saving={editorSaving}
          dirty={isDirty}
          canSave={isDirty}
          statusText={editorStatusText}
          error={editorError}
          onChange={handleEditorChange}
          onSave={() => void handleSaveEditor()}
          onClose={handleCloseEditor}
        />
      ) : (
        <section className="flex-1 overflow-y-auto p-4">
          {error ? (
            <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}
          {statusText ? (
            <div role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              {statusText}
            </div>
          ) : null}
          {downloadProgress ? (
            <div
              role="status"
              aria-label="下载进度"
              className="mb-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm shadow-sm"
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="min-w-0 truncate font-medium">正在下载 {downloadProgress.filename}</span>
                <span className="shrink-0 font-mono text-xs text-[var(--muted)]">
                  {typeof downloadProgress.percent === "number" ? `${downloadProgress.percent}%` : formatDownloadDetail(downloadProgress)}
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={`${downloadProgress.filename} 下载进度`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={typeof downloadProgress.percent === "number" ? downloadProgress.percent : undefined}
                className="h-2 overflow-hidden rounded-full bg-[var(--surface-strong)]"
              >
                <div
                  className="h-full rounded-full bg-[var(--accent)] transition-[width]"
                  style={{ width: `${typeof downloadProgress.percent === "number" ? downloadProgress.percent : 100}%` }}
                />
              </div>
              <div className="mt-1 text-xs text-[var(--muted)]">{formatDownloadDetail(downloadProgress)}</div>
            </div>
          ) : null}
          {loading ? (
            <div className="text-center text-[var(--muted)] mt-10">加载中...</div>
          ) : (
            <FileList
              files={files}
              onDirClick={(name) => void handleDirClick(name)}
              onFileClick={(name) => void handleFileClick(name)}
              onEdit={canMutateFiles ? (file) => void handleOpenEditor(file.name) : undefined}
              onRename={canMutateFiles ? (file) => void handleOpenRenameDialog(file.name) : undefined}
              onDownload={canPreviewFiles ? (file) => void handleDownloadEntry(file) : undefined}
              onDelete={canMutateFiles ? (file) => void handleDeleteEntry(file) : undefined}
              allowDelete={canMutateFiles && !isVirtualRoot}
            />
          )}
        </section>
      )}

      {canPreviewFiles && previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
          botAlias={botAlias}
          previewKind={previewResult?.previewKind}
          contentType={previewResult?.contentType}
          contentBase64={previewResult?.contentBase64}
          loading={previewLoading}
          onClose={() => {
            setPreviewName("");
            setPreviewContent("");
            setPreviewResult(null);
          }}
          statusText={previewStatusText}
          onLoadFull={previewMode !== "full" && canLoadFull ? () => void loadPreview(previewName, "full") : undefined}
          onEdit={canEditPreview ? () => void handleOpenEditor(previewName) : undefined}
          onDownload={canPreviewFiles ? () => void handleDownloadEntry({ name: previewName, isDir: false }) : undefined}
          downloadProgressText={previewDownloadProgress ? formatDownloadDetail(previewDownloadProgress) : ""}
          downloadPercent={previewDownloadProgress?.percent}
        />
      ) : null}
      {canMutateFiles && showCreateFileDialog ? (
        <FileNameDialog
          title="新建文件"
          label="文件名"
          value={pendingFileName}
          confirmText="创建"
          busy={createFileBusy}
          error={createFileError}
          onChange={setPendingFileName}
          onConfirm={() => void handleCreateFile()}
          onClose={handleCloseCreateFileDialog}
        />
      ) : null}
      {canMutateFiles && showRenameDialog ? (
        <FileNameDialog
          title="重命名文件"
          label="文件名"
          value={renameValue}
          confirmText="重命名"
          busy={renameBusy}
          error={renameError}
          onChange={setRenameValue}
          onConfirm={() => void handleRenameFile()}
          onClose={handleCloseRenameDialog}
        />
      ) : null}
    </main>
  );
}
