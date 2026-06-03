import { useEffect, useRef, useState } from "react";
import { ChevronLeft, FolderOpen, FolderPlus, House } from "lucide-react";
import type { DirectoryListing } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { normalizePathInput } from "../utils/pathInput";

type Props = {
  title: string;
  botAlias: string;
  client: WebBotClient;
  initialPath?: string;
  mutateBrowseState?: boolean;
  mode?: "files" | "workdir";
  canCreateDirectory?: boolean;
  onPick: (path: string) => void;
  onClose: () => void;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

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

function isAbsoluteBrowserPath(path: string) {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("/") || path.startsWith("\\\\");
}

export function DirectoryPickerDialog({
  title,
  botAlias,
  client,
  initialPath = "",
  mutateBrowseState = true,
  mode = "files",
  canCreateDirectory = true,
  onPick,
  onClose,
}: Props) {
  const [currentPath, setCurrentPath] = useState("");
  const [entries, setEntries] = useState<DirectoryListing["entries"]>([]);
  const [isVirtualRoot, setIsVirtualRoot] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const currentPathRef = useRef("");
  const homePathRef = useRef("");
  const startPathRef = useRef("");
  const originPathRef = useRef("");
  const originWasVirtualRootRef = useRef(false);
  const restoredRef = useRef(false);

  function applyListing(listing: DirectoryListing) {
    currentPathRef.current = listing.workingDir;
    setCurrentPath(listing.workingDir);
    setEntries(listing.entries);
    setIsVirtualRoot(Boolean(listing.isVirtualRoot));
  }

  async function restoreOriginalPath() {
    if (!mutateBrowseState) {
      return true;
    }
    if (restoredRef.current) {
      return true;
    }
    restoredRef.current = true;

    const originPath = originPathRef.current;
    if (!originPath) {
      return true;
    }

    try {
      if (originWasVirtualRootRef.current) {
        const driveRootMatch = currentPathRef.current.match(/^[A-Za-z]:\\/);
        if (!driveRootMatch) {
          return true;
        }
        await client.changeDirectory(botAlias, driveRootMatch[0]);
        await client.changeDirectory(botAlias, "..");
        return true;
      }
      await client.changeDirectory(botAlias, originPath);
      return true;
    } catch (nextError) {
      restoredRef.current = false;
      setError(getErrorMessage(nextError, "恢复工作目录失败"));
      return false;
    }
  }

  async function loadCurrentDirectory() {
    const listing = mutateBrowseState
      ? await client.listFiles(botAlias)
      : await client.listFiles(botAlias, currentPathRef.current || homePathRef.current || undefined);
    applyListing(listing);
  }

  async function handleCreateDirectory() {
    if (!canCreateDirectory) {
      setError("当前账号无权新建工作目录");
      return;
    }
    const name = newFolderName.trim();
    if (!name) {
      setError("文件夹名称不能为空");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const parentPath = currentPathRef.current || currentPath;
      if (mode === "workdir") {
        await client.createWorkdirDirectory(botAlias, parentPath, name);
      } else {
        await client.createDirectory(botAlias, name, parentPath);
      }
      setNewFolderName("");
      await loadCurrentDirectory();
    } catch (nextError) {
      setError(getErrorMessage(nextError, "新建文件夹失败"));
    } finally {
      setBusy(false);
    }
  }

  async function navigate(path: string, fallback: string) {
    setBusy(true);
    setLoading(true);
    setError("");
    try {
      if (!mutateBrowseState) {
        const normalized = normalizePathInput(path);
        const targetPath = normalized === ".."
          ? getParentBrowserPath(currentPathRef.current)
          : isAbsoluteBrowserPath(normalized)
            ? normalized
            : joinBrowserPath(currentPathRef.current, normalized);
        const listing = await client.listFiles(botAlias, targetPath);
        applyListing(listing);
        return;
      }
      await client.changeDirectory(botAlias, path);
      await loadCurrentDirectory();
    } catch (nextError) {
      setError(getErrorMessage(nextError, fallback));
    } finally {
      setLoading(false);
      setBusy(false);
    }
  }

  async function closeDialog(pickedPath?: string) {
    setBusy(true);
    const restored = await restoreOriginalPath();
    if (!restored) {
      setBusy(false);
      return;
    }
    if (pickedPath) {
      onPick(pickedPath);
    }
    onClose();
  }

  useEffect(() => {
    let active = true;

    async function initialize() {
      setLoading(true);
      setError("");
      try {
        const originListing = await client.listFiles(botAlias);
        const homePath = mutateBrowseState ? await client.getCurrentPath(botAlias) : originListing.workingDir;
        if (!active) {
          return;
        }

        originPathRef.current = originListing.workingDir;
        originWasVirtualRootRef.current = Boolean(originListing.isVirtualRoot);
        homePathRef.current = homePath;

        const preferredPath = normalizePathInput(initialPath) || homePath || originListing.workingDir;
        startPathRef.current = preferredPath;
        if (preferredPath && preferredPath !== originListing.workingDir) {
          try {
            if (!mutateBrowseState) {
              const listing = await client.listFiles(botAlias, preferredPath);
              if (!active) {
                return;
              }
              applyListing(listing);
              return;
            }
            await client.changeDirectory(botAlias, preferredPath);
            if (!active) {
              return;
            }
            await loadCurrentDirectory();
            return;
          } catch (nextError) {
            if (!active) {
              return;
            }
            setError(getErrorMessage(nextError, "加载目录失败"));
          }
        }

        applyListing(originListing);
      } catch (nextError) {
        if (!active) {
          return;
        }
        setError(getErrorMessage(nextError, "加载目录失败"));
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void initialize();
    return () => {
      active = false;
      void restoreOriginalPath();
    };
  }, [botAlias, client, initialPath, mutateBrowseState]);

  const directories = entries.filter((entry) => entry.isDir);

  return (
    <div
      className="workbench-dialog-backdrop fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="workbench-dialog-panel flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-[var(--surface)] shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-[var(--text)]">{title}</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">浏览目录后直接使用当前目录。</p>
          </div>
          <button
            type="button"
            onClick={() => void closeDialog()}
            disabled={busy}
            className="rounded-lg border border-[var(--border)] px-3 py-1 text-sm disabled:opacity-60"
          >
            取消
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] px-5 py-3">
          <button
            type="button"
            onClick={() => void navigate("..", "返回上级目录失败")}
            disabled={busy || loading}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <ChevronLeft className="h-4 w-4" />
            上一级
          </button>
          <button
            type="button"
            onClick={() => void navigate(startPathRef.current, "返回起始目录失败")}
            disabled={busy || loading || !startPathRef.current}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <House className="h-4 w-4" />
            回到起点
          </button>
          <button
            type="button"
            onClick={() => void handleCreateDirectory()}
            disabled={busy || loading || isVirtualRoot || !canCreateDirectory}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <FolderPlus className="h-4 w-4" />
            新增文件夹
          </button>
          <button
            type="button"
            onClick={() => void closeDialog(normalizePathInput(currentPath))}
            disabled={busy || loading || !currentPath || isVirtualRoot}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-[var(--accent-foreground)] hover:opacity-90 disabled:opacity-60"
          >
            使用当前目录
          </button>
        </div>

        <div className="border-b border-[var(--border)] px-5 py-3">
          <p className="text-xs text-[var(--muted)]">当前目录</p>
          <p className="mt-1 break-all text-sm text-[var(--text)]">{currentPath || "加载中..."}</p>
          {isVirtualRoot ? <p className="mt-2 text-xs text-[var(--muted)]">请先选择具体目录或卷。</p> : null}
          {!isVirtualRoot && canCreateDirectory ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <input
                aria-label="新文件夹名称"
                value={newFolderName}
                onChange={(event) => setNewFolderName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleCreateDirectory();
                  }
                }}
                disabled={busy || loading}
                className="min-w-[220px] flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm disabled:opacity-60"
                placeholder="输入新文件夹名"
              />
              <button
                type="button"
                onClick={() => void handleCreateDirectory()}
                disabled={busy || loading || !newFolderName.trim()}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                创建
              </button>
            </div>
          ) : null}
          {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="py-8 text-center text-sm text-[var(--muted)]">目录加载中...</div>
          ) : directories.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--border)] px-4 py-6 text-center text-sm text-[var(--muted)]">
              当前目录没有子文件夹，可直接选择当前目录。
            </div>
          ) : (
            <ul className="space-y-2">
              {directories.map((entry) => (
                <li key={entry.name}>
                  <button
                    type="button"
                    aria-label={`进入目录 ${entry.name}`}
                    onClick={() => void navigate(entry.name, "切换目录失败")}
                    disabled={busy}
                    className="flex w-full items-center gap-3 rounded-xl border border-[var(--border)] px-4 py-3 text-left hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    <FolderOpen className="h-5 w-5 shrink-0 text-[var(--accent)]" />
                    <span className="min-w-0 flex-1 truncate text-sm text-[var(--text)]">{entry.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
