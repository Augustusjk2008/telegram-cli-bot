import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatActionBar } from "../components/ChatActionBar";

test("mobile chat options keeps model, execution mode, and cluster controls reachable", async () => {
  const user = userEvent.setup();
  const onExecutionModeChange = vi.fn();
  const onModelChange = vi.fn();
  const onToggleClusterMode = vi.fn();
  render(
    <ChatActionBar
      mobileLayout
      executionMode="cli"
      supportedExecutionModes={["cli", "native_agent"]}
      onExecutionModeChange={onExecutionModeChange}
      planMode={false}
      onTogglePlanMode={() => undefined}
      clusterEnabled={false}
      onToggleClusterMode={onToggleClusterMode}
      onOpenHistoryPanel={() => undefined}
      modelOptions={[{ value: "gpt", label: "GPT" }, { value: "opus", label: "Opus", title: "Claude Opus" }]}
      selectedModel="gpt"
      onModelChange={onModelChange}
      reasoningEffortOptions={["中", "高"]}
      selectedReasoningEffort="中"
      onReasoningEffortChange={() => undefined}
    />,
  );

  expect(screen.queryByLabelText("模型")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "聊天选项" }));
  expect(screen.getByRole("dialog", { name: "聊天选项" })).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("模型"), "opus");
  await user.click(screen.getByRole("button", { name: "原生 agent" }));
  await user.click(screen.getByRole("button", { name: "开启集群模式" }));

  expect(onModelChange).toHaveBeenCalledWith("opus");
  expect(onExecutionModeChange).toHaveBeenCalledWith("native_agent");
  expect(onToggleClusterMode).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "关闭聊天选项" }));
  expect(screen.getByRole("button", { name: "聊天选项" })).toHaveFocus();
});
