import { useId, useState } from "react";
import type {
  ClusterAgentTask,
  ClusterSlotStatus,
  ClusterTeam,
  ClusterTeamAssignment,
} from "../services/types";
import { toolbarButtonClass } from "./ToolbarButton";

type Props = {
  team?: ClusterTeam | null;
  capacity: number;
  tasks?: ClusterAgentTask[];
  slots?: ClusterSlotStatus[];
  activeAgentId: string;
  navigationDisabled?: boolean;
  onSelectAgent: (agentId: string) => void;
  mobileLayout?: boolean;
};

function tasksForAssignment(
  assignment: ClusterTeamAssignment,
  tasks: ClusterAgentTask[],
) {
  return tasks.filter((task) => (
    task.agentId === assignment.agentId
    && (
      typeof task.assignmentRevision !== "number"
      || task.assignmentRevision === assignment.assignmentRevision
    )
  ));
}

export function ClusterTeamPanel({
  team,
  capacity,
  tasks,
  slots = [],
  activeAgentId,
  navigationDisabled = false,
  onSelectAgent,
  mobileLayout = false,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const assignmentsId = useId();
  const assignments = team?.assignments || [];
  if (assignments.length === 0) {
    return null;
  }

  const viewingChild = activeAgentId !== "main";
  const visibleAssignments = viewingChild
    ? assignments.filter((assignment) => assignment.agentId === activeAgentId)
    : assignments;
  const safeCapacity = Math.max(capacity, assignments.length);
  const isProcessing = (assignment: ClusterTeamAssignment) => tasks !== undefined
    ? tasksForAssignment(assignment, tasks).some((task) => task.status === "queued" || task.status === "running")
    : slots.some((slot) => slot.agentId === assignment.agentId && (slot.status === "queued" || slot.status === "running"));
  const runningCount = assignments.filter(isProcessing).length;
  const activeAgentName = viewingChild
    ? assignments.find((assignment) => assignment.agentId === activeAgentId)?.name || activeAgentId
    : "主 Agent";

  return (
    <section
      data-testid="cluster-team-panel"
      className={`bg-[var(--workbench-panel-elevated-bg)] text-sm text-[var(--text)] ${mobileLayout ? "px-2 py-1" : "px-3 py-2"}`}
    >
      <div className={mobileLayout ? "flex min-h-7 min-w-0 items-center justify-between gap-1" : "flex flex-wrap items-center justify-between gap-2"}>
        <span className={mobileLayout ? "min-w-0 truncate text-xs font-medium" : "font-medium"}>
          {mobileLayout ? `集群 ${assignments.length}/${safeCapacity} · ${runningCount ? `${runningCount} 个运行中` : "待命"} · ${activeAgentName}` : "集群编组"}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          {viewingChild ? (
            <button
              type="button"
              aria-label="返回主 Agent"
              disabled={navigationDisabled}
              onClick={() => onSelectAgent("main")}
              className={toolbarButtonClass("ghost", "sm", "h-7 rounded-md px-2")}
            >
              {mobileLayout ? "主 Agent" : "返回主 Agent"}
            </button>
          ) : !mobileLayout ? (
            <span className="text-xs text-[var(--muted)]">已分配 {assignments.length} / 集群规模 {safeCapacity}</span>
          ) : null}
          <button
            type="button"
            aria-label={expanded ? "收起集群编组" : "展开集群编组"}
            aria-controls={assignmentsId}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
            className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-xs text-[var(--muted)] transition-colors hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]"
          >
            <span aria-hidden="true">{expanded ? "▼" : "▲"}</span>
          </button>
        </div>
      </div>
      {expanded ? <div id={assignmentsId} className={`mt-1 ${mobileLayout ? "max-h-40 overflow-y-auto" : ""}`}>
        {visibleAssignments.map((assignment) => {
          const matchingTasks = tasksForAssignment(assignment, tasks || []);
          const completedCount = matchingTasks.filter((task) => task.status === "completed").length;
          const processing = isProcessing(assignment);
          const name = assignment.name || assignment.agentId;
          const modelTier = [...matchingTasks]
            .reverse()
            .find((task) => String(task.modelTier || "").trim())?.modelTier || "medium";
          return (
            <div
              key={`${assignment.agentId}:${assignment.assignmentRevision}`}
              data-testid="cluster-team-assignment"
              className={`flex items-start gap-3 border-t border-[var(--workbench-hairline)] ${mobileLayout ? "py-1" : "py-2"}`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-medium">{name}</span>
                  {completedCount > 0 ? (
                    <span className="text-xs text-[var(--muted)]">
                      {completedCount === 1 ? "已完成" : `已完成x${completedCount}`}
                    </span>
                  ) : null}
                  <span className={processing ? "text-xs font-medium text-[var(--accent)]" : "text-xs text-[var(--muted)]"}>
                    {processing ? "处理中" : "待命"}
                  </span>
                  <span className="text-xs text-[var(--muted)]">模型档位：{modelTier}</span>
                </div>
              </div>
              {!viewingChild ? (
                <button
                  type="button"
                  aria-label={`查看${name}对话`}
                  disabled={navigationDisabled}
                  onClick={() => onSelectAgent(assignment.agentId)}
                  className="inline-flex h-4 shrink-0 items-center justify-center rounded px-1.5 text-xs font-medium leading-4 text-[var(--muted)] transition-colors hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:pointer-events-none disabled:opacity-55"
                >
                  查看
                </button>
              ) : null}
            </div>
          );
        })}
      </div> : null}
    </section>
  );
}
