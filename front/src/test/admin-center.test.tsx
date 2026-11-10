import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { PublicAccessPanel } from "../components/admin/PublicAccessPanel";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import {
  GENERAL_CODEX_RATE_LIMIT_ID,
  GPT_RESERVE_RATE_LIMIT_ID,
} from "../services/types";
import type { AppUpdatePhase, AppUpdateStatus, CodexUsageStats, TunnelSnapshot } from "../services/types";

afterEach(() => {
  vi.useRealTimers();
});

function createAdminClient() {
  const client = new MockWebBotClient();
  return Object.assign(client, {
    listAdminUsers: vi.fn(async () => []),
    listBots: vi.fn(async () => []),
  });
}

test("管理中心可以直接请求重启后端", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const restart = vi.spyOn(client, "restartService");
  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);

  await screen.findByText("用户权限");
  await user.click(screen.getByRole("button", { name: "重启后端" }));

  expect(restart).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("已请求重启后端")).toBeInTheDocument();
});

async function updateFixture(phase: AppUpdatePhase = "ready"): Promise<AppUpdateStatus> {
  const client = createAdminClient();
  const status = await client.downloadUpdate();
  return { ...status, revision: 10, currentVersion: "1.0.0", latestVersion: "2.0.0", updateAvailable: true, job: {
    ...status.job!, jobId: "persisted-job", revision: 10, phase, currentVersion: "1.0.0", targetVersion: "2.0.0",
    progress: { phase: "download", percent: 42, downloadedBytes: 42, totalBytes: 100, message: "校验更新包" },
  } };
}

async function openUpdates(client: MockWebBotClient, user: ReturnType<typeof userEvent.setup>) {
  const view = render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "网络与升级" }));
  return view;
}

function updateVersion(term: "当前运行版本" | "目标版本") {
  return screen.getByText(term, { selector: "dt" }).nextElementSibling;
}

const LOCAL_URL = "http://127.0.0.1:8765";

test("网络与升级同页展示公网访问和升级，未启用的公网访问可直达 Tunnel 环境配置", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  vi.spyOn(client, "getTunnelStatus").mockResolvedValue({
    mode: "disabled", status: "stopped", source: "disabled", publicUrl: "", localUrl: LOCAL_URL, lastError: "",
  });
  await openUpdates(client, user);
  const access = screen.getByRole("region", { name: "公网访问" });
  expect(screen.getByRole("region", { name: "升级" })).toBeInTheDocument();
  await waitFor(() => expect(within(access).getByRole("status")).toHaveTextContent("未启用"));
  expect(access).not.toHaveTextContent("Quick Tunnel");
  expect(access).not.toHaveTextContent("WEB_PUBLIC_URL");
  await user.click(within(access).getByRole("button", { name: "打开环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  expect(screen.getByRole("button", { name: "Tunnel" })).toHaveAttribute("data-active", "true");
});

test("Quick Tunnel 启动后持续刷新过渡状态直到可访问，并可复制公网地址", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const client = createAdminClient();
  const publicUrl = "https://orbit-demo.trycloudflare.com";
  const quick: TunnelSnapshot = {
    mode: "cloudflare_quick", status: "stopped", source: "quick_tunnel", publicUrl: "", localUrl: LOCAL_URL, lastError: "",
  };
  const read = vi.spyOn(client, "getTunnelStatus")
    .mockResolvedValueOnce(quick)
    .mockResolvedValue({ ...quick, status: "running", publicUrl, verified: true });
  const start = vi.spyOn(client, "startTunnel").mockResolvedValue({ ...quick, status: "waiting_url" });
  render(<PublicAccessPanel client={client} />);
  const access = screen.getByRole("region", { name: "公网访问" });
  await user.click(await within(access).findByRole("button", { name: "启动 Tunnel" }));
  expect(start).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(within(access).getByRole("status")).toHaveTextContent("等待公网地址"));
  await vi.advanceTimersByTimeAsync(2_000);
  await waitFor(() => expect(within(access).getByRole("status")).toHaveTextContent("运行中"));
  expect(within(access).getByText(publicUrl)).toBeInTheDocument();
  await user.click(within(access).getByRole("button", { name: "复制公网地址" }));
  expect(await navigator.clipboard.readText()).toBe(publicUrl);
  expect(within(access).getByRole("button", { name: "已复制公网地址" })).toBeInTheDocument();
  // A settled tunnel is not polled any further.
  await vi.advanceTimersByTimeAsync(6_000);
  expect(read).toHaveBeenCalledTimes(2);
});

test("固定公网转发的 frpc 错误只显示一次并提示可能原因，尝试恢复后更新状态", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const failure = "login to server failed: token mismatch";
  const fixed: TunnelSnapshot = {
    mode: "fixed_public_forward", status: "error", source: "fixed_public_forward",
    publicUrl: "https://hub.example.com/node/lab/", localUrl: LOCAL_URL, lastError: failure,
    nodeId: "lab", basePath: "/node/lab", frpcStatus: "error", frpcPid: null, frpcLastError: failure,
    heartbeatStatus: "online", heartbeatLastAt: "", heartbeatLastError: "",
  };
  vi.spyOn(client, "getTunnelStatus").mockResolvedValue(fixed);
  const restart = vi.spyOn(client, "restartTunnel").mockResolvedValue({
    ...fixed, status: "running", lastError: "", frpcStatus: "running", frpcPid: 4321, frpcLastError: "",
  });
  render(<PublicAccessPanel client={client} />);
  const access = screen.getByRole("region", { name: "公网访问" });
  expect(await within(access).findAllByText(failure)).toHaveLength(1);
  expect(within(access).getByText("可能原因：frps token 错")).toBeInTheDocument();
  await user.click(within(access).getByRole("button", { name: "尝试恢复" }));
  expect(restart).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(within(access).getByRole("status")).toHaveTextContent("运行中"));
  expect(within(access).queryByText(failure)).not.toBeInTheDocument();
  expect(within(access).getByText("4321")).toBeInTheDocument();
});

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
  await user.click(screen.getByRole("checkbox", { name: "自动检查并准备更新" }));
  expect(screen.getByRole("button", { name: "提交准备中..." })).toBeDisabled();
  resolvePrepare({ ...ready, revision: 12, updateEnabled: false, job: { ...ready.job!, revision: 12, phase: "preparing" } });
  expect(await screen.findByTestId("update-job")).toHaveTextContent("正在准备");
  expect(screen.getByRole("checkbox", { name: "自动检查并准备更新" })).not.toBeChecked();
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
  expect(screen.getByTestId("update-job")).not.toHaveTextContent("升级成功");
  const reportedSuccess = { ...ready, revision: 11, job: { ...ready.job!, revision: 11, phase: "succeeded" as const } };
  current.mockResolvedValue(reportedSuccess);
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  await waitFor(() => expect(screen.getByTestId("update-job")).toHaveTextContent("正在核对运行版本"));
  expect(screen.getByTestId("update-job")).not.toHaveTextContent("升级成功");
  current.mockResolvedValue({ ...reportedSuccess, currentVersion: "2.0.0" });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  await waitFor(() => expect(screen.getByTestId("update-job")).toHaveTextContent("升级成功"));
  expect(screen.getByText("新版本已运行，当前页面仍是旧版本界面，请刷新页面以加载新版本。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "刷新页面" })).toBeEnabled();
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

test("检查成功后仅在有新版本时允许准备更新", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const ready = await updateFixture();
  const lastCheck = { checkedAt: "2026-10-24T12:00:00Z", ok: true, cached: false, error: "" };
  const current = vi.spyOn(client, "getCurrentUpdateJob").mockResolvedValue({ ...ready, job: null, lastCheck, latestVersion: "1.0.0", updateAvailable: false });
  await openUpdates(client, user);
  expect(await screen.findByText("已是最新版本（v1.0.0）")).toBeInTheDocument();
  expect(updateVersion("目标版本")).toHaveTextContent("暂无");
  expect(screen.getByRole("button", { name: "准备更新" })).toBeDisabled();
  current.mockResolvedValue({ ...ready, job: null, lastCheck });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  expect(await screen.findByText("发现新版本 v2.0.0")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "准备更新" })).toBeEnabled();
  // A prepared offline package newer than the last online check is not "up to date".
  current.mockResolvedValue({ ...ready, lastCheck, latestVersion: "1.0.0", updateAvailable: false });
  await user.click(screen.getByRole("button", { name: "查询后台状态" }));
  await waitFor(() => expect(updateVersion("目标版本")).toHaveTextContent("v2.0.0"));
  expect(screen.queryByText(/已是最新版本/)).not.toBeInTheDocument();
});

function usageHeroValue(text: string) {
  return screen.queryByText(text, { selector: ".codex-usage-bucket-hero-value" });
}

function usageStat(article: HTMLElement, term: string) {
  return within(article).getByText(term, { selector: "dt" }).nextElementSibling;
}

// Codex is the default provider on the Usage page.
async function openCodexUsageTab(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "Usage" }));
  await screen.findByRole("heading", { name: "Usage", level: 2 });
}

test("Usage 页面切换到 Claude 后复用采集设置", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const getConfig = vi.spyOn(client, "getClaudeUsageConfig");
  const getStats = vi.spyOn(client, "getClaudeUsageStats");
  const updateConfig = vi.spyOn(client, "updateClaudeUsageConfig");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);
  await user.click(screen.getByRole("tab", { name: "Claude" }));

  expect(await screen.findByRole("heading", { name: "Claude 剩余额度趋势" })).toBeInTheDocument();
  expect(getConfig).toHaveBeenCalledTimes(1);
  expect(getStats).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("checkbox", { name: "启用 Claude 额度采集" })).not.toBeChecked();

  await user.click(screen.getByRole("checkbox", { name: "启用 Claude 额度采集" }));
  await waitFor(() => expect(updateConfig).toHaveBeenCalledWith({ enabled: true }));
});

test("Usage 页面合并 Codex 与 Claude，切换后丢弃旧响应并在刷新后保留选择", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const codexStats = await client.getCodexUsageStats();
  let resolveStaleCodexStats!: (stats: CodexUsageStats) => void;
  const getCodexStats = vi.spyOn(client, "getCodexUsageStats").mockImplementationOnce(() => new Promise((resolve) => {
    resolveStaleCodexStats = resolve;
  }));
  const getClaudeConfig = vi.spyOn(client, "getClaudeUsageConfig");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);
  expect(screen.queryByRole("tab", { name: /额度/ })).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Codex" })).toHaveAttribute("aria-selected", "true");
  await waitFor(() => expect(getCodexStats).toHaveBeenCalledTimes(1));

  await user.click(screen.getByRole("tab", { name: "Claude" }));
  expect(await screen.findByRole("heading", { name: "Claude 剩余额度趋势" })).toBeInTheDocument();
  await act(async () => resolveStaleCodexStats(codexStats));
  expect(usageHeroValue("88%")).toBeInTheDocument();
  expect(usageHeroValue("92%")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(getClaudeConfig).toHaveBeenCalledTimes(2));
  expect(screen.getByRole("tab", { name: "Claude" })).toHaveAttribute("aria-selected", "true");

  screen.getByRole("tab", { name: "Claude" }).focus();
  await user.keyboard("{ArrowLeft}");
  expect(screen.getByRole("tab", { name: "Codex" })).toHaveFocus();
  expect(await screen.findByRole("heading", { name: "Codex 剩余额度趋势" })).toBeInTheDocument();
});

test("Usage 页面导入其他设备的额度样本后重载曲线，并可移除导入样本", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const getCodexStats = vi.spyOn(client, "getCodexUsageStats");
  const importSamples = vi.spyOn(client, "importUsageSamples")
    .mockRejectedValueOnce(new Error("不是 Orbit 额度样本导出文件"))
    .mockResolvedValueOnce({
      total: 4,
      inserted: 3,
      duplicates: 1,
      invalid: 0,
      insertedByProvider: { codex: 2, claude: 1 },
    });
  const exportSamples = vi.spyOn(client, "exportUsageSamples");
  const deleteImported = vi.spyOn(client, "deleteImportedUsageSamples").mockResolvedValue({ deleted: 3 });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await openCodexUsageTab(user);
  await waitFor(() => expect(getCodexStats).toHaveBeenCalledTimes(1));

  const file = new File(["{}"], "laptop.json", { type: "application/json" });
  const input = screen.getByLabelText("选择额度样本文件");
  await user.upload(input, file);
  expect(await screen.findByText("不是 Orbit 额度样本导出文件")).toBeInTheDocument();
  expect(getCodexStats).toHaveBeenCalledTimes(1);

  await user.upload(input, file);
  expect(await screen.findByText("已合并 3 条额度样本（Codex 2，Claude 1）；跳过 1 条已存在。")).toBeInTheDocument();
  expect(importSamples).toHaveBeenLastCalledWith(file);
  await waitFor(() => expect(getCodexStats).toHaveBeenCalledTimes(2));

  await user.click(screen.getByRole("button", { name: "导出样本" }));
  expect(await screen.findByText("已导出 6 条额度样本：orbit-quota-samples-mock.json")).toBeInTheDocument();
  expect(exportSamples).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "移除导入" }));
  expect(await screen.findByText("已移除 3 条导入的额度样本。")).toBeInTheDocument();
  expect(deleteImported).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(getCodexStats).toHaveBeenCalledTimes(3));
  confirm.mockRestore();
});

test("全局配置保存全局提示词预设", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const updateGlobal = vi.spyOn(client, "updateGlobalPromptPresets");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "全局配置" }));

  await user.click(await screen.findByRole("button", { name: "新增预设" }));
  await user.type(screen.getByLabelText("全局预设标题 1"), "全局检查");
  await user.type(screen.getByLabelText("全局预设内容 1"), "检查所有变更");
  await user.click(screen.getByRole("button", { name: "保存全局预设" }));
  await waitFor(() => expect(updateGlobal).toHaveBeenCalledTimes(1));
});

test("环境配置将 Telegram Token 标记为敏感项", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Telegram" }));

  const tokenItem = screen.getByText("Telegram Bot Token").closest("article");
  expect(tokenItem).toBeInTheDocument();
  expect(tokenItem?.querySelector('input[type="password"]')).not.toBeNull();
});

test("数据迁移先预览并明确确认停止全部智能体", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const startMigration = vi.spyOn(client, "startStorageMigration");

  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "数据迁移" }));
  await screen.findByRole("heading", { name: "TCB 数据迁移" });

  await user.type(screen.getByRole("textbox", { name: "存储迁移目标目录" }), "D:\\OrbitData");
  await user.click(screen.getByRole("button", { name: "预览并校验" }));
  await screen.findByRole("heading", { name: "迁移预览" });
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
  const article = chart.closest("article") as HTMLElement;
  expect(within(article).getByText("92%", { selector: ".codex-usage-bucket-hero-value" })).toBeInTheDocument();
  expect(usageStat(article, "剩余时长")).toHaveTextContent("7 天");
  expect(article).toHaveTextContent("7 天窗口");
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
  expect(usageStat(chart.closest("article") as HTMLElement, "剩余时长")).toHaveTextContent("30 天");
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

  const chart = await screen.findByRole("img", { name: /共 1 个样本/ });
  expect(usageStat(chart.closest("article") as HTMLElement, "剩余时长")).toHaveTextContent("0 分钟");
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
  // 60% quota left with 70% of the window left: slightly ahead of an even pace.
  expect(within(chart.closest("article") as HTMLElement).getByText("略快于均速")).toBeInTheDocument();
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

test("公告条目保留换行与空格，发布时忽略空段落并重置草稿", async () => {
  const user = userEvent.setup();
  const client = createAdminClient();
  const upsert = vi.spyOn(client, "upsertAnnouncement").mockImplementation(async (input) => ({
    ...input, id: "ann-new", publishedAt: "2026-11-10T09:00:00+08:00",
  }));
  render(<AdminCenterScreen client={client} onClose={() => undefined} initialBots={[]} />);
  await screen.findByText("用户权限");
  await user.click(screen.getByRole("tab", { name: "公告" }));

  const publish = await screen.findByRole("button", { name: "发布公告" });
  expect(publish).toBeDisabled();
  await user.type(screen.getByLabelText("公告标题"), "Cluster upgrade");
  await user.type(screen.getByLabelText("公告摘要"), "Two items");
  const items = screen.getByLabelText("公告段落 1 条目");
  await user.type(items, "first item {Enter}second item");
  expect(items).toHaveValue("first item \nsecond item");
  await user.click(screen.getByRole("button", { name: "移除公告段落 3" }));
  expect(screen.queryByLabelText("公告段落 3 标题")).not.toBeInTheDocument();

  await user.click(publish);
  expect(upsert).toHaveBeenCalledWith({
    publisher: "CLI Bridge",
    title: "Cluster upgrade",
    category: "feature",
    severity: "info",
    summary: "Two items",
    sections: [{ label: "新增", items: ["first item", "second item"] }],
  });
  await waitFor(() => expect(screen.getByLabelText("公告标题")).toHaveValue(""));
  expect(screen.getByLabelText("公告发布者")).toHaveValue("CLI Bridge");
});
