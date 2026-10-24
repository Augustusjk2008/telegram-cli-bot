import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import {
  GENERAL_CODEX_RATE_LIMIT_ID,
  GPT_RESERVE_RATE_LIMIT_ID,
} from "../services/types";

function createAdminClient() {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
  });
}

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
