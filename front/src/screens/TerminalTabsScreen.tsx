import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Maximize2, Minimize2, Plus, X } from "lucide-react";
import type {
  TerminalAction,
  TerminalActionsConfig,
  TerminalActionsEditableConfig,
  TerminalRuntimePlatform,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { TerminalActionsBar } from "../terminal/TerminalActionsBar";
import { TerminalActionsConfigDialog } from "../terminal/TerminalActionsConfigDialog";
import { isTerminalActionVisible, resolveTerminalActionCommand } from "../terminal/terminalActionPlatform";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";
import type { TerminalWorkbenchStatus } from "../workbench/workbenchTypes";

const TerminalScreen = lazy(() =>
  import("./TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

const EMPTY_TERMINAL_ACTIONS_CONFIG: TerminalActionsConfig = {
  schemaVersion: 1,
  actions: [],
  configPath: "",
  exists: false,
  mtimeNs: "",
  editable: false,
  errors: [],
  runtimePlatform: "windows",
};

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
  const [actionsConfig, setActionsConfig] = useState<TerminalActionsConfig>(EMPTY_TERMINAL_ACTIONS_CONFIG);
  const [actionsError, setActionsError] = useState("");
  const [runningActionId, setRunningActionId] = useState("");
  const [showActionsConfig, setShowActionsConfig] = useState(false);
  const [savingActionsConfig, setSavingActionsConfig] = useState(false);
  const [actionsConfigError, setActionsConfigError] = useState("");
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
    let cancelled = false;
    setActionsConfig(EMPTY_TERMINAL_ACTIONS_CONFIG);
    setActionsError("");
    client.getTerminalActionsConfig(botAlias)
      .then((next) => {
        if (cancelled) return;
        setActionsConfig(next);
        setActionsError(next.errors[0] || "");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setActionsError(err instanceof Error ? err.message : "加载快捷命令失败");
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

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

  const runtimePlatform: TerminalRuntimePlatform = actionsConfig?.runtimePlatform ?? "windows";
  const visibleActions = actionsConfig?.actions.filter((action) => isTerminalActionVisible(action, runtimePlatform)) ?? [];
  const actionDisabledReason = disabledReason;
  const focusDisabledReason = disabledReason || (!activeTab ? "请先打开终端" : "");

  async function runTerminalAction(action: TerminalAction) {
    if (disabledReason || runningActionId) {
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
      const actionTab = terminal.tabs.find((tab) => (
        tab.terminalActionBotAlias === botAlias
        && tab.terminalActionId === action.id
        && (remote ? tab.botAlias === botAlias : !tab.botAlias)
      ));
      const tab = actionTab || await terminal.createTab({
        title: action.label,
        start: false,
        activate: false,
        ...(remote ? { botAlias } : {}),
        terminalActionBotAlias: botAlias,
        terminalActionId: action.id,
      });
      await client.runTerminalAction(botAlias, action.id, {
        ownerId: tab.ownerId,
        confirmed: true,
      });
      await terminal.refreshSnapshot(tab.ownerId);
      terminal.selectTab(tab.id);
    } catch (err) {
      setActionsError(err instanceof Error ? err.message : "执行快捷命令失败");
    } finally {
      setRunningActionId("");
    }
  }

  async function saveTerminalActionsConfig(nextConfig: TerminalActionsEditableConfig) {
    if (disabledReason) {
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

  const toolbar = (
    <div
      data-testid="terminal-tabs-toolbar"
      className={`terminal-tabs-toolbar flex min-w-0 max-w-full shrink-0 items-center gap-1 ${embedded ? "border-l border-[var(--workbench-hairline)] px-1" : "w-full border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-1.5"}`}
    >
      <TerminalActionsBar
        actions={visibleActions}
        runtimePlatform={runtimePlatform}
        canEdit={Boolean(actionsConfig)}
        disabled={Boolean(actionDisabledReason)}
        disabledReason={actionDisabledReason}
        disableEdit={!actionsConfig?.editable || Boolean(disabledReason)}
        runningActionId={runningActionId}
        onRunAction={(action) => void runTerminalAction(action)}
        onOpenConfig={() => {
          setActionsConfigError("");
          setShowActionsConfig(true);
        }}
      />
      {onToggleFocus ? (
        <button
          type="button"
          aria-label={focused ? "退出聚焦终端" : "聚焦终端"}
          title={focusDisabledReason || (focused ? "退出聚焦终端" : "聚焦终端")}
          disabled={Boolean(focusDisabledReason)}
          onClick={onToggleFocus}
          className={toolbarButtonClass("ghost", "icon", "h-8 w-8 border-[var(--workbench-hairline)]")}
        >
          {focused ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </button>
      ) : null}
      {actionsError ? <span role="alert" className="max-w-48 truncate px-1 text-[11px] text-[var(--status-danger)]" title={actionsError}>{actionsError}</span> : null}
    </div>
  );

  return (
    <>
      <main data-testid="terminal-tabs-screen" data-ui-density="compact" className="terminal-tabs-screen relative z-[20] flex h-full min-h-0 flex-col bg-[var(--workbench-panel-bg)]">
        <div className="terminal-tab-strip flex min-h-10 shrink-0 items-stretch border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)]">
          <div
            role="tablist"
            aria-label="终端选项卡"
            className="flex min-w-0 flex-1 items-stretch overflow-x-auto overflow-y-hidden"
          >
            {visibleTabs.map((tab) => {
              const active = tab.id === terminal.activeTabId;
              const closing = closingTabId === tab.id;
              return (
                <div key={tab.id} data-active={active ? "true" : "false"} className="terminal-tab flex shrink-0 items-center border-r border-[var(--workbench-hairline)]">
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
              className="ml-1 inline-flex h-8 max-h-full w-8 shrink-0 self-center items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-50"
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
          {embedded ? toolbar : null}
        </div>

        {!embedded ? toolbar : null}

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
              onToggleImmersive={onToggleImmersive}
              onAcceptPendingWorkingDir={onAcceptPendingWorkingDir}
              onCancelPendingWorkingDir={onCancelPendingWorkingDir}
              onWorkbenchStatusChange={onWorkbenchStatusChange}
            /> : <div className="p-4 text-sm text-[var(--muted)]">{remote ? "点击 + 新建 SSH 终端" : "点击 + 新建终端"}</div>}
          </Suspense>
        </div>
      </main>
      {showActionsConfig && actionsConfig && !disabledReason ? (
        <TerminalActionsConfigDialog
          config={actionsConfig}
          saving={savingActionsConfig}
          error={actionsConfigError}
          onSave={(nextConfig) => void saveTerminalActionsConfig(nextConfig)}
          onClose={() => setShowActionsConfig(false)}
        />
      ) : null}
    </>
  );
}
