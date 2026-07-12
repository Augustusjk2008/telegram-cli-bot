import { ClipboardList, History, LoaderCircle, Maximize2, Minimize2, Network, Square } from "lucide-react";
import { AgentSwitcher } from "./AgentSwitcher";
import { toolbarButtonClass } from "./ToolbarButton";
import type { AgentSummary, ChatExecutionMode } from "../services/types";

type Props = {
  executionMode: ChatExecutionMode;
  supportedExecutionModes?: ChatExecutionMode[];
  executionModeDisabled?: boolean;
  onExecutionModeChange: (mode: ChatExecutionMode) => void;
  agents: AgentSummary[];
  activeAgentId: string;
  agentDisabled?: boolean;
  onSelectAgent: (agentId: string) => void;
  showClusterToggle: boolean;
  clusterMode: boolean;
  clusterSaving: boolean;
  clusterDisabled?: boolean;
  onToggleClusterMode: () => void;
  planMode: boolean;
  planDisabled?: boolean;
  onTogglePlanMode: () => void;
  embedded?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onOpenHistoryPanel: () => void;
  onKillTask?: () => void;
  killTaskDisabled?: boolean;
  killTaskBusy?: boolean;
};

const groupClassName = "inline-flex shrink-0 items-center gap-1";
const neutralButtonClassName = toolbarButtonClass("ghost", "sm", "h-8 rounded-md border-transparent bg-transparent px-2.5 text-[var(--muted)]");
const iconButtonClassName = toolbarButtonClass("ghost", "icon", "h-8 w-8 rounded-md border-transparent bg-transparent");
const activeClusterButtonClassName = "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] px-2.5 text-xs font-medium text-[var(--accent)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";
const activePlanButtonClassName = "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-[var(--accent-outline)] bg-[var(--workbench-active-bg)] px-2.5 text-xs font-medium text-[var(--accent)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";
const segmentedButtonClassName = "inline-flex h-8 shrink-0 items-center rounded-md border border-transparent px-2.5 text-xs font-medium text-[var(--muted)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";
const activeSegmentedButtonClassName = "inline-flex h-8 shrink-0 items-center rounded-md border border-[var(--accent-outline)] bg-[var(--workbench-active-bg)] px-2.5 text-xs font-medium text-[var(--accent)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";

export function ChatActionBar({
  executionMode,
  supportedExecutionModes = ["cli"],
  executionModeDisabled = false,
  onExecutionModeChange,
  agents,
  activeAgentId,
  agentDisabled = false,
  onSelectAgent,
  showClusterToggle,
  clusterMode,
  clusterSaving,
  clusterDisabled = false,
  onToggleClusterMode,
  planMode,
  planDisabled = false,
  onTogglePlanMode,
  embedded = false,
  focused = false,
  onToggleFocus,
  onOpenHistoryPanel,
  onKillTask,
  killTaskDisabled = false,
  killTaskBusy = false,
}: Props) {
  return (
    <section className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-3 py-2">
      <div
        data-testid="chat-action-bar"
        className="flex max-w-full gap-2 overflow-x-auto"
      >
        {supportedExecutionModes.length > 1 ? (
          <div className={groupClassName} role="group" aria-label="执行模式">
            <button
              type="button"
              aria-pressed={executionMode === "cli"}
              disabled={executionModeDisabled}
              onClick={() => onExecutionModeChange("cli")}
              className={executionMode === "cli" ? activeSegmentedButtonClassName : segmentedButtonClassName}
            >
              CLI
            </button>
            <button
              type="button"
              aria-pressed={executionMode === "native_agent"}
              disabled={executionModeDisabled}
              onClick={() => onExecutionModeChange("native_agent")}
              className={executionMode === "native_agent" ? activeSegmentedButtonClassName : segmentedButtonClassName}
            >
              原生 agent
            </button>
          </div>
        ) : null}
        {agents.length > 1 ? (
          <div className={groupClassName} role="group" aria-label="聊天上下文">
            <AgentSwitcher
              agents={agents}
              activeAgentId={activeAgentId}
              disabled={agentDisabled}
              onSelect={onSelectAgent}
            />
          </div>
        ) : null}
        <div className={groupClassName} role="group" aria-label="聊天模式">
          {showClusterToggle ? (
            <button
              type="button"
              aria-pressed={clusterMode}
              aria-label={clusterMode ? "关闭集群模式" : "开启集群模式"}
              onClick={onToggleClusterMode}
              disabled={clusterDisabled}
              className={clusterMode
                ? activeClusterButtonClassName
                : neutralButtonClassName}
            >
              {clusterSaving ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Network className="h-4 w-4" />
              )}
              {clusterSaving ? "保存中" : "集群"}
            </button>
          ) : null}
          <button
            type="button"
            aria-pressed={planMode}
            aria-label="计划模式"
            onClick={onTogglePlanMode}
            disabled={planDisabled}
            className={planMode
              ? activePlanButtonClassName
              : neutralButtonClassName}
          >
            <ClipboardList className="h-4 w-4" />
            计划
          </button>
        </div>
        <div className={groupClassName} role="group" aria-label="聊天会话">
          <button
            type="button"
            aria-label="历史会话"
            onClick={onOpenHistoryPanel}
            className={toolbarButtonClass("plain", "sm", "h-8 rounded-md px-2.5")}
          >
            <History className="h-4 w-4" />
            会话
          </button>
          {embedded && onToggleFocus ? (
            <button
              type="button"
              aria-label={focused ? "退出聚焦聊天" : "聚焦聊天"}
              title={focused ? "退出聚焦聊天" : "聚焦聊天"}
              onClick={onToggleFocus}
              className={iconButtonClassName}
            >
              {focused ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          ) : null}
          {onKillTask ? (
            <button
              type="button"
              aria-label="终止任务"
              onClick={onKillTask}
              disabled={killTaskDisabled}
              className={toolbarButtonClass("danger", "sm", "h-8 rounded-md px-2.5")}
            >
              {killTaskBusy ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-4 w-4" />
              )}
              {killTaskBusy ? "终止中" : "终止"}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
