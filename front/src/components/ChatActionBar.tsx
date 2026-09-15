import { useEffect, useRef, useState } from "react";
import { ChevronDown, ClipboardList, History, LoaderCircle, Maximize2, Minimize2, Network, Square, X } from "lucide-react";
import type { ChatComposerModelOption } from "./ChatComposer";
import { toolbarButtonClass } from "./ToolbarButton";
import type { ChatExecutionMode } from "../services/types";

type Props = {
  executionMode: ChatExecutionMode;
  supportedExecutionModes?: ChatExecutionMode[];
  executionModeDisabled?: boolean;
  onExecutionModeChange: (mode: ChatExecutionMode) => void;
  planMode: boolean;
  planDisabled?: boolean;
  onTogglePlanMode: () => void;
  clusterEnabled: boolean;
  clusterDisabled?: boolean;
  clusterSaving?: boolean;
  onToggleClusterMode: () => void;
  embedded?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onOpenHistoryPanel: () => void;
  onKillTask?: () => void;
  killTaskDisabled?: boolean;
  killTaskBusy?: boolean;
  mobileLayout?: boolean;
  modelOptions?: ChatComposerModelOption[];
  selectedModel?: string;
  modelDisabled?: boolean;
  onModelChange?: (model: string) => void;
  reasoningEffortOptions?: string[];
  selectedReasoningEffort?: string;
  reasoningEffortDisabled?: boolean;
  onReasoningEffortChange?: (effort: string) => void;
};

const groupClassName = "inline-flex shrink-0 items-center gap-1";
const neutralButtonClassName = toolbarButtonClass("ghost", "sm", "h-8 rounded-md border-transparent bg-transparent px-2 text-[var(--muted)]");
const iconButtonClassName = toolbarButtonClass("ghost", "icon", "h-8 w-8 rounded-md border-transparent bg-transparent");
const activePlanButtonClassName = "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-[var(--accent-outline)] bg-[var(--workbench-active-bg)] px-2 text-xs font-medium text-[var(--accent)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";
const segmentedButtonClassName = "inline-flex h-8 shrink-0 items-center rounded-md border border-transparent px-2 text-xs font-medium text-[var(--muted)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";
const activeSegmentedButtonClassName = "inline-flex h-8 shrink-0 items-center rounded-md border border-[var(--accent-outline)] bg-[var(--workbench-active-bg)] px-2 text-xs font-medium text-[var(--accent)] transition-colors hover:bg-[var(--workbench-hover-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-60";

export function ChatActionBar({
  executionMode,
  supportedExecutionModes = ["cli"],
  executionModeDisabled = false,
  onExecutionModeChange,
  planMode,
  planDisabled = false,
  onTogglePlanMode,
  clusterEnabled,
  clusterDisabled = false,
  clusterSaving = false,
  onToggleClusterMode,
  embedded = false,
  focused = false,
  onToggleFocus,
  onOpenHistoryPanel,
  onKillTask,
  killTaskDisabled = false,
  killTaskBusy = false,
  mobileLayout = false,
  modelOptions = [],
  selectedModel = "",
  modelDisabled = false,
  onModelChange,
  reasoningEffortOptions = [],
  selectedReasoningEffort = "",
  reasoningEffortDisabled = false,
  onReasoningEffortChange,
}: Props) {
  const [mobileOptionsOpen, setMobileOptionsOpen] = useState(false);
  const optionsRootRef = useRef<HTMLElement>(null);
  const optionsTriggerRef = useRef<HTMLButtonElement>(null);
  const optionsPanelRef = useRef<HTMLDivElement>(null);
  function closeOptions() {
    setMobileOptionsOpen(false);
    optionsTriggerRef.current?.focus();
  }
  useEffect(() => {
    if (!mobileOptionsOpen || !mobileLayout) return;
    optionsPanelRef.current?.focus();
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!optionsRootRef.current?.contains(event.target as Node)) setMobileOptionsOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeOptions();
      }
    };
    document.addEventListener("pointerdown", closeOnPointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [mobileLayout, mobileOptionsOpen]);
  if (mobileLayout) {
    const selectedModelLabel = modelOptions.find((option) => option.value === selectedModel)?.label || "模型";
    const optionsSummary = [
      executionMode === "native_agent" ? "原生" : "CLI",
      selectedModelLabel,
      selectedReasoningEffort,
    ].filter(Boolean).join(" · ");
    return (
      <section ref={optionsRootRef} className="relative z-10 h-10 shrink-0 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2">
        <div data-testid="chat-action-bar" className="flex h-full min-w-0 items-center gap-1">
          <button
            ref={optionsTriggerRef}
            type="button"
            aria-label="聊天选项"
            aria-haspopup="dialog"
            aria-expanded={mobileOptionsOpen}
            title={`聊天选项：${optionsSummary}`}
            onClick={() => setMobileOptionsOpen((value) => !value)}
            className="inline-flex h-8 min-w-0 flex-1 items-center gap-1 rounded-md px-1 text-left text-xs text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
          >
            <span className="min-w-0 truncate">{optionsSummary}</span>
            {clusterEnabled ? <span className="shrink-0 text-[10px] text-[var(--accent)]">集群</span> : null}
            <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-[var(--muted)] transition-transform ${mobileOptionsOpen ? "rotate-180" : ""}`} />
          </button>
          <button
            type="button"
            aria-label="计划模式"
            aria-pressed={planMode}
            onClick={onTogglePlanMode}
            disabled={planDisabled}
            className={planMode ? activePlanButtonClassName : neutralButtonClassName}
          >计划</button>
          <button type="button" aria-label="历史会话" onClick={onOpenHistoryPanel} className={neutralButtonClassName}>会话</button>
          {embedded && onToggleFocus ? (
            <button
              type="button"
              aria-label={focused ? "退出聚焦聊天" : "聚焦聊天"}
              title={focused ? "退出聚焦聊天" : "聚焦聊天"}
              onClick={onToggleFocus}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)]"
            >
              {focused ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          ) : null}
          {onKillTask ? (
            <button type="button" aria-label="终止任务" onClick={onKillTask} disabled={killTaskDisabled} className={toolbarButtonClass("danger", "sm", "h-8 shrink-0 rounded-md px-1.5")}>
              {killTaskBusy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
              {killTaskBusy ? "终止中" : "终止"}
            </button>
          ) : null}
        </div>
        {mobileOptionsOpen ? (
          <div
            ref={optionsPanelRef}
            role="dialog"
            aria-label="聊天选项"
            tabIndex={-1}
            className="absolute left-2 right-2 top-10 z-50 max-h-[min(70dvh,24rem)] overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] p-2 shadow-[var(--shadow-card)]"
          >
            <div className="mb-2 flex items-center justify-between text-sm font-medium">
              聊天选项
              <button type="button" aria-label="关闭聊天选项" onClick={closeOptions} className={iconButtonClassName}><X className="h-4 w-4" /></button>
            </div>
            {supportedExecutionModes.length > 1 ? (
              <div className="mb-2 flex items-center gap-1" role="group" aria-label="执行模式">
                {supportedExecutionModes.map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={executionMode === mode}
                    disabled={executionModeDisabled}
                    onClick={() => onExecutionModeChange(mode)}
                    className={executionMode === mode ? activeSegmentedButtonClassName : segmentedButtonClassName}
                  >{mode === "native_agent" ? "原生 agent" : "CLI"}</button>
                ))}
              </div>
            ) : <p className="mb-2 text-xs">执行模式：{executionMode === "native_agent" ? "原生 agent" : "CLI"}</p>}
            {modelOptions.length > 0 ? (
              <label className="mb-2 block text-xs text-[var(--muted)]">
                模型
                <select
                  value={selectedModel}
                  disabled={modelDisabled || !onModelChange}
                  onChange={(event) => onModelChange?.(event.target.value)}
                  className="mt-1 h-8 w-full rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] px-2 text-xs text-[var(--text)]"
                >
                  {modelOptions.map((option) => <option key={option.value} value={option.value}>{option.title || option.label}</option>)}
                </select>
              </label>
            ) : null}
            {reasoningEffortOptions.length > 0 ? (
              <label className="mb-2 block text-xs text-[var(--muted)]">
                思考深度
                <select
                  value={selectedReasoningEffort}
                  disabled={reasoningEffortDisabled || !onReasoningEffortChange}
                  onChange={(event) => onReasoningEffortChange?.(event.target.value)}
                  className="mt-1 h-8 w-full rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] px-2 text-xs text-[var(--text)]"
                >
                  {reasoningEffortOptions.map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                </select>
              </label>
            ) : null}
            <button
              type="button"
              aria-pressed={clusterEnabled}
              aria-label={clusterEnabled ? "关闭集群模式" : "开启集群模式"}
              onClick={onToggleClusterMode}
              disabled={clusterDisabled}
              className={clusterEnabled ? activePlanButtonClassName : neutralButtonClassName}
            >
              {clusterSaving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
              集群{clusterEnabled ? " 已开启" : ""}
            </button>
          </div>
        ) : null}
      </section>
    );
  }
  return (
    <section className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-1.5">
      <div
        data-testid="chat-action-bar"
        className="flex max-w-full gap-1.5 overflow-x-auto"
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
        <div className={groupClassName} role="group" aria-label="聊天模式">
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
          <button
            type="button"
            aria-pressed={clusterEnabled}
            aria-label={clusterEnabled ? "关闭集群模式" : "开启集群模式"}
            onClick={onToggleClusterMode}
            disabled={clusterDisabled}
            className={clusterEnabled
              ? activePlanButtonClassName
              : neutralButtonClassName}
          >
            {clusterSaving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
            集群
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
