import { AppUpdatePanel } from "../components/admin/AppUpdatePanel";
import { PublicAccessPanel } from "../components/admin/PublicAccessPanel";
import {
  AnnouncementAdminPanel,
  announcementDraftToInput,
  createAnnouncementDraft,
  type AnnouncementDraft,
} from "../components/admin/AnnouncementAdminPanel";
import { cliTypeLabel } from "../utils/cliType";
import { ChatTranslationSettingsPanel } from "../components/ChatTranslationSettingsPanel";
import { ChatConfirmDialog } from "../components/ChatConfirmDialog";
import { GlobalPromptPresetsPanel } from "../components/GlobalPromptPresetsPanel";
import { GlobalUiSettingsPanel } from "../components/GlobalUiSettingsPanel";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, Bell, Eye, EyeOff, RefreshCw, RotateCcw, Save, Trash2 } from "lucide-react";
import { AiInlineCompletionSettingsPanel } from "../components/AiInlineCompletionSettingsPanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  AdminUser,
  AnnouncementItem,
  BotSummary,
  Capability,
  CliErrorStatsResult,
  EnvConfigItem,
  EnvConfigPatchInput,
  EnvConfigPatchResult,
  EnvConfigPatchValue,
  EnvConfigSnapshot,
  EnvConfigValue,
  LanChatConfig,
  LanChatConfigInput,
  RegisterCodeCreateResult,
  RegisterCodeItem,
  NotificationSettingsStatus,
  StorageMigrationPreview,
  StorageMigrationSnapshot,
  StorageMigrationState,
} from "../services/types";
import type {
  UiThemeName,
} from "../theme";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import "../styles/admin-center.css";
import type { UsagePanelProvider } from "../components/admin/UsagePanel";

const UsagePanel = lazy(() => import("../components/admin/UsagePanel").then((module) => ({
  default: module.UsagePanel,
})));

type Props = {
  client?: WebBotClient;
  onClose: () => void;
  initialBots?: BotSummary[];
  onBotsChange?: (bots: BotSummary[]) => void;
  canManageRegisterCodes?: boolean;
  canManageEnvConfig?: boolean;
  currentBotAlias?: string | null;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void | Promise<void>;
  chatEnterToSend?: boolean;
  onChatEnterToSendChange?: (value: boolean) => void;
};

type AdminCenterTab =
  | "global"
  | "users"
  | "invites"
  | "cli-errors"
  | "usage"
  | "network-updates"
  | "announcements"
  | "notifications"
  | "chat-translation"
  | "inline-completion"
  | "lan-chat"
  |  "storage"
  | "env";

const ADMIN_TAB_META: Record<AdminCenterTab, { label: string; description: string }> = {
  global: { label: "全局配置", description: "界面主题、输入习惯与全局提示词预设" },
  env: { label: "环境配置", description: "查看和修改服务运行所用的环境变量" },
  "network-updates": { label: "网络与升级", description: "公网访问状态，以及程序更新的检查、准备与应用" },
  storage: { label: "数据迁移", description: "将运行数据迁移到新的存储目录" },
  users: { label: "用户", description: "账号角色、能力授权与可操作的 Bot" },
  invites: { label: "邀请", description: "生成和管理注册邀请码" },
  "inline-completion": { label: "补全", description: "编辑器 AI 行内补全服务" },
  "chat-translation": { label: "翻译", description: "聊天消息翻译服务" },
  usage: { label: "Usage", description: "各 CLI 的额度与用量趋势" },
  announcements: { label: "公告", description: "向所有用户发布更新与提醒" },
  notifications: { label: "通知", description: "任务完成推送的状态与测试" },
  "lan-chat": { label: "联机聊天", description: "局域网内多实例联机聊天" },
  "cli-errors": { label: "错误", description: "CLI 执行错误的统计与最近记录" },
};

const ADMIN_TAB_GROUPS: Array<{ label: string; tabs: AdminCenterTab[] }> = [
  { label: "系统", tabs: ["global", "env", "network-updates", "storage"] },
  { label: "成员", tabs: ["users", "invites"] },
  { label: "智能与服务", tabs: [ "inline-completion", "chat-translation", "usage"] },
  { label: "消息", tabs: ["announcements", "notifications", "lan-chat"] },
  { label: "诊断", tabs: ["cli-errors"] },
];

const ENV_CATEGORY_LABELS: Record<string, string> = {
  basic: "基础",
  telegram: "Telegram",
  web: "Web",
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
  "telegram",
  "web",
  "tunnel",
  "updates",
  "update",
  "notifications",
  "notification",
  "diagnostics",
  "advanced",
  "frontend",
];

const ACCOUNT_CAPABILITY_OPTIONS: Array<{ id: Capability; label: string }> = [
  { id: "chat_send", label: "聊天" },
  { id: "read_file_content", label: "读文件" },
  { id: "inline_completion", label: "AI 补全" },
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

function formatEnvValue(value: EnvConfigValue | undefined, masked = false) {
  if (masked) return "********";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return value || "";
}

function topEntryLabel(values: Record<string, number>, label = (key: string) => key) {
  const [key, count] = Object.entries(values).sort((left, right) => right[1] - left[1])[0] || [];
  return key ? `${label(key)} (${count})` : "无";
}

function formatShortTime(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatStorageBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatStorageDuration(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) return "-";
  const seconds = Math.round(value);
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours} 小时 ${remainingMinutes} 分钟` : `${hours} 小时`;
}

function nextRoleIsBlocked(user: AdminUser, designatedAdmin?: AdminUser) {
  return user.role !== "admin" && Boolean(designatedAdmin && designatedAdmin.accountId !== user.accountId);
}

const STORAGE_MIGRATION_ACTIVE_STATES: StorageMigrationState[] = [
  "preparing",
  "stopping",
  "copying",
  "rewriting",
  "verifying",
];

function storageMigrationStateText(state: StorageMigrationState) {
  return {
    preparing: "正在扫描源目录",
    stopping: "正在停止智能体",
    copying: "正在复制文件",
    rewriting: "正在重写路径",
    verifying: "正在验证新目录",
    awaiting_restart: "等待重启",
    cleanup_pending: "等待清理原始数据",
    completed: "已完成",
    failed: "失败",
  }[state];
}

function isStorageMigrationActive(snapshot: StorageMigrationSnapshot | null) {
  return Boolean(
    snapshot
    && STORAGE_MIGRATION_ACTIVE_STATES.includes(snapshot.state)
    && (snapshot.maintenance || Boolean(snapshot.jobId && !snapshot.planId)),
  );
}

function isStoragePreviewReady(snapshot: StorageMigrationSnapshot | null): snapshot is StorageMigrationPreview {
  return Boolean(
    snapshot
    && snapshot.planId
    && snapshot.targetRoot
    && !snapshot.maintenance
    && snapshot.canMigrate !== false
    && (snapshot.previewReady || snapshot.state === "preparing" || snapshot.state === "verifying"),
  );
}

function storageProgress(snapshot: StorageMigrationSnapshot | null) {
  if (!snapshot) return 0;
  if (snapshot.progress !== undefined && Number.isFinite(snapshot.progress)) {
    return Math.min(1, Math.max(0, snapshot.progress > 1 ? snapshot.progress / 100 : snapshot.progress));
  }
  if (snapshot.totalBytes > 0 && snapshot.completedBytes !== undefined) {
    return Math.min(1, Math.max(0, snapshot.completedBytes / snapshot.totalBytes));
  }
  if (snapshot.totalFiles && snapshot.completedFiles !== undefined) {
    return Math.min(1, Math.max(0, snapshot.completedFiles / snapshot.totalFiles));
  }
  return 0;
}

function mergeStorageMigrationSnapshot(
  previous: StorageMigrationSnapshot | null,
  next: StorageMigrationSnapshot,
): StorageMigrationSnapshot {
  if (!previous) return next;
  return {
    ...previous,
    ...next,
    currentRoot: next.currentRoot || previous.currentRoot,
    sources: next.sources.length ? next.sources : previous.sources,
    totalBytes: next.totalBytes || previous.totalBytes,
    targetRoot: next.targetRoot || previous.targetRoot,
  };
}

function shortErrorText(value: string) {
  const text = (value || "").trim();
  if (!text) return "-";
  return text.length > 120 ? `${text.slice(0, 117).trim()}...` : text;
}

function pushPlusStatusText(status: NotificationSettingsStatus | null) {
  if (!status) return "后端未提供状态";
  if (!status.pushPlusEnabled) return "未启用";
  return status.pushPlusConfigured ? "已配置" : "未配置 token";
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
  if (item.type === "json") return String(value);
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
  currentBotAlias,
  themeName,
  onThemeChange,
  chatEnterToSend,
  onChatEnterToSendChange,
}: Props) {
  const [activeTab, setActiveTab] = useState<AdminCenterTab>("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [bots, setBots] = useState<BotSummary[]>(initialBots);
  const [registerCodes, setRegisterCodes] = useState<RegisterCodeItem[]>([]);
  const [networkUpdatesRefreshKey, setNetworkUpdatesRefreshKey] = useState(0);
  const [cliErrorStats, setCliErrorStats] = useState<CliErrorStatsResult | null>(null);
  const [cliErrorHours, setCliErrorHours] = useState(24);
  const [usagePanelKey, setUsagePanelKey] = useState(0);
  const [usageProvider, setUsageProvider] = useState<UsagePanelProvider>("codex");
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [announcementDraft, setAnnouncementDraft] = useState<AnnouncementDraft>(() => createAnnouncementDraft());
  const [announcementSaving, setAnnouncementSaving] = useState(false);
  const [announcementDeletingId, setAnnouncementDeletingId] = useState("");
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettingsStatus | null>(null);
  const [chatTranslationPanelKey, setChatTranslationPanelKey] = useState(0);
  const [inlineCompletionPanelKey, setInlineCompletionPanelKey] = useState(0);
  const [testingPushPlus, setTestingPushPlus] = useState(false);
  const [showPushPlusGuide, setShowPushPlusGuide] = useState(false);
  const [lanChatConfig, setLanChatConfig] = useState<LanChatConfig | null>(null);
  const [lanChatDraft, setLanChatDraft] = useState<LanChatConfigInput>({});
  const [lanChatSaving, setLanChatSaving] = useState(false);
  const [storageSnapshot, setStorageSnapshot] = useState<StorageMigrationSnapshot | null>(null);
  const [storagePreview, setStoragePreview] = useState<StorageMigrationPreview | null>(null);
  const [storageTargetRoot, setStorageTargetRoot] = useState("");
  const [storageAction, setStorageAction] = useState<"" | "preview" | "migrate" | "retry">("");
  const [storageConfirmOpen, setStorageConfirmOpen] = useState(false);
  const [envConfig, setEnvConfig] = useState<EnvConfigSnapshot | null>(null);
  const [envDraft, setEnvDraft] = useState<Record<string, EnvConfigValue>>({});
  const [envVisibleSecrets, setEnvVisibleSecrets] = useState<Record<string, boolean>>({});
  const [envSecretActions, setEnvSecretActions] = useState<Record<string, "clear" | "regenerate" | "edit">>({});
  const [activeEnvCategory, setActiveEnvCategory] = useState("");
  const [envPreview, setEnvPreview] = useState<EnvConfigPatchResult | null>(null);
  const [envSaving, setEnvSaving] = useState(false);
  const [envReloading, setEnvReloading] = useState(false);
  const [envSystemReloading, setEnvSystemReloading] = useState(false);
  const [serviceRestarting, setServiceRestarting] = useState(false);
  const [restartConfirmTarget, setRestartConfirmTarget] = useState<"service" | null>(null);
  const [loadedTabs, setLoadedTabs] = useState<Record<AdminCenterTab, boolean>>({
    users: false,
    invites: false,
    "cli-errors": false,
    usage: false,
    "network-updates": false,
    announcements: false,
    notifications: false,
    "inline-completion": false,
    "chat-translation": false,
    "lan-chat": false,
    storage: false,
    env: false,
    global: false,
  });
  const [registerCodeDraftUses, setRegisterCodeDraftUses] = useState("1");
  const [createdRegisterCode, setCreatedRegisterCode] = useState<RegisterCodeCreateResult | null>(null);
  const [registerCodeCreating, setRegisterCodeCreating] = useState(false);
  const [registerCodeActionId, setRegisterCodeActionId] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const totalOwnedBots = useMemo(() => users.reduce((sum, user) => sum + user.ownedBotCount, 0), [users]);
  const designatedAdmin = useMemo(() => users.find((user) => user.role === "admin"), [users]);
  const visibleTabs = useMemo<AdminCenterTab[]>(
    () => [
      ...(canManageEnvConfig ? (["global"] as AdminCenterTab[]) : []),
      "users",
      ...(canManageRegisterCodes ? (["invites"] as AdminCenterTab[]) : []),
      "cli-errors",
      "usage",
      "network-updates",
      "announcements",
      "notifications",
      "inline-completion",
      "chat-translation",
      "lan-chat",
      "storage",
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

  async function loadNotificationSettings(nextNotice = "", refresh = false) {
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
      const settings = client.getNotificationSettings
        ? await client.getNotificationSettings()
        : null;
      setNotificationSettings(settings);
      setLoadedTabs((prev) => ({ ...prev, notifications: true }));
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载通知配置失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadInlineCompletionSettings(nextNotice = "", refresh = false) {
    if (refresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError("");
    if (!nextNotice) {
      setNotice("");
    }

    setInlineCompletionPanelKey((prev) => prev + 1);
    setLoadedTabs((prev) => ({ ...prev, "inline-completion": true }));

    if (nextNotice) {
      setNotice(nextNotice);
    }
    setLoading(false);
    setRefreshing(false);
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

  async function loadStorageMigration(nextNotice = "", refresh = false) {
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
      const snapshot = await client.getStorageMigrationSnapshot();
      setStorageSnapshot(snapshot);
      setLoadedTabs((prev) => ({ ...prev, storage: true }));
      if (snapshot.targetRoot) {
        setStorageTargetRoot(snapshot.targetRoot);
      }
      if (
        isStoragePreviewReady(snapshot)
      ) {
        setStoragePreview({ ...snapshot, planId: snapshot.planId, targetRoot: snapshot.targetRoot });
      }
      if (nextNotice) {
        setNotice(nextNotice);
      }
    } catch (nextError) {
      setError(getErrorMessage(nextError, "加载存储迁移状态失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function refreshActiveTab(nextNotice = "", refresh = false) {
    if (activeTab === "global") {
      setLoadedTabs((prev) => ({ ...prev, global: true }));
      setLoading(false);
    } else if (activeTab === "users") {
      await loadUsers(nextNotice, refresh);
    } else if (activeTab === "invites" && canManageRegisterCodes) {
      await loadInvites(nextNotice, refresh);
    } else if (activeTab === "cli-errors") {
      await loadCliErrorStats(nextNotice, refresh);
    } else if (activeTab === "usage") {
      setLoadedTabs((prev) => ({ ...prev, usage: true }));
      if (refresh) {
        setUsagePanelKey((current) => current + 1);
      }
    } else if (activeTab === "network-updates") {
      // Both panels load and poll on their own; a manual refresh re-reads them together.
      setLoadedTabs((prev) => ({ ...prev, "network-updates": true }));
      setLoading(false);
      if (refresh) setNetworkUpdatesRefreshKey((previous) => previous + 1);
    } else if (activeTab === "notifications") {
      await loadNotificationSettings(nextNotice, refresh);
    } else if (activeTab === "chat-translation") {
      setLoadedTabs((prev) => ({ ...prev, "chat-translation": true }));
      setChatTranslationPanelKey((prev) => prev + 1);
      setLoading(false);
    } else if (activeTab === "inline-completion") {
      await loadInlineCompletionSettings(nextNotice, refresh);
    } else if (activeTab === "lan-chat") {
      await loadLanChat(nextNotice, refresh);
    } else if (activeTab === "storage") {
      await loadStorageMigration(nextNotice, refresh);
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

  useEffect(() => {
    if (activeTab !== "storage" || !isStorageMigrationActive(storageSnapshot)) {
      return undefined;
    }
    let active = true;
    const timer = window.setInterval(() => {
      void client.getStorageMigrationSnapshot().then((snapshot) => {
        if (!active) return;
        setStorageSnapshot(snapshot);
        if (isStoragePreviewReady(snapshot)) {
          setStoragePreview((previous) => previous
            ? {
              ...previous,
              ...snapshot,
              planId: snapshot.planId,
              targetRoot: snapshot.targetRoot || previous.targetRoot,
            }
            : { ...snapshot, planId: snapshot.planId, targetRoot: snapshot.targetRoot });
          if (storagePreview?.jobId && !storagePreview.planId) {
            setStorageAction("");
            setNotice("迁移预览已生成，请确认影响范围");
          }
        } else if (storagePreview?.jobId && !storagePreview.planId && snapshot.state === "failed") {
          setStorageAction("");
        }
      }).catch(() => undefined);
    }, 750);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activeTab, client, storagePreview?.jobId, storagePreview?.planId, isStorageMigrationActive(storageSnapshot)]);

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

  const updateUserRole = async (user: AdminUser) => {
    const nextRole = user.role === "admin" ? "member" : "admin";
    if (nextRole === "admin" && designatedAdmin && designatedAdmin.accountId !== user.accountId) {
      setError(`管理员账号已是 ${designatedAdmin.username}，请先取消现有管理员`);
      return;
    }
    setError("");
    setNotice("");
    try {
      const updated = await client.updateUser(user.accountId, { role: nextRole });
      setUsers((prev) => prev.map((item) => (
        item.accountId === user.accountId ? { ...item, ...updated } : item
      )));
      setNotice(nextRole === "admin" ? `${user.username} 已设为管理员` : `${user.username} 已取消管理员身份`);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "更新管理员账号失败"));
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

  const saveAnnouncement = async () => {
    setAnnouncementSaving(true);
    setError("");
    setNotice("");
    try {
      await client.upsertAnnouncement(announcementDraftToInput(announcementDraft));
      setAnnouncementDraft((prev) => createAnnouncementDraft(prev));
      await loadAnnouncements("公告已发布", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "发布公告失败"));
    } finally {
      setAnnouncementSaving(false);
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
    } catch (nextError) {
      setError(getErrorMessage(nextError, "PushPlus 测试推送失败"));
    } finally {
      setTestingPushPlus(false);
    }
  };

  const openEnvCategory = (category: string) => {
    if (!canManageEnvConfig) {
      setError("当前账号无权查看环境配置");
      return;
    }
    setActiveEnvCategory(category);
    setActiveTab("env");
    setLoadedTabs((prev) => ({ ...prev, env: false }));
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
      await client.updateEnvConfig(buildEnvPatchInput());
      await loadEnvConfig("环境配置已保存", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "保存环境配置失败"));
    } finally {
      setEnvSaving(false);
    }
  };

  const reloadEnvConfig = async () => {
    setEnvReloading(true);
    setError("");
    setNotice("");
    try {
      await client.reloadEnvConfig();
      await loadEnvConfig("已重新加载项目 .env", true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "重新加载环境配置失败"));
    } finally {
      setEnvReloading(false);
    }
  };

  const reloadSystemEnvConfig = async () => {
    setEnvSystemReloading(true);
    setError("");
    setNotice("");
    try {
      const result = await client.reloadSystemEnvConfig();
      const message = result.systemEnvironmentSupported === false
        ? "当前运行环境不支持重新加载 Windows 系统环境变量"
        : "已重新加载 Windows 系统环境变量和项目 .env";
      await loadEnvConfig(message, true);
    } catch (nextError) {
      setError(getErrorMessage(nextError, "重新加载系统环境变量失败"));
    } finally {
      setEnvSystemReloading(false);
    }
  };

  const requestServiceRestart = async () => {
    setServiceRestarting(true);
    setError("");
    setNotice("");
    try {
      await client.restartService();
      setNotice("已请求重启后端");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "请求重启后端失败"));
    } finally {
      setServiceRestarting(false);
    }
  };

  const previewStorageMigration = async () => {
    const target = storageTargetRoot.trim();
    if (!target) {
      setError("目标目录不能为空");
      return;
    }
    setStorageAction("preview");
    setError("");
    setNotice("");
    let waitingForPlan = false;
    try {
      const preview = await client.previewStorageMigration(target);
      setStoragePreview(preview);
      setStorageSnapshot((previous) => mergeStorageMigrationSnapshot(previous, preview));
      waitingForPlan = Boolean(preview.jobId && !preview.planId);
      setNotice(waitingForPlan ? "预览任务已提交，正在扫描源目录..." : "迁移预览已生成，请确认影响范围");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "生成迁移预览失败"));
    } finally {
      if (!waitingForPlan) {
        setStorageAction("");
      }
    }
  };

  const startStorageMigration = async () => {
    if (!storagePreview?.planId) {
      setError("请先生成迁移预览");
      return;
    }
    setStorageAction("migrate");
    setError("");
    setNotice("");
    try {
      const status = await client.startStorageMigration(storagePreview.planId, true);
      setStorageSnapshot(status);
      setStoragePreview(null);
      setStorageConfirmOpen(false);
      setNotice(status.state === "awaiting_restart" ? "迁移已完成校验，请重启服务继续清理原始数据" : "存储迁移已开始");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "启动存储迁移失败"));
    } finally {
      setStorageAction("");
    }
  };

  const retryStorageCleanup = async () => {
    setStorageAction("retry");
    setError("");
    setNotice("");
    try {
      const status = await client.retryStorageMigrationCleanup();
      setStorageSnapshot(status);
      setNotice(status.state === "completed" ? "原始数据清理已完成" : "已重试原始数据清理");
    } catch (nextError) {
      setError(getErrorMessage(nextError, "重试原始数据清理失败"));
    } finally {
      setStorageAction("");
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

  const activeTabMeta = ADMIN_TAB_META[activeTab];
  const activeGroup = ADMIN_TAB_GROUPS.find((group) => group.tabs.includes(activeTab));

  return (
    <main data-ui-density="compact" className="admin-center orbit-shell">
      <header className="admin-cover orbit-cover">
        <div className="orbit-cover-art">
          <ThemeIllustrationLayer surface="adminCenter" />
        </div>
        <div className="admin-cover-inner">
          <div className="admin-cover-copy">
            <p className="admin-cover-eyebrow">Orbit 控制台</p>
            <h1 className="admin-cover-title">管理中心</h1>
            <p className="admin-cover-description">统一管理成员权限、运行环境、服务集成与系统升级。</p>
          </div>
          <div className="admin-cover-actions">
            <button
              type="button"
              onClick={() => setRestartConfirmTarget("service")}
              disabled={serviceRestarting}
              className="orbit-btn admin-btn--warning"
            >
              <RefreshCw className={`h-4 w-4${serviceRestarting ? " animate-spin" : ""}`} />
              {serviceRestarting ? "请求中..." : "重启后端"}
            </button>
            <button type="button" onClick={onClose} className="orbit-btn orbit-btn--secondary">
              <ArrowLeft className="h-4 w-4" />
              返回
            </button>
          </div>
        </div>
      </header>

      <div className="admin-body">
        <nav className="admin-nav orbit-island orbit-island--reading" aria-label="管理中心导航">
          <div role="tablist" aria-label="管理中心功能" className="admin-nav-list">
            {ADMIN_TAB_GROUPS.map((group) => {
              const tabs = group.tabs.filter((tab) => visibleTabs.includes(tab));
              if (!tabs.length) return null;
              return (
                <div key={group.label} role="none" className="admin-nav-group">
                  <div role="none" aria-hidden="true" className="admin-nav-caption">{group.label}</div>
                  {tabs.map((tab) => (
                    <button
                      key={tab}
                      type="button"
                      role="tab"
                      aria-selected={activeTab === tab}
                      onClick={() => setActiveTab(tab)}
                      className="admin-nav-tab"
                    >
                      {ADMIN_TAB_META[tab].label}
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        </nav>

        <div className="admin-content">
          <div className="admin-content-head">
            <div className="admin-content-heading">
              <span className="admin-content-kicker">{activeGroup?.label}</span>
              <span className="admin-content-title">{activeTabMeta.label}</span>
              <span className="admin-content-description">{activeTabMeta.description}</span>
            </div>
            <button
              type="button"
              onClick={() => void refreshActiveTab("", true)}
              disabled={loading || refreshing}
              className="orbit-btn orbit-btn--ghost orbit-btn--sm"
            >
              <RefreshCw className={`h-3.5 w-3.5${refreshing ? " animate-spin" : ""}`} />
              {refreshing ? "刷新中..." : "刷新"}
            </button>
          </div>

          {error ? (
            <div role="alert" className="admin-callout" data-tone="danger">
              <AlertTriangle className="h-4 w-4 flex-none" />
              <span>{error}</span>
            </div>
          ) : null}
          {notice ? (
            <div role="status" className="admin-callout" data-tone="success">
              <span>{notice}</span>
            </div>
          ) : null}

          {loading ? (
            <section className="admin-island orbit-island orbit-island--reading text-sm text-[var(--muted)]">
              加载中...
            </section>
          ) : null}

        {!loading && activeTab === "global" && canManageEnvConfig ? (
          <div className="admin-embed">
            <GlobalUiSettingsPanel
              canManage={canManageEnvConfig}
              themeName={themeName}
              onThemeChange={onThemeChange}
              chatEnterToSend={chatEnterToSend}
              onChatEnterToSendChange={onChatEnterToSendChange}
            />
            <GlobalPromptPresetsPanel
              client={client}
              botAlias={currentBotAlias || initialBots[0]?.alias || "main"}
              canManage={canManageEnvConfig}
            />
          </div>
        ) : null}

        {!loading && activeTab === "users" ? (
          <section aria-labelledby="user-permissions-title" className="admin-island orbit-island orbit-island--reading">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 id="user-permissions-title" className="text-base font-semibold text-[var(--text)]">用户权限</h2>
                <p className="text-xs text-[var(--muted)]">共 {users.length} 人，累计已创建 {totalOwnedBots} 个 Bot</p>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {users.map((user) => (
                <article key={user.accountId} className="admin-user-card admin-well">
                  <div className="admin-user-head">
                    <div className="admin-user-avatar" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-[var(--text)]">{user.username}</p>
                        <span className="orbit-chip" data-tone={user.role === "admin" ? "accent" : undefined}>
                          {user.role}
                        </span>
                        {user.disabled ? (
                          <span className="orbit-chip" data-tone="warning">
                            已停用
                          </span>
                        ) : null}
                      </div>
                      <p className="admin-user-meta">
                        <span className="break-all">{user.accountId}</span>
                        <span>已创建 {user.ownedBotCount}/{user.botCreateLimit} 个 Bot</span>
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void toggleUserDisabled(user)}
                        className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                      >
                        {user.disabled ? "启用" : "停用"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void updateUserRole(user)}
                        disabled={nextRoleIsBlocked(user, designatedAdmin) || !canManageRegisterCodes}
                        className="orbit-btn orbit-btn--secondary orbit-btn--sm"
                      >
                        {user.role === "admin" ? "取消管理员" : "设为管理员"}
                      </button>
                    </div>
                  </div>
                  {user.role === "admin" ? (
                    <div className="admin-permission-lock" role="status">
                      管理员拥有全部账号能力和 Bot 权限
                    </div>
                  ) : (
                    <>
                      <p className="admin-group-caption">账号能力</p>
                      <div className="admin-toggle-grid">
                        {ACCOUNT_CAPABILITY_OPTIONS.map((capability) => (
                          <label key={`${user.accountId}-${capability.id}`} className="admin-permission-toggle">
                            <input
                              className="admin-permission-toggle-input"
                              type="checkbox"
                              aria-label={`${user.username} 账号能力 ${capability.label}`}
                              checked={user.capabilities.includes(capability.id)}
                              onChange={(event) => void updateUserCapabilityGrant(user, capability.id, event.target.checked)}
                            />
                            <span className="admin-permission-toggle-label" title={capability.label}>{capability.label}</span>
                          </label>
                        ))}
                      </div>
                      {bots.length ? <p className="admin-group-caption">可操作 Bot</p> : null}
                      <div className="admin-toggle-grid">
                        {bots.map((bot) => (
                          <label key={`${user.accountId}-${bot.alias}`} className="admin-permission-toggle">
                            <input
                              className="admin-permission-toggle-input"
                              type="checkbox"
                              aria-label={`${user.username} 可操作 Bot ${bot.alias}`}
                              checked={user.allowedBots.includes(bot.alias)}
                              onChange={(event) => void updateUserBotGrant(user, bot.alias, event.target.checked)}
                            />
                            <span className="admin-permission-toggle-label" title={bot.alias}>{bot.alias}</span>
                            {user.ownedBots.includes(bot.alias) ? (
                              <span className="orbit-chip" data-tone="accent">创建者</span>
                            ) : null}
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                </article>
              ))}
              {users.length === 0 ? <p className="text-sm text-[var(--muted)]">暂无用户</p> : null}
            </div>
          </section>
        ) : null}

        {!loading && activeTab === "invites" ? (
          <div className="admin-stack">
            <section className="admin-island orbit-island orbit-island--reading space-y-4">
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
                  className="orbit-btn orbit-btn--primary"
                >
                  <Save className="h-4 w-4" />
                  {registerCodeCreating ? "生成中..." : "生成邀请码"}
                </button>
              </div>

              {createdRegisterCode ? (
                <div className="admin-tint px-3 py-3 text-sm" data-tone="success">
                  最新邀请码: <span className="font-semibold">{createdRegisterCode.code}</span>
                </div>
              ) : null}
            </section>

            <section className="admin-island orbit-island orbit-island--reading space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-[var(--text)]">邀请码列表</h2>
                <span className="text-xs text-[var(--muted)]">共 {registerCodes.length} 个</span>
              </div>

              {registerCodes.length ? registerCodes.map((item) => (
                <article key={item.codeId} className="admin-well p-3 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1 text-sm text-[var(--muted)]">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-[var(--text)]">{item.codePreview}</p>
                        {item.disabled ? (
                          <span className="orbit-chip" data-tone="warning">
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
                        className="orbit-btn orbit-btn--secondary"
                      >
                        +1
                      </button>
                      <button
                        type="button"
                        onClick={() => void mutateRegisterCode(item.codeId, { maxUsesDelta: -1 }, "邀请码次数已减少")}
                        disabled={registerCodeActionId === item.codeId || item.remainingUses <= 0}
                        className="orbit-btn orbit-btn--secondary"
                      >
                        -1
                      </button>
                      <button
                        type="button"
                        onClick={() => void mutateRegisterCode(item.codeId, { disabled: !item.disabled }, item.disabled ? "邀请码已启用" : "邀请码已停用")}
                        disabled={registerCodeActionId === item.codeId}
                        className="orbit-btn orbit-btn--secondary"
                      >
                        {item.disabled ? "启用" : "停用"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeRegisterCode(item.codeId)}
                        disabled={registerCodeActionId === item.codeId}
                        className="orbit-btn admin-btn--danger-quiet"
                      >
                        删除
                      </button>
                    </div>
                  </div>

                  {item.usage.length ? (
                    <div className="admin-well px-3 py-2 text-xs text-[var(--muted)] space-y-1">
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

        {activeTab === "network-updates" ? (
          <div className="admin-stack">
            <PublicAccessPanel
              client={client}
              refreshKey={networkUpdatesRefreshKey}
              onOpenEnvConfig={canManageEnvConfig ? () => openEnvCategory("tunnel") : undefined}
            />
            <AppUpdatePanel client={client} refreshKey={networkUpdatesRefreshKey} />
          </div>
        ) : null}

        {!loading && activeTab === "notifications" ? (
          <section className="admin-island orbit-island orbit-island--reading space-y-4">
            <div className="flex items-start gap-2">
              <Bell className="mt-0.5 h-5 w-5 text-[var(--accent)]" />
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">通知</h2>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
              <p className="admin-well px-3 py-2">
                PushPlus: <span className="font-medium text-[var(--text)]">{pushPlusStatusText(notificationSettings)}</span>
              </p>
              <p className="admin-well px-3 py-2">
                Token: <span className="font-medium text-[var(--text)]">{notificationSettings?.pushPlusConfigured ? "已设置" : "未设置"}</span>
              </p>
              <p className="admin-well px-3 py-2">
                Topic: <span className="font-medium text-[var(--text)]">{notificationSettings?.pushPlusTopicConfigured ? "已设置" : "未设置"}</span>
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void sendPushPlusTest()}
                disabled={testingPushPlus || !notificationSettings?.pushPlusEnabled}
                className="orbit-btn orbit-btn--secondary"
              >
                {testingPushPlus ? "发送中..." : "测试 PushPlus 推送"}
              </button>
              <button
                type="button"
                onClick={() => setShowPushPlusGuide(true)}
                className="orbit-btn orbit-btn--secondary"
              >
                PushPlus 配置教程
              </button>
              <button
                type="button"
                onClick={() => openEnvCategory("notifications")}
                disabled={!canManageEnvConfig}
                className="orbit-btn orbit-btn--secondary"
              >
                打开环境配置
              </button>
            </div>

            {showPushPlusGuide ? (
              <div
                className="admin-well p-4"
                role="dialog"
                aria-label="PushPlus 配置教程"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-semibold text-[var(--text)]">PushPlus 配置教程</h3>
                  <button
                    type="button"
                    onClick={() => setShowPushPlusGuide(false)}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                  >
                    关闭
                  </button>
                </div>
                <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-[var(--text)]">
                  <li>关注 PushPlus 公众号</li>
                  <li>完成实名制认证</li>
                  <li>登录 PushPlus 网站</li>
                  <li>复制 token</li>
                  <li>在环境配置的通知分类写入变量</li>
                </ol>
                <pre className="admin-well mt-3 overflow-x-auto p-3 text-xs text-[var(--text)]">
                  <code>{`PUSHPLUS_ENABLED=true
PUSHPLUS_TOKEN=你的token
PUSHPLUS_TOPIC=可选群组编码`}</code>
                </pre>
              </div>
            ) : null}
          </section>
        ) : null}

        {!loading && activeTab === "usage" ? (
          loadedTabs.usage ? (
            <Suspense fallback={(
              <section className="admin-island orbit-island orbit-island--reading text-sm text-[var(--muted)]">
                正在加载 Usage 面板…
              </section>
            )}>
              <div className="admin-embed">
                <UsagePanel
                  client={client}
                  provider={usageProvider}
                  onProviderChange={setUsageProvider}
                  refreshKey={usagePanelKey}
                />
              </div>
            </Suspense>
          ) : (
            <section className="admin-island orbit-island orbit-island--reading text-sm text-[var(--muted)]">
              正在加载 Usage 面板…
            </section>
          )
        ) : null}

        {!loading && activeTab === "chat-translation" ? (
          <ChatTranslationSettingsPanel key={chatTranslationPanelKey} client={client} onSaved={() => setNotice("聊天翻译配置已保存")} />
        ) : null}

        {!loading && activeTab === "inline-completion" ? (
          <div className="admin-embed">
            <AiInlineCompletionSettingsPanel
              key={inlineCompletionPanelKey}
              client={client}
              onSaved={() => {
                setError("");
                setNotice("AI inline 补全配置已保存");
              }}
              onError={(message) => {
                setNotice("");
                setError(message);
              }}
            />
          </div>
        ) : null}

        {!loading && activeTab === "lan-chat" ? (
          <section className="admin-island orbit-island orbit-island--reading space-y-4">
            <div>
              <h2 className="text-base font-semibold text-[var(--text)]">联机聊天</h2>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {([
                ["off", "关闭"],
                ["host", "作为主机"],
                ["join", "加入主机"],
              ] as const).map(([mode, label]) => (
                <label key={mode} className="admin-choice">
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
              className="orbit-btn orbit-btn--primary"
            >
              <Save className="h-4 w-4" />
              {lanChatSaving ? "保存中..." : "保存联机聊天配置"}
            </button>
          </section>
        ) : null}

        {!loading && activeTab === "storage" ? (
          <section aria-labelledby="storage-migration-title" className="admin-island orbit-island orbit-island--reading space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="storage-migration-title" className="text-base font-semibold text-[var(--text)]">TCB 数据迁移</h2>
                <p className="mt-1 text-sm text-[var(--muted)]">迁移聊天历史、附件、插件和集群 MCP 等运行数据。</p>
              </div>
              <span className="orbit-chip">
                {storageSnapshot && isStorageMigrationActive(storageSnapshot)
                  ? storageMigrationStateText(storageSnapshot.phase || storageSnapshot.state)
                  : storageSnapshot?.canMigrate
                    ? "可开始迁移"
                    : storageSnapshot
                      ? storageMigrationStateText(storageSnapshot.state)
                      : "未读取"}
              </span>
            </div>

            <div className="grid gap-3 text-sm sm:grid-cols-2">
              <p className="break-all admin-well px-3 py-2">
                当前数据根目录: <span className="text-[var(--text)]">{storageSnapshot?.currentRoot || "-"}</span>
              </p>
              <p className="admin-well px-3 py-2">
                已发现数据: <span className="font-medium text-[var(--text)]">
                  {storageSnapshot?.sizePending ? "点击“预览并校验”计算" : formatStorageBytes(storageSnapshot?.totalBytes || 0)}
                </span>
              </p>
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-medium text-[var(--text)]">数据来源</h3>
              {(storageSnapshot?.sources || []).map((source) => (
                <div key={source.id} className="admin-well grid gap-1 px-3 py-2 text-sm sm:grid-cols-[1fr_auto]">
                  <div>
                    <p className="font-medium text-[var(--text)]">{source.label || source.id}</p>
                    <p className="break-all text-xs text-[var(--muted)]">{source.path || "路径由服务管理"}</p>
                  </div>
                  <p className="text-[var(--muted)]">
                    {source.exists ? (source.sizePending ? "待预览计算" : formatStorageBytes(source.sizeBytes)) : "不存在"}
                    {source.sizePending ? "" : ` · ${source.fileCount} 个文件`}
                  </p>
                </div>
              ))}
              {!storageSnapshot?.sources.length ? <p className="text-sm text-[var(--muted)]">暂无可迁移数据</p> : null}
            </div>

            <div className="grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
              <label className="space-y-1">
                <span className="text-sm font-medium text-[var(--text)]">目标目录</span>
                <input
                  aria-label="存储迁移目标目录"
                  value={storageTargetRoot}
                  onChange={(event) => {
                    setStorageTargetRoot(event.target.value);
                    setStoragePreview(null);
                  }}
                  placeholder="例如 D:\\OrbitData"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
              </label>
              <button
                type="button"
                onClick={() => void previewStorageMigration()}
                disabled={storageAction !== "" || !storageTargetRoot.trim()}
                className="orbit-btn orbit-btn--secondary"
              >
                {storageAction === "preview"
                  ? (storagePreview?.jobId && !storagePreview.planId ? "扫描中..." : "校验中...")
                  : "预览并校验"}
              </button>
            </div>

            {storagePreview ? (
              <div className="admin-tint space-y-3 p-3 text-sm" data-tone="warning">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="font-semibold">迁移预览</h3>
                    <p className="mt-1 break-all">目标: {storagePreview.targetRoot}</p>
                    <p>预计迁移: {formatStorageBytes(storagePreview.totalBytes)}</p>
                    <p>当前阶段: {storageMigrationStateText(storagePreview.phase || storagePreview.state)}</p>
                  </div>
                  <span className="font-mono text-xs">
                    {storagePreview.planId ? `planId: ${storagePreview.planId}` : `jobId: ${storagePreview.jobId || "-"}`}
                  </span>
                </div>
                {storagePreview.jobId && !storagePreview.planId ? (
                  <p>预览任务正在后台执行，完成后才能确认迁移。</p>
                ) : null}
                {storagePreview.blockers?.map((blocker) => <p key={blocker} className="font-medium text-[var(--feedback-error-text-stronger)]">无法迁移: {blocker}</p>)}
                {storagePreview.warnings?.map((warning) => <p key={warning}>提示: {warning}</p>)}
                <button
                  type="button"
                  onClick={() => setStorageConfirmOpen(true)}
                  disabled={storageAction !== "" || !storagePreview.planId || storageSnapshot?.maintenance || Boolean(storagePreview.blockers?.length)}
                  className="orbit-btn admin-btn--warning-solid"
                >
                  确认并迁移
                </button>
              </div>
            ) : null}

            {storageSnapshot && (
              isStorageMigrationActive(storageSnapshot)
              || storageSnapshot.maintenance
              || storageSnapshot.state === "awaiting_restart"
              || storageSnapshot.state === "cleanup_pending"
              || storageSnapshot.state === "failed"
              || storageSnapshot.progress !== undefined
            ) ? (
              <div data-testid="storage-migration-progress" className="admin-tint space-y-3 px-3 py-3 text-sm" data-tone="info">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium">当前阶段: {storageMigrationStateText(storageSnapshot.phase || storageSnapshot.state)}</p>
                  {storageSnapshot.jobId ? <span className="font-mono text-xs">jobId: {storageSnapshot.jobId}</span> : null}
                </div>
                <div>
                  <div className="flex justify-between gap-3 text-xs">
                    <span>总进度</span>
                    <span>{Math.round(storageProgress(storageSnapshot) * 100)}%</span>
                  </div>
                  <progress
                    aria-label="迁移总进度"
                    className="mt-1 h-2 w-full accent-[var(--feedback-information-control-strong)]"
                    max={1}
                    value={storageProgress(storageSnapshot)}
                  />
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <p>
                    已处理大小: {formatStorageBytes(storageSnapshot.completedBytes || Math.round(storageProgress(storageSnapshot) * storageSnapshot.totalBytes))}
                    {" / "}{formatStorageBytes(storageSnapshot.totalBytes)}
                  </p>
                  <p>
                    已处理文件: {storageSnapshot.completedFiles || 0}
                    {" / "}{storageSnapshot.totalFiles ?? storageSnapshot.sources.reduce((sum, source) => sum + source.fileCount, 0)}
                  </p>
                  <p className="break-all sm:col-span-2">当前项: {storageSnapshot.currentItem || "-"}</p>
                  <p>速度: {formatStorageBytes(storageSnapshot.speedBytesPerSecond || 0)}/秒</p>
                  <p>预计剩余: {formatStorageDuration(storageSnapshot.etaSeconds)}</p>
                </div>
                {storageSnapshot.message ? <p>{storageSnapshot.message}</p> : null}
                {storageSnapshot.error ? <p className="font-medium text-[var(--feedback-error-text-stronger)]">错误: {storageSnapshot.error}</p> : null}
                {storageSnapshot.recoveryMessage ? <p className="font-medium">恢复提示: {storageSnapshot.recoveryMessage}</p> : null}
                {storageSnapshot.state === "awaiting_restart" ? <p className="font-medium">请重启服务使新数据根目录生效，然后再处理原始数据清理。</p> : null}
                {storageSnapshot.state === "cleanup_pending" ? <p className="font-medium">原始数据尚未清理完成，可以在服务恢复后重试。</p> : null}
              </div>
            ) : null}

            {storageSnapshot?.state === "cleanup_pending" ? (
              <button
                type="button"
                onClick={() => void retryStorageCleanup()}
                disabled={storageAction !== ""}
                className="orbit-btn orbit-btn--secondary"
              >
                {storageAction === "retry" ? "重试中..." : "重试原始数据清理"}
              </button>
            ) : null}

            {storageConfirmOpen ? (
              <div role="dialog" aria-label="确认数据迁移" className="admin-tint admin-tint--strong p-4 text-sm" data-tone="danger">
                <h3 className="font-semibold">确认停止全部智能体并迁移数据？</h3>
                <p className="mt-2">迁移开始前会停止全部智能体进程并 flush 未写入数据。校验通过后，系统会删除已验证的原始数据。迁移期间请勿关闭服务。</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void startStorageMigration()}
                    disabled={storageAction !== ""}
                    className="orbit-btn orbit-btn--danger"
                  >
                    {storageAction === "migrate" ? "启动中..." : "我确认停止全部智能体并继续"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setStorageConfirmOpen(false)}
                    disabled={storageAction !== ""}
                    className="orbit-btn admin-btn--danger-quiet"
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {!loading && activeTab === "env" && canManageEnvConfig ? (
          <section className="admin-island orbit-island orbit-island--reading space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">环境配置</h2>
                <p className="text-sm text-[var(--muted)]">保存写入 .env；可分别重新加载项目 .env 或 Windows 用户/系统环境变量。</p>
                <p className="mt-1 text-xs text-[var(--muted)]">只影响当前进程和之后创建的子进程；监听地址/端口、前端 VITE_*、隧道和已建立的原生会话仍按字段标签重启或重新 build。</p>
                <p className="mt-1 break-all text-xs text-[var(--muted)]">文件: {envConfig?.envPath || ".env"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void reloadSystemEnvConfig()}
                  disabled={envSaving || envReloading || envSystemReloading || envChangedItems.length > 0}
                  className="orbit-btn orbit-btn--secondary"
                >
                  <RefreshCw className={`h-4 w-4${envSystemReloading ? " animate-spin" : ""}`} />
                  {envSystemReloading ? "加载中..." : "重新加载 Windows 环境"}
                </button>
                <button
                  type="button"
                  onClick={() => void reloadEnvConfig()}
                  disabled={envSaving || envReloading || envSystemReloading || envChangedItems.length > 0}
                  className="orbit-btn orbit-btn--secondary"
                >
                  <RefreshCw className={`h-4 w-4${envReloading ? " animate-spin" : ""}`} />
                  {envReloading ? "加载中..." : "重新加载 .env"}
                </button>
                <button
                  type="button"
                  onClick={() => void previewEnvChanges()}
                  disabled={envSaving || envReloading || envSystemReloading || envChangedItems.length === 0 || Boolean(envConflictMessage)}
                  className="orbit-btn orbit-btn--secondary"
                >
                  预览 diff
                </button>
                <button
                  type="button"
                  onClick={() => void saveEnvChanges()}
                  disabled={envSaving || envReloading || envSystemReloading || envChangedItems.length === 0 || Boolean(envConflictMessage)}
                  className="orbit-btn orbit-btn--primary"
                >
                  <Save className="h-4 w-4" />
                  {envSaving ? "保存中..." : "保存环境配置"}
                </button>
              </div>
            </div>

            {envConflictMessage ? (
              <div className="admin-tint px-3 py-3 text-sm" data-tone="danger">
                {envConflictMessage}
              </div>
            ) : null}

            {envPreview ? (
              <div role="dialog" aria-label="环境配置 diff 确认" className="space-y-3 admin-well p-3">
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
                    className="orbit-btn orbit-btn--secondary"
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
                      <div key={item.key} className="admin-well px-3 py-2 text-xs">
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
                  disabled={envSaving || envReloading || envSystemReloading || Boolean(envConflictMessage)}
                  className="orbit-btn orbit-btn--primary"
                >
                  <Save className="h-4 w-4" />
                  确认保存
                </button>
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-[180px_1fr]">
              <nav className="admin-subnav">
                {envCategories.map((category) => (
                  <button
                    key={category}
                    type="button"
                    onClick={() => setActiveEnvCategory(category)}
                    data-active={(activeEnvCategory || envCategories[0]) === category ? "true" : undefined}
                    className="admin-subnav-item"
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
                    <article key={item.key} className="space-y-3 admin-well p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-medium text-[var(--text)]">{item.label}</h3>
                            <span className="orbit-chip">{item.key}</span>
                            {item.restartRequired ? <span className="orbit-chip" data-tone="warning">重启生效</span> : !item.rebuildRequired ? <span className="orbit-chip" data-tone="success">重加载.env生效</span> : null}
                            {item.rebuildRequired ? <span className="orbit-chip" data-tone="info">需 build</span> : null}
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
                              className="orbit-btn orbit-btn--ghost orbit-btn--sm"
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
                              className="orbit-btn orbit-btn--sm admin-btn--danger-quiet"
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
                              className="orbit-btn orbit-btn--ghost orbit-btn--sm"
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
                      ) : item.type === "json" ? (
                        <textarea
                          aria-label={item.label}
                          value={secretMasked ? "********" : formatEnvValue(draftValue)}
                          disabled={secretMasked || secretAction === "regenerate"}
                          rows={7}
                          spellCheck={false}
                          onChange={(event) => {
                            setEnvDraft((prev) => ({
                              ...prev,
                              [item.key]: normalizeEnvDraftValue(item, event.target.value),
                            }));
                            setEnvPreview(null);
                          }}
                          className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 font-mono text-xs text-[var(--text)] disabled:opacity-70"
                        />
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
                        <p className="text-xs text-[var(--feedback-error-text-deep)]">保存后将禁用口令登录。</p>
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
          <AnnouncementAdminPanel
            items={announcements}
            draft={announcementDraft}
            onDraftChange={setAnnouncementDraft}
            saving={announcementSaving}
            deletingId={announcementDeletingId}
            onPublish={() => void saveAnnouncement()}
            onDelete={(id) => void removeAnnouncement(id)}
          />
        ) : null}

        {!loading && activeTab === "cli-errors" ? (
          <section aria-labelledby="cli-error-stats-title" className="admin-island orbit-island orbit-island--reading space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 id="cli-error-stats-title" className="text-base font-semibold text-[var(--text)]">CLI 错误统计</h2>
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
              <p className="admin-well px-3 py-2">
                总错误: <span className="font-semibold text-[var(--text)]">{cliErrorStats?.summary.total || 0}</span>
              </p>
              <p className="admin-well px-3 py-2">
                CLI 最高: <span className="font-semibold text-[var(--text)]">{topEntryLabel(cliErrorStats?.summary.byCliType || {}, cliTypeLabel)}</span>
              </p>
              <p className="admin-well px-3 py-2">
                Bot 最高: <span className="font-semibold text-[var(--text)]">{topEntryLabel(cliErrorStats?.summary.byBot || {})}</span>
              </p>
              <p className="admin-well px-3 py-2">
                类别最高: <span className="font-semibold text-[var(--text)]">{topEntryLabel(cliErrorStats?.summary.byCategory || {})}</span>
              </p>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="admin-well p-3">
                <h3 className="text-sm font-semibold text-[var(--text)]">按类别</h3>
                <div className="mt-3 space-y-2 text-sm">
                  {Object.entries(cliErrorStats?.summary.byCategory || {}).map(([category, count]) => (
                    <div key={category} className="admin-well flex items-center justify-between gap-3 px-3 py-2">
                      <span className="text-[var(--text)]">{category}</span>
                      <span className="text-[var(--muted)]">{count}</span>
                    </div>
                  ))}
                  {!Object.keys(cliErrorStats?.summary.byCategory || {}).length ? (
                    <p className="text-[var(--muted)]">暂无错误</p>
                  ) : null}
                </div>
              </div>

              <div className="admin-well p-3">
                <h3 className="text-sm font-semibold text-[var(--text)]">高频错误</h3>
                <div className="mt-3 space-y-2 text-sm">
                  {(cliErrorStats?.topErrors || []).map((item) => (
                    <div key={`${item.category}-${item.message}`} className="admin-well px-3 py-2">
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

            <div className="overflow-hidden admin-well">
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
                <AlertTriangle className="h-4 w-4 text-[var(--feedback-warning-text)]" />
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
                        <td className="px-3 py-2 text-[var(--text)]">{cliTypeLabel(item.cliType)}</td>
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
      </div>
      {restartConfirmTarget ? (
        <ChatConfirmDialog
          label="确认重启后端"
          title="确认重启后端？"
          description="重启会中断正在运行的智能体任务，Web 和 Telegram 将暂时断开连接。确认现在重启后端吗？"
          confirmLabel="确认重启"
          tone="danger"
          onConfirm={() => {
            setRestartConfirmTarget(null);
            void requestServiceRestart();
          }}
          onCancel={() => setRestartConfirmTarget(null)}
        />
      ) : null}
    </main>
  );
}
