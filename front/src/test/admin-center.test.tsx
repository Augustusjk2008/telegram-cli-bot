import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import {
  GENERAL_CODEX_RATE_LIMIT_ID,
  GPT_RESERVE_RATE_LIMIT_ID,
} from "../services/types";
import type { AppUpdatePhase, AppUpdateStatus } from "../services/types";

function createAdminClient() {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
  });
}

async function updateFixture(phase: AppUpdatePhase = "ready"): Promise<AppUpdateStatus> {
  const client = createAdminClient();
  const status = await client.downloadUpdate();
  return { ...status, revision: 10, currentVersion: "1.0.0", latestVersion: "2.0.0", job: {
    ...status.job!, jobId: "persisted-job", revision: 10, phase, currentVersion: "1.0.0", targetVersion: "2.0.0",
    progress: { phase: "download", percent: 42, downloadedBytes: 42, totalBytes: 100, message: "校验更新包" },
  } };
}

async function openUpdates(client: MockWebBotClient, user: ReturnType<typeof userEvent.setup>) {
  const view = render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "升级" }));
  return view;
}

test("升级任务重新进入后恢复，离线列表失败仍保留在线任务", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const status = await updateFixture("preparing");
  const current = vi.spyOn(client, "getCurrentUpdateJob").mockResolvedValue(status);
  const prepare = vi.spyOn(client, "downloadUpdate");
  vi.spyOn(client, "listOfflineUpdatePackages").mockRejectedValue(new Error("离线目录不可访问"));
  const view = await openUpdates(client, user);
  expect(await screen.findByTestId("update-job")).toHaveTextContent("42%");
  expect(screen.getByText("离线目录不可访问")).toBeInTheDocument();
  view.unmount();
  await openUpdates(client, user);
  expect(await screen.findByTestId("update-job")).toHaveTextContent("persisted-job");
  expect(current).toHaveBeenCalledTimes(2);
  expect(prepare).not.toHaveBeenCalled();
});

test("在线查询失败时仍加载离线包列表", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  vi.spyOn(client, "getCurrentUpdateJob").mockRejectedValue(new Error("连接暂不可用"));
  vi.spyOn(client, "listOfflineUpdatePackages").mockResolvedValue({ artifactsDir: "D:/packages", items: [
    { name: "invalid.zip", path: "D:/packages/invalid.zip", version: "2.0.0", packageKind: "installer", sizeBytes: 1, valid: false, error: "哈希不匹配" },
  ] });
  await openUpdates(client, user);
  expect(await screen.findByText("哈希不匹配")).toBeInTheDocument();
  expect(screen.getByText(/正在确认后台状态/)).toBeInTheDocument();
});

test("保存自动下载开关不会清除正在提交的准备操作或接受旧修订", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const ready = await updateFixture();
  const idle = { ...ready, job: null };
  vi.spyOn(client, "getCurrentUpdateJob").mockResolvedValue(idle);
  let resolvePrepare!: (status: AppUpdateStatus) => void;
  vi.spyOn(client, "downloadUpdate").mockImplementation(() => new Promise((resolve) => { resolvePrepare = resolve; }));
  vi.spyOn(client, "setUpdateEnabled").mockResolvedValue({ ...idle, revision: 11, updateEnabled: false });
  await openUpdates(client, user);
  await user.click(await screen.findByRole("button", { name: "准备更新" }));
  await user.click(screen.getByRole("checkbox", { name: "自动下载更新" }));
  expect(screen.getByRole("button", { name: "提交准备中..." })).toBeDisabled();
  resolvePrepare({ ...ready, revision: 12, updateEnabled: false, job: { ...ready.job!, revision: 12, phase: "preparing" } });
  expect(await screen.findByTestId("update-job")).toHaveTextContent("正在准备");
  expect(screen.getByRole("checkbox", { name: "自动下载更新" })).not.toBeChecked();
});

test("应用断线只查询后台，成功必须匹配运行版本", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const ready = await updateFixture();
  const current = vi.spyOn(client, "getCurrentUpdateJob").mockResolvedValue(ready);
  const apply = vi.spyOn(client, "applyUpdateJob").mockImplementation(async () => {
    current.mockRejectedValue(new TypeError("Failed to fetch"));
    throw new TypeError("Failed to fetch");
  });
  await openUpdates(client, user);
  await user.click(await screen.findByRole("button", { name: "应用更新" }));
  expect(screen.getByRole("dialog", { name: "确认应用更新" })).toHaveTextContent("服务将暂时断开");
  await user.click(screen.getByRole("button", { name: "确认应用并重启服务" }));
  expect(apply).toHaveBeenCalledWith("persisted-job", 10);
  await screen.findByText(/正在确认后台状态/);
  expect(screen.queryByText(/任务阶段: 升级成功/)).not.toBeInTheDocument();
  const reportedSuccess = { ...ready, revision: 11, job: { ...ready.job!, revision: 11, phase: "succeeded" as const } };
  current.mockResolvedValue(reportedSuccess);
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  expect(await screen.findByText(/任务阶段: 正在核对运行版本/)).toBeInTheDocument();
  current.mockResolvedValue({ ...reportedSuccess, currentVersion: "2.0.0" });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  expect(await screen.findByText(/任务阶段: 升级成功/)).toBeInTheDocument();
  expect(apply).toHaveBeenCalledTimes(1);
});

test("确认框绑定任务修订，后台变化要求重新确认", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const ready = await updateFixture();
  const current = vi.spyOn(client, "getCurrentUpdateJob").mockResolvedValue(ready);
  const apply = vi.spyOn(client, "applyUpdateJob");
  await openUpdates(client, user);
  await user.click(await screen.findByRole("button", { name: "应用更新" }));
  current.mockResolvedValue({ ...ready, revision: 11, job: { ...ready.job!, revision: 11 } });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确认应用并重启服务" })).toBeDisabled());
  expect(apply).not.toHaveBeenCalled();
});

test("持久化失败可重试、准备可取消、上传使用选中文件", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  let status = await updateFixture("failed");
  status.job!.error = "依赖准备失败";
  vi.spyOn(client, "getCurrentUpdateJob").mockImplementation(async () => status);
  const retry = vi.spyOn(client, "retryUpdateJob").mockImplementation(async () => {
    status = { ...status, revision: 11, job: { ...status.job!, phase: "preparing", revision: 11, error: "" } };
    return status;
  });
  const cancel = vi.spyOn(client, "cancelUpdateJob").mockImplementation(async () => {
    status = { ...status, revision: 12, job: { ...status.job!, phase: "cancelled", revision: 12 } };
    return status;
  });
  const upload = vi.spyOn(client, "uploadOfflineUpdate").mockRejectedValue(new Error("包清单与文件哈希不匹配"));
  await openUpdates(client, user);
  expect(await screen.findByText("依赖准备失败")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(retry).toHaveBeenCalledWith("persisted-job", 10);
  await user.click(await screen.findByRole("button", { name: "取消准备" }));
  expect(cancel).toHaveBeenCalledWith("persisted-job", 11);
  const file = new File(["package"], "update.zip", { type: "application/zip" });
  await user.upload(screen.getByLabelText("从此设备上传升级包"), file);
  await user.click(screen.getByRole("button", { name: "上传并准备" }));
  expect(upload).toHaveBeenCalledWith(file);
  expect(await screen.findByText("包清单与文件哈希不匹配")).toBeInTheDocument();
});

test("缓存检查失败阻止在线准备，不支持的启动器阻止应用", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const ready = await updateFixture();
  const current = vi.spyOn(client, "getCurrentUpdateJob").mockResolvedValue({ ...ready, job: null,
    lastCheck: { checkedAt: "2026-10-24", ok: false, cached: true, error: "Release 查询失败" },
  });
  await openUpdates(client, user);
  expect(await screen.findByText(/Release 查询失败/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "准备更新" })).toBeDisabled();
  current.mockResolvedValue({ ...ready, launcher: { supported: false, protocol: 0, command: ".\\start.bat", reason: "需使用官方启动器" } });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  expect(await screen.findByRole("button", { name: "应用更新" })).toBeDisabled();
  expect(screen.getByText(".\\start.bat")).toBeInTheDocument();
  current.mockResolvedValue({ ...ready, job: { ...ready.job!, requiresPreparation: true } });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  expect(await screen.findByRole("button", { name: "重试" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "应用更新" })).toBeDisabled();
});

async function openCodexUsageTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Codex 额度" }));
  await screen.findByRole("heading", { name: "Codex 额度" });
}

test("全局配置集中显示通用显示、通知和全局提示词预设", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const updateGlobal = vi.spyOn(client, "updateGlobalPromptPresets");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "全局配置" }));

  expect(await screen.findByRole("heading", { name: "通用显示设置" })).toBeInTheDocument();
  expect(screen.getByLabelText("界面主题")).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "主题管理" })).not.toBeInTheDocument();
  expect(screen.getAllByText(/影响所有智能体/).length).toBeGreaterThan(0);
  expect(screen.queryByLabelText("聊天正文字体")).not.toBeInTheDocument();
  expect(screen.getByLabelText("聊天完成网页通知")).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "全局提示词预设" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "新增预设" }));
  await user.type(screen.getByLabelText("全局预设标题 1"), "全局检查");
  await user.type(screen.getByLabelText("全局预设内容 1"), "检查所有变更");
  await user.click(screen.getByRole("button", { name: "保存全局预设" }));
  await waitFor(() => expect(updateGlobal).toHaveBeenCalledTimes(1));
});

test("环境配置显示 Codex server 语音开关", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Web" }));

  const voiceItem = screen.getByText("Codex server 语音").closest("article");
  expect(voiceItem).toBeInTheDocument();
  expect(voiceItem).toHaveTextContent("TCB_CODEX_SERVER_VOICE_ENABLED");
  expect(voiceItem).toHaveTextContent("重启生效");
});

test("环境配置显示 Telegram 接入字段并标记 Token 为敏感项", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Telegram" }));

  expect(screen.getByText("启用 Telegram")).toBeInTheDocument();
  const broadcastItem = screen.getByText("Telegram 最终回复广播").closest("article");
  expect(broadcastItem).toBeInTheDocument();
  expect(broadcastItem).toHaveTextContent("TELEGRAM_BROADCAST_COMPLETIONS");
  expect(broadcastItem?.querySelector('input[type="checkbox"]')).not.toBeNull();
  const tokenItem = screen.getByText("Telegram Bot Token").closest("article");
  expect(tokenItem).toBeInTheDocument();
  expect(tokenItem?.querySelector('input[type="password"]')).not.toBeNull();
  expect(screen.getByText("Telegram 用户白名单")).toBeInTheDocument();
});

test("数据迁移先预览并明确确认停止全部智能体", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const startMigration = vi.spyOn(client, "startStorageMigration");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "数据迁移" }));
  await screen.findByRole("heading", { name: "TCB 数据迁移" });
  expect(screen.getByText(/当前数据根目录:/)).toBeInTheDocument();
  expect(screen.getByText("聊天历史")).toBeInTheDocument();

  await user.type(screen.getByRole("textbox", { name: "存储迁移目标目录" }), "D:\\OrbitData");
  await user.click(screen.getByRole("button", { name: "预览并校验" }));
  await screen.findByRole("heading", { name: "迁移预览" });
  await waitFor(() => expect(screen.getByTestId("storage-migration-progress")).toHaveTextContent("正在扫描源目录"), {
    timeout: 3000,
  });
  expect(screen.getByTestId("storage-migration-progress")).toHaveTextContent("已处理大小");
  expect(screen.getByTestId("storage-migration-progress")).toHaveTextContent("当前项");
  await waitFor(() => expect(screen.getByRole("button", { name: "确认并迁移" })).toBeEnabled(), {
    timeout: 3000,
  });
  await user.click(screen.getByRole("button", { name: "确认并迁移" }));

  expect(screen.getByRole("dialog", { name: "确认数据迁移" })).toHaveTextContent("停止全部智能体进程");
  expect(screen.getByRole("dialog", { name: "确认数据迁移" })).toHaveTextContent("删除已验证的原始数据");
  await user.click(screen.getByRole("button", { name: "我确认停止全部智能体并继续" }));

  await waitFor(() => expect(startMigration).toHaveBeenCalledWith("mock-storage-plan", true));
  expect(await screen.findByText(/请重启服务使新数据根目录生效/)).toBeInTheDocument();
});

test("数据迁移刷新后从状态接口恢复进度", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const baseSnapshot = await client.getStorageMigrationSnapshot();
  const inProgressSnapshot = {
    ...baseSnapshot,
    state: "copying" as const,
    phase: "copying" as const,
    maintenance: true,
    jobId: "storage-job-1",
    planId: "storage-plan-1",
    totalBytes: 100 * 1024 * 1024,
    completedBytes: 40 * 1024 * 1024,
    totalFiles: 200,
    completedFiles: 80,
    currentItem: "chat-history/workspaces/demo/chat.sqlite",
    speedBytesPerSecond: 4 * 1024 * 1024,
    etaSeconds: 15,
  };
  Object.assign(client, {
    getStorageMigrationSnapshot: vi.fn(async () => inProgressSnapshot),
  });

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "数据迁移" }));

  const progress = await screen.findByTestId("storage-migration-progress");
  expect(progress).toHaveTextContent("正在复制文件");
  expect(progress).toHaveTextContent("40%");
  expect(progress).toHaveTextContent("已处理文件: 80 / 200");
  expect(progress).toHaveTextContent("chat-history/workspaces/demo/chat.sqlite");
  expect(progress).toHaveTextContent("预计剩余: 15 秒");
});

test("Codex 额度趋势隐藏已下线的次要额度桶", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples[0].sampledAt = "2026-07-20T18:45:00+08:00";
  stats.rateLimitSamples[0].resetsAt = "2026-07-20T18:45:00+08:00";
  stats.rateLimitSamples[1].sampledAt = "2026-07-21T18:45:00+08:00";
  stats.rateLimitSamples[1].resetsAt = "2026-07-25T06:45:00+08:00";
  stats.rateLimitSamples[2].sampledAt = "2026-07-26T18:45:00+08:00";
  stats.rateLimitSamples[2].resetsAt = "2026-08-02T18:45:00+08:00";
  stats.rateLimitSamples.push(
    {
      limitId: "codex_bengalfox",
      sampledAt: "2026-07-25T18:45:00+08:00",
      usedPercent: 40,
      windowMinutes: 300,
      resetsAt: "2026-07-25T20:45:00+08:00",
      planType: "pro",
    },
    {
      limitId: "codex_bengalfox",
      sampledAt: "2026-07-26T18:45:00+08:00",
      usedPercent: 50,
      windowMinutes: 300,
      resetsAt: "2026-07-26T19:45:00+08:00",
      planType: "pro",
    },
    {
      limitId: GPT_RESERVE_RATE_LIMIT_ID,
      sampledAt: "2026-07-25T18:45:00+08:00",
      usedPercent: 20,
      windowMinutes: 10080,
      resetsAt: "2026-07-30T18:45:00+08:00",
      planType: "pro",
    },
    {
      limitId: GPT_RESERVE_RATE_LIMIT_ID,
      sampledAt: "2026-07-26T18:45:00+08:00",
      usedPercent: 23,
      windowMinutes: 10080,
      resetsAt: "2026-08-01T18:45:00+08:00",
      planType: "pro",
    },
  );
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex.*共 3 个样本，当前剩余 92%/ });
  expect(screen.queryByRole("img", { name: /gpt-5\.3-codex-spark.*共 2 个样本/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /gpt-reserve.*共 2 个样本，当前剩余 77%/ })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "通用 Codex · Pro", level: 4 })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "gpt-5.3-codex-spark · Pro", level: 4 })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "gpt-reserve · Pro", level: 4 })).not.toBeInTheDocument();
  expect(screen.getByText("当前剩余 92%")).toBeInTheDocument();
  expect(screen.getByText("剩余时长 7 天")).toBeInTheDocument();
  expect(screen.getByText("已用 8%")).toBeInTheDocument();
  expect(chart.closest("article")).toHaveTextContent("7 天窗口");
  expect(screen.queryByText("总 token")).not.toBeInTheDocument();
});

test("Codex 额度趋势重复采样时间退回折线且不产生无效坐标", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    10,
    30,
    20,
  ].map((usedPercent) => ({
    limitId: GENERAL_CODEX_RATE_LIMIT_ID,
    sampledAt: "2026-08-01T00:00:00+08:00",
    usedPercent,
    windowMinutes: 10080,
    resetsAt: "2026-08-08T00:00:00+08:00",
    planType: "pro",
  }));
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex · Pro.*共 3 个样本/ });
  const pathData = chart.querySelector(".codex-usage-rate-limit-line")?.getAttribute("d") || "";
  expect(pathData).not.toMatch(/[QC] |NaN/);
});

test("Codex 额度趋势按套餐拆分相同额度桶", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T18:00:00+08:00",
      usedPercent: 57,
      windowMinutes: 10080,
      resetsAt: "2026-09-01T22:15:24+08:00",
      planType: "pro",
    },
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T19:00:00+08:00",
      usedPercent: 0,
      windowMinutes: 43200,
      resetsAt: "2026-09-26T19:00:00+08:00",
      planType: "free",
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  expect(await screen.findByRole("heading", { name: "通用 Codex · Pro", level: 4 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "通用 Codex · Free", level: 4 })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /通用 Codex · Pro.*共 1 个样本，当前剩余 43%/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /通用 Codex · Free.*共 1 个样本，当前剩余 100%/ })).toBeInTheDocument();
});

test("Codex 额度趋势将缺少套餐字段的样本归入唯一已知套餐", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T18:00:00+08:00",
      usedPercent: 57,
      windowMinutes: 10080,
      resetsAt: "2026-09-01T22:15:24+08:00",
      planType: "pro",
    },
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T19:00:00+08:00",
      usedPercent: 58,
      windowMinutes: 10080,
      resetsAt: "2026-09-01T22:15:24+08:00",
      planType: null,
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  expect(await screen.findByRole("heading", { name: "通用 Codex · Pro", level: 4 })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "通用 Codex · 套餐未知", level: 4 })).not.toBeInTheDocument();
  expect(screen.getByRole("img", { name: /通用 Codex · Pro.*共 2 个样本/ })).toBeInTheDocument();
});

test("Codex Free 额度趋势按 30 天窗口显示剩余时长", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-08-27T19:00:00+08:00",
      usedPercent: 0,
      windowMinutes: 43200,
      resetsAt: "2026-09-26T19:00:00+08:00",
      planType: "free",
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex · Free.*剩余时长 30 天/ });
  const durationTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-duration-tick"));
  expect(screen.getByText("剩余时长 30 天")).toBeInTheDocument();
  expect(durationTicks.at(-1)?.textContent?.trim()).toBe("30 天");
});

test("Codex 额度趋势仅有一个样本时不绘制折线或数据点", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = stats.rateLimitSamples.slice(0, 1);
  stats.rateLimitSamples[0].resetsAt = "not-a-time";
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  const { container } = render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  await screen.findByRole("img", { name: /共 1 个样本/ });
  expect(screen.getByText("剩余时长 0 分钟")).toBeInTheDocument();
  expect(container.querySelector(".codex-usage-rate-limit-chart circle")).not.toBeInTheDocument();
  expect(container.querySelector(".codex-usage-rate-limit-line")).not.toBeInTheDocument();
  expect(container.querySelector(".codex-usage-rate-limit-duration-line")).not.toBeInTheDocument();
});

test("Codex 额度趋势纵轴按额度和时长的查询范围同步缩放", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-07-20T00:00:00+08:00",
      usedPercent: 90,
      windowMinutes: 10080,
      resetsAt: "2026-07-22T02:24:00+08:00",
      planType: "pro",
    },
    {
      limitId: GENERAL_CODEX_RATE_LIMIT_ID,
      sampledAt: "2026-07-21T00:00:00+08:00",
      usedPercent: 40,
      windowMinutes: 10080,
      resetsAt: "2026-07-25T21:36:00+08:00",
      planType: "pro",
    },
  ];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  const chart = await screen.findByRole("img", { name: /通用 Codex.*共 2 个样本/ });
  const quotaTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-quota-tick"));
  const durationTicks = Array.from(chart.querySelectorAll(".codex-usage-rate-limit-duration-tick"));
  expect(quotaTicks.map((tick) => tick.textContent?.trim())).toEqual([
    "10%", "25%", "40%", "55%", "70%",
  ]);
  expect(durationTicks.map((tick) => tick.textContent?.trim())).toEqual([
    "0.7 天", "1.75 天", "2.8 天", "3.85 天", "4.9 天",
  ]);
});

test("Codex 额度趋势没有样本时仍显示已知额度入口", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const stats = await client.getCodexUsageStats();
  stats.rateLimitSamples = [];
  vi.spyOn(client, "getCodexUsageStats").mockResolvedValue(stats);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);

  expect(screen.getByRole("heading", { name: "通用 Codex", level: 4 })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "gpt-5.3-codex-spark", level: 4 })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "gpt-reserve", level: 4 })).not.toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /Codex 剩余额度与剩余时长趋势/ })).not.toBeInTheDocument();
});
