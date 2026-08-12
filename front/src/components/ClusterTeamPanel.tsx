import type {
  ClusterAgentTask,
  ClusterSlotStatus,
  ClusterTeam,
  ClusterTeamAssignment,
} from "../services/types";

type Props = {
  team?: ClusterTeam | null;
  capacity: number;
  tasks?: ClusterAgentTask[];
  slots?: ClusterSlotStatus[];
};

function slotStatusForAssignment(
  assignment: ClusterTeamAssignment,
  tasks: ClusterAgentTask[],
): ClusterSlotStatus {
  const task = [...tasks].reverse().find((item) => item.agentId === assignment.agentId);
  const status = task && ["queued", "running", "completed", "failed", "cancelled"].includes(task.status)
    ? task.status as ClusterSlotStatus["status"]
    : "idle";
  return {
    agentId: assignment.agentId,
    assigned: true,
    roleName: assignment.name,
    responsibility: assignment.responsibility,
    assignmentRevision: assignment.assignmentRevision,
    status: status === "queued" || status === "running" ? status : "idle",
  };
}

function slotStatusText(status: ClusterSlotStatus["status"]) {
  if (status === "queued") return "排队中";
  if (status === "running") return "运行中";
  return "待命";
}

export function ClusterTeamPanel({ team, capacity, tasks = [], slots = [] }: Props) {
  const assignments = team?.assignments || [];
  if (assignments.length === 0) {
    return null;
  }
  const safeCapacity = Math.max(capacity, assignments.length);

  return (
    <section
      data-testid="cluster-team-panel"
      className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-2 text-sm text-[var(--text)] shadow-[var(--shadow-surface)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">集群编组</span>
        <span className="text-xs text-[var(--muted)]">已分配 {assignments.length} / 集群规模 {safeCapacity}</span>
      </div>
      <div className="mt-3 space-y-2">
        {assignments.map((assignment) => {
          const slot = slots.find((item) => item.agentId === assignment.agentId)
            || slotStatusForAssignment(assignment, tasks);
          return (
            <div key={`${assignment.agentId}:${assignment.assignmentRevision}`} className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface)] px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{assignment.name || assignment.agentId}</span>
                <span className="rounded-md bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--muted)]">
                  {slotStatusText(slot.status)}
                </span>
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words text-xs text-[var(--muted)]">{assignment.responsibility}</p>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-[var(--muted)]">如需调整角色，请通过普通聊天告诉主 Agent“重新编组”。</p>
    </section>
  );
}
