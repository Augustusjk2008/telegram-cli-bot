import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ClusterTeamPanel } from "../components/ClusterTeamPanel";

test("shows the automatic assignment hint for an empty team", () => {
  render(<ClusterTeamPanel team={{ version: 1, assignments: [] }} capacity={3} />);

  expect(screen.getByText("当前未编组，主 Agent 会在任务需要时自动分配角色")).toBeInTheDocument();
  expect(screen.getByText("已分配 0 / 集群规模 3")).toBeInTheDocument();
});

test("shows assigned roles, responsibilities, and current task status", () => {
  render(
    <ClusterTeamPanel
      capacity={4}
      team={{
        version: 1,
        assignments: [{
          agentId: "cluster-slot-1",
          name: "前端审查",
          responsibility: "检查界面状态与回归测试",
          assignmentRevision: 2,
        }],
      }}
      tasks={[{
        taskId: "task-1",
        agentId: "cluster-slot-1",
        roleName: "任务快照名称",
        responsibility: "任务快照职责",
        status: "running",
        modelTier: "medium",
        allowWrite: false,
        createdAt: "2026-08-12T00:00:00Z",
        startedAt: "2026-08-12T00:00:01Z",
        completedAt: "",
        error: "",
      }]}
    />,
  );

  expect(screen.getByText("前端审查")).toBeInTheDocument();
  expect(screen.getByText("检查界面状态与回归测试")).toBeInTheDocument();
  expect(screen.getByText("运行中")).toBeInTheDocument();
  expect(screen.getByText("已分配 1 / 集群规模 4")).toBeInTheDocument();
});
