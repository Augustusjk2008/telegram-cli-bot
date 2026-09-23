import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import type { WebBotClient } from "../services/webBotClient";
import { usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";
import type { TerminalWorkbenchStatus } from "../workbench/workbenchTypes";

const TerminalScreen = lazy(() =>
  import("./TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

type Props = {
  authToken: string;
  botAlias: string;
  client: WebBotClient;
  isVisible: boolean;
  preferredWorkingDir: string;
  remote?: boolean;
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

function tabButtonClass(active: boolean) {
  return [
    "inline-flex h-9 min-w-0 max-w-48 items-center gap-1.5 border-r border-[var(--workbench-hairline)] px-3 text-xs transition-colors",
    active
      ? "bg-[var(--terminal-bg)] text-[var(--text)]"
      : "bg-[var(--workbench-titlebar-bg)] text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]",
  ].join(" ");
}

export function TerminalTabsScreen({
  authToken,
  botAlias,
  client,
  isVisible,
  preferredWorkingDir,
  remote = false,
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
  const [creating, setCreating] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [reconnectVersions, setReconnectVersions] = useState<Record<string, number>>({});
  const [closingTabId, setClosingTabId] = useState("");
  const [toolbarHost, setToolbarHost] = useState<HTMLDivElement | null>(null);
  const visibleTabs = terminal.tabs.filter((tab) => remote ? tab.botAlias === botAlias : !tab.botAlias);

  const createTerminal = useCallback(async () => {
    if (disabledReason || creating) {
      return;
    }
    setCreating(true);
    try {
      await terminal.createTab({
        cwd: remote ? preferredWorkingDir : (terminal.activeTab?.botAlias ? preferredWorkingDir : terminal.activeTab?.cwd || preferredWorkingDir),
        ...(remote ? { botAlias, title: `SSH ${botAlias}` } : {}),
      });
    } finally {
      setCreating(false);
    }
  }, [creating, disabledReason, preferredWorkingDir, terminal, remote, botAlias]);

  const closeTerminalTab = useCallback(async (tabId: string) => {
    if (closingTabId || disabledReason) {
      return;
    }
    setClosingTabId(tabId);
    try {
      await terminal.closeTab(tabId);
    } finally {
      setClosingTabId("");
    }
  }, [closingTabId, disabledReason, terminal]);

  const activeTab = visibleTabs.find((tab) => tab.id === terminal.activeTabId);

  useEffect(() => {
    if (!activeTab && visibleTabs[0]) terminal.selectTab(visibleTabs[0].id);
  }, [activeTab, visibleTabs, terminal]);

  useEffect(() => {
    if (activeTab || !onWorkbenchStatusChange) {
      return;
    }
    onWorkbenchStatusChange({
      connected: false,
      connectionText: "未启动",
      currentCwd: "",
    });
  }, [activeTab, onWorkbenchStatusChange]);

  return (
    <main data-testid="terminal-tabs-screen" data-ui-density="compact" className="flex h-full min-h-0 flex-col bg-[var(--workbench-panel-bg)]">
      <div className="flex min-h-10 shrink-0 items-stretch border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)]">
        <div
          role="tablist"
          aria-label="终端选项卡"
          className="flex min-w-0 flex-1 items-stretch overflow-x-auto"
        >
          {visibleTabs.map((tab) => {
            const active = tab.id === terminal.activeTabId;
            const closing = closingTabId === tab.id;
            return (
              <div key={tab.id} className="flex shrink-0 items-center border-r border-[var(--workbench-hairline)]">
                <button
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-controls={`terminal-panel-${tab.id}`}
                  onClick={() => terminal.selectTab(tab.id)}
                  className={tabButtonClass(active)}
                >
                  <span className="max-w-32 truncate">{tab.title}</span>
                </button>
                <button
                  type="button"
                  aria-label={`关闭${tab.title}`}
                  title={`关闭${tab.title}`}
                  disabled={Boolean(closingTabId) || Boolean(disabledReason)}
                  onClick={() => void closeTerminalTab(tab.id)}
                  className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {closing ? <span className="text-[10px]">...</span> : <X className="h-3.5 w-3.5" />}
                </button>
              </div>
            );
          })}
          <button
            type="button"
            aria-label="新建终端"
            title="新建终端"
            onClick={() => void createTerminal()}
            disabled={Boolean(disabledReason) || creating}
            className="ml-1 inline-flex h-8 w-8 shrink-0 self-center items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
        {activeTab?.botAlias && <button type="button" className="px-3 text-xs" disabled={Boolean(disabledReason) || reconnecting} onClick={async () => {
          setReconnecting(true);
          try {
            await terminal.restartTab(activeTab.id);
            setReconnectVersions((prev) => ({ ...prev, [activeTab.id]: (prev[activeTab.id] || 0) + 1 }));
          } finally { setReconnecting(false); }
        }}>{reconnecting ? "连接中…" : "重新连接终端"}</button>}
        {embedded ? (
          <div
            ref={setToolbarHost}
            data-testid="terminal-tabs-toolbar"
            className="ml-auto flex shrink-0 items-center gap-1 border-l border-[var(--workbench-hairline)] px-1"
          />
        ) : null}
      </div>

      <div id={`terminal-panel-${activeTab?.id || "empty"}`} role="tabpanel" className="min-h-0 flex-1">
        <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">加载终端...</div>}>
          {activeTab || (!remote && !terminal.activeTab?.botAlias) ? <TerminalScreen
            key={activeTab ? `${activeTab.id}:${reconnectVersions[activeTab.id] || 0}` : "empty-terminal"}
            authToken={authToken}
            botAlias={botAlias}
            remote={Boolean(activeTab?.botAlias)}
            client={client}
            isVisible={isVisible}
            pendingWorkingDir={pendingWorkingDir}
            themeName={themeName}
            isImmersive={isImmersive}
            disabledReason={disabledReason}
            embedded={embedded}
            focused={focused}
            toolbarHost={embedded ? toolbarHost : null}
            onToggleFocus={onToggleFocus}
            onToggleImmersive={onToggleImmersive}
            onAcceptPendingWorkingDir={onAcceptPendingWorkingDir}
            onCancelPendingWorkingDir={onCancelPendingWorkingDir}
            onWorkbenchStatusChange={onWorkbenchStatusChange}
          /> : <div className="p-4 text-sm text-[var(--muted)]">{remote ? "点击 + 新建 SSH 终端" : "点击 + 新建终端"}</div>}
        </Suspense>
      </div>
    </main>
  );
}
