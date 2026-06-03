import { useEffect, useRef, useState } from "react";
import { Maximize2, Minimize2, RefreshCw, X } from "lucide-react";
import "@xterm/xterm/css/xterm.css";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { createTerminalSession, type TerminalSession } from "../services/terminalSession";
import type {
  TerminalAction,
  TerminalActionsConfig,
  TerminalActionsEditableConfig,
  TerminalRuntimePlatform,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { TerminalActionsBar } from "../terminal/TerminalActionsBar";
import { TerminalActionsConfigDialog } from "../terminal/TerminalActionsConfigDialog";
import { isTerminalActionVisible, resolveTerminalActionCommand } from "../terminal/terminalActionPlatform";
import { usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";
import type { TerminalWorkbenchStatus } from "../workbench/workbenchTypes";

type Props = {
  authToken: string;
  botAlias: string;
  client?: WebBotClient;
  isVisible: boolean;
  preferredWorkingDir: string;
  pendingWorkingDir?: string;
  themeName?: UiThemeName;
  isImmersive?: boolean;
  disabledReason?: string;
  embedded?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onToggleImmersive?: () => void;
  onAcceptPendingWorkingDir?: () => void;
  onCancelPendingWorkingDir?: () => void;
  onWorkbenchStatusChange?: (status: TerminalWorkbenchStatus) => void;
};

type Disposable = {
  dispose: () => void;
};

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
  return nestedViewport instanceof HTMLElement ? nestedViewport : null;
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
  client = new MockWebBotClient(),
  isVisible,
  preferredWorkingDir,
  pendingWorkingDir,
  themeName = DEFAULT_UI_THEME,
  isImmersive = false,
  disabledReason = "",
  embedded = false,
  focused = false,
  onToggleFocus,
  onToggleImmersive,
  onAcceptPendingWorkingDir,
  onCancelPendingWorkingDir,
  onWorkbenchStatusChange,
}: Props) {
  const terminal = usePersistentTerminal();
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
  const lastThemeRef = useRef(themeName);
  const isFollowingRef = useRef(true);
  const isVisibleRef = useRef(isVisible);
  const previousVisibleRef = useRef(isVisible);
  const [instanceId, setInstanceId] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [isFollowing, setIsFollowing] = useState(true);
  const [ptyMode, setPtyMode] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const [actionsConfig, setActionsConfig] = useState<TerminalActionsConfig | null>(null);
  const [actionsError, setActionsError] = useState("");
  const [runningActionId, setRunningActionId] = useState("");
  const [showActionsConfig, setShowActionsConfig] = useState(false);
  const [savingActionsConfig, setSavingActionsConfig] = useState(false);
  const [actionsConfigError, setActionsConfigError] = useState("");
  const terminalFontSize = getTerminalFontSize();
  const terminalDisabled = Boolean(disabledReason);
  const runtimePlatform: TerminalRuntimePlatform = actionsConfig?.runtimePlatform ?? "windows";
  const visibleActions = actionsConfig?.actions.filter((action) => isTerminalActionVisible(action, runtimePlatform)) ?? [];
  const runningWorkingDir = terminal.snapshot.cwd.trim();
  const stagedWorkingDir = pendingWorkingDir?.trim() || "";
  const preferredTerminalDir = preferredWorkingDir.trim();
  const resolvedPtyMode = ptyMode ?? terminal.snapshot.ptyMode;
  const hasRunningTerminal = terminal.snapshot.started && !terminal.snapshot.closed;

  useEffect(() => {
    isVisibleRef.current = isVisible;
  }, [isVisible]);

  useEffect(() => {
    let cancelled = false;
    client.getTerminalActionsConfig(botAlias)
      .then((next) => {
        if (cancelled) return;
        setActionsConfig(next);
        setActionsError(next.errors[0] || "");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setActionsConfig(null);
        setActionsError(err instanceof Error ? err.message : "加载快捷命令失败");
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

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

    viewport.style.overflow = "hidden";
    viewport.style.touchAction = "pan-x pan-y";
    viewport.style.overscrollBehavior = "contain";

    const scrollTarget = getScrollTarget(viewport);
    if (scrollTarget) {
      scrollTarget.style.overflow = "auto";
      scrollTarget.style.touchAction = "pan-x pan-y";
      scrollTarget.style.overscrollBehavior = "contain";
      scrollTarget.style.scrollbarGutter = "stable";
      (scrollTarget.style as CSSStyleDeclaration & { webkitOverflowScrolling?: string }).webkitOverflowScrolling = "touch";
    }

    const xtermRoot = viewport.querySelector(".xterm");
    if (xtermRoot instanceof HTMLElement) {
      xtermRoot.style.width = "100%";
      xtermRoot.style.minWidth = "0";
    }

    const xtermScreen = viewport.querySelector(".xterm-screen");
    if (xtermScreen instanceof HTMLElement) {
      xtermScreen.style.minWidth = "100%";
      xtermScreen.style.width = "100%";
    }
  }

  function jumpToLatest() {
    sessionRef.current?.term.scrollToBottom();
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

  async function rebuildTerminal() {
    if (terminalDisabled) {
      return;
    }
    const nextWorkingDir = stagedWorkingDir || preferredTerminalDir || runningWorkingDir;
    if (!nextWorkingDir) {
      return;
    }
    disposeSession();
    setError("");
    setFollowing(true);
    try {
      await terminal.rebuild(nextWorkingDir);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重建终端失败");
      setIsConnected(false);
    }
  }

  async function closeTerminal() {
    if (terminalDisabled) {
      return;
    }
    disposeSession();
    setError("");
    setFollowing(true);
    await terminal.close();
  }

  async function runTerminalAction(action: TerminalAction) {
    if (terminalDisabled) {
      return;
    }
    const command = resolveTerminalActionCommand(action, runtimePlatform);
    if (!command) {
      setActionsError("当前平台未配置命令");
      return;
    }
    if (action.confirm && !window.confirm(`执行命令？\n\n${command}`)) {
      return;
    }
    setRunningActionId(action.id);
    setActionsError("");
    try {
      await client.runTerminalAction(botAlias, action.id, {
        ownerId: terminal.ownerId,
        confirmed: true,
      });
      await terminal.refreshSnapshot();
      setFollowing(true);
    } catch (err) {
      setActionsError(err instanceof Error ? err.message : "执行快捷命令失败");
    } finally {
      setRunningActionId("");
    }
  }

  async function saveTerminalActionsConfig(nextConfig: TerminalActionsEditableConfig) {
    if (!actionsConfig || terminalDisabled) {
      return;
    }
    setSavingActionsConfig(true);
    setActionsConfigError("");
    try {
      const saved = await client.saveTerminalActionsConfig(botAlias, nextConfig, actionsConfig.mtimeNs);
      setActionsConfig(saved);
      setActionsError(saved.errors[0] || "");
      setShowActionsConfig(false);
    } catch (err) {
      setActionsConfigError(err instanceof Error ? err.message : "保存快捷命令失败");
    } finally {
      setSavingActionsConfig(false);
    }
  }

  useEffect(() => {
    if (terminalDisabled) {
      disposeSession();
      setError("");
      setFollowing(true);
      return;
    }
  }, [terminalDisabled]);

  useEffect(() => {
    if (terminal.snapshot.started || sessionRef.current === null) {
      return;
    }
    disposeSession();
  }, [terminal.snapshot.closed, terminal.snapshot.started]);

  useEffect(() => {
    if (terminalDisabled) {
      return;
    }
    if ((!isVisible && sessionRef.current === null) || !terminal.snapshot.started || terminal.snapshot.closed) {
      return;
    }
    if (sessionRef.current || launchPendingRef.current || !containerRef.current) {
      return;
    }

    launchPendingRef.current = true;
    setError("");

    try {
      let session!: TerminalSession;
      session = createTerminalSession(containerRef.current, {
        token: authToken,
        ownerId: terminal.ownerId,
        fromSeq: 0,
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
      setInstanceId((value) => value + 1);
      session.connect();

      queueLayoutWork({ refit: true, follow: true, focus: isVisible });
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法初始化终端");
    } finally {
      launchPendingRef.current = false;
    }
  }, [authToken, isVisible, terminal.attachNonce, terminal.ownerId, terminal.snapshot.closed, terminal.snapshot.started, terminalDisabled, terminalFontSize, themeName]);

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
    const viewport = viewportRef.current;
    if (!sessionRef.current || !viewport || typeof ResizeObserver === "undefined") {
      return;
    }

    let previousWidth = viewport.clientWidth;
    let previousHeight = viewport.clientHeight;
    const observer = new ResizeObserver(() => {
      const nextWidth = viewport.clientWidth;
      const nextHeight = viewport.clientHeight;
      if (nextWidth === previousWidth && nextHeight === previousHeight) {
        return;
      }
      previousWidth = nextWidth;
      previousHeight = nextHeight;
      queueLayoutWork({
        refit: true,
        syncViewport: true,
        syncFollowing: true,
        follow: isFollowingRef.current,
      });
    });

    observer.observe(viewport);

    return () => {
      observer.disconnect();
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
    sessionRef.current.setTheme(themeName);
  }, [themeName]);

  useEffect(() => {
    return () => {
      clearQueuedLayoutWork();
      disposeSession();
    };
  }, []);

  const effectiveError = disabledReason || error || terminal.error || actionsError;
  const connectionText = effectiveError
    ? terminalDisabled
      ? "无权限"
      : error && hasRunningTerminal
        ? "WebSocket 连接失败"
        : "连接失败"
    : isConnected
      ? "已连接"
      : terminal.snapshot.connectionText || "未启动";
  const canCloseTerminal = !terminalDisabled && terminal.snapshot.started && !terminal.snapshot.closed;
  const canRebuildTerminal = !terminalDisabled && Boolean(stagedWorkingDir || preferredTerminalDir || runningWorkingDir);

  useEffect(() => {
    onWorkbenchStatusChange?.({
      connected: terminal.snapshot.started && !terminal.snapshot.closed,
      connectionText,
      currentCwd: runningWorkingDir,
      nextRebuildCwd: stagedWorkingDir,
    });
  }, [connectionText, onWorkbenchStatusChange, runningWorkingDir, stagedWorkingDir, terminal.snapshot.closed, terminal.snapshot.started]);

  return (
    <main data-testid="terminal-screen-root" className="flex h-full flex-col bg-[var(--workbench-panel-bg)]">
      <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold text-[var(--text)]">{connectionText}</h1>
              {stagedWorkingDir ? (
                <span className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
                  下次重建目录
                </span>
              ) : null}
              {resolvedPtyMode !== null ? (
                <span className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
                  {resolvedPtyMode ? "PTY" : "PIPE"}
                </span>
              ) : null}
            </div>
            {effectiveError ? (
              <p className="mt-0.5 text-xs text-red-600">{effectiveError}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <TerminalActionsBar
              actions={[]}
              runtimePlatform={runtimePlatform}
              canEdit={Boolean(actionsConfig?.editable) && !terminalDisabled}
              disabled={terminalDisabled}
              runningActionId=""
              onRunAction={() => {}}
              onOpenConfig={() => {
                setActionsConfigError("");
                setShowActionsConfig(true);
              }}
            />
            {embedded && onToggleFocus ? (
              <button
                type="button"
                aria-label={focused ? "退出聚焦终端" : "聚焦终端"}
                title={focused ? "退出聚焦终端" : "聚焦终端"}
                onClick={onToggleFocus}
                className={toolbarButtonClass("ghost", "icon", "h-8 w-8 border-[var(--workbench-hairline)]")}
              >
                {focused ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </button>
            ) : null}
            <button
              type="button"
              onClick={closeTerminal}
              disabled={!canCloseTerminal}
              className={toolbarButtonClass("plain", "sm", "h-8")}
            >
              <X className="h-3.5 w-3.5" />
              关闭终端
            </button>
            <button
              type="button"
              onClick={rebuildTerminal}
              disabled={!canRebuildTerminal}
              className={toolbarButtonClass("primary", "sm", "h-8")}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              重建终端
            </button>
          </div>
        </div>
        {stagedWorkingDir ? (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2.5 py-1.5 text-xs shadow-[var(--shadow-soft)]">
            <span className="font-medium text-[var(--text)]">下次重建目录</span>
            <span className="truncate text-[var(--muted)]">{stagedWorkingDir}</span>
            <button
              type="button"
              onClick={onAcceptPendingWorkingDir}
              disabled={terminalDisabled}
              className={toolbarButtonClass("plain", "sm", "h-7")}
            >
              设为下次重建
            </button>
            <button
              type="button"
              onClick={onCancelPendingWorkingDir}
              disabled={terminalDisabled}
              className={toolbarButtonClass("ghost", "sm", "h-7")}
            >
              取消
            </button>
          </div>
        ) : null}
        <div data-testid="terminal-instance-id" className="sr-only">
          {instanceId}
        </div>
      </header>

      <section className="relative flex-1 overflow-hidden border-b border-[var(--workbench-hairline)] bg-[var(--terminal-bg)]">
        {!terminal.snapshot.started || terminal.snapshot.closed ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-[var(--terminal-muted)]">
            {terminal.snapshot.closed ? "终端已关闭" : "未启动终端"}
          </div>
        ) : (
          <div
            ref={viewportRef}
            data-testid="terminal-viewport"
            style={{
              overflow: "hidden",
              touchAction: "pan-x pan-y",
              overscrollBehavior: "contain",
            }}
            className="h-full"
          >
            <div data-testid="terminal-shell-frame" className="h-full w-full bg-[var(--terminal-bg)] px-3 py-2">
              {/* Keep padding off the xterm host; FitAddon measures the host size directly. */}
              <div ref={containerRef} className="terminal-shell h-full w-full min-h-full min-w-0" />
            </div>
          </div>
        )}
        {!isFollowing ? (
          <button
            type="button"
            onClick={jumpToLatest}
            className="absolute bottom-4 right-4 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)] shadow-[var(--shadow-card)]"
          >
            回到最新输出
          </button>
        ) : null}
      </section>

      {visibleActions.length > 0 ? (
        <div
          data-testid="terminal-actions-panel"
          className="border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2"
        >
          <TerminalActionsBar
            actions={visibleActions}
            runtimePlatform={runtimePlatform}
            canEdit={false}
            disabled={terminalDisabled}
            runningActionId={runningActionId}
            onRunAction={(action) => void runTerminalAction(action)}
            onOpenConfig={() => {}}
          />
        </div>
      ) : null}

      {!embedded && isVisible && onToggleImmersive ? (
        <button
          type="button"
          onClick={onToggleImmersive}
          aria-label={isImmersive ? "退出沉浸模式" : "进入沉浸模式"}
          className="absolute bottom-24 right-4 z-20 inline-flex h-12 w-12 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur hover:bg-[var(--workbench-hover-bg)]"
        >
          {isImmersive ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
        </button>
      ) : null}

      {!embedded ? (
        <div className="grid grid-cols-4 gap-2 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] p-3 pb-safe">
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\u0003");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            Ctrl+C
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\t");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            Tab
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\u001b");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            Esc
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.focus();
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            键盘
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\u001b[A");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\u001b[B");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            ↓
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\u001b[D");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            ←
          </button>
          <button
            type="button"
            onClick={() => {
              if (!terminalDisabled) sessionRef.current?.sendControl("\u001b[C");
            }}
            disabled={terminalDisabled}
            className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm font-medium hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
          >
            →
          </button>
        </div>
      ) : null}
      {showActionsConfig && actionsConfig && !terminalDisabled ? (
        <TerminalActionsConfigDialog
          config={actionsConfig}
          saving={savingActionsConfig}
          error={actionsConfigError}
          onSave={(nextConfig) => void saveTerminalActionsConfig(nextConfig)}
          onClose={() => setShowActionsConfig(false)}
        />
      ) : null}
    </main>
  );
}
