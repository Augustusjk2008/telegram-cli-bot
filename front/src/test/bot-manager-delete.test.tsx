import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { ClusterModelTiersPanel } from "../components/ClusterModelTiersPanel";
import { BotListScreen } from "../screens/BotListScreen";
import { DesktopBotManagerScreen } from "../screens/DesktopBotManagerScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";

test("bot list requires strong confirmation before deleting workspace", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const removeBot = vi.spyOn(client, "removeBot");

  render(<BotListScreen client={client} onSelect={vi.fn()} />);

  await user.click(await screen.findByRole("button", { name: "删除 team2" }));
  const dialog = await screen.findByRole("dialog", { name: "删除智能体 team2" });
  const historyCheckbox = within(dialog).getByLabelText("同时删除历史记录（包含所有子 agents）");

  await user.click(within(dialog).getByLabelText("同时删除工作区和所有记录"));
  expect(historyCheckbox).toBeChecked();
  expect(historyCheckbox).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "彻底删除" })).toBeDisabled();

  await user.type(within(dialog).getByLabelText("输入永久删除确认词"), "永久删除");
  await user.click(within(dialog).getByRole("button", { name: "彻底删除" }));

  expect(removeBot).toHaveBeenCalledWith("team2", { deleteHistory: true, deleteWorkspace: true });
});

test("desktop bulk delete does not expose workspace delete", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);

  await user.click(await screen.findByLabelText("选择 team2"));
  await user.click(screen.getByRole("button", { name: "批量删除" }));

  const dialog = await screen.findByRole("dialog", { name: "批量删除 1 个智能体" });
  expect(within(dialog).getByLabelText("同时删除历史记录（包含所有子 agents）")).toBeInTheDocument();
  expect(within(dialog).queryByLabelText("同时删除工作区和所有记录")).not.toBeInTheDocument();
});

test("desktop create panel submits unsafe bypass when explicitly checked", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const addBot = vi.spyOn(client, "addBot");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} canRunUnsafeCli />);

  await user.click(await screen.findByRole("button", { name: "新增智能体" }));
  const toggle = await screen.findByLabelText("新智能体默认绕过审批和沙箱");
  expect(toggle).not.toBeChecked();
  expect(toggle).not.toBeDisabled();

  await user.click(toggle);
  await user.type(screen.getByLabelText("新智能体别名"), "desktopunsafe");
  await user.clear(screen.getByLabelText("新智能体工作目录"));
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\desktopunsafe");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => {
    expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
      alias: "desktopunsafe",
      bypassApprovalAndSandbox: true,
    }));
  });
});

test("cluster model tiers configure model and reasoning independently", async () => {
  const user = userEvent.setup();
  const onReasoningChange = vi.fn();
  const props = {
    value: { low: "fast-model", medium: "", high: "" },
    reasoningEfforts: { low: "medium", medium: "", high: "" },
    modelOptions: ["fast-model", "strong-model"],
    reasoningOptions: ["ultra", "max", "xhigh", "high", "medium", "low"],
    onChange: vi.fn(),
    onReasoningChange,
  } as ComponentProps<typeof ClusterModelTiersPanel>;

  render(<ClusterModelTiersPanel {...props} />);

  expect(screen.getByLabelText("低档模型")).toHaveValue("fast-model");
  expect(screen.getByLabelText("低档思考深度")).toHaveValue("medium");
  await user.selectOptions(screen.getByLabelText("低档思考深度"), "ultra");
  expect(onReasoningChange).toHaveBeenCalledWith({ low: "ultra", medium: "", high: "" });
});

test("cluster settings expose one cluster size and hide fixed-role editors when enabled", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.updateClusterConfig("main", { enabled: true, maxParallelAgents: 4 });

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "配置" }));

  expect(await screen.findByLabelText("集群规模")).toHaveValue("4");
  expect(screen.getAllByLabelText("集群规模")).toHaveLength(1);
  expect(screen.getByLabelText("子 Agent 写入策略")).toHaveValue("all_agents");
  expect(screen.getByRole("option", { name: "允许子 Agent 写入" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "允许子 Agent 按任务申请写入" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("任务超时（秒）")).toHaveValue(1800);
  expect(screen.getByLabelText("任务超时（秒）")).toHaveAttribute("min", "60");
  expect(screen.getByLabelText("任务超时（秒）")).toHaveAttribute("max", "3600");
  expect(screen.queryByText("集群模板")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Agent" })).not.toBeInTheDocument();
});

test("cluster timeout saves on blur without reloading the bot list", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const listBots = vi.spyOn(client, "listBots");
  const updateClusterConfig = vi.spyOn(client, "updateClusterConfig");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "配置" }));

  const timeoutInput = await screen.findByLabelText("任务超时（秒）");
  fireEvent.change(timeoutInput, { target: { value: "2400" } });

  expect(timeoutInput).toHaveValue(2400);
  expect(updateClusterConfig).not.toHaveBeenCalled();
  expect(listBots).toHaveBeenCalledTimes(1);

  fireEvent.blur(timeoutInput);

  await waitFor(() => expect(updateClusterConfig).toHaveBeenCalledTimes(1));
  expect(updateClusterConfig).toHaveBeenCalledWith("main", expect.objectContaining({
    defaultTimeoutSeconds: 2400,
  }));
  expect(listBots).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "概览" }));
  await user.click(screen.getByRole("button", { name: "配置" }));
  expect(await screen.findByLabelText("任务超时（秒）")).toHaveValue(2400);
});

test("cluster resize blockers can open or archive the blocking conversation", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.updateClusterConfig("main", { enabled: true, maxParallelAgents: 4 });
  const originalUpdateClusterConfig = client.updateClusterConfig.bind(client);
  vi.spyOn(client, "updateClusterConfig").mockImplementation(async (alias, input) => {
    if (input.maxParallelAgents === 2) {
      throw new WebApiClientError("旧会话仍占用高位槽位", {
        status: 409,
        code: "cluster_resize_blocked",
        data: {
          code: "cluster_resize_blocked",
          targetSize: 2,
          minimumSize: 4,
          blockers: [{
            conversationId: "conv-blocked",
            title: "旧的并行任务",
            executionMode: "cli",
            roleCount: 3,
            outsideAgentIds: ["cluster-slot-4"],
            minimumSize: 4,
          }],
        },
      });
    }
    return originalUpdateClusterConfig(alias, input);
  });
  const selectConversation = vi.spyOn(client, "selectConversation").mockResolvedValue({
    conversation: {
      id: "conv-blocked",
      title: "旧的并行任务",
      lastMessagePreview: "",
      messageCount: 0,
      pinned: false,
      active: true,
      status: "active",
      botAlias: "main",
      cliType: "codex",
      agentId: "main",
      workingDir: "C:\\workspace",
      createdAt: "2026-08-12T00:00:00Z",
      updatedAt: "2026-08-12T00:00:00Z",
    },
    messages: [],
  });
  const archiveConversation = vi.spyOn(client, "archiveConversation").mockResolvedValue({
    archivedConversationId: "conv-blocked",
    activeConversationId: "",
    items: [],
  });
  const onSelect = vi.fn();

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={onSelect} />);
  await user.click(await screen.findByRole("button", { name: "配置" }));
  await user.selectOptions(await screen.findByLabelText("集群规模"), "2");

  const alert = await screen.findByRole("alert", { name: "缩容受阻" });
  expect(within(alert).getByText("旧的并行任务")).toBeInTheDocument();
  expect(within(alert).getByText(/cluster-slot-4/)).toBeInTheDocument();

  await user.click(within(alert).getByRole("button", { name: "打开会话" }));
  await waitFor(() => expect(selectConversation).toHaveBeenCalledWith("main", "conv-blocked", {
    agentId: "main",
    executionMode: "cli",
  }));
  expect(onSelect).toHaveBeenCalledWith("main");

  await user.click(within(alert).getByRole("button", { name: "归档会话" }));
  await waitFor(() => expect(archiveConversation).toHaveBeenCalledWith("main", "conv-blocked", {
    agentId: "main",
    executionMode: "cli",
  }));
  expect(screen.queryByRole("alert", { name: "缩容受阻" })).not.toBeInTheDocument();
});
