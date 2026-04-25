import { clsx } from "clsx";
import { FilePlus, FolderPlus, RefreshCw, Upload } from "lucide-react";
import { type DragEvent, type KeyboardEvent, type MouseEvent, useRef, useState } from "react";
import { FileNameDialog } from "../components/FileNameDialog";
import { VirtualList } from "../components/virtual/VirtualList";
import type { GitTreeDecorationKind } from "../services/types";
import { type FileTreeNode, type UseFileTreeResult } from "./useFileTree";

type Props = {
  tree: UseFileTreeResult;
  onOpenFile: (path: string) => void;
  onCreatedFile: (path: string, content: string, lastModifiedNs?: string) => void;
  onRenamedFile: (oldPath: string, nextPath: string) => void;
  onDeletedFile: (path: string) => void;
  onRequestPreview: (path: string) => void;
  onRequestDiff?: (path: string) => void | Promise<void>;
  onRequestUpload: (files: File[]) => Promise<void>;
  gitDecorations: Record<string, GitTreeDecorationKind>;
  onRefreshGitDecorations: () => Promise<void>;
  onRequestSetWorkdir: (path: string) => void;
  structureOnly?: boolean;
  focused: boolean;
  onToggleFocus: () => void;
};

type TreeContextMenuState = {
  entry: FileTreeNode;
  absolutePath: string;
  x: number;
  y: number;
};

type FileTreeVisibleRow =
  | { type: "entry"; entry: FileTreeNode; depth: number }
  | { type: "status"; branchPath: string; depth: number; text: string; tone: "muted" | "error" };

const TREE_CONTEXT_MENU_WIDTH_PX = 152;
const TREE_CONTEXT_MENU_PADDING_PX = 8;
const INTERNAL_FILE_DRAG_TYPE = "application/x-tcb-file-path";

function branchLabel(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function clamp(value: number, min: number, max: number) {
  if (min > max) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

function joinAbsoluteTreePath(rootPath: string, path: string) {
  if (!path) {
    return rootPath;
  }
  const trimmedRoot = rootPath.replace(/[\\/]+$/, "");
  if (!trimmedRoot) {
    return path;
  }
  const separator = trimmedRoot.includes("\\") ? "\\" : "/";
  const normalizedPath = path.replace(/[\\/]+/g, separator);
  return `${trimmedRoot}${separator}${normalizedPath}`;
}

function resolveContextMenuPosition(x: number, y: number, isDir: boolean) {
  const estimatedHeight = isDir ? 96 : 192;
  return {
    x: clamp(x, TREE_CONTEXT_MENU_PADDING_PX, window.innerWidth - TREE_CONTEXT_MENU_WIDTH_PX - TREE_CONTEXT_MENU_PADDING_PX),
    y: clamp(y, TREE_CONTEXT_MENU_PADDING_PX, window.innerHeight - estimatedHeight - TREE_CONTEXT_MENU_PADDING_PX),
  };
}

function parentTreePath(path: string) {
  const lastSlash = path.lastIndexOf("/");
  return lastSlash >= 0 ? path.slice(0, lastSlash) : "";
}

function dataTransferTypes(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer?.types || []);
}

function hasInternalTreeEntryDrag(event: DragEvent<HTMLElement>) {
  return dataTransferTypes(event).includes(INTERNAL_FILE_DRAG_TYPE);
}

function canMoveTreeEntryToDirectory(sourcePath: string, targetDirectoryPath: string) {
  if (!sourcePath || parentTreePath(sourcePath) === targetDirectoryPath) {
    return false;
  }
  if (sourcePath === targetDirectoryPath || targetDirectoryPath.startsWith(`${sourcePath}/`)) {
    return false;
  }
  return true;
}

function resolveGitDecoration(
  path: string,
  isDir: boolean,
  gitDecorations: Record<string, GitTreeDecorationKind>,
) {
  const direct = gitDecorations[path];
  if (direct === "ignored" || direct === "added" || !isDir) {
    return direct;
  }

  let inherited: GitTreeDecorationKind | undefined = direct === "modified" ? "modified" : undefined;
  const prefix = `${path}/`;
  for (const [candidate, decoration] of Object.entries(gitDecorations)) {
    if (!candidate.startsWith(prefix)) {
      continue;
    }
    if (decoration === "added") {
      return "added";
    }
    if (decoration === "modified") {
      inherited = "modified";
    }
  }
  return inherited;
}

function treeItemToneClass(gitDecoration?: GitTreeDecorationKind) {
  if (gitDecoration === "ignored") {
    return "text-[var(--muted)]";
  }
  if (gitDecoration === "added") {
    return "text-emerald-500 font-semibold";
  }
  if (gitDecoration === "modified") {
    return "text-yellow-400 font-semibold";
  }
  return "text-[var(--text)] font-semibold";
}

type TreeIconKind =
  | "folder-closed"
  | "folder-open"
  | "file-env"
  | "file-git"
  | "file-json"
  | "file-ini"
  | "file-html"
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

const JSON_FILE_EXTENSIONS = new Set([
  "json",
  "jsonc",
  "json5",
]);

const HTML_FILE_EXTENSIONS = new Set([
  "html",
  "htm",
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

  if (normalized.startsWith(".env")) {
    return "file-env";
  }
  if (normalized.startsWith(".git")) {
    return "file-git";
  }
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
  if (JSON_FILE_EXTENSIONS.has(extension)) {
    return "file-json";
  }
  if (extension === "ini") {
    return "file-ini";
  }
  if (HTML_FILE_EXTENSIONS.has(extension)) {
    return "file-html";
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
    case "file-env":
      return "text-lime-700";
    case "file-git":
      return "text-orange-600";
    case "file-json":
      return "text-amber-700";
    case "file-ini":
      return "text-slate-600";
    case "file-html":
      return "text-orange-600";
    case "file-js-ts":
      return "text-sky-600";
    case "file-python":
      return "text-[var(--muted)]";
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

function FileBadgeIcon({ kind, label, className }: { kind: Exclude<TreeIconKind, "folder-closed" | "folder-open">; label: string; className?: string }) {
  const typographyClass = label.length >= 4
    ? "text-[5.75px] tracking-[-0.1em]"
    : label.length >= 3
      ? "text-[7.25px] tracking-[-0.08em]"
    : label.length === 2
      ? "text-[8.75px] tracking-[-0.04em]"
      : "text-[10px]";

  return (
    <span
      aria-hidden="true"
      data-icon={kind}
      className={clsx(
        "inline-flex h-4 w-4 shrink-0 select-none items-center justify-center font-black leading-none",
        treeIconToneClass(kind),
        typographyClass,
        className,
      )}
    >
      {label}
    </span>
  );
}

function ShellIcon({ kind }: { kind: "file-shell" }) {
  return (
    <span aria-hidden="true" data-icon={kind} className={clsx("inline-flex h-4 w-4 shrink-0 items-center justify-center", treeIconToneClass(kind))}>
      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2.75" y="3.25" width="14.5" height="13.5" rx="2.25" />
        <path d="M6.1 8.15 8.65 10 6.1 11.85" />
        <path d="M10 12.1h3.6" />
      </svg>
    </span>
  );
}

function GitBranchIcon({ kind }: { kind: "file-git" }) {
  return (
    <span aria-hidden="true" data-icon={kind} className={clsx("inline-flex h-4 w-4 shrink-0 items-center justify-center", treeIconToneClass(kind))}>
      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="6" cy="4.5" r="1.9" />
        <circle cx="14" cy="6.25" r="1.9" />
        <circle cx="6" cy="15.5" r="1.9" />
        <path d="M6 6.4v7.2" />
        <path d="M8 6.1c1 .7 2.15 1.05 3.35 1.05H12.1" />
      </svg>
    </span>
  );
}

function IniGearIcon({ kind }: { kind: "file-ini" }) {
  return (
    <span aria-hidden="true" data-icon={kind} className={clsx("inline-flex h-4 w-4 shrink-0 items-center justify-center", treeIconToneClass(kind))}>
      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 3.15 11 4.55l1.68-.2.82 1.48 1.63.62-.28 1.66 1.35 1.02-1.02 1.35.28 1.66-1.63.62-.82 1.48-1.68-.2-1 1.4-1-1.4-1.68.2-.82-1.48-1.63-.62.28-1.66-1.02-1.35 1.35-1.02-.28-1.66 1.63-.62.82-1.48 1.68.2z" />
        <circle cx="10" cy="10" r="2.15" />
      </svg>
    </span>
  );
}

function PythonIcon({ kind }: { kind: "file-python" }) {
  return (
    <span aria-hidden="true" data-icon={kind} className="inline-flex h-4 w-4 shrink-0 items-center justify-center">
      <svg viewBox="0 0 20 20" className="h-4 w-4">
        <path fill="#3776AB" d="M10 2.2H7.45A3.25 3.25 0 0 0 4.2 5.45v2.1h5.15c1 0 1.8.8 1.8 1.8v1.55h1.4a3.25 3.25 0 0 0 3.25-3.25V5.45A3.25 3.25 0 0 0 12.65 2.2z" />
        <circle cx="8.1" cy="4.75" r=".8" fill="#fff" />
        <path fill="#FFD43B" d="M10 17.8h2.55a3.25 3.25 0 0 0 3.25-3.25V12.4h-5.15a1.8 1.8 0 0 0-1.8 1.8v1.55H7.45A3.25 3.25 0 0 1 4.2 12.5v2.05a3.25 3.25 0 0 0 3.25 3.25z" />
        <circle cx="11.9" cy="15.25" r=".8" fill="#fff" />
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
    case "file-env":
      return <FileBadgeIcon kind={kind} label=".env" />;
    case "file-git":
      return <GitBranchIcon kind={kind} />;
    case "file-json":
      return <FileBadgeIcon kind={kind} label="{…}" />;
    case "file-ini":
      return <IniGearIcon kind={kind} />;
    case "file-html":
      return <FileBadgeIcon kind={kind} label="</>" />;
    case "file-js-ts":
      return <FileBadgeIcon kind={kind} label="JS" />;
    case "file-python":
      return <PythonIcon kind={kind} />;
    case "file-c-cpp":
      return <FileBadgeIcon kind={kind} label="C++" />;
    case "file-shell":
      return <ShellIcon kind={kind} />;
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
      return <FileBadgeIcon kind={kind} label="FI" />;
  }
}

export function FileTreePane({
  tree,
  onOpenFile,
  onCreatedFile,
  onRenamedFile,
  onDeletedFile,
  onRequestPreview,
  onRequestDiff,
  onRequestUpload,
  gitDecorations,
  onRefreshGitDecorations,
  onRequestSetWorkdir,
  structureOnly = false,
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
  const [contextMenu, setContextMenu] = useState<TreeContextMenuState | null>(null);
  const [dragDepth, setDragDepth] = useState(0);
  const [draggedEntryPath, setDraggedEntryPath] = useState("");
  const [dropTargetPath, setDropTargetPath] = useState("");
  const [actionError, setActionError] = useState("");
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const contextMenuDecoration = contextMenu
    ? resolveGitDecoration(contextMenu.entry.path, contextMenu.entry.isDir, gitDecorations)
    : undefined;

  function closeContextMenu() {
    setContextMenu(null);
  }

  function resetInternalDrag() {
    setDraggedEntryPath("");
    setDropTargetPath("");
  }

  function openRenameDialog(path: string, name: string) {
    setRenameTargetPath(path);
    setRenameValue(name);
    setRenameError("");
    setShowRenameDialog(true);
  }

  function openContextMenu(entry: FileTreeNode, absolutePath: string, x: number, y: number) {
    const position = resolveContextMenuPosition(x, y, entry.isDir);
    setContextMenu({
      entry,
      absolutePath,
      x: position.x,
      y: position.y,
    });
  }

  function handleEntryContextMenu(event: MouseEvent<HTMLButtonElement>, entry: FileTreeNode, absolutePath: string) {
    if (structureOnly) {
      return;
    }
    event.preventDefault();
    openContextMenu(entry, absolutePath, event.clientX, event.clientY);
  }

  function handleEntryContextMenuKey(event: KeyboardEvent<HTMLButtonElement>, entry: FileTreeNode, absolutePath: string) {
    if (structureOnly) {
      return;
    }
    if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) {
      return;
    }
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    openContextMenu(entry, absolutePath, rect.left + 12, rect.bottom + 4);
  }

  async function handleCreateFile() {
    setCreateFileBusy(true);
    setCreateFileError("");
    setActionError("");
    try {
      const result = await tree.createFile(pendingFileName.trim(), "");
      setShowCreateFileDialog(false);
      setPendingFileName("");
      onCreatedFile(result.path, "", result.lastModifiedNs);
      await onRefreshGitDecorations();
    } catch (error) {
      setCreateFileError(error instanceof Error ? error.message : "新建文件失败");
    } finally {
      setCreateFileBusy(false);
    }
  }

  async function handleRenameFile() {
    setRenameBusy(true);
    setRenameError("");
    setActionError("");
    try {
      const result = await tree.renameFile(renameTargetPath, renameValue.trim());
      closeContextMenu();
      setShowRenameDialog(false);
      setRenameTargetPath("");
      setRenameValue("");
      onRenamedFile(result.oldPath, result.path);
      await onRefreshGitDecorations();
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
    setActionError("");
    try {
      await tree.createDirectory(name);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "新建文件夹失败");
    }
  }

  async function handleDelete(entry: FileTreeNode) {
    const message = entry.isDir
      ? `确定删除文件夹 ${entry.path} 吗？此操作会递归删除其中的所有内容。`
      : `确定删除文件 ${entry.path} 吗？`;
    if (!window.confirm(message)) {
      return;
    }

    setActionError("");
    try {
      await tree.deletePath(entry.path);
      if (!entry.isDir) {
        onDeletedFile(entry.path);
      }
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "删除失败");
    }
  }

  async function handleCopyFile(path: string) {
    setActionError("");
    try {
      await tree.copyFile(path);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "复制失败");
    }
  }

  async function handleMoveFile(path: string, targetParentPath: string) {
    if (!canMoveTreeEntryToDirectory(path, targetParentPath)) {
      return;
    }
    setActionError("");
    try {
      const result = await tree.moveFile(path, targetParentPath);
      onRenamedFile(result.oldPath, result.path);
      await onRefreshGitDecorations();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "移动失败");
    } finally {
      resetInternalDrag();
    }
  }

  function handleEntryDragStart(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (structureOnly) {
      event.preventDefault();
      return;
    }
    setDraggedEntryPath(entry.path);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(INTERNAL_FILE_DRAG_TYPE, entry.path);
    event.dataTransfer.setData("text/plain", entry.path);
  }

  function handleDirectoryDragOver(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (structureOnly || !entry.isDir || !hasInternalTreeEntryDrag(event)) {
      return;
    }
    const sourcePath = draggedEntryPath || event.dataTransfer.getData(INTERNAL_FILE_DRAG_TYPE);
    if (!canMoveTreeEntryToDirectory(sourcePath, entry.path)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setDropTargetPath(entry.path);
  }

  function handleDirectoryDragLeave(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (!hasInternalTreeEntryDrag(event)) {
      return;
    }
    const relatedTarget = event.relatedTarget;
    if (relatedTarget instanceof Node && event.currentTarget.contains(relatedTarget)) {
      return;
    }
    setDropTargetPath((current) => current === entry.path ? "" : current);
  }

  function handleDirectoryDrop(event: DragEvent<HTMLButtonElement>, entry: FileTreeNode) {
    if (structureOnly || !entry.isDir || !hasInternalTreeEntryDrag(event)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const sourcePath = event.dataTransfer.getData(INTERNAL_FILE_DRAG_TYPE);
    void handleMoveFile(sourcePath, entry.path);
  }

  async function handleUpload(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setActionError("");
    await onRequestUpload(files);
    await tree.refreshRoot({ preserveExpandedPaths: true });
    await onRefreshGitDecorations();
  }

  async function handleRefresh() {
    setActionError("");
    await tree.refreshRoot({ preserveExpandedPaths: true });
    await onRefreshGitDecorations();
  }

  function flattenBranch(entries: FileTreeNode[], depth: number): FileTreeVisibleRow[] {
    const rows: FileTreeVisibleRow[] = [];
    for (const entry of entries) {
      rows.push({ type: "entry", entry, depth });
      if (!entry.isDir || !tree.isExpanded(entry.path)) {
        continue;
      }
      const branch = tree.branches[entry.path];
      if (branch?.loading) {
        rows.push({ type: "status", branchPath: entry.path, depth: depth + 1, text: "加载中...", tone: "muted" });
      }
      if (branch?.error) {
        rows.push({ type: "status", branchPath: entry.path, depth: depth + 1, text: branch.error, tone: "error" });
      }
      if (branch?.entries?.length) {
        rows.push(...flattenBranch(branch.entries, depth + 1));
      }
    }
    return rows;
  }

  function renderTreeRow(row: FileTreeVisibleRow) {
    if (row.type === "status") {
      return (
        <div
          className={clsx("flex h-full items-center px-2 text-[11px]", row.tone === "error" ? "text-red-700" : "text-[var(--muted)]")}
          style={{ paddingLeft: `${row.depth * 12 + 24}px` }}
        >
          {row.text}
        </div>
      );
    }

    const { entry, depth } = row;
    const expanded = tree.isExpanded(entry.path);
    const dirLabel = branchLabel(entry.path);
    const absolutePath = joinAbsoluteTreePath(tree.rootPath, entry.path);
    const iconKind = entry.isDir
      ? (expanded ? "folder-open" : "folder-closed")
      : getFileIconKind(entry.name);
    const gitDecoration = resolveGitDecoration(entry.path, entry.isDir, gitDecorations);
    const isIgnored = gitDecoration === "ignored";
    const itemToneClass = treeItemToneClass(gitDecoration);

    return (
      <div
        className="group flex h-full min-w-0 items-center rounded-md text-[12px]"
        data-tree-path={entry.path}
        data-git-state={gitDecoration || "clean"}
        data-git-ignored={isIgnored ? "true" : "false"}
        data-highlighted={tree.highlightedPath === entry.path ? "true" : "false"}
        data-drop-target={dropTargetPath === entry.path ? "true" : "false"}
        style={{ paddingLeft: `${depth * 12}px` }}
      >
        {entry.isDir ? (
          <button
            type="button"
            draggable={!structureOnly}
            aria-label={`${expanded ? "收起" : "展开"} ${entry.path}`}
            onContextMenu={(event) => handleEntryContextMenu(event, entry, absolutePath)}
            onKeyDown={(event) => handleEntryContextMenuKey(event, entry, absolutePath)}
            onDragStart={(event) => handleEntryDragStart(event, entry)}
            onDragOver={(event) => handleDirectoryDragOver(event, entry)}
            onDragLeave={(event) => handleDirectoryDragLeave(event, entry)}
            onDrop={(event) => handleDirectoryDrop(event, entry)}
            onDragEnd={resetInternalDrag}
            onClick={() => void tree.toggleDirectory(entry.path)}
            className={clsx(
              "min-w-0 flex-1 rounded px-2 py-0.5 text-left hover:bg-[var(--surface-strong)]",
              dropTargetPath === entry.path && "bg-[var(--accent-soft)] outline outline-1 outline-[var(--accent)]",
              itemToneClass,
            )}
          >
            <span className="flex min-w-0 items-center gap-2">
              <TreeNodeIcon kind={iconKind} />
              <span className="truncate">{dirLabel}</span>
            </span>
          </button>
        ) : (
          <button
            type="button"
            draggable={!structureOnly}
            aria-label={`打开 ${entry.path}`}
            onContextMenu={(event) => handleEntryContextMenu(event, entry, absolutePath)}
            onKeyDown={(event) => handleEntryContextMenuKey(event, entry, absolutePath)}
            onDragStart={(event) => handleEntryDragStart(event, entry)}
            onDragEnd={resetInternalDrag}
            onClick={() => {
              if (!structureOnly) {
                onOpenFile(entry.path);
              }
            }}
            className={clsx("min-w-0 flex-1 rounded px-2 py-0.5 text-left hover:bg-[var(--surface-strong)]", itemToneClass)}
          >
            <span className="flex min-w-0 items-center gap-2">
              <TreeNodeIcon kind={iconKind} />
              <span className="truncate">{entry.name}</span>
            </span>
          </button>
        )}
      </div>
    );
  }

  const visibleTreeRows = !tree.loading && !tree.error ? flattenBranch(tree.rootEntries, 0) : [];

  return (
    <div
      data-testid="desktop-file-tree-dropzone"
      onDragEnter={(event) => {
        if (hasInternalTreeEntryDrag(event)) {
          return;
        }
        event.preventDefault();
        setDragDepth((current) => current + 1);
      }}
      onDragOver={(event) => {
        if (hasInternalTreeEntryDrag(event)) {
          return;
        }
        event.preventDefault();
      }}
      onDragLeave={(event) => {
        if (hasInternalTreeEntryDrag(event)) {
          return;
        }
        event.preventDefault();
        setDragDepth((current) => Math.max(0, current - 1));
      }}
      onDrop={(event) => {
        if (hasInternalTreeEntryDrag(event)) {
          event.preventDefault();
          resetInternalDrag();
          return;
        }
        event.preventDefault();
        if (structureOnly) {
          return;
        }
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
          {!structureOnly ? (
            <>
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
            </>
          ) : null}
          <button
            type="button"
            aria-label="刷新文件树"
            title="刷新文件树"
            onClick={() => void handleRefresh()}
            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          {!structureOnly ? (
            <>
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
            </>
          ) : null}
        </div>
      </div>

      <div data-testid="desktop-file-tree-scroll" className="flex min-h-0 flex-1 flex-col px-2 py-2">
        {actionError ? (
          <div className="mb-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-[12px] text-red-700">
            {actionError}
          </div>
        ) : null}
        {tree.loading ? (
          <div className="px-2 py-2 text-[12px] text-[var(--muted)]">加载中...</div>
        ) : null}
        {!tree.loading && tree.error ? (
          <div className="px-2 py-2 text-[12px] text-red-700">{tree.error}</div>
        ) : null}
        {!tree.loading && !tree.error ? (
          <VirtualList
            items={visibleTreeRows}
            rowHeight={28}
            className="flex-1"
            dataTestId="desktop-file-tree-virtual-list"
            getKey={(row) => row.type === "entry" ? row.entry.path : `${row.branchPath}-${row.tone}`}
            renderRow={(row) => renderTreeRow(row)}
          />
        ) : null}
      </div>

      {contextMenu ? (
        <>
          <div
            className="fixed inset-0 z-20"
            onClick={closeContextMenu}
            onContextMenu={(event) => {
              event.preventDefault();
              closeContextMenu();
            }}
          />
          <div
            role="menu"
            aria-label="文件树菜单"
            className="fixed z-30 min-w-36 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]"
            style={{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }}
            onContextMenu={(event) => {
              event.preventDefault();
            }}
          >
            {contextMenu.entry.isDir ? (
              <button
                type="button"
                onClick={() => {
                  onRequestSetWorkdir(contextMenu.absolutePath);
                  closeContextMenu();
                }}
                className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
              >
                设为工作目录
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => {
                    onRequestPreview(contextMenu.entry.path);
                    closeContextMenu();
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  预览
                </button>
                {contextMenuDecoration === "modified" && onRequestDiff ? (
                  <button
                    type="button"
                    onClick={() => {
                      void onRequestDiff(contextMenu.entry.path);
                      closeContextMenu();
                    }}
                    className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                  >
                    Diff
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    openRenameDialog(contextMenu.entry.path, contextMenu.entry.name);
                    closeContextMenu();
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  改名
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const path = contextMenu.entry.path;
                    closeContextMenu();
                    void handleCopyFile(path);
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  复制
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void tree.downloadFile(contextMenu.entry.path);
                    closeContextMenu();
                  }}
                  className="flex w-full rounded-sm px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                >
                  下载
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => {
                closeContextMenu();
                void handleDelete(contextMenu.entry);
              }}
              className="flex w-full rounded-sm px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
            >
              删除
            </button>
          </div>
        </>
      ) : null}

      {!structureOnly && dragDepth > 0 ? (
        <div
          data-testid="desktop-file-drop-overlay"
          className="pointer-events-none absolute inset-3 flex items-center justify-center rounded-2xl border border-dashed border-[var(--accent)] bg-[var(--accent-soft)] text-sm font-medium text-[var(--text)]"
        >
          释放文件以上传到当前工作区根目录
        </div>
      ) : null}

      {!structureOnly && showCreateFileDialog ? (
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

      {!structureOnly && showRenameDialog ? (
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
