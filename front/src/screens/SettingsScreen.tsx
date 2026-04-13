import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Copy, Globe, LogOut, RefreshCw, RotateCw, Save, Square } from "lucide-react";
import { AvatarPicker } from "../components/AvatarPicker";
import { BotIdentity } from "../components/BotIdentity";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { AvatarAsset, BotOverview, CliParamField, CliParamsPayload, GitProxySettings, TunnelSnapshot } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_AVATAR_ASSETS, readStoredUserAvatarName } from "../utils/avatar";
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
  UI_THEME_OPTIONS,
  type ChatBodyFontFamilyName,
  type ChatBodyFontSizeName,
  type ChatBodyLineHeightName,
  type ChatBodyParagraphSpacingName,
  type UiThemeName,
} from "../theme";

type Props = {
  botAlias: string;
  botAvatarName?: string;
  client?: WebBotClient;
  onLogout: () => void;
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
};

type DraftValues = Record<string, string | boolean>;
type BuildLogStatus = "idle" | "running" | "success" | "error";

function fieldLabel(key: string, field: CliParamField) {
  return field.description || key;
}

function buildDraftValues(payload: CliParamsPayload): DraftValues {
  const drafts: DraftValues = {};
  for (const [key, field] of Object.entries(payload.schema)) {
    const value = payload.params[key];
    if (field.type === "boolean") {
      drafts[key] = Boolean(value);
      continue;
    }
    if (field.type === "string_list") {
      drafts[key] = Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
      continue;
    }
    drafts[key] = value == null ? "" : String(value);
  }
  return drafts;
}

function toRequestValue(field: CliParamField, value: string | boolean) {
  if (field.type === "boolean") {
    return Boolean(value);
  }
  if (field.type === "string_list") {
    return String(value)
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return value;
}

function tunnelStatusText(status: TunnelSnapshot["status"]) {
  if (status === "running") return "运行中";
  if (status === "starting") return "启动中";
  if (status === "error") return "异常";
  return "已停止";
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function SettingsScreen({
  botAlias,
  botAvatarName,
  client = new MockWebBotClient(),
  onLogout,
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
}: Props) {
  const [overview, setOverview] = useState<BotOverview | null>(null);
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [tunnel, setTunnel] = useState<TunnelSnapshot | null>(null);
  const [gitProxySettings, setGitProxySettings] = useState<GitProxySettings | null>(null);
  const [avatarAssets, setAvatarAssets] = useState<AvatarAsset[]>(DEFAULT_AVATAR_ASSETS);
  const [draftValues, setDraftValues] = useState<DraftValues>({});
  const [cliTypeDraft, setCliTypeDraft] = useState("codex");
  const [cliPathDraft, setCliPathDraft] = useState("");
  const [gitProxyPortDraft, setGitProxyPortDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [workdirDraft, setWorkdirDraft] = useState("");
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "reset" | "kill">("");
  const [savingParamKey, setSavingParamKey] = useState("");
  const [savingCliConfig, setSavingCliConfig] = useState(false);
  const [savingWorkdir, setSavingWorkdir] = useState(false);
  const [savingGitProxy, setSavingGitProxy] = useState(false);
  const [resettingCliParams, setResettingCliParams] = useState(false);
  const [tunnelAction, setTunnelAction] = useState<"" | "start" | "stop" | "restart" | "copy">("");
  const [serviceAction, setServiceAction] = useState<"" | "restart_service" | "build_frontend">("");
  const [showBuildLog, setShowBuildLog] = useState(false);
  const [buildLogLines, setBuildLogLines] = useState<string[]>([]);
  const [buildLogStatus, setBuildLogStatus] = useState<BuildLogStatus>("idle");
  const [buildLogSummary, setBuildLogSummary] = useState("");
  const buildLogViewportRef = useRef<HTMLDivElement | null>(null);
  const workdirLocked = overview?.botMode === "assistant";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    Promise.allSettled([
      client.getBotOverview(botAlias),
      client.getCliParams(botAlias),
      client.getTunnelStatus(),
      botAlias === "main" ? client.getGitProxySettings() : Promise.resolve(null),
      client.listAvatarAssets(),
    ])
      .then(([overviewResult, cliParamsResult, tunnelResult, gitProxyResult, avatarAssetsResult]) => {
        if (cancelled) return;

        if (overviewResult.status !== "fulfilled" || cliParamsResult.status !== "fulfilled") {
          const reason = overviewResult.status !== "fulfilled" ? overviewResult.reason : cliParamsResult.reason;
          setError(getErrorMessage(reason, "加载设置失败"));
          setLoading(false);
          return;
        }

        const overviewData = overviewResult.value;
        const cliParamsData = cliParamsResult.value;
        const tunnelData = tunnelResult.status === "fulfilled" ? tunnelResult.value : null;
        const gitProxyData = gitProxyResult.status === "fulfilled" ? gitProxyResult.value : null;
        const avatarData = avatarAssetsResult.status === "fulfilled" && avatarAssetsResult.value.length > 0
          ? avatarAssetsResult.value
          : DEFAULT_AVATAR_ASSETS;

        setOverview(overviewData);
        setCliParams(cliParamsData);
        setAvatarAssets(avatarData);
        setDraftValues(buildDraftValues(cliParamsData));
        setCliTypeDraft(overviewData.cliType);
        setCliPathDraft(overviewData.cliPath || "");
        setWorkdirDraft(overviewData.workingDir);
        setTunnel(tunnelData);
        setGitProxySettings(gitProxyData);
        setGitProxyPortDraft(gitProxyData?.port || "");
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
  }, [botAlias, client]);

  useEffect(() => {
    if (!showBuildLog || !buildLogViewportRef.current) {
      return;
    }
    buildLogViewportRef.current.scrollTop = buildLogViewportRef.current.scrollHeight;
  }, [buildLogLines, buildLogSummary, showBuildLog]);

  const syncCliParams = (payload: CliParamsPayload) => {
    setCliParams(payload);
    setDraftValues(buildDraftValues(payload));
  };

  const confirmReset = async () => {
    setActionLoading("reset");
    setError("");
    setNotice("");
    try {
      await client.resetSession(botAlias);
      setNotice("当前会话已重置");
      setShowResetConfirm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置会话失败");
    } finally {
      setActionLoading("");
    }
  };

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

  const saveCliParam = async (key: string) => {
    if (!cliParams) return;
    const field = cliParams.schema[key];
    if (!field) return;

    setSavingParamKey(key);
    setError("");
    setNotice("");
    try {
      const next = await client.updateCliParam(
        botAlias,
        key,
        toRequestValue(field, draftValues[key] ?? ""),
      );
      syncCliParams(next);
      setNotice("参数已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存参数失败");
    } finally {
      setSavingParamKey("");
    }
  };

  const resetCurrentCliParams = async () => {
    setResettingCliParams(true);
    setError("");
    setNotice("");
    try {
      const next = await client.resetCliParams(botAlias);
      syncCliParams(next);
      setNotice("CLI 参数已恢复默认值");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置 CLI 参数失败");
    } finally {
      setResettingCliParams(false);
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
      const nextCliParams = await client.getCliParams(botAlias);
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setCliTypeDraft(nextBot.cliType);
      setCliPathDraft(nextBot.cliPath || nextCliPath);
      syncCliParams(nextCliParams);
      setNotice("CLI 配置已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新 CLI 配置失败");
    } finally {
      setSavingCliConfig(false);
    }
  };

  const saveWorkdir = async () => {
    const nextWorkdir = workdirDraft.trim();
    if (!nextWorkdir) {
      setError("工作目录不能为空");
      return;
    }

    setSavingWorkdir(true);
    setError("");
    setNotice("");
    try {
      const nextBot = await client.updateBotWorkdir(botAlias, nextWorkdir);
      setOverview((prev) => (prev ? { ...prev, ...nextBot } : { ...nextBot }));
      setWorkdirDraft(nextBot.workingDir);
      setNotice("工作目录已更新");
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新工作目录失败");
    } finally {
      setSavingWorkdir(false);
    }
  };

  const saveGitProxy = async () => {
    const nextPort = gitProxyPortDraft.trim();
    if (nextPort && (!/^\d+$/.test(nextPort) || Number(nextPort) < 1 || Number(nextPort) > 65535)) {
      setError("代理端口必须是 1 到 65535 之间的整数");
      return;
    }

    setSavingGitProxy(true);
    setError("");
    setNotice("");
    try {
      const nextSettings = await client.updateGitProxySettings(nextPort);
      setGitProxySettings(nextSettings);
      setGitProxyPortDraft(nextSettings.port);
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

  const restartService = async () => {
    setServiceAction("restart_service");
    setError("");
    setNotice("");
    try {
      await client.restartService();
      setNotice("已请求重启服务，请稍后刷新页面");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重启服务失败");
    } finally {
      setServiceAction("");
    }
  };

  const buildFrontend = async () => {
    setServiceAction("build_frontend");
    setError("");
    setNotice("");
    setShowBuildLog(true);
    setBuildLogLines([]);
    setBuildLogStatus("running");
    setBuildLogSummary("");
    try {
      const result = await client.runSystemScriptStream("build_web_frontend", (line) => {
        setBuildLogLines((prev) => [...prev, line]);
      });
      if (!result.success) {
        const message = result.output || "前端构建失败";
        setBuildLogStatus("error");
        setBuildLogSummary("前端构建失败");
        setError(message);
        return;
      }
      setBuildLogStatus("success");
      setBuildLogSummary("前端构建成功");
      setNotice("前端构建完成");
    } catch (err) {
      const message = err instanceof Error ? err.message : "前端构建失败";
      setBuildLogStatus("error");
      setBuildLogSummary("前端构建失败");
      setError(message);
    } finally {
      setServiceAction("");
    }
  };

  const buildLogStatusText = buildLogStatus === "running"
    ? "构建中"
    : buildLogStatus === "success"
      ? "构建成功"
      : buildLogStatus === "error"
        ? "构建失败"
        : "等待开始";

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

  return (
    <main className="flex flex-col h-full bg-[var(--bg)]">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
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

      <section className="flex-1 overflow-y-auto p-4 space-y-6">
        {loading ? (
          <div className="text-center text-[var(--muted)]">加载中...</div>
        ) : null}
        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {notice}
          </div>
        ) : null}

        {botAlias === "main" ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
            <h2 className="text-base font-semibold text-[var(--text)]">界面与阅读</h2>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {UI_THEME_OPTIONS.map((themeOption) => {
                const isActive = themeName === themeOption.value;
                return (
                  <button
                    key={themeOption.value}
                    type="button"
                    aria-label={themeOption.label}
                    aria-pressed={isActive}
                    onClick={() => handleThemeChange(themeOption.value)}
                    className={
                      isActive
                        ? "rounded-2xl border border-[var(--accent)] bg-[var(--accent-soft)] p-4 text-left shadow-sm"
                        : "rounded-2xl border border-[var(--border)] bg-[var(--bg)] p-4 text-left hover:bg-[var(--surface-strong)]"
                    }
                    >
                      <div
                        className="mb-3 rounded-2xl border p-3"
                        style={{
                          backgroundColor: themeOption.preview.surface,
                        borderColor: themeOption.preview.border,
                      }}
                    >
                      <div className="flex gap-2">
                        <span
                          className="h-3 w-8 rounded-full"
                          style={{ backgroundColor: themeOption.preview.accent }}
                        />
                        <span
                          className="h-3 w-8 rounded-full border"
                          style={{
                            backgroundColor: themeOption.preview.surface,
                            borderColor: themeOption.preview.border,
                          }}
                        />
                        <span
                          className="h-3 w-8 rounded-full"
                          style={{ backgroundColor: themeOption.preview.accentStrong }}
                        />
                      </div>
                    </div>
                    <div className="font-medium text-[var(--text)]">{themeOption.label}</div>
                  </button>
                );
              })}
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

        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
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
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 text-sm text-[var(--muted)] space-y-4">
            <div className="space-y-2">
              <p><span className="font-medium text-[var(--text)]">CLI:</span> {overview.cliType}</p>
              {overview.cliPath ? (
                <p className="break-all"><span className="font-medium text-[var(--text)]">CLI 路径:</span> {overview.cliPath}</p>
              ) : null}
              <p><span className="font-medium text-[var(--text)]">状态:</span> {overview.status}</p>
              <p className="break-all"><span className="font-medium text-[var(--text)]">目录:</span> {overview.workingDir}</p>
            </div>

            <div className="space-y-3 border-t border-[var(--border)] pt-4">
              <h2 className="font-medium text-[var(--text)]">Bot CLI 配置</h2>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-sm text-[var(--text)]">CLI 类型</span>
                  <select
                    aria-label="CLI 类型"
                    value={cliTypeDraft}
                    onChange={(event) => setCliTypeDraft(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
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
                    onChange={(event) => setCliPathDraft(event.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={() => void saveCliConfig()}
                disabled={savingCliConfig}
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
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
              <div className="flex items-center gap-2">
                <input
                  id="bot-workdir"
                  aria-label="工作目录"
                  type="text"
                  value={workdirDraft}
                  onChange={(event) => setWorkdirDraft(event.target.value)}
                  readOnly={workdirLocked}
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
                {workdirLocked ? null : (
                  <button
                    type="button"
                    onClick={() => void saveWorkdir()}
                    disabled={savingWorkdir}
                    className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                  >
                    <Save className="h-4 w-4" />
                    {savingWorkdir ? "保存中..." : "保存工作目录"}
                  </button>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {botAlias === "main" ? (
          <>
            <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
              <h2 className="text-base font-semibold text-[var(--text)]">Git 代理</h2>
              <div className="flex items-center gap-2">
                <input
                  aria-label="Git 代理端口"
                  type="text"
                  inputMode="numeric"
                  value={gitProxyPortDraft}
                  onChange={(event) => setGitProxyPortDraft(event.target.value)}
                  placeholder="例如 7897"
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                />
                <button
                  type="button"
                  onClick={() => void saveGitProxy()}
                  disabled={savingGitProxy}
                  className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                >
                  <Save className="h-4 w-4" />
                  {savingGitProxy ? "保存中..." : "保存 Git 代理"}
                </button>
              </div>
              <p className="text-xs text-[var(--muted)]">
                当前状态: {gitProxySettings?.port ? `127.0.0.1:${gitProxySettings.port}` : "直连"}
              </p>
            </div>

            <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
              <h2 className="text-base font-semibold text-[var(--text)]">服务管理</h2>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void buildFrontend()}
                  disabled={serviceAction !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {serviceAction === "build_frontend" ? "构建中..." : "重建前端"}
                </button>
                <button
                  type="button"
                  onClick={() => void restartService()}
                  disabled={serviceAction !== ""}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                >
                  {serviceAction === "restart_service" ? "重启中..." : "重启服务"}
                </button>
              </div>
            </div>
          </>
        ) : null}

        {cliParams ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--text)]">CLI 参数</h2>
                <p className="text-sm text-[var(--muted)]">当前 CLI: {cliParams.cliType}</p>
              </div>
              <button
                type="button"
                onClick={() => void resetCurrentCliParams()}
                disabled={resettingCliParams}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                <RefreshCw className="h-4 w-4" />
                {resettingCliParams ? "重置中..." : "恢复默认参数"}
              </button>
            </div>

            <div className="space-y-3">
              {Object.entries(cliParams.schema).map(([key, field]) => {
                const label = fieldLabel(key, field);
                const value = draftValues[key] ?? "";
                const inputId = `cli-param-${key}`;

                return (
                  <div key={key} className="rounded-xl border border-[var(--border)] p-3 space-y-3">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <label htmlFor={inputId} className="font-medium text-[var(--text)]">{label}</label>
                        <p className="text-xs text-[var(--muted)]">{key}</p>
                      </div>
                      <button
                        type="button"
                        aria-label={`保存 ${label}`}
                        onClick={() => void saveCliParam(key)}
                        disabled={savingParamKey === key}
                        className="inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white hover:opacity-90 disabled:opacity-60"
                      >
                        <Save className="h-4 w-4" />
                        {savingParamKey === key ? "保存中..." : "保存"}
                      </button>
                    </div>

                    {field.type === "boolean" ? (
                      <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)]">
                        <span>{label}</span>
                        <input
                          id={inputId}
                          aria-label={label}
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.checked }))}
                          className="h-4 w-4"
                        />
                      </label>
                    ) : field.enum ? (
                      <select
                        id={inputId}
                        aria-label={label}
                        value={String(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                      >
                        {field.enum.map((item) => (
                          <option key={item} value={item}>{item}</option>
                        ))}
                      </select>
                    ) : field.type === "string_list" ? (
                      <textarea
                        id={inputId}
                        aria-label={label}
                        rows={3}
                        value={String(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                        placeholder="每行一个参数"
                      />
                    ) : (
                      <input
                        id={inputId}
                        aria-label={label}
                        type={field.type === "number" ? "number" : "text"}
                        value={String(value)}
                        onChange={(event) => setDraftValues((prev) => ({ ...prev, [key]: event.target.value }))}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {tunnel ? (
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] p-4 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Globe className="h-5 w-5 text-[var(--accent)]" />
                  <h2 className="text-base font-semibold text-[var(--text)]">公网访问</h2>
                </div>
                <p className="text-sm text-[var(--muted)]">状态: {tunnelStatusText(tunnel.status)}</p>
              </div>
              <span className="rounded-full bg-[var(--surface-strong)] px-3 py-1 text-xs text-[var(--muted)]">
                {tunnel.source === "manual_config" ? "手工地址" : "Quick Tunnel"}
              </span>
            </div>

            <div className="space-y-2 text-sm text-[var(--muted)]">
              <p className="break-all"><span className="font-medium text-[var(--text)]">公网:</span> {tunnel.publicUrl || "未建立公网地址"}</p>
              <p className="break-all"><span className="font-medium text-[var(--text)]">本地:</span> {tunnel.localUrl}</p>
              {tunnel.lastError ? (
                <p className="break-all text-red-700"><span className="font-medium">错误:</span> {tunnel.lastError}</p>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-2">
              {tunnel.source !== "manual_config" ? (
                <>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("start")}
                    disabled={tunnelAction !== "" || tunnel.status === "running" || tunnel.status === "starting"}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    启动 Tunnel
                  </button>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("stop")}
                    disabled={tunnelAction !== "" || tunnel.status === "stopped"}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    停止 Tunnel
                  </button>
                  <button
                    type="button"
                    onClick={() => void runTunnelAction("restart")}
                    disabled={tunnelAction !== ""}
                    className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    <RotateCw className="h-4 w-4" />
                    重启 Tunnel
                  </button>
                </>
              ) : (
                <div className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted)]">
                  当前使用 `WEB_PUBLIC_URL` 手工配置地址
                </div>
              )}

              <button
                type="button"
                onClick={() => void copyTunnelUrl()}
                disabled={tunnelAction !== "" || !tunnel.publicUrl}
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
              >
                <Copy className="h-4 w-4" />
                复制公网地址
              </button>
            </div>
          </div>
        ) : null}

        <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] overflow-hidden divide-y divide-[var(--border)]">
          <button
            onClick={() => setShowKillConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <Square className="w-5 h-5" />
              终止当前任务
            </span>
          </button>
          <button
            onClick={() => setShowResetConfirm(true)}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)] text-[var(--danger)]"
          >
            <span className="flex items-center gap-3">
              <RefreshCw className="w-5 h-5" />
              重置当前会话
            </span>
          </button>
          <button
            onClick={onLogout}
            className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface-strong)] active:bg-[var(--border)]"
          >
            <span className="flex items-center gap-3">
              <LogOut className="w-5 h-5" />
              退出登录
            </span>
          </button>
        </div>
      </section>

      {showResetConfirm ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-sm w-full shadow-[var(--shadow-card)]">
            <div className="flex items-center gap-3 text-[var(--danger)] mb-4">
              <AlertTriangle className="w-6 h-6" />
              <h2 className="text-lg font-bold">危险操作</h2>
            </div>
            <p className="text-[var(--text)] mb-6">确定要重置当前会话吗？此操作不可恢复。</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowResetConfirm(false)}
                className="px-4 py-2 rounded-lg border border-[var(--border)] hover:bg-[var(--surface-strong)]"
              >
                取消
              </button>
              <button
                onClick={() => void confirmReset()}
                disabled={actionLoading === "reset"}
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                {actionLoading === "reset" ? "重置中..." : "确定重置"}
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
                className="px-4 py-2 rounded-lg bg-[var(--danger)] text-white hover:opacity-90"
              >
                {actionLoading === "kill" ? "终止中..." : "确定终止"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showBuildLog ? (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50" role="dialog" aria-modal="true" aria-labelledby="build-log-title">
          <div className="bg-[var(--surface)] rounded-2xl p-6 max-w-2xl w-full shadow-[var(--shadow-card)] space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <h2 id="build-log-title" className="text-lg font-bold text-[var(--text)]">前端构建日志</h2>
                <p className="text-sm text-[var(--muted)]">状态: {buildLogStatusText}</p>
              </div>
              <button
                type="button"
                onClick={() => setShowBuildLog(false)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
              >
                关闭
              </button>
            </div>

            <div
              ref={buildLogViewportRef}
              className="h-72 overflow-y-auto rounded-xl bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-slate-100 whitespace-pre-wrap break-all"
            >
              {buildLogLines.length > 0 ? buildLogLines.join("\n") : "等待构建输出..."}
            </div>

            {buildLogSummary ? (
              <div className={buildLogStatus === "success"
                ? "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700"
                : "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"}
              >
                {buildLogSummary}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </main>
  );
}
