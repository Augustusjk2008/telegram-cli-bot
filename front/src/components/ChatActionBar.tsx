import { ClipboardList, History, LoaderCircle, Maximize2, Minimize2, Network, Square } from "lucide-react";
import { AgentSwitcher } from "./AgentSwitcher";
import type { AgentSummary } from "../services/types";

type Props = {
  visibleModelOptions: string[];
  selectedModel: string;
  modelDisabled?: boolean;
  onModelChange: (model: string) => void;
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

const groupClassName = "inline-flex shrink-0 items-center gap-2";
const neutralButtonClassName = "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-[var(--border)] px-3 text-sm font-medium text-[var(--muted)] hover:bg-[var(--surface-strong)] disabled:opacity-60";
const iconButtonClassName = "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]";

export function ChatActionBar({
  visibleModelOptions,
  selectedModel,
  modelDisabled = false,
  onModelChange,
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
    <section className="border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      <div
        data-testid="chat-action-bar"
        className="flex max-w-full gap-2 overflow-x-auto pb-1"
      >
        <div className={groupClassName} role="group" aria-label="聊天上下文">
          {visibleModelOptions.length > 0 ? (
            <select
              aria-label="模型"
              value={selectedModel}
              disabled={modelDisabled}
              onChange={(event) => onModelChange(event.target.value)}
              className="h-8 max-w-[10rem] shrink-0 truncate rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              {visibleModelOptions.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
            </select>
          ) : null}
          <AgentSwitcher
            agents={agents}
            activeAgentId={activeAgentId}
            disabled={agentDisabled}
            onSelect={onSelectAgent}
          />
        </div>
        <div className={groupClassName} role="group" aria-label="聊天模式">
          {showClusterToggle ? (
            <button
              type="button"
              aria-pressed={clusterMode}
              aria-label={clusterMode ? "关闭集群模式" : "开启集群模式"}
              onClick={onToggleClusterMode}
              disabled={clusterDisabled}
              className={clusterMode
                ? "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-60"
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
              ? "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-sky-200 bg-sky-50 px-3 text-sm font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-60"
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
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-[var(--border)] px-3 text-sm font-medium hover:bg-[var(--surface-strong)]"
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
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-3 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-60"
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
