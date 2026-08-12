import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ClusterTeamPanel } from "../components/ClusterTeamPanel";
import type { ClusterAgentTask } from "../services/types";

function task(
  taskId: string,
  agentId: string,
  status: ClusterAgentTask["status"],
  assignmentRevision: number,
  modelTier: ClusterAgentTask["modelTier"] = "medium",
): ClusterAgentTask {
  return {
    taskId,
    agentId,
    assignmentRevision,
    status,
    modelTier,
    allowWrite: false,
    createdAt: "2026-08-12T00:00:00Z",
    startedAt: "2026-08-12T00:00:01Z",
    completedAt: status === "completed" ? "2026-08-12T00:00:02Z" : "",
    error: "",
  };
}

const team = {
  version: 1 as const,
  assignments: [
    {
      agentId: "cluster-slot-1",
      name: "前端审查",
      responsibility: "检查界面状态与回归测试",
      assignmentRevision: 2,
    },
    {
      agentId: "cluster-slot-2",
      name: "后端验证",
      responsibility: "验证接口与任务状态",
      assignmentRevision: 1,
    },
  ],
};

test("hides an empty team", () => {
  render(
    <ClusterTeamPanel
      team={{ version: 1, assignments: [] }}
      capacity={3}
      activeAgentId="main"
      onSelectAgent={() => undefined}
    />,
  );

  expect(screen.queryByTestId("cluster-team-panel")).not.toBeInTheDocument();
});

test("shows completed counts and live status inside flat assignment rows", async () => {
  const user = userEvent.setup();
  const onSelectAgent = vi.fn();
  render(
    <ClusterTeamPanel
      capacity={4}
      team={team}
      activeAgentId="main"
      onSelectAgent={onSelectAgent}
      slots={[
        {
          agentId: "cluster-slot-1",
          assigned: true,
          roleName: "旧静态名称",
          responsibility: "旧职责",
          assignmentRevision: 2,
          status: "idle",
        },
      ]}
      tasks={[
        task("task-1", "cluster-slot-1", "completed", 2),
        task("task-2", "cluster-slot-1", "completed", 2),
        task("task-3", "cluster-slot-1", "completed", 2),
        task("task-running", "cluster-slot-1", "running", 2, "high"),
        task("task-old-revision", "cluster-slot-1", "completed", 1),
        task("task-backend", "cluster-slot-2", "completed", 1),
      ]}
    />,
  );

  const rows = screen.getAllByTestId("cluster-team-assignment");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByText("前端审查")).toBeInTheDocument();
  expect(within(rows[0]).getByText("模型档位：high")).toBeInTheDocument();
  expect(within(rows[0]).getByText("已完成x3")).toBeInTheDocument();
  expect(within(rows[0]).getByText("处理中")).toBeInTheDocument();
  expect(within(rows[1]).getByText("已完成")).toBeInTheDocument();
  expect(within(rows[1]).getByText("待命")).toBeInTheDocument();
  expect(screen.queryByText("检查界面状态与回归测试")).not.toBeInTheDocument();
  expect(screen.queryByText("旧静态名称")).not.toBeInTheDocument();
  expect(screen.queryByText(/如需调整角色/)).not.toBeInTheDocument();
  expect(screen.getByTestId("cluster-team-panel").className).not.toContain("shadow-");

  await user.click(within(rows[0]).getByRole("button", { name: "查看前端审查对话" }));
  expect(onSelectAgent).toHaveBeenCalledWith("cluster-slot-1");
});

test("shows only the current child Agent and offers a return to main", async () => {
  const user = userEvent.setup();
  const onSelectAgent = vi.fn();
  render(
    <ClusterTeamPanel
      capacity={4}
      team={team}
      activeAgentId="cluster-slot-2"
      onSelectAgent={onSelectAgent}
      tasks={[task("task-backend", "cluster-slot-2", "completed", 1)]}
    />,
  );

  expect(screen.getByText("后端验证")).toBeInTheDocument();
  expect(screen.getByText("模型档位：medium")).toBeInTheDocument();
  expect(screen.queryByText("前端审查")).not.toBeInTheDocument();
  expect(screen.queryByText("验证接口与任务状态")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /查看.*对话/ })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "返回主 Agent" }));
  expect(onSelectAgent).toHaveBeenCalledWith("main");
});
