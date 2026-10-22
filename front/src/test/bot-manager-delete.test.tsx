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

test("bot list archives and restores a non-main bot", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const archiveBot = vi.spyOn(client, "archiveBot");
  const unarchiveBot = vi.spyOn(client, "unarchiveBot");
  const onBotsChange = vi.fn();

  render(<BotListScreen client={client} onSelect={vi.fn()} onBotsChange={onBotsChange} />);

  await user.click(await screen.findByRole("button", { name: "归档 team2" }));
  await waitFor(() => expect(archiveBot).toHaveBeenCalledWith("team2"));
  expect(await screen.findByText("已归档")).toBeInTheDocument();
  expect(onBotsChange.mock.lastCall?.[0].some((bot: { alias: string }) => bot.alias === "team2")).toBe(false);
  expect((await client.listBots()).some((bot) => bot.alias === "team2")).toBe(false);

  await user.click(screen.getByRole("button", { name: "取消归档 team2" }));
  await waitFor(() => expect(unarchiveBot).toHaveBeenCalledWith("team2"));
});

test("desktop manager exposes archive lifecycle actions", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const archiveBot = vi.spyOn(client, "archiveBot");
  const unarchiveBot = vi.spyOn(client, "unarchiveBot");

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);

  await user.click(await screen.findByRole("button", { name: "聚焦 team2" }));
  await user.click(screen.getByRole("button", { name: "归档 team2" }));
  await waitFor(() => expect(archiveBot).toHaveBeenCalledWith("team2"));
  expect(await screen.findByRole("button", { name: "取消归档 team2" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "取消归档 team2" }));
  await waitFor(() => expect(unarchiveBot).toHaveBeenCalledWith("team2"));
});

test("desktop agent list labels remote workspaces", async () => {
  const client = new MockWebBotClient();
  const listBots = client.listBots.bind(client);
  vi.spyOn(client, "listBots").mockImplementation(async () => (await listBots()).map((bot) => (
    bot.alias === "team2"
      ? { ...bot, remoteWorkspace: { connectionId: "ssh-1", host: "remote.test", port: 22, username: "dev", root: "/work", hostKeyFingerprint: "SHA256:test" } }
      : bot
  )));

  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);

  expect(within(await screen.findByRole("button", { name: "聚焦 team2" })).getByText("远程")).toBeInTheDocument();
  expect(within(screen.getByRole("button", { name: "聚焦 main" })).queryByText("远程")).not.toBeInTheDocument();
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

test.each(["codex", "pi", "deepseek"])("%s exposes the shared cluster controls and hides fixed-role editors when enabled", async (runtime) => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  if (runtime === "pi") {
    await client.updateBotExecutionConfig("main", {
      supportedExecutionModes: ["native_agent"], defaultExecutionMode: "native_agent",
      nativeAgent: { provider: "", model: "", piAgent: "" },
    });
  } else {
    await client.updateBotCli("main", runtime, runtime === "deepseek" ? "dsh" : "codex");
  }
  await client.updateClusterConfig("main", { enabled: true, maxParallelAgents: 4 });
  const updateCluster = vi.spyOn(client, "updateClusterConfig");

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
  for (const tier of ["低档", "中档", "高档"]) {
    expect(screen.getByLabelText(`${tier}模型`)).toBeEnabled();
    expect(screen.getByLabelText(`${tier}思考深度`)).toBeEnabled();
  }
  await user.click(screen.getByLabelText("启用集群模式"));
  await waitFor(() => expect(updateCluster).toHaveBeenCalledWith("main", expect.objectContaining({ enabled: false })));
  expect(screen.getByLabelText("启用集群模式")).not.toBeChecked();
  await user.click(screen.getByLabelText("启用集群模式"));
  await waitFor(() => expect(updateCluster).toHaveBeenLastCalledWith("main", expect.objectContaining({ enabled: true })));
});

test("DeepSeek cluster tiers use and persist the Harness model and reasoning schema", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.updateBotCli("main", "deepseek", "dsh");
  const updateCluster = vi.spyOn(client, "updateClusterConfig");
  const nativeModels = vi.spyOn(client, "getNativeAgentModels");
  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "配置" }));

  const model = await screen.findByLabelText("低档模型");
  const effort = screen.getByLabelText("低档思考深度");
  expect(within(model).getAllByRole("option").map((option) => (option as HTMLOptionElement).value))
    .toEqual(["", "none", "deepseek-flash", "deepseek-v4-pro"]);
  expect(within(effort).getAllByRole("option").map((option) => (option as HTMLOptionElement).value))
    .toEqual(["", "none", "off", "low", "high", "max"]);
  expect(nativeModels).not.toHaveBeenCalled();
  await user.selectOptions(model, "deepseek-flash");
  await user.selectOptions(effort, "max");
  await waitFor(() => expect(updateCluster).toHaveBeenLastCalledWith("main", expect.objectContaining({
    modelTiers: { low: "deepseek-flash", medium: "", high: "" },
    reasoningEfforts: { low: "max", medium: "", high: "" },
  })));
});

test("Pi cluster tiers use each model's reasoning options and clear incompatible values atomically", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.updateBotExecutionConfig("main", {
    supportedExecutionModes: ["native_agent"], defaultExecutionMode: "native_agent",
    nativeAgent: { provider: "pi", model: "pi/main", piAgent: "main" },
  });
  client.setClusterStatus("main", {
    modelTiers: { low: "pi/fast", medium: "", high: "pi/strong" },
    reasoningEfforts: { low: "low", medium: "xhigh", high: "max" },
  });
  const nativeModels = vi.spyOn(client, "getNativeAgentModels").mockResolvedValue({
    selectedModel: "pi/main",
    items: [
      { id: "pi/main", provider: "pi", model: "main", name: "Main", label: "Main", reasoningEfforts: ["off", "high"] },
      { id: "pi/fast", provider: "pi", model: "fast", name: "Fast", label: "Fast", reasoningEfforts: ["off", "low"] },
      { id: "pi/strong", provider: "pi", model: "strong", name: "Strong", label: "Strong", reasoningEfforts: ["low", "high", "max"] },
      { id: "pi/plain", provider: "pi", model: "plain", name: "Plain", label: "Plain", reasoningEfforts: [] },
    ],
  });
  const cliParams = vi.spyOn(client, "getCliParams");
  const updateCluster = vi.spyOn(client, "updateClusterConfig");
  render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "配置" }));

  const lowModel = await screen.findByLabelText("低档模型");
  const optionValues = (label: string) => within(screen.getByLabelText(label)).getAllByRole("option")
    .filter((option) => !(option as HTMLOptionElement).disabled)
    .map((option) => (option as HTMLOptionElement).value);
  expect(nativeModels).toHaveBeenCalledWith("main");
  expect(cliParams).not.toHaveBeenCalled();
  expect(optionValues("低档模型")).toEqual(["", "pi/main", "pi/fast", "pi/strong", "pi/plain"]);
  expect(optionValues("低档思考深度")).toEqual(["", "off", "low"]);
  expect(optionValues("中档思考深度")).toEqual(["", "off", "high"]);
  expect(optionValues("高档思考深度")).toEqual(["", "low", "high", "max"]);
  expect(within(screen.getByLabelText("中档思考深度")).getByRole("option", { name: /xhigh.*不支持/ })).toBeDisabled();

  await user.selectOptions(lowModel, "pi/strong");
  await waitFor(() => expect(updateCluster).toHaveBeenLastCalledWith("main", expect.objectContaining({
    modelTiers: { low: "pi/strong", medium: "", high: "pi/strong" },
    reasoningEfforts: { low: "low", medium: "", high: "max" },
  })));
  expect(optionValues("低档思考深度")).toEqual(["", "low", "high", "max"]);
  expect(screen.getByLabelText("中档思考深度")).toHaveValue("");

  await user.selectOptions(lowModel, "");
  expect(updateCluster).toHaveBeenLastCalledWith("main", expect.objectContaining({
    modelTiers: { low: "", medium: "", high: "pi/strong" },
    reasoningEfforts: { low: "", medium: "", high: "max" },
  }));
  expect(screen.getByLabelText("低档思考深度")).toHaveValue("");
  expect(optionValues("低档思考深度")).toEqual(["", "off", "high"]);

  await user.selectOptions(screen.getByLabelText("高档模型"), "pi/plain");
  expect(updateCluster).toHaveBeenCalledTimes(3);
  expect(updateCluster).toHaveBeenLastCalledWith("main", expect.objectContaining({
    modelTiers: { low: "", medium: "", high: "pi/plain" },
    reasoningEfforts: { low: "", medium: "", high: "" },
  }));
  expect(optionValues("高档思考深度")).toEqual([""]);
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


test.each(["list", "desktop"])("%s creates DeepSeek with local CLI capabilities", async (surface) => {
  const client = new MockWebBotClient();
  const addBot = vi.spyOn(client, "addBot");
  if (surface === "desktop") {
    render(<DesktopBotManagerScreen client={client} currentAlias="main" onSelect={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "新增智能体" }));
  } else {
    render(<BotListScreen client={client} onSelect={vi.fn()} />);
  }
  await userEvent.selectOptions(await screen.findByLabelText("新智能体 CLI 类型"), "deepseek");
  expect(screen.getByLabelText("新智能体 CLI 路径")).toHaveValue("dsh");
  expect(screen.queryByLabelText("新智能体默认绕过审批和沙箱")).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("运行后端")).queryByRole("option", { name: "原生 agent" })).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("工作区位置")).getByRole("option", { name: "远程 SSH（Linux / Windows）" })).toBeDisabled();
  await userEvent.type(screen.getByLabelText("新智能体别名"), "deepseek-test");
  await userEvent.click(screen.getByRole("button", { name: "创建智能体" }));
  await waitFor(() => expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
    cliType: "deepseek", cliPath: "dsh", supportedExecutionModes: ["cli"], defaultExecutionMode: "cli", bypassApprovalAndSandbox: false,
  })));
  expect((await client.getCliParams("deepseek-test")).params).toEqual({
    model: null,
    reasoning_effort: null,
    permission_mode: "workspace-write",
    extra_args: [],
  });
});
