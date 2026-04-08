import { FileEntry } from "../services/types";
import { Folder, FileText } from "lucide-react";

type Props = {
  files: FileEntry[];
  onDirClick: (name: string) => void;
  onFileClick: (name: string) => void;
};

export function FileList({ files, onDirClick, onFileClick }: Props) {
  if (files.length === 0) {
    return <div className="text-center text-[var(--muted)] py-8">目录为空</div>;
  }

  return (
    <ul className="divide-y divide-[var(--border)] bg-[var(--surface)] rounded-xl border border-[var(--border)] overflow-hidden">
      {files.map((file) => (
        <li key={file.name}>
          <button
            onClick={() => file.isDir ? onDirClick(file.name) : onFileClick(file.name)}
            className="w-full flex items-center gap-3 p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] transition-colors text-left"
          >
            {file.isDir ? (
              <Folder className="w-5 h-5 text-blue-500" />
            ) : (
              <FileText className="w-5 h-5 text-gray-500" />
            )}
            <div className="flex-1 truncate">
              <span className="font-medium">{file.name}</span>
              {!file.isDir && file.size !== undefined && (
                <span className="ml-2 text-xs text-[var(--muted)]">
                  {(file.size / 1024).toFixed(1)} KB
                </span>
              )}
            </div>
            {file.updatedAt && (
              <span className="text-xs text-[var(--muted)]">
                {new Date(file.updatedAt).toLocaleDateString()}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
