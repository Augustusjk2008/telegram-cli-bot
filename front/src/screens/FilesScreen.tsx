import { useEffect, useState } from "react";
import { ChevronLeft, Upload } from "lucide-react";
import { FileList } from "../components/FileList";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileEntry } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client?: WebBotClient;
};

export function FilesScreen({ botAlias, client = new MockWebBotClient() }: Props) {
  const [currentPath, setCurrentPath] = useState("/");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewName, setPreviewName] = useState("");
  const [previewContent, setPreviewContent] = useState("");

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

  const handleFileClick = async (name: string) => {
    try {
      const content = await client.readFile(botAlias, name);
      setPreviewName(name);
      setPreviewContent(content || "文件为空");
    } catch (err) {
      setError(err instanceof Error ? err.message : "预览文件失败");
    }
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
          <h1 className="text-lg font-semibold truncate">{botAlias} - {currentPath}</h1>
        </div>
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
          <FileList files={files} onDirClick={(name) => void handleDirClick(name)} onFileClick={(name) => void handleFileClick(name)} />
        )}
      </section>

      {previewName ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-5 max-w-md w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center justify-between mb-4 gap-4">
              <h2 className="text-lg font-semibold truncate">{previewName}</h2>
              <button onClick={() => { setPreviewName(""); setPreviewContent(""); }} className="px-3 py-1 rounded-lg border border-[var(--border)]">
                关闭
              </button>
            </div>
            <pre className="max-h-[50vh] overflow-auto rounded-xl bg-[var(--surface-strong)] p-4 text-sm whitespace-pre-wrap break-all">
              {previewContent}
            </pre>
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => void client.downloadFile(botAlias, previewName)}
                className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white"
              >
                下载
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
