import { Download, FileText, Folder, Trash2 } from "lucide-react";
import { FileEntry } from "../services/types";

type Props = {
  files: FileEntry[];
  onDirClick: (name: string) => void;
  onFileClick: (name: string) => void;
  onDownload: (file: FileEntry) => void;
  onDelete: (file: FileEntry) => void;
  allowDelete?: boolean;
};

export function FileList({ files, onDirClick, onFileClick, onDownload, onDelete, allowDelete = true }: Props) {
  if (files.length === 0) {
    return <div className="text-center text-[var(--muted)] py-8">目录为空</div>;
  }

  return (
    <ul className="divide-y divide-[var(--border)] bg-[var(--surface)] rounded-xl border border-[var(--border)] overflow-hidden">
      {files.map((file) => (
        <li key={file.name} className="flex items-center gap-2 p-2">
          <button
            type="button"
            aria-label={`${file.isDir ? "进入" : "打开"} ${file.name}`}
            onClick={() => file.isDir ? onDirClick(file.name) : onFileClick(file.name)}
            className="min-w-0 flex-1 flex items-center gap-3 rounded-lg p-2 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] transition-colors text-left"
          >
            {file.isDir ? (
              <Folder className="w-5 h-5 text-blue-500" />
            ) : (
              <FileText className="w-5 h-5 text-gray-500" />
            )}
            <div className="min-w-0 flex-1 truncate">
              <span className="font-medium">{file.name}</span>
              {!file.isDir && file.size !== undefined && (
                <span className="ml-2 text-xs text-[var(--muted)]">
                  {(file.size / 1024).toFixed(1)} KB
                </span>
              )}
            </div>
            {file.updatedAt && (
              <span className="shrink-0 text-xs text-[var(--muted)]">
                {new Date(file.updatedAt).toLocaleDateString()}
              </span>
            )}
          </button>
          {!file.isDir ? (
            <button
              type="button"
              aria-label={`下载 ${file.name}`}
              title={`下载 ${file.name}`}
              onClick={() => onDownload(file)}
              className="shrink-0 rounded-lg border border-[var(--border)] p-2 text-[var(--accent)] hover:bg-[var(--surface-strong)]"
            >
              <Download className="w-4 h-4" />
            </button>
          ) : null}
          {allowDelete ? (
            <button
              type="button"
              aria-label={`删除 ${file.name}`}
              title={`删除 ${file.name}`}
              onClick={() => onDelete(file)}
              className="shrink-0 rounded-lg border border-[var(--border)] p-2 text-red-600 hover:bg-red-50"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
