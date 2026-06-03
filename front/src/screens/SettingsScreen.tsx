import { clsx } from "clsx";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, Bell, Copy, Globe, LogOut, RotateCw, Save, Square } from "lucide-react";
import { AvatarPicker } from "../components/AvatarPicker";
import { AgentSettingsPanel } from "../components/AgentSettingsPanel";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { BotIdentity } from "../components/BotIdentity";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { StateBadge } from "../components/StateBadge";
import { ThemeDropdown } from "../components/ThemeDropdown";
import { toolbarButtonClass } from "../components/ToolbarButton";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError } from "../services/types";
import type {
  AvatarAsset,
  BotOverview,
  BrowserNotificationPermission,
  CliType,
  GitProxySettings,
  NotificationSettingsStatus,
  TunnelSnapshot,
  UpdateBotWorkdirOptions,
  WorkdirChangeConflict,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_AVATAR_ASSETS, readStoredUserAvatarName } from "../utils/avatar";
import { normalizePathInput } from "../utils/pathInput";
import { defaultCliPathForType } from "./useBotManager";
import {
  CHAT_BODY_FONT_FAMILY_OPTIONS,
  CHAT_BODY_FONT_SIZE_OPTIONS,
  CHAT_BODY_LINE_HEIGHT_OPTIONS,
  CHAT_BODY_PARAGRAPH_SPACING_OPTIONS,
  DEFAULT_CHAT_BODY_FONT_FAMILY,
  DEFAULT_CHAT_BODY_FONT_SIZE,
  DEFAULT_CHAT_BODY_LINE_HEIGHT,
  DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  DEFAULT_UI_THEME,
  type ChatBodyFontFamilyName,
  type ChatBodyFontSizeName,
  type ChatBodyLineHeightName,
  type ChatBodyParagraphSpacingName,
  type UiThemeName,
} from "../theme";
import {
  getBrowserNotificationPermission,
  readChatCompletionWebNotificationEnabled,
  requestBrowserNotificationPermission,
  writeChatCompletionWebNotificationEnabled,
} from "../utils/chatNotificationEvents";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  onLogout: () => void;
  embedded?: boolean;
  prefilledWorkdir?: string;
  onWorkdirUpdated?: (workingDir: string) => void;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void;
  chatBodyFontFamily?: ChatBodyFontFamilyName;
  onChatBodyFontFamilyChange?: (fontFamily: ChatBodyFontFamilyName) => void;
  chatBodyFontSize?: ChatBodyFontSizeName;
  onChatBodyFontSizeChange?: (fontSize: ChatBodyFontSizeName) => void;
  chatBodyLineHeight?: ChatBodyLineHeightName;
  onChatBodyLineHeightChange?: (lineHeight: ChatBodyLineHeightName) => void;
  chatBodyParagraphSpacing?: ChatBodyParagraphSpacingName;
  onChatBodyParagraphSpacingChange?: (paragraphSpacing: ChatBodyParagraphSpacingName) => void;
  userAvatarName?: string;
  onUserAvatarChange?: (avatarName: string) => void;
  sessionCapabilities?: string[];
  showBotRuntimeSettings?: boolean;
  onOpenBotManager?: () => void;
};

const TUNNEL_STATUS_REFRESH_INTERVAL_MS = 5000;

function settingsPanelClass(extra = "") {
  return clsx(
    "rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 shadow-[var(--shadow-soft)]",
    extra,
  );
}

function settingsActionPanelClass(extra = "") {
  return clsx(
    "overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-soft)]",
    extra,
  );
}

function settingsButtonClass(kind: "plain" | "primary" | "danger" = "plain", extra = "") {
  if (kind === "danger") {
    return toolbarButtonClass("danger", "md", extra);
  }
  return toolbarButtonClass(kind, "md", extra);
}

function isValidGitProxyAddress(value: string) {
  const address = value.trim();
  if (!address) return true;
  const port = /^\d+$/.test(address) ? address : address.split(":").pop() || "";
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    return false;
  }
  if (/^\d+$/.test(address)) {
    return true;
  }
  return /^[A-Za-z0-9.-]+:\d+$/.test(address) || /^\[[^\]\s]+\]:\d+$/.test(address);
}

function gitProxyStatusText(settings: GitProxySettings | null) {
  return settings?.address ? settings.address : "直连";
}

function tunnelStatusText(status: TunnelSnapshot["status"]) {
  if (status === "running") return "运行中";
  if (status === "waiting_local") return "等待本地服务";
  if (status === "waiting_url") return "等待公网地址";
  if (status === "connected") return "公网地址已创建";
  if (status === "verifying_public") return "正在验证公网地址";
  if (status === "starting") return "启动中";
  if (status === "error") return "异常";
  return "已停止";
}

function tunnelSourceText(tunnel: TunnelSnapshot) {
  if (tunnel.source === "fixed_public_forward" || tunnel.mode === "fixed_public_forward") return "固定公网转发";
  if (tunnel.source === "manual_config") return "手工地址";
  return "Quick Tunnel";
}

function isFixedPublicForward(tunnel: TunnelSnapshot) {
  return tunnel.source === "fixed_public_forward" || tunnel.mode === "fixed_public_forward";
}

function normalizeTunnelServiceStatus(value: string | null | undefined) {
  return String(value || "").trim().toLowerCase();
}

function tunnelServiceTone(value: string | null | undefined): "neutral" | "success" | "warning" | "danger" | "accent" {
  const status = normalizeTunnelServiceStatus(value);
  if (!status || ["stopped", "disabled", "offline"].includes(status)) return "neutral";
  if (["running", "connected", "online", "ok", "healthy", "success"].includes(status)) return "success";
  if (["starting", "pending", "waiting", "verifying"].some((token) => status.includes(token))) return "warning";
  if (["error", "failed", "timeout", "forbidden"].some((token) => status.includes(token))) return "danger";
  return "accent";
}

function frpcStatusText(value: string | null | undefined, fallbackStatus?: TunnelSnapshot["status"]) {
  const status = normalizeTunnelServiceStatus(value) || normalizeTunnelServiceStatus(fallbackStatus);
  if (!status || status === "stopped") return "已停止";
  if (["running", "connected", "online", "ok", "healthy", "success"].includes(status)) return "运行中";
  if (status === "starting") return "启动中";
  if (["waiting", "pending"].some((token) => status.includes(token))) return "等待中";
  if (["error", "failed", "timeout", "forbidden"].some((token) => status.includes(token))) return "异常";
  return value || tunnelStatusText(fallbackStatus || "stopped");
}

function heartbeatStatusText(value: string | null | undefined) {
  const status = normalizeTunnelServiceStatus(value);
  if (!status || ["stopped", "disabled", "offline"].includes(status)) return "未上报";
  if (["running", "connected", "online", "ok", "healthy", "success"].includes(status)) return "正常";
  if (status === "starting") return "启动中";
  if (["waiting", "pending"].some((token) => status.includes(token))) return "等待中";
  if (["error", "failed", "timeout", "forbidden"].some((token) => status.includes(token))) return "异常";
  return value || "未上报";
}

function fixedForwardErrorHint(value: string | null | undefined) {
  const text = String(value || "").trim();
  if (!text) return "";
  const normalized = text.toLowerCase();
  if (
    normalized.includes("403")
    || (normalized.includes("node") && normalized.includes("token"))
  ) {
    return "节点 token 错";
  }
  if (
    normalized.includes("login to server failed")
    || normalized.includes("authorization failed")
    || normalized.includes("auth failed")
    || (normalized.includes("frps") && normalized.includes("token"))
  ) {
    return "frps token 错";
  }
  if (
    ["timeout", "timed out", "10060", "10061", "refused", "unreachable", "no route", "i/o timeout"].some((token) => normalized.includes(token))
    && (normalized.includes("7000") || normalized.includes("frps") || normalized.includes("dial tcp") || normalized.includes("connect"))
  ) {
    return "frps 端口不通/安全组未放通";
  }
  return "";
}

function notificationPermissionText(permission: BrowserNotificationPermission) {
  if (permission === "granted") return "已允许";
  if (permission === "denied") return "已拒绝";
  if (permission === "unsupported") return "浏览器不支持";
  return "未询问";
}

function pushPlusStatusText(status: NotificationSettingsStatus | null) {
  if (!status) return "后端未提供状态";
  if (!status.pushPlusEnabled) return "未启用";
  return status.pushPlusConfigured ? "已配置" : "未配置 token";
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function asWebApiClientError(error: unknown): WebApiClientError | null {
  if (error instanceof WebApiClientError) {
    return error;
  }
  if (!error || typeof error !== "object") {
    return null;
  }
  const candidate = error as Partial<WebApiClientError> & { name?: unknown };
  if (candidate.name === "WebApiClientError" || typeof candidate.code === "string") {
    return candidate as WebApiClientError;
  }
  return null;
}

export function SettingsScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  onLogout,
  embedded = false,
  prefilledWorkdir,
  onWorkdirUpdated,
  themeName = DEFAULT_UI_THEME,
  onThemeChange,
  chatBodyFontFamily = DEFAULT_CHAT_BODY_FONT_FAMILY,
  onChatBodyFontFamilyChange,
  chatBodyFontSize = DEFAULT_CHAT_BODY_FONT_SIZE,
  onChatBodyFontSizeChange,
  chatBodyLineHeight = DEFAULT_CHAT_BODY_LINE_HEIGHT,
  onChatBodyLineHeightChange,
  chatBodyParagraphSpacing = DEFAULT_CHAT_BODY_PARAGRAPH_SPACING,
  onChatBodyParagraphSpacingChange,
  userAvatarName = readStoredUserAvatarName(),
  onUserAvatarChange,
  sessionCapabilities = [],
  showBotRuntimeSettings = true,
  onOpenBotManager,
}: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [tunnel, setTunnel] = useState<TunnelSnapshot | null>(null);
  const [gitProxySettings, setGitProxySettings] = useState<GitProxySettings | null>(null);
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettingsStatus | null>(null);
  const [notificationEnabled, setNotificationEnabled] = useState(() => readChatCompletionWebNotificationEnabled());
  const [notificationPermission, setNotificationPermission] = useState<BrowserNotificationPermission>(() => getBrowserNotificationPermission());
  const [avatarAssets, setAvatarAssets] = useState<AvatarAsset[]>(DEFAULT_AVATAR_ASSETS);
  const [cliTypeDraft, setCliTypeDraft] = useState<CliType>("codex");
  const [cliPathDraft, setCliPathDraft] = useState("");
  const [gitProxyAddressDraft, setGitProxyAddressDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [workdirDraft, setWorkdirDraft] = useState("");
  const [pendingWorkdirConflict, setPendingWorkdirConflict] = useState<WorkdirChangeConflict | null>(null);
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [showPushPlusGuide, setShowPushPlusGuide] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "kill">("");
  const [savingCliConfig, setSavingCliConfig] = useState(false);
  const [savingWorkdir, setSavingWorkdir] = useState(false);
  const [savingGitProxy, setSavingGitProxy] = useState(false);
  const [requestingNotificationPermission, setRequestingNotificationPermission] = useState(false);
  const [testingPushPlus, setTestingPushPlus] = useState(false);
  const [tunnelAction, setTunnelAction] = useState<"" | "start" | "stop" | "restart" | "copy">("");
  const isMainBot = botAlias === "main";
  const workdirLocked = overview?.botMode === "assistant";
  const canManageBotRuntime = sessionCapabilities.length === 0 || sessionCapabilities.includes("admin_ops");
  const canManageCliParams = canManageBotRuntime || sessionCapabilities.includes("manage_cli_params");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    Promise.allSettled([
      client.getBotOverview(botAlias),
      client.getTunnelStatus(),
      isMainBot ? client.getGitProxySettings() : Promise.resolve(null),
      client.getNotificationSettings?.() ?? Promise.resolve(null),
      client.listAvatarAssets(),
    ])
      .then(([
        overviewResult,
        tunnelResult,
        gitProxyResult,
        notificationSettingsResult,
        avatarAssetsResult,
      ]) => {
        if (cancelled) return;

        if (overviewResult.status !== "fulfilled") {
          setError(getErrorMessage(overviewResult.reason, "加载设置失败"));
          setLoading(false);
          return;
        }

        const overviewData = overviewResult.value;
        const tunnelData = tunnelResult.status === "fulfilled" ? tunnelResult.value : null;
        const gitProxyData = gitProxyResult.status === "fulfilled" ? gitProxyResult.value : null;
        const notificationData = notificationSettingsResult.status === "fulfilled" ? notificationSettingsResult.value : null;
        const avatarData = avatarAssetsResult.status === "fulfilled" && avatarAssetsResult.value.length > 0
          ? avatarAssetsResult.value
          : DEFAULT_AVATAR_ASSETS;

        setOverview(overviewData);
        setAvatarAssets(avatarData);
        setCliTypeDraft(overviewData.cliType);
        setCliPathDraft(overviewData.cliPath || "");
        setWorkdirDraft(normalizePathInput(prefilledWorkdir || overviewData.workingDir));
        setTunnel(tunnelData);
        setGitProxySettings(gitProxyData);
        setNotificationSettings(notificationData);
        setNotificationPermission(getBrowserNotificationPermission());
        setGitProxyAddressDraft(gitProxyData?.address || (gitProxyData?.port ? `127.0.0.1:${gitProxyData.port}` : ""));
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(getErrorMessage(err, "加载设置失败"));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [botAlias, client, isMainBot, prefilledWorkdir]);

  useEffect(() => {
    if (!["starting", "connected", "verifying_public"].includes(tunnel?.status || "") || !tunnel?.publicUrl || tunnelAction !== "") {
      return;
    }

    let cancelled = false;
    const timer = window.setInterval(() => {
      void client.getTunnelStatus()
        .then((next) => {
          if (cancelled) return;
          setError("");
          setTunnel(next);
          if (next.status === "running") {
            setNotice("Tunnel 已连接");
          }
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(getErrorMessage(err, "刷新 Tunnel 状态失败"));
        });
    }, TUNNEL_STATUS_REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [client, tunnel?.status, tunnel?.publicUrl, tunnelAction]);

  useEffect(() => {
    if (!prefilledWorkdir) {
      return;
    }
    setWorkdirDraft(normalizePathInput(prefilledWorkdir));
    setPendingWorkdirConflict(null);
  }, [prefilledWorkdir]);

  const confirmKill = async () => {
    setActionLoading("kill");
    setError("");
    setNotice("");
    try {
      const message = await client.killTask(botAlias);
      setNotice(message || "已发送终止任务请求");
      setShowKillConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "终止任务失败");
    } finally {
      setActionLoading("");
    }
  };

  const saveCliConfig = async () => {
    const nextCliPath = cliPathDraft.trim();
    if (!nextCliPath) {
      setError("CLI 路径不能为空");
      return;
    }

    setSavingCliConfig(true);
    setError("");
    setNotice("");
    try {
      const nextBot = await client.updateBotCli(botAlias, cliTypeDraft, nextCliPath);
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setCliTypeDraft(nextBot.cliType);
      setCliPathDraft(nextBot.cliPath || nextCliPath);
      setNotice("CLI 配置已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 CLI 配置失败");
    } finally {
      setSavingCliConfig(false);
    }
  };

  const applyWorkdirChange = async (options: UpdateBotWorkdirOptions = {}) => {
    const nextWorkdir = normalizePathInput(workdirDraft);
    setSavingWorkdir(true);
    try {
      const nextBot = await client.updateBotWorkdir(botAlias, nextWorkdir, options);
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setWorkdirDraft(nextBot.workingDir);
      setPendingWorkdirConflict(null);
      setNotice("工作目录已更新");
      onWorkdirUpdated?.(nextBot.workingDir);
    } finally {
      setSavingWorkdir(false);
    }
  };

  const saveWorkdir = async () => {
    const nextWorkdir = normalizePathInput(workdirDraft);
    if (!nextWorkdir) {
      setError("工作目录不能为空");
      return;
    }

    setError("");
    setNotice("");
    try {
      await applyWorkdirChange();
    } catch (err) {
      const clientError = asWebApiClientError(err);
      if (clientError?.code === "workdir_change_requires_reset" && clientError.data) {
        setPendingWorkdirConflict(clientError.data as WorkdirChangeConflict);
        return;
      }
      if (clientError?.code === "workdir_change_blocked_processing") {
        setPendingWorkdirConflict(null);
        setError("当前仍有任务运行，请先停止任务再切换工作目录");
        return;
      }
      setError(getErrorMessage(err, "更新工作目录失败"));
    }
  };

  const confirmWorkdirChange = async () => {
    setError("");
    setNotice("");
    try {
      await applyWorkdirChange({ forceReset: true });
    } catch (err) {
      const clientError = asWebApiClientError(err);
      if (clientError?.code === "workdir_change_requires_reset" && clientError.data) {
        setPendingWorkdirConflict(clientError.data as WorkdirChangeConflict);
        return;
      }
      if (clientError?.code === "workdir_change_blocked_processing") {
        setPendingWorkdirConflict(null);
        setError("当前仍有任务运行，请先停止任务再切换工作目录");
        return;
      }
      setError(getErrorMessage(err, "更新工作目录失败"));
    }
  };

  const saveGitProxy = async () => {
    const nextAddress = gitProxyAddressDraft.trim();
    if (!isValidGitProxyAddress(nextAddress)) {
      setError("代理地址必须是 host:port，或 1 到 65535 之间的端口");
      return;
    }

    setSavingGitProxy(true);
    setError("");
    setNotice("");
    try {
      const nextSettings = await client.updateGitProxySettings(nextAddress);
      setGitProxySettings(nextSettings);
      setGitProxyAddressDraft(nextSettings.address);
      setNotice("Git 代理设置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Git 代理失败");
    } finally {
      setSavingGitProxy(false);
    }
  };

  const handleThemeChange = (nextTheme: UiThemeName) => {
    if (nextTheme === themeName) {
      return;
    }
    setNotice("界面主题已切换");
    onThemeChange?.(nextTheme);
  };

  const handleNotificationToggle = (enabled: boolean) => {
    setNotificationEnabled(enabled);
    writeChatCompletionWebNotificationEnabled(enabled);
    setNotice(enabled ? "聊天完成通知已开启" : "聊天完成通知已关闭");
  };

  const requestNotificationPermission = async () => {
    setRequestingNotificationPermission(true);
    setError("");
    setNotice("");
    try {
      const nextPermission = await requestBrowserNotificationPermission();
      setNotificationPermission(nextPermission);
      if (nextPermission === "granted") {
        handleNotificationToggle(true);
      } else if (nextPermission === "denied") {
        setNotice("浏览器已拒绝通知权限");
      } else if (nextPermission === "unsupported") {
        setNotice("当前浏览器不支持通知");
      }
    } finally {
      setRequestingNotificationPermission(false);
    }
  };

  const sendPushPlusTest = async () => {
    if (!client.sendPushPlusTest) {
      setError("当前后端不支持 PushPlus 测试推送");
      return;
    }
    setTestingPushPlus(true);
    setError("");
    setNotice("");
    try {
      await client.sendPushPlusTest();
      setNotice("PushPlus 测试推送已发送");
    } catch (err) {
      setError(getErrorMessage(err, "PushPlus 测试推送失败"));
    } finally {
      setTestingPushPlus(false);
    }
  };

  const handleChatBodyFontFamilyChange = (nextFontFamily: ChatBodyFontFamilyName) => {
    if (nextFontFamily === chatBodyFontFamily) {
      return;
    }
    setNotice("聊天正文字体已更新");
    onChatBodyFontFamilyChange?.(nextFontFamily);
  };

  const handleChatBodyFontSizeChange = (nextFontSize: ChatBodyFontSizeName) => {
    if (nextFontSize === chatBodyFontSize) {
      return;
    }
    setNotice("聊天正文字号已更新");
    onChatBodyFontSizeChange?.(nextFontSize);
  };

  const handleChatBodyLineHeightChange = (nextLineHeight: ChatBodyLineHeightName) => {
    if (nextLineHeight === chatBodyLineHeight) {
      return;
    }
    setNotice("聊天行间距已更新");
    onChatBodyLineHeightChange?.(nextLineHeight);
  };

  const handleChatBodyParagraphSpacingChange = (nextParagraphSpacing: ChatBodyParagraphSpacingName) => {
    if (nextParagraphSpacing === chatBodyParagraphSpacing) {
      return;
    }
    setNotice("聊天段间距已更新");
    onChatBodyParagraphSpacingChange?.(nextParagraphSpacing);
  };

  const runTunnelAction = async (action: "start" | "stop" | "restart") => {
    setTunnelAction(action);
    setError("");
    setNotice("");
    try {
      const next = action === "start"
        ? await client.startTunnel()
        : action === "stop"
          ? await client.stopTunnel()
          : await client.restartTunnel();
      setTunnel(next);
      setNotice(action === "restart" ? "Tunnel 已重启" : action === "start" ? "Tunnel 已启动" : "Tunnel 已停止");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tunnel 操作失败");
    } finally {
      setTunnelAction("");
    }
  };

  const copyTunnelUrl = async () => {
    if (!tunnel?.publicUrl) return;
    setTunnelAction("copy");
    setError("");
    setNotice("");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(tunnel.publicUrl);
      }
      setNotice("公网地址已复制");
    } catch (err) {
      setError(err instanceof Error ? err.message : "复制公网地址失败");
    } finally {
      setTunnelAction("");
    }
  };

  const pushPlusGuideDialog = showPushPlusGuide ? (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="PushPlus 配置教程"
    >
      <div className="w-[min(32rem,calc(100vw-2rem))] rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
        <h2 className="text-base font-semibold text-[var(--text)]">PushPlus 配置教程</h2>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-[var(--text)]">
          <li>关注 PushPlus 公众号</li>
          <li>完成实名制认证</li>
          <li>登录 PushPlus 网站</li>
          <li>复制 token</li>
          <li>编辑项目 `.env`</li>
        </ol>
        <pre className="mt-4 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 text-xs text-[var(--text)]">
          <code>{`PUSHPLUS_ENABLED=true
PUSHPLUS_TOKEN=你的token
PUSHPLUS_TOPIC=可选群组编码`}</code>
        </pre>
        <p className="mt-3 text-sm text-[var(--muted)]">
          PUSHPLUS_TOPIC 可不填；不填时只推送给 token 所属账号。
        </p>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={() => setShowPushPlusGuide(false)}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--surface-strong)]"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--bg)]")}>
      {embedded ? null : (
        <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] p-4">
          {botAvatarName || overview?.avatarName ? (
            <BotIdentity
              alias={overview?.alias || botAlias}
              avatarName={botAvatarName || overview?.avatarName}
              size={32}
              nameClassName="truncate text-xl font-bold text-[var(--text)]"
              subtitle={<p className="text-sm text-[var(--muted)]">设置</p>}
            />
          ) : (
            <h1 className="text-xl font-bold">设置</h1>
          )}
        </header>
      )}

      <section className={clsx("flex-1 overflow-y-auto space-y-4", embedded ? "bg-[var(--workbench-titlebar-bg)] p-3" : "p-4")}>
        {loading ? (
          <div className="text-center text-[var(--muted)]">加载中...</div>
        ) : null}
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {notice}
          </div>
        ) : null}

        {botAlias === "main" ? (
          <div className={settingsPanelClass("space-y-4")}>
            <h2 className="text-base font-semibold text-[var(--text)]">界面与阅读</h2>

            <div className="space-y-2">
              <div className="text-sm font-medium text-[var(--text)]">界面主题</div>
              <ThemeDropdown value={themeName} onChange={handleThemeChange} />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天正文字体</div>
                <select
                  aria-label="聊天正文字体"
                  value={chatBodyFontFamily}
                  onChange={(event) => handleChatBodyFontFamilyChange(event.target.value as ChatBodyFontFamilyName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_FONT_FAMILY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天行间距</div>
                <select
                  aria-label="聊天行间距"
                  value={chatBodyLineHeight}
                  onChange={(event) => handleChatBodyLineHeightChange(event.target.value as ChatBodyLineHeightName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_LINE_HEIGHT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天正文字号</div>
                <select
                  aria-label="聊天正文字号"
                  value={chatBodyFontSize}
                  onChange={(event) => handleChatBodyFontSizeChange(event.target.value as ChatBodyFontSizeName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_FONT_SIZE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <div className="text-sm font-medium text-[var(--text)]">聊天段间距</div>
                <select
                  aria-label="聊天段间距"
                  value={chatBodyParagraphSpacing}
                  onChange={(event) => handleChatBodyParagraphSpacingChange(event.target.value as ChatBodyParagraphSpacingName)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  {CHAT_BODY_PARAGRAPH_SPACING_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
        ) : null}

        <div className={settingsPanelClass("space-y-4")}>
          <div className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-[var(--accent)]" />
            <h2 className="text-base font-semibold text-[var(--text)]">通知</h2>
          </div>

          <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
            <span className="text-sm text-[var(--text)]">聊天完成网页通知</span>
            <input
              aria-label="聊天完成网页通知"
              type="checkbox"
              checked={notificationEnabled}
              onChange={(event) => handleNotificationToggle(event.target.checked)}
              className="h-4 w-4"
            />
          </label>

          <div className="grid grid-cols-1 gap-3 text-sm text-[var(--muted)] sm:grid-cols-2">
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              浏览器权限: <span className="font-medium text-[var(--text)]">{notificationPermissionText(notificationPermission)}</span>
            </div>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
              PushPlus: <span className="font-medium text-[var(--text)]">{pushPlusStatusText(notificationSettings)}</span>
            </div>
          </div>

          <div className="flex flex-col items-start gap-2">
            <button
              type="button"
              onClick={() => void requestNotificationPermission()}
              disabled={requestingNotificationPermission || notificationPermission === "unsupported"}
              className={settingsButtonClass("plain")}
            >
              <Bell className="h-4 w-4" />
              {requestingNotificationPermission ? "请求中..." : "请求浏览器通知权限"}
            </button>
            <button
              type="button"
              onClick={() => void sendPushPlusTest()}
              disabled={testingPushPlus || !notificationSettings?.pushPlusEnabled}
              className={settingsButtonClass("plain")}
            >
              {testingPushPlus ? "发送中..." : "测试 PushPlus 推送"}
            </button>
            <button
              type="button"
              onClick={() => setShowPushPlusGuide(true)}
              className={settingsButtonClass("plain")}
            >
              PushPlus 配置教程
            </button>
          </div>
        </div>

        <div className={settingsPanelClass("space-y-4")}>
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-base font-semibold text-[var(--text)]">我的头像</h2>
            <AvatarPicker
              assets={avatarAssets}
              selectedName={userAvatarName}
              previewAlt="我的头像预览"
              selectLabel="我的头像"
              kind="user"
              onSelect={(avatarName) => {
                onUserAvatarChange?.(avatarName);
                setNotice("我的头像已更新");
              }}
            />
          </div>
        </div>

        {overview ? (
          showBotRuntimeSettings ? (
            <section
              aria-labelledby={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
              className={settingsPanelClass("space-y-4 text-sm text-[var(--muted)]")}
            >
              <div className="space-y-1">
                <h2
                  id={isMainBot ? "main-bot-ops-title" : "bot-runtime-title"}
                  className="text-base font-semibold text-[var(--text)]"
                >
                  {isMainBot ? "主 Bot 运维" : "Bot CLI 配置"}
                </h2>
                {isMainBot ? (
                  <p className="text-sm text-[var(--muted)]">主 Bot 的运行配置入口。</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <p><span className="font-medium text-[var(--text)]">CLI:</span> {overview.cliType}</p>
                {overview.cliPath ? (
                  <p className="break-all"><span className="font-medium text-[var(--text)]">CLI 路径:</span> {overview.cliPath}</p>
                ) : null}
                <p><span className="font-medium text-[var(--text)]">状态:</span> {overview.status}</p>
                <p className="break-all"><span className="font-medium text-[var(--text)]">目录:</span> {overview.workingDir}</p>
              </div>

              <div className="space-y-3 border-t border-[var(--border)] pt-4">
                <h3 className="font-medium text-[var(--text)]">运行配置</h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-sm text-[var(--text)]">CLI 类型</span>
                    <select
                      aria-label="CLI 类型"
                      value={cliTypeDraft}
                      disabled={!canManageBotRuntime}
                      onChange={(event) => setCliTypeDraft(event.target.value as CliType)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                    >
                      <option value="codex">codex</option>
                      <option value="claude">claude</option>
                      <option value="kimi">kimi</option>
                    </select>
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm text-[var(--text)]">CLI 路径</span>
                    <input
                      aria-label="CLI 路径"
                      type="text"
                      value={cliPathDraft}
                      disabled={!canManageBotRuntime}
                      onChange={(event) => setCliPathDraft(event.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-60"
                      placeholder={defaultCliPathForType(cliTypeDraft)}
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => void saveCliConfig()}
                  disabled={!canManageBotRuntime || savingCliConfig}
                  className={settingsButtonClass("primary")}
                >
                  <Save className="h-4 w-4" />
                  {savingCliConfig ? "保存中..." : "保存 CLI 配置"}
                </button>
              </div>

              <div className="space-y-3 border-t border-[var(--border)] pt-4">
                <div>
                  <label htmlFor="bot-workdir" className="font-medium text-[var(--text)]">工作目录</label>
                  {workdirLocked ? <p className="mt-1 text-xs text-[var(--muted)]">assistant 型 Bot 的默认工作目录已锁定</p> : null}
                </div>
                <div>
                  <input
                    id="bot-workdir"
                    aria-label="工作目录"
                    type="text"
                    value={workdirDraft}
                    onChange={(event) => {
                      setWorkdirDraft(event.target.value);
                      if (pendingWorkdirConflict) {
                        setPendingWorkdirConflict(null);
                      }
                    }}
                    readOnly={workdirLocked || !canManageBotRuntime}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </div>
                {workdirLocked ? null : (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      aria-label="浏览工作目录"
                      onClick={() => setShowWorkdirPicker(true)}
                      disabled={!canManageBotRuntime || savingWorkdir}
                      className={settingsButtonClass("plain")}
                    >
                      浏览目录
                    </button>
                    <button
                      type="button"
                      onClick={() => void saveWorkdir()}
                      disabled={!canManageBotRuntime || savingWorkdir}
                      className={settingsButtonClass("primary")}
                    >
                      <Save className="h-4 w-4" />
                      {savingWorkdir ? "保存中..." : "保存工作目录"}
                    </button>
                  </div>
                )}
              </div>
            </section>
          ) : null
        ) : null}

        {showWorkdirPicker && !workdirLocked ? (
          <DirectoryPickerDialog
            title="选择工作目录"
            botAlias={botAlias}
            client={client}
            initialPath={workdirDraft}
            onPick={(workingDir) => {
              setWorkdirDraft(workingDir);
              setPendingWorkdirConflict(null);
            }}
            onClose={() => setShowWorkdirPicker(false)}
          />
        ) : null}

        {isMainBot ? (
          <div className={settingsPanelClass("space-y-4")}>
            <h2 className="text-base font-semibold text-[var(--text)]">Git 代理</h2>
            <div data-testid="git-proxy-control-row" className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <input
                aria-label="Git 代理地址"
                type="text"
                inputMode="text"
                value={gitProxyAddressDraft}
                onChange={(event) => setGitProxyAddressDraft(event.target.value)}
                placeholder="例如 192.168.1.10:7897 或 7897"
                className="w-full min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
              />
              <button
                type="button"
                aria-label="保存 Git 代理"
                onClick={() => void saveGitProxy()}
                disabled={savingGitProxy}
                className={settingsButtonClass("primary", "w-full sm:w-auto")}
              >
                <Save className="h-4 w-4" />
                {savingGitProxy ? "保存中..." : "保存"}
              </button>
            </div>
            <p className="text-xs text-[var(--muted)]">
              当前状态: {gitProxyStatusText(gitProxySettings)}
            </p>
          </div>
        ) : null}

        {overview && showBotRuntimeSettings ? (
          <AgentSettingsPanel
            botAlias={botAlias}
            botMode={overview.botMode || "cli"}
            client={client}
            canManage={canManageBotRuntime}
          />
        ) : null}

        {overview && showBotRuntimeSettings ? (
          <BotCliParamsPanel
            botAlias={botAlias}
            client={client}
            canManage={canManageCliParams}
            reloadKey={`${botAlias}:${overview.cliType}:${overview.cliPath || ""}`}
          />
        ) : null}

        {tunnel ? (
          <div className={settingsPanelClass("space-y-4")}>
            {(() => {
              const fixedForward = isFixedPublicForward(tunnel);
              const frpcStatus = fixedForward ? frpcStatusText(tunnel.frpcStatus, tunnel.status) : "";
              const heartbeatStatus = fixedForward ? heartbeatStatusText(tunnel.heartbeatStatus) : "";
              const frpcErrorHint = fixedForwardErrorHint(tunnel.frpcLastError || tunnel.lastError);
              const heartbeatErrorHint = fixedForwardErrorHint(tunnel.heartbeatLastError);

              return (
                <>
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Globe className="h-5 w-5 text-[var(--accent)]" />
                  <h2 className="text-base font-semibold text-[var(--text)]">公网访问</h2>
                </div>
                <p className="text-sm text-[var(--muted)]">状态: {tunnelStatusText(tunnel.status)}</p>
              </div>
              <StateBadge tone="neutral">
                {tunnelSourceText(tunnel)}
              </StateBadge>
            </div>

            <div className="space-y-2 text-sm text-[var(--muted)]">
              <p className="break-all"><span className="font-medium text-[var(--text)]">HTTPS 访问:</span> {tunnel.publicUrl || "未建立公网地址"}</p>
              <p className="break-all"><span className="font-medium text-[var(--text)]">本地转发目标:</span> {tunnel.localUrl}</p>
              {fixedForward && tunnel.nodeId ? (
                <p className="break-all"><span className="font-medium text-[var(--text)]">Node ID:</span> {tunnel.nodeId}</p>
              ) : null}
              {fixedForward && tunnel.basePath ? (
                <p className="break-all"><span className="font-medium text-[var(--text)]">Base Path:</span> {tunnel.basePath}</p>
              ) : null}
              {tunnel.publicUrl && tunnel.source === "quick_tunnel" && tunnel.status !== "running" && !tunnel.lastError ? (
                <p className="break-all">公网地址已创建，正在验证</p>
              ) : null}
              {tunnel.lastError ? (
                <p className="break-all text-red-700"><span className="font-medium">错误:</span> {tunnel.lastError}</p>
              ) : null}
            </div>

            {fixedForward ? (
              <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-3 text-[var(--muted)]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-[var(--text)]">frpc 状态</span>
                    <StateBadge tone={tunnelServiceTone(tunnel.frpcStatus || tunnel.status)}>{frpcStatus}</StateBadge>
                  </div>
                  <div className="mt-2 space-y-1">
                    <p>PID: {tunnel.frpcPid ?? tunnel.pid ?? "未启动"}</p>
                    {tunnel.frpcLastError ? (
                      <p className="break-all text-red-700">错误: {tunnel.frpcLastError}</p>
                    ) : null}
                    {frpcErrorHint ? (
                      <p className="text-red-700">提示: {frpcErrorHint}</p>
                    ) : null}
                  </div>
                </div>

                <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-3 text-[var(--muted)]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-[var(--text)]">Heartbeat</span>
                    <StateBadge tone={tunnelServiceTone(tunnel.heartbeatStatus)}>{heartbeatStatus}</StateBadge>
                  </div>
                  <div className="mt-2 space-y-1">
                    <p className="break-all">最近上报: {tunnel.heartbeatLastAt || "暂无"}</p>
                    {tunnel.heartbeatLastError ? (
                      <p className="break-all text-red-700">错误: {tunnel.heartbeatLastError}</p>
                    ) : null}
                    {heartbeatErrorHint ? (
                      <p className="text-red-700">提示: {heartbeatErrorHint}</p>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2">
              {tunnel.source === "quick_tunnel" ? (
                <>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("start")}
                    disabled={tunnelAction !== "" || tunnel.status === "running" || tunnel.status === "starting" || tunnel.status === "connected" || tunnel.status === "verifying_public" || tunnel.status === "waiting_url"}
                    className={settingsButtonClass("plain")}
                  >
                    启动 Tunnel
                  </button>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("stop")}
                    disabled={tunnelAction !== "" || tunnel.status === "stopped"}
                    className={settingsButtonClass("plain")}
                  >
                    停止 Tunnel
                  </button>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("restart")}
                    disabled={tunnelAction !== ""}
                    className={settingsButtonClass("plain")}
                  >
                    <RotateCw className="h-4 w-4" />
                    重启 Tunnel
                  </button>
                </>
              ) : (
                <div className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-2 text-sm text-[var(--muted)]">
                  {tunnel.source === "fixed_public_forward"
                    ? "固定公网转发在管理中心配置"
                    : "当前使用 `WEB_PUBLIC_URL` 手工配置地址"}
                </div>
              )}

              <button
                type="button"
                onClick={() => void copyTunnelUrl()}
                disabled={tunnelAction !== "" || !tunnel.publicUrl}
                className={settingsButtonClass("plain")}
              >
                <Copy className="h-4 w-4" />
                复制公网地址
              </button>
            </div>
                </>
              );
            })()}
          </div>
        ) : null}

        <div className={settingsActionPanelClass("divide-y divide-[var(--workbench-hairline)]")}>
          <button
            onClick={() => setShowKillConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--workbench-hover-bg)] active:bg-[var(--workbench-active-bg)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <Square className="w-5 h-5" />
              终止当前任务
            </span>
          </button>
          {embedded ? null : (
            <button
              onClick={onLogout}
              className="w-full flex items-center justify-between p-4 hover:bg-[var(--workbench-hover-bg)] active:bg-[var(--workbench-active-bg)]"
            >
              <span className="flex items-center gap-3">
                <LogOut className="w-5 h-5" />
                退出登录
              </span>
            </button>
          )}
        </div>
      </section>

      {pendingWorkdirConflict ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workdir-reset-title"
        >
          <div className="w-full max-w-md rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl">
            <h2 id="workdir-reset-title" className="text-base font-semibold text-[var(--text)]">
              确认切换工作目录
            </h2>
            <p className="mt-3 text-sm text-[var(--muted)]">切换工作目录会丢失当前会话。</p>
            <p className="mt-2 break-all text-sm text-[var(--text)]">
              当前目录：{pendingWorkdirConflict.currentWorkingDir}
            </p>
            <p className="break-all text-sm text-[var(--text)]">
              目标目录：{pendingWorkdirConflict.requestedWorkingDir}
            </p>
            <p className="text-sm text-[var(--muted)]">
              将清空 {pendingWorkdirConflict.historyCount} 条聊天消息。
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setPendingWorkdirConflict(null)}
                disabled={savingWorkdir}
                className="rounded-full border border-[var(--border)] px-4 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void confirmWorkdirChange()}
                disabled={savingWorkdir}
                className="tcb-solid-danger rounded-full px-4 py-2 text-sm hover:opacity-90 disabled:opacity-60"
              >
                {savingWorkdir ? "切换中..." : "确认并切换"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showKillConfirm ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">终止任务</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要终止当前正在运行的任务吗？</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowKillConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button
                onClick={() => void confirmKill()}
                disabled={actionLoading === "kill"}
                className="tcb-solid-danger px-4 py-2 rounded-lg hover:opacity-90"
              >
                {actionLoading === "kill" ? "终止中..." : "确定终止"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {pushPlusGuideDialog && typeof document !== "undefined" ? createPortal(pushPlusGuideDialog, document.body) : pushPlusGuideDialog}

    </main>
  );
}
