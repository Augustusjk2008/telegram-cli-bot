import { useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2, RefreshCw, X } from "lucide-react";
import "@xterm/xterm/css/xterm.css";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { createTerminalSession, type TerminalSession } from "../services/terminalSession";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";

type Props = {
  authToken: string;
  botAlias: string;
  client?: WebBotClient;
  isVisible: boolean;
  preferredWorkingDir: string;
  themeName?: UiThemeName;
  isImmersive?: boolean;
  embedded?: boolean;
  onToggleImmersive?: () => void;
};

type Disposable = {
  dispose: () => void;
};

const defaultTerminalClient = new MockWebBotClient();
const FOLLOW_THRESHOLD_PX = 24;

function scheduleLayout(callback: () => void) {
  if (typeof window.requestAnimationFrame === "function") {
    return window.requestAnimationFrame(() => callback());
  }
  return window.setTimeout(callback, 0);
}

function cancelScheduledLayout(handle: number) {
  if (typeof window.cancelAnimationFrame === "function") {
    window.cancelAnimationFrame(handle);
    return;
  }
  window.clearTimeout(handle);
}

function getScrollTarget(viewport: HTMLDivElement | null) {
  const nestedViewport = viewport?.querySelector(".xterm-viewport");
  return nestedViewport instanceof HTMLElement ? nestedViewport : viewport;
}

function isNearBottom(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= FOLLOW_THRESHOLD_PX;
}

function getTerminalFontSize() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return 13;
  }
  return window.matchMedia("(pointer: coarse)").matches ? 12 : 13;
}

export function TerminalScreen({
  authToken,
  botAlias,
  client = defaultTerminalClient,
  isVisible,
  preferredWorkingDir,
  themeName = DEFAULT_UI_THEME,
  isImmersive = false,
  embedded = false,
  onToggleImmersive,
}: Props) {
  const layoutHandleRef = useRef<number | null>(null);
  const layoutRequestRef = useRef({
    refit: false,
    syncViewport: false,
    follow: false,
    syncFollowing: false,
    focus: false,
  });
  const sessionRef = useRef<TerminalSession | null>(null);
  const listenerDisposersRef = useRef<Disposable[]>([]);
  const launchPendingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const latestWorkingDirRef = useRef(preferredWorkingDir.trim());
  const lastThemeRef = useRef(themeName);
  const isFollowingRef = useRef(true);
  const isVisibleRef = useRef(isVisible);
  const previousVisibleRef = useRef(isVisible);
  const [launchKey, setLaunchKey] = useState(0);
  const [instanceId, setInstanceId] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [isFollowing, setIsFollowing] = useState(true);
  const [ptyMode, setPtyMode] = useState<boolean | null>(null);
  const [activeWorkingDir, setActiveWorkingDir] = useState(preferredWorkingDir.trim());
  const [error, setError] = useState("");
  const [isTerminalClosed, setIsTerminalClosed] = useState(false);
  const terminalFontSize = getTerminalFontSize();

  useEffect(() => {
    isVisibleRef.current = isVisible;
  }, [isVisible]);

  function setFollowing(nextValue: boolean) {
    isFollowingRef.current = nextValue;
    setIsFollowing(nextValue);
  }

  function flushLayoutWork() {
    layoutHandleRef.current = null;
    const request = layoutRequestRef.current;
    layoutRequestRef.current = {
      refit: false,
      syncViewport: false,
      follow: false,
      syncFollowing: false,
      focus: false,
    };

    const session = sessionRef.current;
    if (request.refit && session) {
      session.fit();
    }
    if (request.refit || request.syncViewport) {
      configureTerminalViewport();
    }
    if (request.syncFollowing) {
      syncFollowingStateFromViewport();
    }
    if (request.follow && session && isFollowingRef.current) {
      jumpToLatest();
    }
    if (request.focus && session && isVisibleRef.current) {
      session.focus();
    }
  }

  function queueLayoutWork(nextRequest: Partial<typeof layoutRequestRef.current>) {
    const request = layoutRequestRef.current;
    request.refit ||= Boolean(nextRequest.refit);
    request.syncViewport ||= Boolean(nextRequest.syncViewport);
    request.follow ||= Boolean(nextRequest.follow);
    request.syncFollowing ||= Boolean(nextRequest.syncFollowing);
    request.focus ||= Boolean(nextRequest.focus);
    if (layoutHandleRef.current !== null) {
      return;
    }
    let ranSynchronously = false;
    const handle = scheduleLayout(() => {
      ranSynchronously = true;
      flushLayoutWork();
    });
    if (!ranSynchronously) {
      layoutHandleRef.current = handle;
    }
  }

  function clearQueuedLayoutWork() {
    if (layoutHandleRef.current === null) {
      return;
    }
    cancelScheduledLayout(layoutHandleRef.current);
    layoutHandleRef.current = null;
    layoutRequestRef.current = {
      refit: false,
      syncViewport: false,
      follow: false,
      syncFollowing: false,
      focus: false,
    };
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

  function configureTerminalViewport() {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    viewport.style.overflow = "scroll";
    viewport.style.touchAction = "pan-x pan-y";
    viewport.style.overscrollBehavior = "contain";

    const scrollTarget = getScrollTarget(viewport);
    if (scrollTarget) {
      scrollTarget.style.overflow = "auto";
      scrollTarget.style.touchAction = "pan-x pan-y";
      scrollTarget.style.overscrollBehavior = "contain";
      scrollTarget.style.scrollbarGutter = "stable both-edges";
      (scrollTarget.style as CSSStyleDeclaration & { webkitOverflowScrolling?: string }).webkitOverflowScrolling = "touch";
    }

    const xtermScreen = viewport.querySelector(".xterm-screen");
    if (xtermScreen instanceof HTMLElement) {
      xtermScreen.style.minWidth = "100%";
      xtermScreen.style.width = "max-content";
    }
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
    clearQueuedLayoutWork();
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
    setIsTerminalClosed(false);
    if (nextWorkingDir) {
      setActiveWorkingDir(nextWorkingDir);
    }
    setLaunchKey((value) => value + 1);
  }

  function closeTerminal() {
    disposeSession();
    setError("");
    setFollowing(true);
    setIsTerminalClosed(true);
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
    if (!isVisible || isTerminalClosed || sessionRef.current || launchPendingRef.current || !containerRef.current) {
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
        shell: "auto",
        fontSize: terminalFontSize,
        themeName,
        onOpen: () => {
          setIsConnected(true);
          setError("");
          queueLayoutWork({ refit: true, follow: true });
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
          queueLayoutWork({ follow: true });
        }),
        session.term.onScroll(() => {
          queueLayoutWork({ syncFollowing: true });
        }),
      ];

      sessionRef.current = session;
      setActiveWorkingDir(workingDir);
      setInstanceId((value) => value + 1);
      session.connect();

      queueLayoutWork({ refit: true, follow: true, focus: isVisible });
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法初始化终端");
    } finally {
      launchPendingRef.current = false;
    }
  }, [activeWorkingDir, authToken, isTerminalClosed, isVisible, launchKey, themeName]);

  useEffect(() => {
    const becameVisible = !previousVisibleRef.current && isVisible;
    previousVisibleRef.current = isVisible;

    if (!becameVisible || !sessionRef.current) {
      return;
    }
    queueLayoutWork({ refit: true, follow: true, focus: true });
  }, [isVisible]);

  useEffect(() => {
    if (!sessionRef.current) {
      return;
    }

    const refitTerminal = () => {
      queueLayoutWork({ refit: true, follow: true });
    };

    window.addEventListener("resize", refitTerminal);
    window.visualViewport?.addEventListener("resize", refitTerminal);

    return () => {
      window.removeEventListener("resize", refitTerminal);
      window.visualViewport?.removeEventListener("resize", refitTerminal);
    };
  }, [instanceId]);

  useEffect(() => {
    if (lastThemeRef.current === themeName) {
      return;
    }

    lastThemeRef.current = themeName;

    if (!sessionRef.current) {
      return;
    }
    rebuildTerminal();
  }, [themeName]);

  useEffect(() => {
    return () => {
      clearQueuedLayoutWork();
      disposeSession();
    };
  }, []);

  const connectionText = error ? "连接失败" : isConnected ? "已连接" : instanceId > 0 ? "连接中..." : "准备启动";
  const canCloseTerminal = !isTerminalClosed && sessionRef.current !== null;

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
            {error ? (
              <p className="mt-1 text-xs text-red-600">{error}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={closeTerminal}
              disabled={!canCloseTerminal}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface)] disabled:opacity-50"
            >
              <X className="h-4 w-4" />
              关闭终端
            </button>
            <button
              type="button"
              onClick={rebuildTerminal}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface)] disabled:opacity-60"
            >
              <RefreshCw className="h-4 w-4" />
              重建终端
            </button>
          </div>
        </div>
        <div data-testid="terminal-instance-id" className="sr-only">
          {instanceId}
        </div>
      </header>

      <section className="relative flex-1 overflow-hidden bg-[var(--terminal-bg)]">
        {isTerminalClosed ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-[var(--terminal-muted)]">
            终端已关闭
          </div>
        ) : (
          <div
            ref={viewportRef}
            data-testid="terminal-viewport"
            style={{
              overflow: "scroll",
              touchAction: "pan-x pan-y",
              overscrollBehavior: "contain",
            }}
            onScroll={() => {
              queueLayoutWork({ syncFollowing: true });
            }}
            className="h-full"
          >
            <div ref={containerRef} className="terminal-shell h-full min-h-full min-w-full px-3 py-2" />
          </div>
        )}
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

      {!embedded && isVisible && onToggleImmersive ? (
        <button
          type="button"
          onClick={onToggleImmersive}
          aria-label={isImmersive ? "退出沉浸模式" : "进入沉浸模式"}
          className="absolute bottom-24 right-4 z-20 inline-flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur hover:bg-[var(--surface-strong)]"
        >
          {isImmersive ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
        </button>
      ) : null}

      {!embedded ? (
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
      ) : null}
    </main>
  );
}
