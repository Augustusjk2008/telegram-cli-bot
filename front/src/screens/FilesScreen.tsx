import { useEffect, useState } from "react";
import { ChevronLeft, FolderPlus, House, Upload } from "lucide-react";
import { BotIdentity } from "../components/BotIdentity";
import { FileList } from "../components/FileList";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileEntry, FileReadResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import {
  getFilePreviewStatusText,
  isFilePreviewFullyLoaded,
  isFilePreviewTooLarge,
} from "../utils/filePreview";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
};

export function FilesScreen({ botAlias, botAvatarName, client = new MockWebBotClient() }: Props) {
  const [currentPath, setCurrentPath] = useState("/");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewMode, setPreviewMode] = useState<"preview" | "full">("preview");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState<FileReadResult | null>(null);

  async function loadListing() {
    setLoading(true);
    setError("");
    try {
      const listing = await client.listFiles(botAlias);
      setCurrentPath(listing.workingDir);
      setFiles(listing.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载目录失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadListing();
  }, [botAlias, client]);

  const handleDirClick = async (name: string) => {
    try {
      await client.changeDirectory(botAlias, name);
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换目录失败");
    }
  };

  const handleBack = async () => {
    try {
      await client.changeDirectory(botAlias, "..");
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "返回上级目录失败");
    }
  };

  const handleHome = async () => {
    try {
      setError("");
      const workingDir = await client.getCurrentPath(botAlias);
      await client.changeDirectory(botAlias, workingDir);
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "返回工作目录失败");
    }
  };

  const handleCreateDirectory = async () => {
    const name = window.prompt("请输入新文件夹名称", "")?.trim();
    if (!name) {
      return;
    }

    setError("");
    try {
      await client.createDirectory(botAlias, name);
      await loadListing();
    } catch (err) {
      setError(err instanceof Error ? err.message : "新建文件夹失败");
    }
  };

  const handleDeleteEntry = async (file: FileEntry) => {
    const message = file.isDir
      ? `确定删除文件夹 ${file.name} 吗？此操作会递归删除其中的所有内容。`
      : `确定删除文件 ${file.name} 吗？`;
    if (!window.confirm(message)) {
      return;
    }

    setError("");
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
    }
  };

  const handleDownloadEntry = async (file: FileEntry) => {
    try {
      setError("");
      await client.downloadFile(botAlias, file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "下载文件失败");
    }
  };

  const loadPreview = async (name: string, mode: "preview" | "full") => {
    setPreviewLoading(true);
    try {
      const result = mode === "full"
        ? await client.readFileFull(botAlias, name)
        : await client.readFile(botAlias, name);
      setPreviewName(name);
      setPreviewMode(result.mode === "cat" ? "full" : "preview");
      setPreviewResult(result);
      setPreviewContent(result.content || "文件为空");
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === "full" ? "读取全文失败" : "预览文件失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const previewStatusText = getFilePreviewStatusText(previewResult);
  const canLoadFull = !isFilePreviewFullyLoaded(previewResult) && !isFilePreviewTooLarge(previewResult?.fileSizeBytes);

  const handleFileClick = async (name: string) => {
    await loadPreview(name, "preview");
  };

  return (
    <main className="flex flex-col h-full bg-[var(--bg)]">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)] flex items-center justify-between">
        <div className="flex items-center gap-2 overflow-hidden">
          {currentPath !== "/" && currentPath !== "." ? (
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
            <p className="truncate text-xs text-[var(--muted)]">{currentPath}</p>
          </div>
        </div>
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
          <button
            type="button"
            aria-label="新建文件夹"
            title="新建文件夹"
            onClick={() => void handleCreateDirectory()}
            className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)]"
          >
            <FolderPlus className="w-5 h-5" />
          </button>
          <label className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)] cursor-pointer">
            <Upload className="w-5 h-5" />
            <input
              type="file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                void client.uploadFile(botAlias, file)
                  .then(() => loadListing())
                  .catch((err: Error) => setError(err.message || "上传失败"));
              }}
            />
          </label>
        </div>
      </header>

      <section className="flex-1 overflow-y-auto p-4">
        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {loading ? (
          <div className="text-center text-[var(--muted)] mt-10">加载中...</div>
        ) : (
          <FileList
            files={files}
            onDirClick={(name) => void handleDirClick(name)}
            onFileClick={(name) => void handleFileClick(name)}
            onDownload={(file) => void handleDownloadEntry(file)}
            onDelete={(file) => void handleDeleteEntry(file)}
          />
        )}
      </section>

      {previewName ? (
        <FilePreviewDialog
          title={previewName}
          content={previewContent}
          mode={previewMode}
          loading={previewLoading}
          onClose={() => {
            setPreviewName("");
            setPreviewContent("");
            setPreviewResult(null);
          }}
          statusText={previewStatusText}
          onLoadFull={previewMode !== "full" && canLoadFull ? () => void loadPreview(previewName, "full") : undefined}
          onDownload={() => void client.downloadFile(botAlias, previewName)}
        />
      ) : null}
    </main>
  );
}
