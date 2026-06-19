import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Eye, EyeOff, RefreshCw, RotateCcw, Save, Trash2 } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  AdminUser,
  AnnouncementItem,
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  BotSummary,
  Capability,
  CliErrorStatsResult,
  CreateAnnouncementInput,
  EnvConfigItem,
  EnvConfigPatchInput,
  EnvConfigPatchResult,
  EnvConfigPatchValue,
  EnvConfigSnapshot,
  EnvConfigValue,
  LanChatConfig,
  LanChatConfigInput,
  NativeAgentConfigPayload,
  NativeAgentPreflightCheck,
  NativeAgentPreflightResult,
  OfflineUpdatePackageList,
  RegisterCodeCreateResult,
  RegisterCodeItem,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client?: WebBotClient;
  onClose: () => void;
  initialBots?: BotSummary[];
  onBotsChange?: (bots: BotSummary[]) => void;
  canManageRegisterCodes?: boolean;
  canManageEnvConfig?: boolean;
};

type AdminCenterTab = "users" | "invites" | "cli-errors" | "updates" | "announcements" | "lan-chat" | "native-agent" | "env";

const ENV_CATEGORY_LABELS: Record<string, string> = {
  basic: "基础",
  web: "Web",
  native_agent: "原生 Agent",
  tunnel: "Tunnel",
  updates: "更新",
  update: "更新",
  notifications: "通知",
  notification: "通知",
  diagnostics: "诊断",
  advanced: "高级",
  frontend: "前端构建项",
};

const ENV_CATEGORY_ORDER = [
  "basic",
  "web",
  "native_agent",
  "tunnel",
  "updates",
  "update",
  "notifications",
  "notification",
  "diagnostics",
  "advanced",
  "frontend",
];

const DEFAULT_ANNOUNCEMENT_DRAFT: CreateAnnouncementInput = {
  publisher: "CLI Bridge",
  title: "管理中心更新",
  category: "feature",
  severity: "info",
  summary: "管理中心权限、插件和更新能力已合并。",
  sections: [
    { label: "新增", items: ["新增权限管理入口"] },
    { label: "影响", items: ["所有用户登录后会看到新公告"] },
    { label: "操作", items: ["点关闭后不再重复弹出"] },
  ],
};

const ACCOUNT_CAPABILITY_OPTIONS: Array<{ id: Capability; label: string }> = [
  { id: "chat_send", label: "聊天" },
  { id: "read_file_content", label: "读文件" },
  { id: "write_files", label: "写文件" },
  { id: "terminal_exec", label: "终端" },
  { id: "debug_exec", label: "调试" },
  { id: "git_ops", label: "Git" },
  { id: "manage_bots", label: "管理智能体" },
  { id: "create_workdir_directory", label: "新建工作目录" },
  { id: "run_plugins", label: "运行插件" },
  { id: "run_unsafe_cli", label: "高风险 CLI" },
  { id: "admin_ops", label: "管理操作" },
  { id: "manage_register_codes", label: "邀请码/用户" },
];

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function formatPackageKind(kind?: string) {
  if (kind === "installer") return "Windows 安装版";
  if (kind === "portable") return "Windows 绿色版";
  if (kind === "linux") return "Linux";
  if (kind === "macos") return "macOS";
  return "未知";
}

function formatEnvValue(value: EnvConfigValue | undefined, masked = false) {
  if (masked) return "********";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return value || "";
}

function topEntryLabel(values: Record<string, number>) {
  const [key, count] = Object.entries(values).sort((left, right) => right[1] - left[1])[0] || [];
  return key ? `${key} (${count})` : "无";
}

function formatShortTime(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function nativePreflightStatus(preflight?: NativeAgentPreflightResult) {
  if (!preflight) return "未运行";
  if (!preflight.ok) return "失败";
  return preflight.checks.some((check) => check.severity === "warning" && !check.ok) ? "警告" : "通过";
}

function nativePreflightStatusClass(preflight?: NativeAgentPreflightResult) {
  const status = nativePreflightStatus(preflight);
  if (status === "失败") return "border-red-200 bg-red-50 text-red-700";
  if (status === "警告") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "通过") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  return "border-[var(--border)] bg-[var(--bg)] text-[var(--muted)]";
}

function nativePreflightCheckClass(check: NativeAgentPreflightCheck) {
  if (check.severity === "error" && !check.ok) return "border-red-200 bg-red-50 text-red-800";
  if (check.severity === "warning" && !check.ok) return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-[var(--border)] bg-[var(--bg)] text-[var(--muted)]";
}

function shortErrorText(value: string) {
  const text = (value || "").trim();
  if (!text) return "-";
  return text.length > 120 ? `${text.slice(0, 117).trim()}...` : text;
}

function envValueEquals(left: EnvConfigValue | undefined, right: EnvConfigValue | undefined) {
  return formatEnvValue(left) === formatEnvValue(right);
}

function normalizeEnvDraftValue(item: EnvConfigItem, value: string | boolean): EnvConfigValue {
  if (item.type === "boolean") return Boolean(value);
  if (item.type === "number") return Number(value || 0);
  if (item.type === "csv") {
    return String(value).split(",").map((part) => part.trim()).filter(Boolean);
  }
  return String(value);
}

function envDraftString(values: Record<string, EnvConfigValue>, key: string) {
  const value = values[key];
  if (Array.isArray(value)) return value.join(",");
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return String(value || "");
}

export function AdminCenterScreen({
  client = new MockWebBotClient(),
  onClose,
  initialBots = [],
  onBotsChange,
  canManageRegisterCodes = true,
  canManageEnvConfig = true,
}: Props) {
  const [activeTab, setActiveTab] = useState<AdminCenterTab>("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [bots, setBots] = useState<BotSummary[]>(initialBots);
  const [registerCodes, setRegisterCodes] = useState<RegisterCodeItem[]>([]);
  const [updateStatus, setUpdateStatus] = useState<AppUpdateStatus | null>(null);
  const [offlinePackages, setOfflinePackages] = useState<OfflineUpdatePackageList | null>(null);
  const [cliErrorStats, setCliErrorStats] = useState<CliErrorStatsResult | null>(null);
  const [cliErrorHours, setCliErrorHours] = useState(24);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [announcementDraft, setAnnouncementDraft] = useState<CreateAnnouncementInput>(DEFAULT_ANNOUNCEMENT_DRAFT);
  const [announcementSaving, setAnnouncementSaving] = useState(false);
  const [announcementDeletingId, setAnnouncementDeletingId] = useState("");
  const [lanChatConfig, setLanChatConfig] = useState<LanChatConfig | null>(null);
  const [lanChatDraft, setLanChatDraft] = useState<LanChatConfigInput>({});
  const [lanChatSaving, setLanChatSaving] = useState(false);
  const [nativeAgentConfig, setNativeAgentConfig] = useState<NativeAgentConfigPayload | null>(null);
  const [nativeAgentDraft, setNativeAgentDraft] = useState("");
  const [nativeAgentSystemPromptDraft, setNativeAgentSystemPromptDraft] = useState("");
  const [nativeAgentSaving, setNativeAgentSaving] = useState(false);
  const [nativeAgentPreflightRunning, setNativeAgentPreflightRunning] = useState(false);
  const [envConfig, setEnvConfig] = useState<EnvConfigSnapshot | null>(null);
  const [envDraft, setEnvDraft] = useState<Record<string, EnvConfigValue>>({});
  const [envVisibleSecrets, setEnvVisibleSecrets] = useState<Record<string, boolean>>({});
  const [envSecretActions, setEnvSecretActions] = useState<Record<string, "clear" | "regenerate" | "edit">>({});
  const [activeEnvCategory, setActiveEnvCategory] = useState("");
  const [envPreview, setEnvPreview] = useState<EnvConfigPatchResult | null>(null);
  const [envSaving, setEnvSaving] = useState(false);
  const [envRestarting, setEnvRestarting] = useState(false);
  const [envSavedImpact, setEnvSavedImpact] = useState<EnvConfigPatchResult | null>(null);
  const [loadedTabs, setLoadedTabs] = useState<Record<AdminCenterTab, boolean>>({
    users: false,
    invites: false,
    "cli-errors": false,
    updates: false,
    announcements: false,
    "lan-chat": false,
    "native-agent": false,
    env: false,
  });
  const [manualPackagePath, setManualPackagePath] = useState("");
  const [registerCodeDraftUses, setRegisterCodeDraftUses] = useState("1");
  const [createdRegisterCode, setCreatedRegisterCode] = useState<RegisterCodeCreateResult | null>(null);
  const [registerCodeCreating, setRegisterCodeCreating] = useState(false);
  const [registerCodeActionId, setRegisterCodeActionId] = useState("");
  const [updateAction, setUpdateAction] = useState<"" | "toggle" | "check" | "download" | "offline">("");
  const [updateLogLines, setUpdateLogLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const totalOwnedBots = useMemo(() => users.reduce((sum, user) => sum + user.ownedBotCount, 0), [users]);
  const visibleTabs = useMemo<AdminCenterTab[]>(
    () => [
      "users",
      ...(canManageRegisterCodes ? (["invites"] as AdminCenterTab[]) : []),
      "cli-errors",
      "updates",
      "announcements",
      "lan-chat",
      "native-agent",
      ...(canManageEnvConfig ? (["env"] as AdminCenterTab[]) : []),
    ],
    [canManageEnvConfig, canManageRegisterCodes],
  );
  const envCategories = useMemo(() => {
    const categories = Array.from(new Set((envConfig?.items || []).map((item) => item.category)));
    return categories.sort((left, right) => {
      const leftIndex = ENV_CATEGORY_ORDER.indexOf(left);
      const rightIndex = ENV_CATEGORY_ORDER.indexOf(right);
      return (leftIndex < 0 ? 999 : leftIndex) - (rightIndex < 0 ? 999 : rightIndex);
    });
  }, [envConfig]);
  const envChangedItems = useMemo(() => (envConfig?.items || []).filter((item) => {
    const action = envSecretActions[item.key];
    if (action === "clear" || action === "regenerate") return true;
    return Object.prototype.hasOwnProperty.call(envDraft, item.key)
      && !envValueEquals(envDraft[item.key], item.value);
  }), [envConfig, envDraft, envSecretActions]);
  const activeEnvItems = useMemo(() => {
    const category = activeEnvCategory || envCategories[0] || "";
    return (envConfig?.items || []).filter((item) => item.category === category);
  }, [activeEnvCategory, envCategories, envConfig]);
  const envConflictMessage = useMemo(() => {
    const fixedEnabled = envDraft.WEB_FIXED_PUBLIC_FORWARD_ENABLED === true
      || envDraftString(envDraft, "WEB_FIXED_PUBLIC_FORWARD_ENABLED").toLowerCase() === "true";
    const tunnelMode = envDraftString(envDraft, "WEB_TUNNEL_MODE").trim();
    if (fixedEnabled && tunnelMode === "cloudflare_quick") {
      return "固定公网转发和 Cloudflare Quick Tunnel 不能同时启用。";
    }
    return "";
  }, [envDraft]);

  useEffect(() => {
    if (!visibleTabs.includes(activeTab)) {
      setActiveTab(visibleTabs[0] || "users");
    }
  }, [activeTab, visibleTabs]);

  async function loadUsers(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const usersPromise = client.listAdminUsers();
      const botsPromise = bots.length > 0 ? Promise.resolve(bots) : client.listBots();
      const [usersData, botsData] = await Promise.all([
        usersPromise,
        botsPromise,
      ]);
      setUsers(usersData);
      setBots(botsData);
      onBotsChange?.(botsData);
      setLoadedTabs((prev) => ({ ...prev, users: true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载用户权限失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadInvites(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const codesData = await client.listRegisterCodes();
      setRegisterCodes(codesData);
      setLoadedTabs((prev) => ({ ...prev, invites: true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载邀请码失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadUpdates(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const [updateData, packageData] = await Promise.all([
        client.getUpdateStatus(),
        client.listOfflineUpdatePackages(),
      ]);
      setUpdateStatus(updateData);
      setOfflinePackages(packageData);
      setLoadedTabs((prev) => ({ ...prev, updates: true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载升级信息失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadCliErrorStats(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const data = await client.getCliErrorStats({ hours: cliErrorHours, limit: 50 });
      setCliErrorStats(data);
      setLoadedTabs((prev) => ({ ...prev, "cli-errors": true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载 CLI 错误统计失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadAnnouncements(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const data = await client.listAnnouncements();
      setAnnouncements(data.items);
      setLoadedTabs((prev) => ({ ...prev, announcements: true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载公告失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadLanChat(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const config = await client.getLanChatConfig();
      setLanChatConfig(config);
      setLanChatDraft({
        mode: config.mode,
        roomName: config.roomName,
        instanceName: config.instanceName,
        hostUrl: config.hostUrl,
        lanOnly: config.lanOnly,
        autoConnect: config.autoConnect,
      });
      setLoadedTabs((prev) => ({ ...prev, "lan-chat": true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载联机聊天配置失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadNativeAgentConfig(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const config = await client.getNativeAgentConfig();
      setNativeAgentConfig(config);
      setNativeAgentDraft(JSON.stringify(config.config || {}, null, 2));
      setNativeAgentSystemPromptDraft(String(config.config?.system_prompt ?? config.config?.systemPrompt ?? ""));
      setLoadedTabs((prev) => ({ ...prev, "native-agent": true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载原生 Agent 配置失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadEnvConfig(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }
    try {
      const config = await client.getEnvConfig();
      setEnvConfig(config);
      setEnvDraft(Object.fromEntries(config.items.map((item) => [item.key, item.value])));
      setEnvSecretActions({});
      setEnvVisibleSecrets({});
      setEnvPreview(null);
      setLoadedTabs((prev) => ({ ...prev, env: true }));
      if (config.items.length) {
        const firstCategory = ENV_CATEGORY_ORDER.find((category) =>
          config.items.some((item) => item.category === category),
        ) || config.items[0].category;
        setActiveEnvCategory((current) => current || firstCategory);
      }
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载环境配置失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function refreshActiveTab(nextNotice = "", refresh = false) {
    if (activeTab === "users") {
      await loadUsers(nextNotice, refresh);
    } else if (activeTab === "invites" && canManageRegisterCodes) {
      await loadInvites(nextNotice, refresh);
    } else if (activeTab === "cli-errors") {
      await loadCliErrorStats(nextNotice, refresh);
    } else if (activeTab === "updates") {
      await loadUpdates(nextNotice, refresh);
    } else if (activeTab === "lan-chat") {
      await loadLanChat(nextNotice, refresh);
    } else if (activeTab === "native-agent") {
      await loadNativeAgentConfig(nextNotice, refresh);
    } else if (activeTab === "env" && canManageEnvConfig) {
      await loadEnvConfig(nextNotice, refresh);
    } else {
      await loadAnnouncements(nextNotice, refresh);
    }
  }

  useEffect(() => {
    if (loadedTabs[activeTab]) {
      return;
    }
    void refreshActiveTab();
  }, [activeTab, canManageEnvConfig, canManageRegisterCodes, client, loadedTabs]);

  const appendUpdateLog = (message?: string) => {
    if (!message) {
      return;
    }
    setUpdateLogLines((prev) => [...prev, message]);
  };

  const updateUserBotGrant = async (user: AdminUser, alias: string, enabled: boolean) => {
    const nextAllowed = enabled
      ? [...user.allowedBots, alias]
      : user.allowedBots.filter((item) => item !== alias);
    setError("");
    setNotice("");
    try {
      const updated = await client.updateUserBotPermissions(user.accountId, nextAllowed);
      setUsers((prev) => prev.map((item) => (
        item.accountId === user.accountId
          ? { ...item, allowedBots: updated.allowedBots }
          : item
      )));
      setNotice(`${user.username} 的 Bot 权限已更新`);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "更新 Bot 权限失败"));
    }
  };

  const updateUserCapabilityGrant = async (user: AdminUser, capability: Capability, enabled: boolean) => {
    const nextCapabilities = enabled
      ? Array.from(new Set([...user.capabilities, capability]))
      : user.capabilities.filter((item) => item !== capability);
    setError("");
    setNotice("");
    try {
      const updated = await client.updateUser(user.accountId, { capabilities: nextCapabilities });
      setUsers((prev) => prev.map((item) => (
        item.accountId === user.accountId
          ? { ...item, capabilities: updated.capabilities }
          : item
      )));
      setNotice(`${user.username} 的账号能力已更新`);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "更新账号能力失败"));
    }
  };

  const toggleUserDisabled = async (user: AdminUser) => {
    setError("");
    setNotice("");
    try {
      const updated = await client.updateUser(user.accountId, { disabled: !user.disabled });
      setUsers((prev) => prev.map((item) => (
        item.accountId === user.accountId ? { ...item, disabled: updated.disabled } : item
      )));
      setNotice(updated.disabled ? `${user.username} 已停用` : `${user.username} 已启用`);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "更新用户状态失败"));
    }
  };

  const createRegisterCode = async () => {
    const maxUses = Number(registerCodeDraftUses);
    if (!Number.isInteger(maxUses) || maxUses <= 0) {
      setError("邀请码可用次数至少为 1");
      return;
    }
    setRegisterCodeCreating(true);
    setError("");
    setNotice("");
    try {
      const created = await client.createRegisterCode(maxUses);
      setCreatedRegisterCode(created);
      setRegisterCodeDraftUses("1");
      await loadInvites("邀请码已生成", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "生成邀请码失败"));
    } finally {
      setRegisterCodeCreating(false);
    }
  };

  const mutateRegisterCode = async (
    codeId: string,
    input: { maxUsesDelta?: number; disabled?: boolean },
    successNotice: string,
  ) => {
    setRegisterCodeActionId(codeId);
    setError("");
    setNotice("");
    try {
      await client.updateRegisterCode(codeId, input);
      await loadInvites(successNotice, true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "更新邀请码失败"));
    } finally {
      setRegisterCodeActionId("");
    }
  };

  const removeRegisterCode = async (codeId: string) => {
    setRegisterCodeActionId(codeId);
    setError("");
    setNotice("");
    try {
      await client.deleteRegisterCode(codeId);
      await loadInvites("邀请码已删除", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "删除邀请码失败"));
    } finally {
      setRegisterCodeActionId("");
    }
  };

  const saveUpdateToggle = async (enabled: boolean) => {
    setUpdateAction("toggle");
    setError("");
    setNotice("");
    try {
      const nextStatus = await client.setUpdateEnabled(enabled);
      setUpdateStatus(nextStatus);
      setNotice(enabled ? "已启用自动下载更新" : "已关闭自动下载更新");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "保存更新设置失败"));
    } finally {
      setUpdateAction("");
    }
  };

  const checkOnlineUpdate = async () => {
    setUpdateAction("check");
    setError("");
    setNotice("");
    setUpdateLogLines(["检查联网更新"]);
    try {
      const nextStatus = await client.checkForUpdate();
      setUpdateStatus(nextStatus);
      appendUpdateLog(`当前版本: ${nextStatus.currentVersion}`);
      appendUpdateLog(`可用版本: ${nextStatus.latestVersion || "暂无"}`);
      setNotice("已检查联网更新");
    } catch (nextError) {
      const message = getErrorMessage(nextError, "检查更新失败");
      appendUpdateLog(`失败原因: ${message}`);
      setError(message);
    } finally {
      setUpdateAction("");
    }
  };

  const downloadOnlineUpdate = async () => {
    setUpdateAction("download");
    setError("");
    setNotice("");
    setUpdateLogLines([]);
    try {
      const nextStatus = await client.downloadUpdateStream((event: AppUpdateDownloadProgress) => {
        appendUpdateLog(event.message);
      });
      setUpdateStatus(nextStatus);
      appendUpdateLog("已设置待应用");
      setNotice("联网更新包已下载");
    } catch (nextError) {
      const message = getErrorMessage(nextError, "联网下载失败");
      appendUpdateLog(`失败原因: ${message}`);
      setError(message);
    } finally {
      setUpdateAction("");
    }
  };

  const prepareOffline = async (path: string, version = "") => {
    const normalizedPath = path.trim();
    if (!normalizedPath) {
      setError("本地离线包路径不能为空");
      return;
    }
    setUpdateAction("offline");
    setError("");
    setNotice("");
    setUpdateLogLines([]);
    try {
      const nextStatus = await client.prepareOfflineUpdateStream(normalizedPath, version, (event) => {
        appendUpdateLog(event.message);
      });
      setUpdateStatus(nextStatus);
      setManualPackagePath(normalizedPath);
      appendUpdateLog("已设置待应用");
      setNotice("离线升级包已设置");
    } catch (nextError) {
      const message = getErrorMessage(nextError, "离线升级失败");
      appendUpdateLog(`失败原因: ${message}`);
      setError(message);
    } finally {
      setUpdateAction("");
    }
  };

  const updateAnnouncementDraft = <K extends keyof CreateAnnouncementInput>(key: K, value: CreateAnnouncementInput[K]) => {
    setAnnouncementDraft((prev) => ({ ...prev, [key]: value }));
  };

  const updateAnnouncementSection = (index: number, key: "label" | "items", value: string) => {
    setAnnouncementDraft((prev) => ({
      ...prev,
      sections: prev.sections.map((section, sectionIndex) => {
        if (sectionIndex !== index) {
          return section;
        }
        return key === "label"
          ? { ...section, label: value }
          : { ...section, items: value.split("\n").map((item) => item.trim()).filter(Boolean) };
      }),
    }));
  };

  const saveAnnouncement = async () => {
    setAnnouncementSaving(true);
    setError("");
    setNotice("");
    try {
      await client.upsertAnnouncement(announcementDraft);
      await loadAnnouncements("公告已发布", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "发布公告失败"));
    } finally {
      setAnnouncementSaving(false);
    }
  };

  const saveLanChatConfig = async () => {
    setLanChatSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await client.updateLanChatConfig(lanChatDraft);
      setLanChatConfig(saved);
      setLanChatDraft({
        mode: saved.mode,
        roomName: saved.roomName,
        instanceName: saved.instanceName,
        hostUrl: saved.hostUrl,
        roomKey: saved.roomKey || "",
        lanOnly: saved.lanOnly,
        autoConnect: saved.autoConnect,
      });
      setNotice("联机聊天配置已保存");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "保存联机聊天配置失败"));
    } finally {
      setLanChatSaving(false);
    }
  };

  const saveNativeAgentConfig = async () => {
    setNativeAgentSaving(true);
    setError("");
    setNotice("");
    try {
      const parsed = JSON.parse(nativeAgentDraft || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setError("配置必须是 JSON 对象");
        return;
      }
      const nextConfig = { ...(parsed as Record<string, unknown>) };
      const normalizedSystemPrompt = nativeAgentSystemPromptDraft.trim();
      if (normalizedSystemPrompt) {
        nextConfig.system_prompt = normalizedSystemPrompt;
      } else {
        delete nextConfig.system_prompt;
        delete nextConfig.systemPrompt;
      }
      const saved = await client.updateNativeAgentConfig(nextConfig);
      setNativeAgentConfig({ ...saved, preflight: undefined });
      setNativeAgentDraft(JSON.stringify(saved.config || {}, null, 2));
      setNativeAgentSystemPromptDraft(String(saved.config?.system_prompt ?? saved.config?.systemPrompt ?? ""));
      setNotice(saved.needsRestart ? "配置已保存，重启原生 agent 后生效；请重新运行检查" : "原生 Agent 配置已保存；请重新运行检查");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "保存原生 Agent 配置失败"));
    } finally {
      setNativeAgentSaving(false);
    }
  };

  const runNativeAgentPreflight = async () => {
    setNativeAgentPreflightRunning(true);
    setError("");
    setNotice("");
    try {
      const preflight = await client.runNativeAgentPreflight();
      setNativeAgentConfig((prev) => prev ? { ...prev, preflight } : prev);
      setNotice(preflight.ok ? "运行检查完成" : "运行检查失败");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "运行检查失败"));
    } finally {
      setNativeAgentPreflightRunning(false);
    }
  };

  const buildEnvPatchInput = (): EnvConfigPatchInput => {
    const values: Record<string, EnvConfigPatchValue> = {};
    for (const item of envChangedItems) {
      const action = envSecretActions[item.key];
      if (action === "clear" || action === "regenerate") {
        values[item.key] = { action };
      } else if (item.sensitive && item.masked && !envVisibleSecrets[item.key]) {
        values[item.key] = { masked: true };
      } else {
        values[item.key] = envDraft[item.key];
      }
    }
    return { values };
  };

  const previewEnvChanges = async () => {
    if (!envChangedItems.length) {
      setError("没有可保存的环境配置改动");
      return;
    }
    if (envConflictMessage) {
      setError(envConflictMessage);
      return;
    }
    setEnvSaving(true);
    setError("");
    setNotice("");
    try {
      const preview = await client.previewEnvConfig(buildEnvPatchInput());
      setEnvPreview(preview);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "预览环境配置失败"));
    } finally {
      setEnvSaving(false);
    }
  };

  const saveEnvChanges = async () => {
    if (!envChangedItems.length) {
      setError("没有可保存的环境配置改动");
      return;
    }
    if (envConflictMessage) {
      setError(envConflictMessage);
      return;
    }
    setEnvSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await client.updateEnvConfig(buildEnvPatchInput());
      setEnvSavedImpact(result);
      await loadEnvConfig("环境配置已保存", true);
      setEnvSavedImpact(result);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "保存环境配置失败"));
    } finally {
      setEnvSaving(false);
    }
  };

  const requestEnvRestart = async () => {
    setEnvRestarting(true);
    setError("");
    setNotice("");
    try {
      await client.restartService();
      setNotice("已请求重启服务");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "请求重启服务失败"));
    } finally {
      setEnvRestarting(false);
    }
  };

  const removeAnnouncement = async (id: string) => {
    setAnnouncementDeletingId(id);
    setError("");
    setNotice("");
    try {
      await client.deleteAnnouncement(id);
      await loadAnnouncements("公告已删除", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "删除公告失败"));
    } finally {
      setAnnouncementDeletingId("");
    }
  };

  return (
    <main className="min-h-[100dvh] bg-[var(--bg)]">
      <div className="mx-auto flex min-h-[100dvh] max-w-6xl flex-col p-4">
        <header className="mb-6 flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold text-[var(--text)]">管理中心</h1>
            <p className="text-sm text-[var(--muted)]">用户权限、邀请码和升级入口集中到这里。</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
          >
            <ArrowLeft className="h-4 w-4" />
            返回
          </button>
        </header>

        <div className="mb-4 flex flex-wrap items-center gap-2">
          {visibleTabs.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              onClick={() => setActiveTab(tab)}
              className={activeTab === tab
                ? "rounded-md px-3 py-2 text-sm tcb-selected-accent"
                : "rounded-md border border-[var(--border)] px-3 py-2 text-sm"}
            >
              {tab === "users"
                ? "用户权限"
                : tab === "invites"
                  ? "邀请码"
                  : tab === "updates"
                    ? "升级"
                    : tab === "cli-errors"
                      ? "CLI 错误"
                    : tab === "announcements"
                      ? "公告"
                    : tab === "native-agent"
                      ? "原生 Agent"
                      : tab === "env"
                        ? "环境配置"
                        : "联机聊天"}
            </button>
          ))}
          <button
            type="button"
            onClick={() => void refreshActiveTab("", true)}
            disabled={loading || refreshing}
            className="ml-auto inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            <RefreshCw className="h-4 w-4" />
            {refreshing ? "刷新中..." : "刷新"}
          </button>
        </div>

        {error ? (
          <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {notice}
          </div>
        ) : null}

        {loading ? (
          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-sm text-[var(--muted)]">
            加载中...
          </section>
        ) : null}

        {!loading && activeTab === "users" ? (
          <section aria-labelledby="user-permissions-title" className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 id="user-permissions-title" className="text-base font-semibold text-[var(--text)]">用户权限</h2>
                <p className="text-xs text-[var(--muted)]">共 {users.length} 人，累计已创建 {totalOwnedBots} 个 Bot</p>
              </div>
            </div>
            <div className="mt-3 space-y-3">
              {users.map((user) => (
                <article key={user.accountId} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-[var(--text)]">{user.username}</p>
                        <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--muted)]">
                          {user.role}
                        </span>
                        {user.disabled ? (
                          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                            已停用
                          </span>
                        ) : null}
                      </div>
                      <p className="text-xs text-[var(--muted)]">{user.accountId}</p>
                      <p className="text-xs text-[var(--muted)]">已创建 {user.ownedBotCount}/{user.botCreateLimit} 个 Bot</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void toggleUserDisabled(user)}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                    >
                      {user.disabled ? "启用" : "停用"}
                    </button>
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {ACCOUNT_CAPABILITY_OPTIONS.map((capability) => (
                      <label key={`${user.accountId}-${capability.id}`} className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
                        <input
                          type="checkbox"
                          aria-label={`${user.username} 账号能力 ${capability.label}`}
                          checked={user.capabilities.includes(capability.id)}
                          onChange={(event) => void updateUserCapabilityGrant(user, capability.id, event.target.checked)}
                        />
                        <span>{capability.label}</span>
                      </label>
                    ))}
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {bots.map((bot) => (
                      <label key={`${user.accountId}-${bot.alias}`} className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
                        <input
                          type="checkbox"
                          aria-label={`${user.username} 可操作 Bot ${bot.alias}`}
                          checked={user.allowedBots.includes(bot.alias)}
                          onChange={(event) => void updateUserBotGrant(user, bot.alias, event.target.checked)}
                        />
                        <span>{bot.alias}</span>
                        {user.ownedBots.includes(bot.alias) ? (
                          <span className="text-xs text-[var(--muted)]">创建者</span>
                        ) : null}
                      </label>
                    ))}
                  </div>
                </article>
              ))}
              {users.length === 0 ? <p className="text-sm text-[var(--muted)]">暂无用户</p> : null}
            </div>
          </section>
        ) : null}

        {!loading && activeTab === "invites" ? (
          <div className="space-y-4">
            <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-4">
              <div className="flex flex-wrap items-end gap-3">
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">可用次数</span>
                  <input
                    aria-label="邀请码可用次数"
                    type="number"
                    min={1}
                    value={registerCodeDraftUses}
                    onChange={(event) => setRegisterCodeDraftUses(event.target.value)}
                    className="w-32 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void createRegisterCode()}
                  disabled={registerCodeCreating}
                  className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {registerCodeCreating ? "生成中..." : "生成邀请码"}
                </button>
              </div>

              {createdRegisterCode ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-700">
                  最新邀请码: <span className="font-semibold">{createdRegisterCode.code}</span>
                </div>
              ) : null}
            </section>

            <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-[var(--text)]">邀请码列表</h2>
                <span className="text-xs text-[var(--muted)]">共 {registerCodes.length} 个</span>
              </div>

              {registerCodes.length ? registerCodes.map((item) => (
                <article key={item.codeId} className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1 text-sm text-[var(--muted)]">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-[var(--text)]">{item.codePreview}</p>
                        {item.disabled ? (
                          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
                            已停用
                          </span>
                        ) : null}
                      </div>
                      <p>已用 {item.usedCount} / {item.maxUses}，剩余 {item.remainingUses}</p>
                      <p>创建: {item.createdAt || "未知"} · 创建人: {item.createdBy || "未知"}</p>
                      <p>最近使用: {item.lastUsedAt || "未使用"}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void mutateRegisterCode(item.codeId, { maxUsesDelta: 1 }, "邀请码次数已增加")}
                        disabled={registerCodeActionId === item.codeId}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        +1
                      </button>
                      <button
                        type="button"
                        onClick={() => void mutateRegisterCode(item.codeId, { maxUsesDelta: -1 }, "邀请码次数已减少")}
                        disabled={registerCodeActionId === item.codeId || item.remainingUses <= 0}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        -1
                      </button>
                      <button
                        type="button"
                        onClick={() => void mutateRegisterCode(item.codeId, { disabled: !item.disabled }, item.disabled ? "邀请码已启用" : "邀请码已停用")}
                        disabled={registerCodeActionId === item.codeId}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                      >
                        {item.disabled ? "启用" : "停用"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeRegisterCode(item.codeId)}
                        disabled={registerCodeActionId === item.codeId}
                        className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                      >
                        删除
                      </button>
                    </div>
                  </div>

                  {item.usage.length ? (
                    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)] space-y-1">
                      {item.usage.map((usage, index) => (
                        <p key={`${item.codeId}-${index}`}>{usage.usedAt || "未知时间"} · {usage.usedBy || "未知用户"}</p>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-[var(--muted)]">暂无使用记录</p>
                  )}
                </article>
              )) : (
                <p className="text-sm text-[var(--muted)]">暂无邀请码</p>
              )}
            </section>
          </div>
        ) : null}

        {!loading && activeTab === "lan-chat" ? (
          <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div>
              <h2 className="text-base font-semibold text-[var(--text)]">联机聊天</h2>
              <p className="text-sm text-[var(--muted)]">一台实例作为主机，其它实例填主机地址和房间密钥加入。</p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {([
                ["off", "关闭"],
                ["host", "作为主机"],
                ["join", "加入主机"],
              ] as const).map(([mode, label]) => (
                <label key={mode} className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">
                  <input
                    type="radio"
                    name="lan-chat-mode"
                    checked={(lanChatDraft.mode || lanChatConfig?.mode || "off") === mode}
                    onChange={() => setLanChatDraft((prev) => ({ ...prev, mode }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">房间名</span>
                <input
                  aria-label="房间名"
                  value={lanChatDraft.roomName || ""}
                  onChange={(event) => setLanChatDraft((prev) => ({ ...prev, roomName: event.target.value }))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">本节点名称</span>
                <input
                  aria-label="本节点名称"
                  value={lanChatDraft.instanceName || ""}
                  onChange={(event) => setLanChatDraft((prev) => ({ ...prev, instanceName: event.target.value }))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <label className="space-y-1 sm:col-span-2">
                <span className="text-sm text-[var(--text)]">主机地址</span>
                <input
                  aria-label="主机地址"
                  value={lanChatDraft.hostUrl || ""}
                  onChange={(event) => setLanChatDraft((prev) => ({ ...prev, hostUrl: event.target.value }))}
                  placeholder="http://192.168.1.100:8765"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <label className="space-y-1 sm:col-span-2">
                <span className="text-sm text-[var(--text)]">房间密钥</span>
                <input
                  aria-label="房间密钥"
                  value={lanChatDraft.roomKey || ""}
                  onChange={(event) => setLanChatDraft((prev) => ({ ...prev, roomKey: event.target.value }))}
                  placeholder={lanChatConfig?.roomKeyPreview || "保存主机模式时自动生成"}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(lanChatDraft.lanOnly)}
                  onChange={(event) => setLanChatDraft((prev) => ({ ...prev, lanOnly: event.target.checked }))}
                />
                仅允许局域网节点
              </label>
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(lanChatDraft.autoConnect)}
                  onChange={(event) => setLanChatDraft((prev) => ({ ...prev, autoConnect: event.target.checked }))}
                />
                启动后自动连接
              </label>
            </div>

            <button
              type="button"
              onClick={() => void saveLanChatConfig()}
              disabled={lanChatSaving}
              className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {lanChatSaving ? "保存中..." : "保存联机聊天配置"}
            </button>
          </section>
        ) : null}

        {!loading && activeTab === "native-agent" ? (
          <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">Pi 原生 agent 配置</h2>
                <p className="text-sm text-[var(--muted)]">Pi provider/model 配置。保存后需重启原生 agent。</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void runNativeAgentPreflight()}
                  disabled={nativeAgentPreflightRunning}
                  className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  <RefreshCw className="h-4 w-4" />
                  {nativeAgentPreflightRunning ? "检查中..." : "运行检查"}
                </button>
                <button
                  type="button"
                  onClick={() => void saveNativeAgentConfig()}
                  disabled={nativeAgentSaving}
                  className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {nativeAgentSaving ? "保存中..." : "保存配置"}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 text-xs text-[var(--muted)] lg:grid-cols-2">
              <p className="break-all rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                Pi settings: {nativeAgentConfig?.configPath || "-"}
              </p>
              <p className="break-all rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                Pi models: {nativeAgentConfig?.modelsPath || "-"}
              </p>
              <p className="break-all rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                Workspace history: {nativeAgentConfig?.workspaceHistoryEnabled ? "启用" : "关闭"}
              </p>
            </div>

            <div className={`rounded-lg border px-3 py-3 text-sm ${nativePreflightStatusClass(nativeAgentConfig?.preflight)}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">运行检查: {nativePreflightStatus(nativeAgentConfig?.preflight)}</p>
                <p className="text-xs">{nativeAgentConfig?.preflight?.message || "保存配置后运行检查"}</p>
              </div>
              {nativeAgentConfig?.preflight?.checks.length ? (
                <div className="mt-3 grid gap-2 lg:grid-cols-2">
                  {nativeAgentConfig.preflight.checks.map((check) => (
                    <div key={check.key} className={`rounded-lg border px-3 py-2 ${nativePreflightCheckClass(check)}`}>
                      <div className="flex items-start justify-between gap-2">
                        <p className="font-medium text-[var(--text)]">{check.key}</p>
                        <span className="text-xs">{check.ok ? "通过" : check.severity === "warning" ? "警告" : "失败"}</span>
                      </div>
                      <p className="mt-1 text-xs">{check.message}</p>
                      {!check.ok && check.fix ? <p className="mt-1 text-xs">修复: {check.fix}</p> : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            <label className="block space-y-2">
              <span className="text-sm font-medium text-[var(--text)]">全局提示词</span>
              <textarea
                aria-label="原生 Agent 全局提示词"
                value={nativeAgentSystemPromptDraft}
                onChange={(event) => setNativeAgentSystemPromptDraft(event.target.value)}
                rows={6}
                className="min-h-32 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                placeholder="启动 Pi 时通过 --system-prompt 注入"
              />
              <span className="block text-xs text-[var(--muted)]">仅新启动的 Pi runtime 生效。</span>
            </label>

            <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
              <label className="space-y-2">
                <span className="text-sm font-medium text-[var(--text)]">配置 JSON</span>
                <textarea
                  aria-label="原生 Agent 配置 JSON"
                  value={nativeAgentDraft}
                  onChange={(event) => setNativeAgentDraft(event.target.value)}
                  spellCheck={false}
                  rows={22}
                  className="min-h-[28rem] w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs text-[var(--text)]"
                />
              </label>

              <div className="space-y-2">
                <h3 className="text-sm font-medium text-[var(--text)]">模型预览</h3>
                {(nativeAgentConfig?.models || []).length ? (
                  <div className="space-y-2">
                    {nativeAgentConfig?.models.map((model) => (
                      <div key={model.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">
                        <p className="font-medium text-[var(--text)]">{model.provider} / {model.name}</p>
                        <p className="text-xs text-[var(--muted)]">
                          context {model.contextWindow?.toLocaleString() || "未配置"}
                          {model.outputLimit ? ` · output ${model.outputLimit.toLocaleString()}` : ""}
                          {model.reasoningEfforts?.length ? ` · reasoning ${model.reasoningEfforts.join(" / ")}` : ""}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--muted)]">
                    暂无模型
                  </p>
                )}
              </div>
            </div>
          </section>
        ) : null}

        {!loading && activeTab === "env" && canManageEnvConfig ? (
          <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">环境配置</h2>
                <p className="text-sm text-[var(--muted)]">保存写入 .env；运行时配置多需重启服务，VITE_* 需重新 build。</p>
                <p className="mt-1 break-all text-xs text-[var(--muted)]">文件: {envConfig?.envPath || ".env"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void previewEnvChanges()}
                  disabled={envSaving || envChangedItems.length === 0 || Boolean(envConflictMessage)}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  预览 diff
                </button>
                <button
                  type="button"
                  onClick={() => void saveEnvChanges()}
                  disabled={envSaving || envChangedItems.length === 0 || Boolean(envConflictMessage)}
                  className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {envSaving ? "保存中..." : "保存环境配置"}
                </button>
              </div>
            </div>

            {envSavedImpact && (envSavedImpact.restartRequiredKeys.length || envSavedImpact.rebuildRequiredKeys.length) ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                <span>
                  {envSavedImpact.restartRequiredKeys.length ? `需重启: ${envSavedImpact.restartRequiredKeys.join(", ")}` : ""}
                  {envSavedImpact.restartRequiredKeys.length && envSavedImpact.rebuildRequiredKeys.length ? "；" : ""}
                  {envSavedImpact.rebuildRequiredKeys.length ? `需重新 build: ${envSavedImpact.rebuildRequiredKeys.join(", ")}` : ""}
                </span>
                {envSavedImpact.restartRequiredKeys.length ? (
                  <button
                    type="button"
                    onClick={() => void requestEnvRestart()}
                    disabled={envRestarting}
                    className="rounded-lg border border-transparent bg-amber-600 px-3 py-2 text-sm text-white hover:bg-amber-700 disabled:opacity-60"
                  >
                    {envRestarting ? "请求中..." : "重启服务"}
                  </button>
                ) : null}
              </div>
            ) : null}

            {envConflictMessage ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-700">
                {envConflictMessage}
              </div>
            ) : null}

            {envPreview ? (
              <div role="dialog" aria-label="环境配置 diff 确认" className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-[var(--text)]">保存前确认</p>
                    <p className="text-xs text-[var(--muted)]">
                      变更 {envPreview.changedKeys.length} 项
                      {envPreview.restartRequiredKeys.length ? ` · 重启 ${envPreview.restartRequiredKeys.length} 项` : ""}
                      {envPreview.rebuildRequiredKeys.length ? ` · 重建 ${envPreview.rebuildRequiredKeys.length} 项` : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setEnvPreview(null)}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
                  >
                    取消
                  </button>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {envChangedItems.map((item) => {
                    const action = envSecretActions[item.key];
                    const afterValue = action === "clear"
                      ? ""
                      : action === "regenerate"
                        ? "重新生成"
                        : formatEnvValue(envDraft[item.key], item.sensitive && !envVisibleSecrets[item.key]);
                    return (
                      <div key={item.key} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs">
                        <p className="font-medium text-[var(--text)]">{item.key}</p>
                        <p className="break-all text-[var(--muted)]">- {formatEnvValue(item.value, item.sensitive)}</p>
                        <p className="break-all text-[var(--text)]">+ {afterValue || "空值"}</p>
                      </div>
                    );
                  })}
                </div>
                <button
                  type="button"
                  onClick={() => void saveEnvChanges()}
                  disabled={envSaving || Boolean(envConflictMessage)}
                  className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  确认保存
                </button>
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-[180px_1fr]">
              <nav className="flex gap-2 overflow-x-auto lg:flex-col lg:overflow-visible">
                {envCategories.map((category) => (
                  <button
                    key={category}
                    type="button"
                    onClick={() => setActiveEnvCategory(category)}
                    className={(activeEnvCategory || envCategories[0]) === category
                      ? "whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm tcb-selected-accent"
                      : "whitespace-nowrap rounded-lg border border-[var(--border)] px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"}
                  >
                    {ENV_CATEGORY_LABELS[category] || category}
                  </button>
                ))}
              </nav>

              <div className="space-y-3">
                {activeEnvItems.map((item) => {
                  const draftValue = envDraft[item.key] ?? item.value;
                  const secretAction = envSecretActions[item.key];
                  const secretMasked = item.sensitive && item.masked && !envVisibleSecrets[item.key] && secretAction !== "edit";
                  return (
                    <article key={item.key} className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-medium text-[var(--text)]">{item.label}</h3>
                            <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--muted)]">{item.key}</span>
                            {item.restartRequired ? <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">重启生效</span> : null}
                            {item.rebuildRequired ? <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs text-sky-700">需 build</span> : null}
                          </div>
                          <p className="text-sm text-[var(--muted)]">{item.description}</p>
                          <p className="text-xs text-[var(--muted)]">默认: {formatEnvValue(item.defaultValue)} · 来源: {item.source || "未知"}</p>
                        </div>
                        {item.sensitive ? (
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setEnvVisibleSecrets((prev) => ({ ...prev, [item.key]: !prev[item.key] }));
                                setEnvSecretActions((prev) => ({ ...prev, [item.key]: "edit" }));
                              }}
                              className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--surface-strong)]"
                            >
                              {envVisibleSecrets[item.key] ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                              {envVisibleSecrets[item.key] ? "遮蔽" : "显示"}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setEnvSecretActions((prev) => ({ ...prev, [item.key]: "clear" }));
                                setEnvDraft((prev) => ({ ...prev, [item.key]: "" }));
                                setEnvPreview(null);
                              }}
                              className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              清空
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setEnvSecretActions((prev) => ({ ...prev, [item.key]: "regenerate" }));
                                setEnvDraft((prev) => ({ ...prev, [item.key]: "重新生成" }));
                                setEnvPreview(null);
                              }}
                              className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--surface-strong)]"
                            >
                              <RotateCcw className="h-3.5 w-3.5" />
                              重新生成
                            </button>
                          </div>
                        ) : null}
                      </div>

                      {item.type === "boolean" ? (
                        <label className="inline-flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={Boolean(draftValue)}
                            onChange={(event) => {
                              setEnvDraft((prev) => ({ ...prev, [item.key]: event.target.checked }));
                              setEnvPreview(null);
                            }}
                          />
                          启用
                        </label>
                      ) : item.type === "select" && item.options?.length ? (
                        <select
                          aria-label={item.label}
                          value={String(draftValue || "")}
                          onChange={(event) => {
                            setEnvDraft((prev) => ({ ...prev, [item.key]: event.target.value }));
                            setEnvPreview(null);
                          }}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                        >
                          {item.options.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          aria-label={item.label}
                          type={item.type === "number" ? "number" : item.type === "password" && secretMasked ? "password" : "text"}
                          value={secretMasked ? "********" : formatEnvValue(draftValue)}
                          disabled={secretMasked || secretAction === "regenerate"}
                          onChange={(event) => {
                            setEnvDraft((prev) => ({
                              ...prev,
                              [item.key]: normalizeEnvDraftValue(item, event.target.value),
                            }));
                            if (item.sensitive) {
                              setEnvSecretActions((prev) => ({ ...prev, [item.key]: "edit" }));
                            }
                            setEnvPreview(null);
                          }}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-70"
                        />
                      )}
                      {item.key === "WEB_API_TOKEN" && envSecretActions[item.key] === "clear" ? (
                        <p className="text-xs text-red-700">保存后将禁用口令登录。</p>
                      ) : null}
                    </article>
                  );
                })}
                {activeEnvItems.length === 0 ? (
                  <p className="text-sm text-[var(--muted)]">暂无环境配置项</p>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}

        {!loading && activeTab === "announcements" ? (
          <div className="space-y-4">
            <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">发布公告</h2>
                <p className="text-sm text-[var(--muted)]">发布后系统自动生成编号和时间，用户下次登录会自动看到。</p>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">发布者</span>
                  <input
                    aria-label="公告发布者"
                    value={announcementDraft.publisher}
                    onChange={(event) => updateAnnouncementDraft("publisher", event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">标题</span>
                  <input
                    aria-label="公告标题"
                    value={announcementDraft.title}
                    onChange={(event) => updateAnnouncementDraft("title", event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">分类</span>
                  <select
                    aria-label="公告分类"
                    value={announcementDraft.category}
                    onChange={(event) => updateAnnouncementDraft("category", event.target.value as AnnouncementItem["category"])}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  >
                    {["release", "feature", "fix", "maintenance", "notice"].map((item) => (
                      <option key={item} value={item}>{item}</option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">级别</span>
                  <select
                    aria-label="公告级别"
                    value={announcementDraft.severity}
                    onChange={(event) => updateAnnouncementDraft("severity", event.target.value as AnnouncementItem["severity"])}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  >
                    {["info", "success", "warning", "danger"].map((item) => (
                      <option key={item} value={item}>{item}</option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="space-y-1">
                <span className="text-sm text-[var(--text)]">摘要</span>
                <textarea
                  aria-label="公告摘要"
                  value={announcementDraft.summary}
                  onChange={(event) => updateAnnouncementDraft("summary", event.target.value)}
                  rows={2}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>

              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                {announcementDraft.sections.map((section, index) => (
                  <div key={index} className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                    <input
                      aria-label={`公告段落 ${index + 1} 标题`}
                      value={section.label}
                      onChange={(event) => updateAnnouncementSection(index, "label", event.target.value)}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                    />
                    <textarea
                      aria-label={`公告段落 ${index + 1} 条目`}
                      value={section.items.join("\n")}
                      onChange={(event) => updateAnnouncementSection(index, "items", event.target.value)}
                      rows={4}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                    />
                  </div>
                ))}
              </div>

              <button
                type="button"
                onClick={() => void saveAnnouncement()}
                disabled={announcementSaving}
                className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                {announcementSaving ? "发布中..." : "发布公告"}
              </button>
            </section>

            <section className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-[var(--text)]">公告列表</h2>
                <span className="text-xs text-[var(--muted)]">共 {announcements.length} 条</span>
              </div>
              {announcements.length ? announcements.map((item) => (
                <article key={item.id} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <p className="font-medium text-[var(--text)]">{item.title}</p>
                      <p className="break-all text-xs text-[var(--muted)]">{item.id}</p>
                      <p className="text-sm text-[var(--muted)]">{item.summary}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void removeAnnouncement(item.id)}
                      disabled={announcementDeletingId === item.id}
                      className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                    >
                      {announcementDeletingId === item.id ? "删除中..." : "删除"}
                    </button>
                  </div>
                </article>
              )) : (
                <p className="text-sm text-[var(--muted)]">暂无公告</p>
              )}
            </section>
          </div>
        ) : null}

        {!loading && activeTab === "updates" ? (
          <section aria-labelledby="update-center-title" className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div>
              <h2 id="update-center-title" className="text-base font-semibold text-[var(--text)]">升级</h2>
              <p className="text-sm text-[var(--muted)]">可联网下载，也可选离线包设为待应用。</p>
            </div>

            <div className="grid grid-cols-1 gap-3 text-sm text-[var(--muted)] sm:grid-cols-2">
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">当前版本: {updateStatus?.currentVersion || "未知"}</p>
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">当前包: {formatPackageKind(updateStatus?.currentPackageKind)}</p>
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">可用版本: {updateStatus?.latestVersion || "暂无"}</p>
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">待应用: {updateStatus?.pendingUpdateVersion || "无"}</p>
            </div>

            <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-3 text-sm">
              <span>自动下载更新</span>
              <input
                type="checkbox"
                checked={Boolean(updateStatus?.updateEnabled)}
                disabled={updateAction === "toggle"}
                onChange={(event) => void saveUpdateToggle(event.target.checked)}
              />
            </label>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void checkOnlineUpdate()}
                disabled={updateAction !== ""}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                {updateAction === "check" ? "检查中..." : "检查联网更新"}
              </button>
              <button
                type="button"
                onClick={() => void downloadOnlineUpdate()}
                disabled={updateAction !== ""}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                {updateAction === "download" ? "下载中..." : "联网下载"}
              </button>
            </div>

            <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <p className="text-sm text-[var(--muted)]">离线包目录: {offlinePackages?.artifactsDir || ".release-local/artifacts"}</p>
              <div className="flex flex-wrap gap-2">
                {offlinePackages?.items.map((item) => (
                  <button
                    key={item.path}
                    type="button"
                    disabled={updateAction !== "" || !item.valid}
                    onClick={() => void prepareOffline(item.path, item.version)}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                    title={item.valid ? item.path : item.error || item.path}
                  >
                    {item.name} · {formatPackageKind(item.packageKind)}
                  </button>
                ))}
              </div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  aria-label="本地离线包路径"
                  value={manualPackagePath}
                  onChange={(event) => setManualPackagePath(event.target.value)}
                  placeholder="本地离线包路径"
                  className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
                />
                <button
                  type="button"
                  onClick={() => void prepareOffline(manualPackagePath)}
                  disabled={updateAction !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  使用本地包升级
                </button>
              </div>
            </div>

            <div role="log" className="h-56 overflow-y-auto rounded-lg bg-slate-950 p-3 font-mono text-xs text-slate-100 whitespace-pre-wrap break-all">
              {updateLogLines.length ? updateLogLines.join("\n") : "暂无升级输出"}
            </div>
          </section>
        ) : null}

        {!loading && activeTab === "cli-errors" ? (
          <section aria-labelledby="cli-error-stats-title" className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 id="cli-error-stats-title" className="text-base font-semibold text-[var(--text)]">CLI 错误统计</h2>
                <p className="text-sm text-[var(--muted)]">最近错误、类别和高频文本。</p>
              </div>
              <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                时间范围
                <select
                  value={cliErrorHours}
                  onChange={(event) => {
                    setCliErrorHours(Number(event.target.value));
                    setLoadedTabs((prev) => ({ ...prev, "cli-errors": false }));
                  }}
                  className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                >
                  <option value={24}>24 小时</option>
                  <option value={72}>72 小时</option>
                  <option value={168}>7 天</option>
                </select>
              </label>
            </div>

            <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                总错误: <span className="font-semibold text-[var(--text)]">{cliErrorStats?.summary.total || 0}</span>
              </p>
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                CLI 最高: <span className="font-semibold text-[var(--text)]">{topEntryLabel(cliErrorStats?.summary.byCliType || {})}</span>
              </p>
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                Bot 最高: <span className="font-semibold text-[var(--text)]">{topEntryLabel(cliErrorStats?.summary.byBot || {})}</span>
              </p>
              <p className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                类别最高: <span className="font-semibold text-[var(--text)]">{topEntryLabel(cliErrorStats?.summary.byCategory || {})}</span>
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <h3 className="text-sm font-semibold text-[var(--text)]">按类别</h3>
                <div className="mt-3 space-y-2 text-sm">
                  {Object.entries(cliErrorStats?.summary.byCategory || {}).map(([category, count]) => (
                    <div key={category} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] px-3 py-2">
                      <span className="text-[var(--text)]">{category}</span>
                      <span className="text-[var(--muted)]">{count}</span>
                    </div>
                  ))}
                  {!Object.keys(cliErrorStats?.summary.byCategory || {}).length ? (
                    <p className="text-[var(--muted)]">暂无错误</p>
                  ) : null}
                </div>
              </div>

              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
                <h3 className="text-sm font-semibold text-[var(--text)]">高频错误</h3>
                <div className="mt-3 space-y-2 text-sm">
                  {(cliErrorStats?.topErrors || []).map((item) => (
                    <div key={`${item.category}-${item.message}`} className="rounded-lg border border-[var(--border)] px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[var(--muted)]">{item.category}</span>
                        <span className="text-[var(--text)]">{item.count} 次</span>
                      </div>
                      <p className="mt-1 break-all text-[var(--text)]">{item.message}</p>
                    </div>
                  ))}
                  {!cliErrorStats?.topErrors.length ? <p className="text-[var(--muted)]">暂无高频错误</p> : null}
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg)]">
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <h3 className="text-sm font-semibold text-[var(--text)]">最近错误</h3>
                <span className="ml-auto text-xs text-[var(--muted)]">最近: {formatShortTime(cliErrorStats?.summary.latestAt || "")}</span>
              </div>
              <div className="max-h-[420px] overflow-auto">
                <table className="min-w-full text-left text-sm">
                  <thead className="sticky top-0 bg-[var(--surface)] text-xs text-[var(--muted)]">
                    <tr>
                      <th className="px-3 py-2 font-medium">时间</th>
                      <th className="px-3 py-2 font-medium">Bot</th>
                      <th className="px-3 py-2 font-medium">CLI</th>
                      <th className="px-3 py-2 font-medium">类别</th>
                      <th className="px-3 py-2 font-medium">错误</th>
                      <th className="px-3 py-2 font-medium">ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(cliErrorStats?.items || []).map((item) => (
                      <tr key={item.turnId} className="border-t border-[var(--border)] align-top">
                        <td className="whitespace-nowrap px-3 py-2 text-[var(--muted)]">{formatShortTime(item.startedAt)}</td>
                        <td className="px-3 py-2 text-[var(--text)]">{item.botAlias}</td>
                        <td className="px-3 py-2 text-[var(--text)]">{item.cliType}</td>
                        <td className="px-3 py-2 text-[var(--text)]">{item.category}</td>
                        <td className="max-w-md break-all px-3 py-2 text-[var(--text)]">{shortErrorText(item.errorMessage || item.errorCode)}</td>
                        <td className="break-all px-3 py-2 font-mono text-xs text-[var(--muted)]">
                          {item.conversationId}<br />{item.turnId}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!cliErrorStats?.items.length ? (
                  <p className="px-3 py-4 text-sm text-[var(--muted)]">暂无错误记录</p>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
