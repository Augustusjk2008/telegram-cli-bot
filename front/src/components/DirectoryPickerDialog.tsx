import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowUp, Check, ChevronRight, Folder, FolderOpen, FolderPlus, HardDrive, House, LoaderCircle, TriangleAlert, X } from "lucide-react";
import type { DirectoryListing } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import { normalizePathInput } from "../utils/pathInput";
import "./DirectoryPickerDialog.css";

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
  if (/^[A-Za-z]:$/.test(normalized)) {
    return "::windows-drives::";
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
  const panelRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const ids = useId();

  function applyListing(listing: DirectoryListing) {
    currentPathRef.current = listing.workingDir;
    setCurrentPath(listing.workingDir);
    setEntries(listing.entries);
    setIsVirtualRoot(Boolean(listing.isVirtualRoot));
    if (listRef.current) {
      listRef.current.scrollTop = 0;
    }
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

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus();
    return () => opener?.focus();
  }, []);

  const directories = entries.filter((entry) => entry.isDir);
  // The first listing shows a spinner; later navigations keep the old rows, dimmed, until the next arrive.
  const initialLoading = loading && !currentPath;

  const dialog = (
    <div className="orbit-backdrop dirpick-backdrop fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <section
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${ids}-title`}
        aria-describedby={`${ids}-description`}
        tabIndex={-1}
        className="orbit-dialog dirpick"
        onKeyDown={(event) => {
          if (event.key !== "Escape" || busy) {
            return;
          }
          event.stopPropagation();
          void closeDialog();
        }}
      >
        <header className="dirpick-head">
          <span className="dirpick-head-icon" aria-hidden="true">
            <FolderOpen className="h-4 w-4" />
          </span>
          <div className="dirpick-head-copy">
            <h2 id={`${ids}-title`}>{title}</h2>
            <p id={`${ids}-description`}>进入目标目录后，点击「使用当前目录」。</p>
          </div>
          <button
            type="button"
            aria-label="关闭"
            title="关闭"
            onClick={() => void closeDialog()}
            disabled={busy}
            className="orbit-btn orbit-btn--ghost orbit-btn--icon orbit-btn--sm"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        </header>

        <div className="dirpick-bar">
          <button
            type="button"
            aria-label="上一级"
            title="上一级"
            onClick={() => void navigate("..", "返回上级目录失败")}
            disabled={busy || loading}
            className="orbit-btn orbit-btn--secondary orbit-btn--icon"
          >
            <ArrowUp aria-hidden="true" className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label="回到起点"
            title="回到起点"
            onClick={() => void navigate(startPathRef.current, "返回起始目录失败")}
            disabled={busy || loading || !startPathRef.current}
            className="orbit-btn orbit-btn--secondary orbit-btn--icon"
          >
            <House aria-hidden="true" className="h-4 w-4" />
          </button>
          <p className="dirpick-path" title={currentPath || undefined} aria-live="polite">
            <span className="sr-only">当前目录：</span>
            <span className="dirpick-path-value">{currentPath || "加载中..."}</span>
            {loading ? <LoaderCircle aria-hidden="true" className="dirpick-path-spinner h-3.5 w-3.5 animate-spin" /> : null}
          </p>
        </div>
        {isVirtualRoot ? <p className="dirpick-note">请先选择具体目录或卷。</p> : null}
        {error ? (
          <p role="alert" className="dirpick-error">
            <TriangleAlert aria-hidden="true" className="h-4 w-4" />
            <span>{error}</span>
          </p>
        ) : null}

        <div ref={listRef} className="dirpick-body" aria-busy={loading || undefined}>
          {initialLoading ? (
            <div className="dirpick-state">
              <LoaderCircle aria-hidden="true" className="h-5 w-5 animate-spin" />
              <span>目录加载中...</span>
            </div>
          ) : directories.length === 0 ? (
            <div className="dirpick-state dirpick-empty">
              <FolderOpen aria-hidden="true" className="h-6 w-6" />
              <p>当前目录没有子文件夹</p>
              <span>{!isVirtualRoot && canCreateDirectory ? "可直接使用当前目录，或在下方新建文件夹" : "可直接使用当前目录"}</span>
            </div>
          ) : (
            <ul className="dirpick-list" aria-label="子目录">
              {directories.map((entry) => (
                <li key={entry.name}>
                  <button
                    type="button"
                    aria-label={`进入目录 ${entry.name}`}
                    title={entry.name}
                    onClick={() => void navigate(entry.name, "切换目录失败")}
                    disabled={busy}
                    className="dirpick-row"
                  >
                    {isVirtualRoot
                      ? <HardDrive aria-hidden="true" className="dirpick-row-icon h-4 w-4" />
                      : <Folder aria-hidden="true" className="dirpick-row-icon h-4 w-4" />}
                    <span className="dirpick-row-name">{entry.name}</span>
                    <ChevronRight aria-hidden="true" className="dirpick-row-go h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {!isVirtualRoot && canCreateDirectory ? (
          <div className="dirpick-create">
            <div className="dirpick-create-field">
              <FolderPlus aria-hidden="true" className="h-4 w-4" />
              <input
                aria-label="新文件夹名称"
                value={newFolderName}
                onChange={(event) => setNewFolderName(event.target.value)}
                onKeyDown={(event) => {
                  // Enter that commits an IME composition must not create a half-typed folder.
                  if (event.key !== "Enter" || event.nativeEvent.isComposing || event.keyCode === 229) {
                    return;
                  }
                  event.preventDefault();
                  void handleCreateDirectory();
                }}
                disabled={busy || loading}
                className="orbit-field"
                placeholder="在当前目录新建文件夹"
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <button
              type="button"
              onClick={() => void handleCreateDirectory()}
              disabled={busy || loading || !newFolderName.trim()}
              className="orbit-btn orbit-btn--secondary"
            >
              创建
            </button>
          </div>
        ) : null}

        <footer className="dirpick-foot">
          <button type="button" onClick={() => void closeDialog()} disabled={busy} className="orbit-btn orbit-btn--ghost">
            取消
          </button>
          <button
            type="button"
            onClick={() => void closeDialog(normalizePathInput(currentPath))}
            disabled={busy || loading || !currentPath || isVirtualRoot}
            className="orbit-btn orbit-btn--primary"
          >
            <Check aria-hidden="true" className="h-4 w-4" />
            使用当前目录
          </button>
        </footer>
      </section>
    </div>
  );
  // Render at the viewport level so ancestors with transforms, filters or overflow clipping cannot trap the overlay.
  return typeof document === "undefined" ? dialog : createPortal(dialog, document.body);
}
