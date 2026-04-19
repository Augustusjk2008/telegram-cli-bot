import { useEffect, useRef, useState } from "react";
import { ChevronLeft, FolderOpen, House } from "lucide-react";
import type { DirectoryListing } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { normalizePathInput } from "../utils/pathInput";

type Props = {
  title: string;
  botAlias: string;
  client: WebBotClient;
  initialPath?: string;
  onPick: (path: string) => void;
  onClose: () => void;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function DirectoryPickerDialog({
  title,
  botAlias,
  client,
  initialPath = "",
  onPick,
  onClose,
}: Props) {
  const [currentPath, setCurrentPath] = useState("");
  const [entries, setEntries] = useState<DirectoryListing["entries"]>([]);
  const [isVirtualRoot, setIsVirtualRoot] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const currentPathRef = useRef("");
  const homePathRef = useRef("");
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
    if (restoredRef.current) {
      return;
    }
    restoredRef.current = true;

    const originPath = originPathRef.current;
    if (!originPath) {
      return;
    }

    try {
      if (originWasVirtualRootRef.current) {
        const driveRootMatch = currentPathRef.current.match(/^[A-Za-z]:\\/);
        if (!driveRootMatch) {
          return;
        }
        await client.changeDirectory(botAlias, driveRootMatch[0]);
        await client.changeDirectory(botAlias, "..");
        return;
      }
      await client.changeDirectory(botAlias, originPath);
    } catch {
      return;
    }
  }

  async function loadCurrentDirectory() {
    const listing = await client.listFiles(botAlias);
    applyListing(listing);
  }

  async function navigate(path: string, fallback: string) {
    setBusy(true);
    setLoading(true);
    setError("");
    try {
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
    await restoreOriginalPath();
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
        const [originListing, homePath] = await Promise.all([
          client.listFiles(botAlias),
          client.getCurrentPath(botAlias),
        ]);
        if (!active) {
          return;
        }

        originPathRef.current = originListing.workingDir;
        originWasVirtualRootRef.current = Boolean(originListing.isVirtualRoot);
        homePathRef.current = homePath;

        const preferredPath = normalizePathInput(initialPath) || homePath || originListing.workingDir;
        if (preferredPath && preferredPath !== originListing.workingDir) {
          try {
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
  }, [botAlias, client, initialPath]);

  const directories = entries.filter((entry) => entry.isDir);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-[var(--surface)] shadow-[var(--shadow-card)]">
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
            onClick={() => void navigate(homePathRef.current, "返回起始目录失败")}
            disabled={busy || loading || !homePathRef.current}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <House className="h-4 w-4" />
            回到起点
          </button>
          <button
            type="button"
            onClick={() => void closeDialog(normalizePathInput(currentPath))}
            disabled={busy || loading || !currentPath || isVirtualRoot}
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
          >
            使用当前目录
          </button>
        </div>

        <div className="border-b border-[var(--border)] px-5 py-3">
          <p className="text-xs text-[var(--muted)]">当前目录</p>
          <p className="mt-1 break-all text-sm text-[var(--text)]">{currentPath || "加载中..."}</p>
          {isVirtualRoot ? <p className="mt-2 text-xs text-[var(--muted)]">请先选择一个具体盘符。</p> : null}
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
