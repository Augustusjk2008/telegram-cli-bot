import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import "@xterm/xterm/css/xterm.css";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { createTerminalSession, type TerminalSession } from "../services/terminalSession";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  authToken: string;
  botAlias: string;
  client?: WebBotClient;
  isVisible: boolean;
  preferredWorkingDir: string;
};

type Disposable = {
  dispose: () => void;
};

const defaultTerminalClient = new MockWebBotClient();
const FOLLOW_THRESHOLD_PX = 24;

function scheduleLayout(callback: () => void) {
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(() => callback());
    return;
  }
  window.setTimeout(callback, 0);
}

function getScrollTarget(viewport: HTMLDivElement | null) {
  const nestedViewport = viewport?.querySelector(".xterm-viewport");
  return nestedViewport instanceof HTMLElement ? nestedViewport : viewport;
}

function isNearBottom(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= FOLLOW_THRESHOLD_PX;
}

export function TerminalScreen({
  authToken,
  botAlias,
  client = defaultTerminalClient,
  isVisible,
  preferredWorkingDir,
}: Props) {
  const sessionRef = useRef<TerminalSession | null>(null);
  const listenerDisposersRef = useRef<Disposable[]>([]);
  const launchPendingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const latestWorkingDirRef = useRef(preferredWorkingDir.trim());
  const isFollowingRef = useRef(true);
  const [launchKey, setLaunchKey] = useState(0);
  const [instanceId, setInstanceId] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [isFollowing, setIsFollowing] = useState(true);
  const [ptyMode, setPtyMode] = useState<boolean | null>(null);
  const [activeWorkingDir, setActiveWorkingDir] = useState(preferredWorkingDir.trim());
  const [error, setError] = useState("");

  function setFollowing(nextValue: boolean) {
    isFollowingRef.current = nextValue;
    setIsFollowing(nextValue);
  }

  function cleanupTerminalListeners() {
    for (const disposable of listenerDisposersRef.current) {
      disposable.dispose();
    }
    listenerDisposersRef.current = [];
  }

  function syncFollowingStateFromViewport() {
    const scrollTarget = getScrollTarget(viewportRef.current);
    if (!scrollTarget) {
      return;
    }
    setFollowing(isNearBottom(scrollTarget));
  }

  function jumpToLatest() {
    const session = sessionRef.current;
    const scrollTarget = getScrollTarget(viewportRef.current);
    session?.term.scrollToBottom();
    if (scrollTarget) {
      scrollTarget.scrollTop = scrollTarget.scrollHeight;
    }
    setFollowing(true);
  }

  function disposeSession() {
    cleanupTerminalListeners();
    const session = sessionRef.current;
    sessionRef.current = null;
    session?.dispose();
    setIsConnected(false);
    setPtyMode(null);
  }

  function rebuildTerminal() {
    const nextWorkingDir = latestWorkingDirRef.current || preferredWorkingDir.trim() || activeWorkingDir;
    disposeSession();
    setError("");
    setFollowing(true);
    if (nextWorkingDir) {
      setActiveWorkingDir(nextWorkingDir);
    }
    setLaunchKey((value) => value + 1);
  }

  useEffect(() => {
    const nextWorkingDir = preferredWorkingDir.trim();
    if (!nextWorkingDir) {
      return;
    }
    latestWorkingDirRef.current = nextWorkingDir;
    if (!sessionRef.current) {
      setActiveWorkingDir(nextWorkingDir);
    }
  }, [preferredWorkingDir]);

  useEffect(() => {
    let cancelled = false;

    void client.getBotOverview(botAlias)
      .then((overview) => {
        if (cancelled) {
          return;
        }
        const nextWorkingDir = overview.workingDir.trim() || latestWorkingDirRef.current;
        if (!nextWorkingDir) {
          return;
        }
        latestWorkingDirRef.current = nextWorkingDir;
        if (!sessionRef.current) {
          setActiveWorkingDir(nextWorkingDir);
          setError("");
        }
      })
      .catch((err) => {
        if (cancelled || sessionRef.current || latestWorkingDirRef.current) {
          return;
        }
        setError(err instanceof Error ? err.message : "无法初始化终端");
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client, preferredWorkingDir]);

  useEffect(() => {
    if (!isVisible || sessionRef.current || launchPendingRef.current || !containerRef.current) {
      return;
    }

    const workingDir = latestWorkingDirRef.current || activeWorkingDir.trim();
    if (!workingDir) {
      return;
    }

    launchPendingRef.current = true;
    setError("");

    try {
      let session!: TerminalSession;
      session = createTerminalSession(containerRef.current, {
        token: authToken,
        cwd: workingDir,
        shell: "powershell",
        onOpen: () => {
          setIsConnected(true);
          setError("");
          scheduleLayout(() => {
            session.fit();
            if (isFollowingRef.current) {
              jumpToLatest();
            }
          });
        },
        onClose: () => {
          setIsConnected(false);
        },
        onError: (message) => {
          setError(message);
          setIsConnected(false);
        },
        onPtyMode: (enabled) => {
          setPtyMode(enabled);
        },
      });

      cleanupTerminalListeners();
      listenerDisposersRef.current = [
        session.term.onWriteParsed(() => {
          if (!isFollowingRef.current) {
            return;
          }
          scheduleLayout(() => {
            session.term.scrollToBottom();
            const scrollTarget = getScrollTarget(viewportRef.current);
            if (scrollTarget) {
              scrollTarget.scrollTop = scrollTarget.scrollHeight;
            }
          });
        }),
        session.term.onScroll(() => {
          scheduleLayout(() => {
            syncFollowingStateFromViewport();
          });
        }),
      ];

      sessionRef.current = session;
      setActiveWorkingDir(workingDir);
      setInstanceId((value) => value + 1);
      session.connect();

      scheduleLayout(() => {
        session.fit();
        if (isVisible) {
          if (isFollowingRef.current) {
            jumpToLatest();
          }
          session.focus();
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法初始化终端");
    } finally {
      launchPendingRef.current = false;
    }
  }, [activeWorkingDir, authToken, isVisible, launchKey]);

  useEffect(() => {
    if (!isVisible || !sessionRef.current) {
      return;
    }
    scheduleLayout(() => {
      sessionRef.current?.fit();
      if (isFollowingRef.current) {
        jumpToLatest();
      }
    });
  }, [instanceId, isVisible]);

  useEffect(() => {
    if (!sessionRef.current) {
      return;
    }

    const refitTerminal = () => {
      scheduleLayout(() => {
        sessionRef.current?.fit();
        if (isFollowingRef.current) {
          jumpToLatest();
        }
      });
    };

    window.addEventListener("resize", refitTerminal);
    window.visualViewport?.addEventListener("resize", refitTerminal);

    return () => {
      window.removeEventListener("resize", refitTerminal);
      window.visualViewport?.removeEventListener("resize", refitTerminal);
    };
  }, [instanceId]);

  useEffect(() => {
    return () => {
      disposeSession();
    };
  }, []);

  const connectionText = error ? "连接失败" : isConnected ? "已连接" : instanceId > 0 ? "连接中..." : "准备启动";
  const showReconnectHint = Boolean(latestWorkingDirRef.current)
    && Boolean(activeWorkingDir)
    && latestWorkingDirRef.current !== activeWorkingDir;

  return (
    <main data-testid="terminal-screen-root" className="flex h-full flex-col bg-[var(--bg)]">
      <header className="border-b border-[var(--border)] bg-[var(--surface-strong)] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold text-[var(--text)]">{connectionText}</h1>
              {ptyMode !== null ? (
                <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--muted)]">
                  {ptyMode ? "PTY" : "PIPE"}
                </span>
              ) : null}
            </div>
            <p className="truncate text-xs text-[var(--muted)]">
              {activeWorkingDir || "等待工作目录..."}
            </p>
            {showReconnectHint ? (
              <p className="truncate text-[11px] text-[var(--muted)]">
                当前 Bot 目录已变化，点“重建终端”后切换到 {latestWorkingDirRef.current}
              </p>
            ) : (
              <p className="text-[11px] text-[var(--muted)]">
                手机优先：看输出为主，切页不会断开，会话只在重建时切到新目录。
              </p>
            )}
            {error ? (
              <p className="mt-1 text-xs text-red-600">{error}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={rebuildTerminal}
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface)] disabled:opacity-60"
          >
            <RefreshCw className="h-4 w-4" />
            重建终端
          </button>
        </div>
        <div data-testid="terminal-instance-id" className="sr-only">
          {instanceId}
        </div>
      </header>

      <section className="relative flex-1 overflow-hidden bg-[#09101f]">
        <div
          ref={viewportRef}
          data-testid="terminal-viewport"
          onScroll={() => {
            syncFollowingStateFromViewport();
          }}
          className="h-full overflow-auto"
        >
          <div ref={containerRef} className="h-full min-h-full w-full px-3 py-2" />
        </div>
        {!isFollowing ? (
          <button
            type="button"
            onClick={jumpToLatest}
            className="absolute bottom-4 right-4 rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white shadow-[var(--shadow-card)]"
          >
            回到最新输出
          </button>
        ) : null}
      </section>

      <div className="grid grid-cols-4 gap-2 border-t border-[var(--border)] bg-[var(--surface)] p-3 pb-safe">
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\u0003")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          Ctrl+C
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\t")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          Tab
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\u001b")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          Esc
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.focus()}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          键盘
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\u001b[A")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          ↑
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\u001b[B")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          ↓
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\u001b[D")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          ←
        </button>
        <button
          type="button"
          onClick={() => sessionRef.current?.sendControl("\u001b[C")}
          className="rounded-xl border border-[var(--border)] px-3 py-3 text-sm font-medium"
        >
          →
        </button>
      </div>
    </main>
  );
}
