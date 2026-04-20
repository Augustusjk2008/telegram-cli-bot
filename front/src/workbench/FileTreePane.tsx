import { Bot, Download, Eye, FilePlus, FolderPlus, Pencil, RefreshCw, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { FileNameDialog } from "../components/FileNameDialog";
import { type FileTreeNode, type UseFileTreeResult } from "./useFileTree";

type Props = {
  tree: UseFileTreeResult;
  onOpenFile: (path: string) => void;
  onCreatedFile: (path: string, content: string, lastModifiedNs?: string) => void;
  onRenamedFile: (oldPath: string, nextPath: string) => void;
  onDeletedFile: (path: string) => void;
  onRequestPreview: (path: string) => void;
  onRequestUpload: (files: File[]) => Promise<void>;
  onRequestSetWorkdir: (path: string) => void;
  focused: boolean;
  onToggleFocus: () => void;
};

function branchLabel(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

type TreeIconKind =
  | "folder-closed"
  | "folder-open"
  | "file-js-ts"
  | "file-python"
  | "file-c-cpp"
  | "file-shell"
  | "file-csharp"
  | "file-code"
  | "file-config"
  | "file-markdown"
  | "file-text"
  | "file-document"
  | "file-pdf"
  | "file-sheet"
  | "file-presentation"
  | "file-image"
  | "file-audio"
  | "file-video"
  | "file-font"
  | "file-database"
  | "file-archive"
  | "file-generic";

const JS_TS_FILE_EXTENSIONS = new Set([
  "js",
  "jsx",
  "ts",
  "tsx",
  "mjs",
  "cjs",
  "mts",
  "cts",
  "vue",
  "svelte",
  "astro",
]);

const PYTHON_FILE_EXTENSIONS = new Set([
  "py",
  "pyi",
  "pyw",
  "ipynb",
]);

const C_CPP_FILE_EXTENSIONS = new Set([
  "c",
  "cc",
  "cpp",
  "cxx",
  "cp",
  "h",
  "hpp",
  "hh",
  "hxx",
  "ipp",
  "inl",
  "ixx",
  "tpp",
  "txx",
  "m",
  "mm",
]);

const SHELL_FILE_EXTENSIONS = new Set([
  "sh",
  "bash",
  "zsh",
  "fish",
  "ksh",
  "ps1",
  "psm1",
  "psd1",
  "bat",
  "cmd",
  "nu",
]);

const SHELL_FILE_NAMES = new Set([
  ".bashrc",
  ".bash_profile",
  ".bash_aliases",
  ".profile",
  ".zshrc",
  ".zprofile",
  ".zshenv",
  ".zlogin",
  ".zlogout",
  "gradlew",
  "mvnw",
]);

const CSHARP_FILE_EXTENSIONS = new Set([
  "cs",
  "csx",
  "csproj",
  "sln",
]);

const GENERIC_CODE_FILE_EXTENSIONS = new Set([
  "java",
  "go",
  "rs",
  "rb",
  "php",
  "swift",
  "kt",
  "kts",
  "scala",
  "lua",
  "dart",
  "r",
  "pl",
  "pm",
  "zig",
  "hs",
  "elm",
  "ex",
  "exs",
  "erl",
  "hrl",
  "ml",
  "mli",
  "clj",
  "cljs",
  "cljc",
  "fs",
  "fsi",
  "fsx",
  "vb",
  "html",
  "htm",
  "css",
  "scss",
  "sass",
  "less",
  "vue",
  "svelte",
  "astro",
]);

const CONFIG_FILE_EXTENSIONS = new Set([
  "json",
  "jsonc",
  "yaml",
  "yml",
  "toml",
  "ini",
  "conf",
  "cfg",
  "json5",
  "lock",
  "properties",
  "xml",
  "plist",
  "cmake",
]);

const CONFIG_FILE_NAMES = new Set([
  ".dockerignore",
  "dockerfile",
  "makefile",
  ".env",
  ".env.local",
  ".env.development",
  ".env.production",
  ".gitignore",
  ".gitattributes",
  ".editorconfig",
  ".npmrc",
  ".nvmrc",
  ".yarnrc",
  ".yarnrc.yml",
  ".prettierrc",
  ".prettierignore",
  ".eslintrc",
  ".eslintignore",
  ".stylelintrc",
  ".stylelintignore",
  "package.json",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
  "bun.lock",
  "bun.lockb",
  "tsconfig.json",
  "jsconfig.json",
  "deno.json",
  "deno.jsonc",
  "turbo.json",
  "nx.json",
  "lerna.json",
  "vite.config.ts",
  "vite.config.js",
  "vitest.config.ts",
  "vitest.config.js",
  "eslint.config.js",
  "eslint.config.mjs",
  "eslint.config.cjs",
  "eslint.config.ts",
  "prettier.config.js",
  "prettier.config.mjs",
  "prettier.config.cjs",
  "prettier.config.ts",
  "tailwind.config.js",
  "tailwind.config.cjs",
  "tailwind.config.ts",
  "postcss.config.js",
  "postcss.config.cjs",
  "postcss.config.mjs",
  "postcss.config.ts",
  "jest.config.js",
  "jest.config.cjs",
  "jest.config.mjs",
  "jest.config.ts",
  "webpack.config.js",
  "webpack.config.cjs",
  "webpack.config.ts",
  "rollup.config.js",
  "rollup.config.mjs",
  "rollup.config.ts",
  "babel.config.js",
  "babel.config.cjs",
  "babel.config.mjs",
  "babel.config.json",
  "next.config.js",
  "next.config.mjs",
  "next.config.ts",
  "nuxt.config.ts",
  "nuxt.config.js",
  "svelte.config.js",
  "svelte.config.ts",
  "astro.config.mjs",
  "astro.config.ts",
  "docker-compose.yml",
  "docker-compose.yaml",
  "compose.yml",
  "compose.yaml",
  "pyproject.toml",
  "poetry.lock",
  "pdm.lock",
  "uv.lock",
  "pipfile",
  "pipfile.lock",
  "requirements.txt",
  "requirements-dev.txt",
  "cargo.toml",
  "cargo.lock",
  "go.mod",
  "go.sum",
  "gemfile",
  "gemfile.lock",
  "composer.json",
  "composer.lock",
  "podfile",
  "podfile.lock",
  "cmakelists.txt",
  "meson.build",
  "meson.options",
  "build.gradle",
  "build.gradle.kts",
  "settings.gradle",
  "settings.gradle.kts",
  "gradle.properties",
  "procfile",
  "jenkinsfile",
]);

const MARKDOWN_FILE_EXTENSIONS = new Set([
  "md",
  "mdx",
  "markdown",
  "mkd",
  "mdown",
  "rst",
]);

const TEXT_FILE_EXTENSIONS = new Set([
  "txt",
  "log",
  "text",
]);

const DOCUMENT_FILE_EXTENSIONS = new Set([
  "doc",
  "docx",
  "odt",
  "rtf",
  "pages",
]);

const PDF_FILE_EXTENSIONS = new Set([
  "pdf",
]);

const SHEET_FILE_EXTENSIONS = new Set([
  "csv",
  "tsv",
  "xls",
  "xlsx",
  "ods",
]);

const PRESENTATION_FILE_EXTENSIONS = new Set([
  "ppt",
  "pptx",
  "odp",
  "key",
]);

const IMAGE_FILE_EXTENSIONS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "bmp",
  "ico",
  "avif",
  "heic",
  "heif",
  "tif",
  "tiff",
  "psd",
  "ai",
  "eps",
]);

const AUDIO_FILE_EXTENSIONS = new Set([
  "mp3",
  "wav",
  "flac",
  "aac",
  "ogg",
  "m4a",
  "opus",
  "aiff",
  "mid",
  "midi",
]);

const VIDEO_FILE_EXTENSIONS = new Set([
  "mp4",
  "mov",
  "mkv",
  "avi",
  "webm",
  "m4v",
  "wmv",
  "flv",
  "mpeg",
  "mpg",
]);

const FONT_FILE_EXTENSIONS = new Set([
  "ttf",
  "otf",
  "woff",
  "woff2",
  "eot",
  "fon",
]);

const DATABASE_FILE_EXTENSIONS = new Set([
  "sql",
  "db",
  "db3",
  "sqlite",
  "sqlite3",
  "mdb",
  "accdb",
  "parquet",
  "duckdb",
]);

const ARCHIVE_FILE_EXTENSIONS = new Set([
  "zip",
  "tar",
  "gz",
  "tgz",
  "rar",
  "7z",
  "bz2",
  "xz",
  "lz",
  "lz4",
  "cab",
  "iso",
  "zst",
]);

function normalizedFileName(name: string) {
  return name.trim().toLowerCase();
}

function getFileExtension(name: string) {
  const normalized = normalizedFileName(name);
  if (!normalized) {
    return "";
  }
  if (normalized.startsWith(".") && normalized.indexOf(".", 1) === -1) {
    return normalized;
  }
  const lastDotIndex = normalized.lastIndexOf(".");
  if (lastDotIndex < 0 || lastDotIndex === normalized.length - 1) {
    return "";
  }
  return normalized.slice(lastDotIndex + 1);
}

function getFileIconKind(name: string): TreeIconKind {
  const normalized = normalizedFileName(name);
  const extension = getFileExtension(name);

  if (IMAGE_FILE_EXTENSIONS.has(extension)) {
    return "file-image";
  }
  if (AUDIO_FILE_EXTENSIONS.has(extension)) {
    return "file-audio";
  }
  if (VIDEO_FILE_EXTENSIONS.has(extension)) {
    return "file-video";
  }
  if (FONT_FILE_EXTENSIONS.has(extension)) {
    return "file-font";
  }
  if (ARCHIVE_FILE_EXTENSIONS.has(extension)) {
    return "file-archive";
  }
  if (PDF_FILE_EXTENSIONS.has(extension)) {
    return "file-pdf";
  }
  if (SHEET_FILE_EXTENSIONS.has(extension)) {
    return "file-sheet";
  }
  if (PRESENTATION_FILE_EXTENSIONS.has(extension)) {
    return "file-presentation";
  }
  if (DOCUMENT_FILE_EXTENSIONS.has(extension)) {
    return "file-document";
  }
  if (DATABASE_FILE_EXTENSIONS.has(extension)) {
    return "file-database";
  }
  if (SHELL_FILE_NAMES.has(normalized)) {
    return "file-shell";
  }
  if (
    CONFIG_FILE_NAMES.has(normalized)
    || CONFIG_FILE_EXTENSIONS.has(extension)
    || normalized.startsWith(".env")
  ) {
    return "file-config";
  }
  if (MARKDOWN_FILE_EXTENSIONS.has(extension)) {
    return "file-markdown";
  }
  if (TEXT_FILE_EXTENSIONS.has(extension)) {
    return "file-text";
  }
  if (JS_TS_FILE_EXTENSIONS.has(extension) || normalized.endsWith(".d.ts")) {
    return "file-js-ts";
  }
  if (PYTHON_FILE_EXTENSIONS.has(extension)) {
    return "file-python";
  }
  if (C_CPP_FILE_EXTENSIONS.has(extension)) {
    return "file-c-cpp";
  }
  if (SHELL_FILE_EXTENSIONS.has(extension)) {
    return "file-shell";
  }
  if (CSHARP_FILE_EXTENSIONS.has(extension)) {
    return "file-csharp";
  }
  if (GENERIC_CODE_FILE_EXTENSIONS.has(extension)) {
    return "file-code";
  }
  return "file-generic";
}

function treeIconToneClass(kind: TreeIconKind) {
  switch (kind) {
    case "folder-closed":
    case "folder-open":
      return "text-amber-600";
    case "file-js-ts":
      return "text-sky-600";
    case "file-python":
      return "text-emerald-600";
    case "file-c-cpp":
      return "text-cyan-700";
    case "file-shell":
      return "text-lime-700";
    case "file-csharp":
      return "text-violet-600";
    case "file-code":
      return "text-indigo-600";
    case "file-config":
      return "text-fuchsia-600";
    case "file-markdown":
      return "text-emerald-700";
    case "file-text":
      return "text-slate-600";
    case "file-document":
      return "text-slate-700";
    case "file-pdf":
      return "text-red-600";
    case "file-sheet":
      return "text-teal-600";
    case "file-presentation":
      return "text-orange-600";
    case "file-image":
      return "text-rose-600";
    case "file-audio":
      return "text-pink-600";
    case "file-video":
      return "text-indigo-500";
    case "file-font":
      return "text-amber-700";
    case "file-database":
      return "text-cyan-600";
    case "file-archive":
      return "text-stone-600";
    default:
      return "text-[var(--muted)]";
  }
}

function FileBadgeIcon({ kind, label }: { kind: Exclude<TreeIconKind, "folder-closed" | "folder-open" | "file-generic">; label: string }) {
  const className = `inline-flex h-4 w-4 shrink-0 items-center justify-center ${treeIconToneClass(kind)}`;
  const fontSize = label.length >= 3 ? 3.1 : 4.05;

  return (
    <span aria-hidden="true" data-icon={kind} className={className}>
      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 2.75h5.5l3 3V16A1.25 1.25 0 0 1 13.25 17.25h-7.5A1.25 1.25 0 0 1 4.5 16V4A1.25 1.25 0 0 1 6 2.75Z" />
        <path d="M11.5 2.9v3h2.9" />
        <text
          x="9.9"
          y="12.25"
          fill="currentColor"
          stroke="none"
          textAnchor="middle"
          fontSize={fontSize}
          fontWeight="700"
          fontFamily="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
          letterSpacing={label.length >= 3 ? "-0.15px" : "0"}
        >
          {label}
        </text>
      </svg>
    </span>
  );
}

function TreeNodeIcon({ kind }: { kind: TreeIconKind }) {
  const className = `inline-flex h-4 w-4 shrink-0 items-center justify-center ${treeIconToneClass(kind)}`;

  switch (kind) {
    case "folder-closed":
      return (
        <span aria-hidden="true" data-icon={kind} className={className}>
          <svg viewBox="0 0 20 20" className="h-4 w-4 fill-current">
            <path d="M2.75 5.5A2.25 2.25 0 0 1 5 3.25h3.08c.44 0 .86.18 1.18.49l.73.73c.14.14.33.22.53.22H15a2.25 2.25 0 0 1 2.25 2.25v6.3A2.25 2.25 0 0 1 15 15.5H5a2.25 2.25 0 0 1-2.25-2.25z" />
          </svg>
        </span>
      );
    case "folder-open":
      return (
        <span aria-hidden="true" data-icon={kind} className={className}>
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2.75 6h4.14c.43 0 .84-.17 1.15-.48l.65-.64c.3-.3.71-.48 1.15-.48H15a2 2 0 0 1 2 2v.5" />
            <path d="M3.1 8.4h13.8l-1 5.12A1.9 1.9 0 0 1 14.04 15H5.95a1.9 1.9 0 0 1-1.86-1.48z" />
          </svg>
        </span>
      );
    case "file-js-ts":
      return <FileBadgeIcon kind={kind} label="JS" />;
    case "file-python":
      return <FileBadgeIcon kind={kind} label="PY" />;
    case "file-c-cpp":
      return <FileBadgeIcon kind={kind} label="C++" />;
    case "file-shell":
      return <FileBadgeIcon kind={kind} label="SH" />;
    case "file-csharp":
      return <FileBadgeIcon kind={kind} label="C#" />;
    case "file-code":
      return <FileBadgeIcon kind={kind} label="<>" />;
    case "file-config":
      return <FileBadgeIcon kind={kind} label="CFG" />;
    case "file-markdown":
      return <FileBadgeIcon kind={kind} label="MD" />;
    case "file-text":
      return <FileBadgeIcon kind={kind} label="TXT" />;
    case "file-document":
      return <FileBadgeIcon kind={kind} label="DOC" />;
    case "file-pdf":
      return <FileBadgeIcon kind={kind} label="PDF" />;
    case "file-sheet":
      return <FileBadgeIcon kind={kind} label="XLS" />;
    case "file-presentation":
      return <FileBadgeIcon kind={kind} label="PPT" />;
    case "file-image":
      return <FileBadgeIcon kind={kind} label="IMG" />;
    case "file-audio":
      return <FileBadgeIcon kind={kind} label="AUD" />;
    case "file-video":
      return <FileBadgeIcon kind={kind} label="VID" />;
    case "file-font":
      return <FileBadgeIcon kind={kind} label="FNT" />;
    case "file-database":
      return <FileBadgeIcon kind={kind} label="DB" />;
    case "file-archive":
      return <FileBadgeIcon kind={kind} label="ZIP" />;
    default:
      return (
        <span aria-hidden="true" data-icon={kind} className={className}>
          <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 2.75h5.5l3 3V16A1.25 1.25 0 0 1 13.25 17.25h-7.5A1.25 1.25 0 0 1 4.5 16V4A1.25 1.25 0 0 1 6 2.75Z" />
            <path d="M8.1 10.5h3.8" />
            <path d="M8.1 13h3.8" />
          </svg>
        </span>
      );
  }
}

export function FileTreePane({
  tree,
  onOpenFile,
  onCreatedFile,
  onRenamedFile,
  onDeletedFile,
  onRequestPreview,
  onRequestUpload,
  onRequestSetWorkdir,
  focused,
  onToggleFocus,
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
  const [dragDepth, setDragDepth] = useState(0);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);

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

  async function handleUpload(files: File[]) {
    if (files.length === 0) {
      return;
    }
    await onRequestUpload(files);
    await tree.refreshRoot({ preserveExpandedPaths: true });
  }

  function renderBranch(entries: FileTreeNode[], depth: number) {
    return (
      <ul className="space-y-0.5">
        {entries.map((entry) => {
          const expanded = tree.isExpanded(entry.path);
          const branch = tree.branches[entry.path];
          const dirLabel = branchLabel(entry.path);
          const absolutePath = `${tree.rootPath.replace(/[\\/]+$/, "")}/${entry.path}`;
          const iconKind = entry.isDir
            ? (expanded ? "folder-open" : "folder-closed")
            : getFileIconKind(entry.name);

          return (
            <li key={entry.path}>
              <div
                className="group flex min-w-0 items-center gap-1.5 rounded-md text-[12px]"
                data-highlighted={tree.highlightedPath === entry.path ? "true" : "false"}
                style={{ paddingLeft: `${depth * 12}px` }}
              >
                {entry.isDir ? (
                  <button
                    type="button"
                    aria-label={`${expanded ? "收起" : "展开"} ${entry.path}`}
                    onClick={() => void tree.toggleDirectory(entry.path)}
                    className="min-w-0 flex-1 rounded px-2 py-1 text-left text-[var(--text)] hover:bg-[var(--surface-strong)]"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <TreeNodeIcon kind={iconKind} />
                      <span className="truncate">{dirLabel}</span>
                    </span>
                  </button>
                ) : (
                  <button
                    type="button"
                    aria-label={`打开 ${entry.path}`}
                    onClick={() => onOpenFile(entry.path)}
                    className="min-w-0 flex-1 rounded px-2 py-1 text-left text-[var(--text)] hover:bg-[var(--surface-strong)]"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <TreeNodeIcon kind={iconKind} />
                      <span className="truncate">{entry.name}</span>
                    </span>
                  </button>
                )}

                {entry.isDir ? (
                  <>
                    <button
                      type="button"
                      aria-label={`设 ${entry.path} 为 Bot 工作目录`}
                      title={`设 ${entry.path} 为 Bot 工作目录`}
                      onClick={() => onRequestSetWorkdir(absolutePath)}
                      className="shrink-0 rounded p-1 text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
                    >
                      <Bot className="h-3.5 w-3.5" />
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      aria-label={`预览 ${entry.path}`}
                      title={`预览 ${entry.path}`}
                      onClick={() => onRequestPreview(entry.path)}
                      className="shrink-0 rounded p-1 text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </button>
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
    <div
      data-testid="desktop-file-tree-dropzone"
      onDragEnter={(event) => {
        event.preventDefault();
        setDragDepth((current) => current + 1);
      }}
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        setDragDepth((current) => Math.max(0, current - 1));
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragDepth(0);
        const files = Array.from(event.dataTransfer?.files || []);
        if (files.length > 0) {
          void handleUpload(files);
        }
      }}
      className="relative flex h-full min-h-0 flex-col"
    >
      <div className="border-b border-[var(--border)] px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="truncate text-[11px] text-[var(--muted)]">{tree.rootPath}</div>
          <button
            type="button"
            aria-label={focused ? "退出聚焦文件区" : "聚焦文件区"}
            onClick={onToggleFocus}
            className="rounded border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
          >
            {focused ? "恢复" : "聚焦"}
          </button>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <input
            ref={uploadInputRef}
            aria-label="上传文件"
            type="file"
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.target.files || []);
              if (files.length > 0) {
                void handleUpload(files);
              }
              event.currentTarget.value = "";
            }}
          />
          <button
            type="button"
            aria-label="上传文件"
            title="上传文件"
            onClick={() => uploadInputRef.current?.click()}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
          >
            <Upload className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="刷新文件树"
            title="刷新文件树"
            onClick={() => void tree.refreshRoot({ preserveExpandedPaths: true })}
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

      {dragDepth > 0 ? (
        <div
          data-testid="desktop-file-drop-overlay"
          className="pointer-events-none absolute inset-3 flex items-center justify-center rounded-2xl border border-dashed border-[var(--accent)] bg-[var(--accent-soft)] text-sm font-medium text-[var(--text)]"
        >
          释放文件以上传到当前工作区根目录
        </div>
      ) : null}

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
