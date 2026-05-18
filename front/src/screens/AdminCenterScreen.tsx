import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, RefreshCw, Save } from "lucide-react";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type {
  AdminUser,
  AnnouncementItem,
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  BotSummary,
  CreateAnnouncementInput,
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
};

type AdminCenterTab = "users" | "invites" | "updates" | "announcements";

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

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function formatPackageKind(kind?: string) {
  if (kind === "installer") return "安装版";
  if (kind === "portable") return "绿色版";
  if (kind === "linux") return "Linux";
  return "未知";
}

export function AdminCenterScreen({
  client = new MockWebBotClient(),
  onClose,
  initialBots = [],
  onBotsChange,
}: Props) {
  const [activeTab, setActiveTab] = useState<AdminCenterTab>("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [bots, setBots] = useState<BotSummary[]>(initialBots);
  const [registerCodes, setRegisterCodes] = useState<RegisterCodeItem[]>([]);
  const [updateStatus, setUpdateStatus] = useState<AppUpdateStatus | null>(null);
  const [offlinePackages, setOfflinePackages] = useState<OfflineUpdatePackageList | null>(null);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [announcementDraft, setAnnouncementDraft] = useState<CreateAnnouncementInput>(DEFAULT_ANNOUNCEMENT_DRAFT);
  const [announcementSaving, setAnnouncementSaving] = useState(false);
  const [announcementDeletingId, setAnnouncementDeletingId] = useState("");
  const [loadedTabs, setLoadedTabs] = useState<Record<AdminCenterTab, boolean>>({
    users: false,
    invites: false,
    updates: false,
    announcements: false,
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

  async function refreshActiveTab(nextNotice = "", refresh = false) {
    if (activeTab === "users") {
      await loadUsers(nextNotice, refresh);
    } else if (activeTab === "invites") {
      await loadInvites(nextNotice, refresh);
    } else if (activeTab === "updates") {
      await loadUpdates(nextNotice, refresh);
    } else {
      await loadAnnouncements(nextNotice, refresh);
    }
  }

  useEffect(() => {
    if (loadedTabs[activeTab]) {
      return;
    }
    void refreshActiveTab();
  }, [activeTab, client, loadedTabs]);

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
          {(["users", "invites", "updates", "announcements"] as AdminCenterTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              onClick={() => setActiveTab(tab)}
              className={activeTab === tab
                ? "rounded-md bg-[var(--accent)] px-3 py-2 text-sm text-[var(--accent-foreground)]"
                : "rounded-md border border-[var(--border)] px-3 py-2 text-sm"}
            >
              {tab === "users" ? "用户权限" : tab === "invites" ? "邀请码" : tab === "updates" ? "升级" : "公告"}
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
                    {bots.map((bot) => (
                      <label key={`${user.accountId}-${bot.alias}`} className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
                        <input
                          type="checkbox"
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
                  className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-[var(--accent-foreground)] hover:opacity-90 disabled:opacity-60"
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
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-[var(--accent-foreground)] hover:opacity-90 disabled:opacity-60"
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
                    {item.name}
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
      </div>
    </main>
  );
}
