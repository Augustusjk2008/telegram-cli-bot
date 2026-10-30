import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { createTerminalSession, type TerminalSession } from "../services/terminalSession";
import type { WebBotClient } from "../services/webBotClient";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { ImmersiveToggleButton } from "../components/ImmersiveToggleButton";
import { usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import type { UiThemeName } from "../theme";
import { getCurrentAppearance, resolvedTerminalTheme, useResolvedAppearance } from "../theme/appearanceRuntime";
import type { TerminalWorkbenchStatus } from "../workbench/workbenchTypes";

type Props = {
  authToken: string;
  botAlias: string;
  remote?: boolean;
  client?: WebBotClient;
  isVisible: boolean;
  pendingWorkingDir?: string;
  themeName?: UiThemeName;
  isImmersive?: boolean;
  disabledReason?: string;
  embedded?: boolean;
  onToggleImmersive?: () => void;
  onAcceptPendingWorkingDir?: () => void;
  onCancelPendingWorkingDir?: () => void;
  onWorkbenchStatusChange?: (status: TerminalWorkbenchStatus) => void;
};

type Disposable = {
  dispose: () => void;
};

const FOLLOW_THRESHOLD_PX = 24;

type MobileTerminalButton = {
  label: string;
  ariaLabel: string;
} & (
  | { control: string }
  | { focus: true }
);

const MOBILE_TERMINAL_BUTTONS: MobileTerminalButton[] = [
  { label: "Ctrl+C", ariaLabel: "Ctrl+C", control: "\u0003" },
  { label: "Ctrl+D", ariaLabel: "Ctrl+D", control: "\u0004" },
  { label: "Ctrl+L", ariaLabel: "Ctrl+L", control: "\u000c" },
  { label: "Esc", ariaLabel: "Escape", control: "\u001b" },
  { label: "Tab", ariaLabel: "Tab", control: "\t" },
  { label: "⇧Tab", ariaLabel: "Shift+Tab", control: "\u001b[Z" },
  { label: "Enter", ariaLabel: "Enter", control: "\r" },
  { label: "键盘", ariaLabel: "唤起键盘", focus: true },
  { label: "↑", ariaLabel: "上方向键", control: "\u001b[A" },
  { label: "↓", ariaLabel: "下方向键", control: "\u001b[B" },
  { label: "←", ariaLabel: "左方向键", control: "\u001b[D" },
  { label: "→", ariaLabel: "右方向键", control: "\u001b[C" },
];

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
  remote = false,
  client = new MockWebBotClient(),
  isVisible,
  pendingWorkingDir,
  isImmersive = false,
  disabledReason = "",
  embedded = false,
  onToggleImmersive,
  onAcceptPendingWorkingDir,
  onCancelPendingWorkingDir,
  onWorkbenchStatusChange,
}: Props) {
  const appearance = useResolvedAppearance();
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
  const terminalRootRef = useRef<HTMLElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const isFollowingRef = useRef(true);
  const isVisibleRef = useRef(isVisible);
  const previousVisibleRef = useRef(isVisible);
  const [instanceId, setInstanceId] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const [isFollowing, setIsFollowing] = useState(true);
  const [ptyMode, setPtyMode] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const terminalFontSize = getTerminalFontSize();
  const terminalDisabled = Boolean(disabledReason);
  const runningWorkingDir = terminal.snapshot.cwd.trim();
  const stagedWorkingDir = pendingWorkingDir?.trim() || "";
  const resolvedPtyMode = ptyMode ?? terminal.snapshot.ptyMode;
  const hasRunningTerminal = terminal.snapshot.started && !terminal.snapshot.closed;

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
      const ownerId = terminal.ownerId;
      session = createTerminalSession(containerRef.current, {
        token: authToken,
        ownerId,
        previousRecoveryState: terminal.getClientRecoveryState(ownerId),
        fontSize: terminalFontSize,
        theme: resolvedTerminalTheme(getCurrentAppearance(), embedded),
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
        onRecoveryState: (state) => {
          terminal.setClientRecoveryState(ownerId, state);
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
  }, [authToken, embedded, isVisible, terminal.attachNonce, terminal.getClientRecoveryState, terminal.ownerId, terminal.setClientRecoveryState, terminal.snapshot.closed, terminal.snapshot.started, terminalDisabled, terminalFontSize]);

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
    sessionRef.current?.setTheme(resolvedTerminalTheme(appearance, embedded));
  }, [appearance.revision, embedded, instanceId]);

  useEffect(() => {
    return () => {
      clearQueuedLayoutWork();
      disposeSession();
    };
  }, []);

  const effectiveError = disabledReason || error || terminal.error;
  const connectionText = effectiveError
    ? terminalDisabled
      ? "无权限"
      : error && hasRunningTerminal
        ? "WebSocket 连接失败"
        : "连接失败"
    : isConnected
      ? "已连接"
      : terminal.snapshot.connectionText || "未启动";
  useEffect(() => {
    onWorkbenchStatusChange?.({
      connected: terminal.snapshot.started && !terminal.snapshot.closed,
      connectionText,
      currentCwd: runningWorkingDir,
      nextTerminalCwd: stagedWorkingDir,
    });
  }, [connectionText, onWorkbenchStatusChange, runningWorkingDir, stagedWorkingDir, terminal.snapshot.closed, terminal.snapshot.started]);

  const stagedWorkingDirControls = stagedWorkingDir ? (
    <div className={embedded
      ? "flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-1.5 text-xs"
      : "mt-2 flex flex-wrap items-center gap-2 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2.5 py-1.5 text-xs shadow-[var(--shadow-surface)]"}
    >
      <span className="font-medium text-[var(--text)]">新终端工作目录</span>
      <span className="truncate text-[var(--muted)]">{stagedWorkingDir}</span>
      <button
        type="button"
        onClick={onAcceptPendingWorkingDir}
        disabled={terminalDisabled}
        className={toolbarButtonClass("plain", "sm", "h-7")}
      >
        设为新终端目录
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
  ) : null;

  return (
    <main ref={terminalRootRef} data-testid="terminal-screen-root" className={`relative flex h-full flex-col ${embedded ? "bg-transparent" : "bg-[var(--workbench-panel-bg)]"}`}>
      {!embedded ? (
        <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold text-[var(--text)]">{connectionText}</h1>
              {stagedWorkingDir ? (
                <span className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
                  新终端目录
                </span>
              ) : null}
              {resolvedPtyMode !== null ? (
                <span className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]">
                  {resolvedPtyMode ? "PTY" : "PIPE"}
                </span>
              ) : null}
            </div>
            {effectiveError ? (
              <p className="mt-0.5 text-xs text-[var(--status-danger)]">{effectiveError}</p>
            ) : null}
          </div>
        </div>
        {stagedWorkingDirControls}
        </header>
      ) : (
        <>
          {effectiveError ? (
            <div role="alert" className="shrink-0 border-b border-[var(--workbench-hairline)] bg-[var(--status-danger-bg)] px-3 py-1 text-xs text-[var(--status-danger)]">
              {effectiveError}
            </div>
          ) : null}
          {stagedWorkingDirControls}
        </>
      )}
      <div data-testid="terminal-instance-id" className="sr-only">
        {instanceId}
      </div>

      <section className={`relative flex-1 overflow-hidden border-b border-[var(--workbench-hairline)] ${embedded ? "bg-transparent" : "bg-[var(--terminal-bg)]"}`}>
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
            <div data-testid="terminal-shell-frame" className={`h-full w-full px-3 py-2 ${embedded ? "bg-transparent" : "bg-[var(--terminal-bg)]"}`}>
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

      {!embedded && isVisible && onToggleImmersive ? (
        <ImmersiveToggleButton
          containerRef={terminalRootRef}
          isImmersive={isImmersive}
          storageKey={`tcb.terminalImmersiveButton.${botAlias}`}
          onToggle={onToggleImmersive}
        />
      ) : null}

      {!embedded ? (
        <div
          role="group"
          aria-label="终端快捷键"
          className="grid shrink-0 grid-cols-6 gap-1 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-1.5 pb-[calc(env(safe-area-inset-bottom)+0.375rem)]"
        >
          {MOBILE_TERMINAL_BUTTONS.map((button) => (
            <button
              key={button.ariaLabel}
              type="button"
              aria-label={button.ariaLabel}
              title={button.ariaLabel}
              onClick={() => {
                if (terminalDisabled) {
                  return;
                }
                if ("control" in button) {
                  sessionRef.current?.sendControl(button.control);
                } else {
                  sessionRef.current?.focus();
                }
              }}
              disabled={terminalDisabled}
              className="h-9 min-w-0 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-0.5 text-xs font-medium hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
            >
              {button.label}
            </button>
          ))}
        </div>
      ) : null}
    </main>
  );
}
