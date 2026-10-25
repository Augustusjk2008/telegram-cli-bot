import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatActionBar } from "../components/ChatActionBar";

test("mobile chat options keeps model, execution mode, and cluster controls reachable", async () => {
  const user = userEvent.setup();
  const onExecutionModeChange = vi.fn();
  const onProviderChange = vi.fn();
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
      providerOptions={[{ id: "deepseek", label: "DeepSeek" }, { id: "siliconflow", label: "SiliconFlow" }]}
      selectedProvider="deepseek"
      onProviderChange={onProviderChange}
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

  await user.selectOptions(screen.getByLabelText("Provider"), "siliconflow");
  await user.selectOptions(screen.getByLabelText("模型"), "opus");
  await user.click(screen.getByRole("button", { name: "原生 agent" }));
  await user.click(screen.getByRole("button", { name: "开启集群模式" }));

  expect(onModelChange).toHaveBeenCalledWith("opus");
  expect(onProviderChange).toHaveBeenCalledWith("siliconflow");
  expect(onExecutionModeChange).toHaveBeenCalledWith("native_agent");
  expect(onToggleClusterMode).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "关闭聊天选项" }));
  expect(screen.getByRole("button", { name: "聊天选项" })).toHaveFocus();
});

test("single DeepSeek provider is shown as a read-only chat option", async () => {
  render(
    <ChatActionBar
      mobileLayout
      executionMode="cli"
      onExecutionModeChange={() => undefined}
      planMode={false}
      onTogglePlanMode={() => undefined}
      clusterEnabled={false}
      onToggleClusterMode={() => undefined}
      onOpenHistoryPanel={() => undefined}
      providerOptions={[{ id: "deepseek", label: "DeepSeek" }]}
      selectedProvider="deepseek"
    />,
  );

  await userEvent.click(screen.getByRole("button", { name: "聊天选项" }));
  expect(screen.getByLabelText("Provider")).toHaveTextContent("DeepSeek");
  expect(screen.queryByRole("combobox", { name: "Provider" })).not.toBeInTheDocument();
});
