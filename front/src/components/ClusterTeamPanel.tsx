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
}: Props) {
  const assignments = team?.assignments || [];
  if (assignments.length === 0) {
    return null;
  }

  const viewingChild = activeAgentId !== "main";
  const visibleAssignments = viewingChild
    ? assignments.filter((assignment) => assignment.agentId === activeAgentId)
    : assignments;
  const safeCapacity = Math.max(capacity, assignments.length);

  return (
    <section
      data-testid="cluster-team-panel"
      className="bg-[var(--workbench-panel-elevated-bg)] px-3 py-2 text-sm text-[var(--text)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">集群编组</span>
        {viewingChild ? (
          <button
            type="button"
            aria-label="返回主 Agent"
            disabled={navigationDisabled}
            onClick={() => onSelectAgent("main")}
            className={toolbarButtonClass("ghost", "sm", "h-7 rounded-md px-2")}
          >
            返回主 Agent
          </button>
        ) : (
          <span className="text-xs text-[var(--muted)]">已分配 {assignments.length} / 集群规模 {safeCapacity}</span>
        )}
      </div>
      <div className="mt-1">
        {visibleAssignments.map((assignment) => {
          const matchingTasks = tasksForAssignment(assignment, tasks || []);
          const completedCount = matchingTasks.filter((task) => task.status === "completed").length;
          const processing = tasks !== undefined
            ? matchingTasks.some((task) => task.status === "queued" || task.status === "running")
            : slots.some((slot) => (
              slot.agentId === assignment.agentId
              && (slot.status === "queued" || slot.status === "running")
            ));
          const name = assignment.name || assignment.agentId;
          const modelTier = [...matchingTasks]
            .reverse()
            .find((task) => String(task.modelTier || "").trim())?.modelTier || "medium";
          return (
            <div
              key={`${assignment.agentId}:${assignment.assignmentRevision}`}
              data-testid="cluster-team-assignment"
              className="flex items-start gap-3 border-t border-[var(--workbench-hairline)] py-2"
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
                  className={toolbarButtonClass("ghost", "sm", "h-7 rounded-md px-2")}
                >
                  查看
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
