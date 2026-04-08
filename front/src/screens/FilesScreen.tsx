import { useState, useEffect } from "react";
import { FileEntry } from "../services/types";
import { FileList } from "../components/FileList";
import { mockFiles } from "../mocks/files";
import { ChevronLeft, Upload } from "lucide-react";

export function FilesScreen({ botAlias }: { botAlias: string }) {
  const [currentPath, setCurrentPath] = useState("/");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    // Simulate network delay
    setTimeout(() => {
      const botFiles = mockFiles[botAlias] || {};
      setFiles(botFiles[currentPath] || []);
      setLoading(false);
    }, 300);
  }, [botAlias, currentPath]);

  const handleDirClick = (name: string) => {
    setCurrentPath(prev => prev === "/" ? `/${name}` : `${prev}/${name}`);
  };

  const handleBack = () => {
    setCurrentPath(prev => {
      if (prev === "/") return prev;
      const parts = prev.split("/");
      parts.pop();
      return parts.length === 1 ? "/" : parts.join("/");
    });
  };

  const handleFileClick = (name: string) => {
    alert(`预览文件: ${name}`);
  };

  return (
    <main className="flex flex-col h-full bg-[var(--bg)]">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)] flex items-center justify-between">
        <div className="flex items-center gap-2 overflow-hidden">
          {currentPath !== "/" && (
            <button onClick={handleBack} className="p-1 rounded-md hover:bg-[var(--border)]">
              <ChevronLeft className="w-5 h-5" />
            </button>
          )}
          <h1 className="text-lg font-semibold truncate">{botAlias} - {currentPath}</h1>
        </div>
        <button className="p-2 rounded-md hover:bg-[var(--border)] text-[var(--accent)]" onClick={() => alert("模拟上传文件")}>
          <Upload className="w-5 h-5" />
        </button>
      </header>
      
      <section className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="text-center text-[var(--muted)] mt-10">加载中...</div>
        ) : (
          <FileList files={files} onDirClick={handleDirClick} onFileClick={handleFileClick} />
        )}
      </section>
    </main>
  );
}
