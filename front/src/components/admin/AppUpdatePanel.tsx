import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Ban,
  ChevronRight,
  CircleArrowUp,
  CircleCheck,
  CircleX,
  Clock3,
  Download,
  FileArchive,
  FileUp,
  FolderOpen,
  HardDriveDownload,
  HeartPulse,
  LifeBuoy,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  Rocket,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  Undo2,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import type { AppUpdateJob, AppUpdatePhase, AppUpdateStatus, OfflineUpdatePackageList } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { APP_VERSION } from "../../theme";
import { getErrorMessage } from "../../utils/errorMessage";
import "./AppUpdatePanel.css";

type Tone = "accent" | "info" | "success" | "warning" | "danger" | "neutral";
/** Which island shows an action's error, so it lands next to the button that caused it. */
type ActionScope = "overview" | "job" | "offline";

const PHASES: Record<AppUpdatePhase, string> = {
  preparing: "正在准备", ready: "准备完成，等待确认", waiting_restart: "等待服务重启",
  applying: "正在应用文件", awaiting_health: "等待新版本健康确认", succeeded: "升级成功",
  failed: "升级失败", cancelled: "已取消", rolling_back: "正在恢复旧版本",
  rolled_back: "已恢复旧版本", recovery_required: "需要人工恢复",
};
const PHASE_TONES: Record<AppUpdatePhase, Tone> = {
  preparing: "accent", ready: "success", waiting_restart: "accent", applying: "accent", awaiting_health: "accent",
  succeeded: "success", failed: "danger", cancelled: "neutral", rolling_back: "warning",
  rolled_back: "warning", recovery_required: "danger",
};
const PHASE_ICONS: Record<AppUpdatePhase, LucideIcon> = {
  preparing: Download, ready: PackageCheck, waiting_restart: RefreshCw, applying: RefreshCw, awaiting_health: HeartPulse,
  succeeded: CircleCheck, failed: CircleX, cancelled: Ban, rolling_back: Undo2,
  rolled_back: Undo2, recovery_required: LifeBuoy,
};
const RETRY_PHASES = new Set(["failed", "cancelled"]);
const LOG_PHASES = new Set(["failed", "rolled_back", "recovery_required"]);
const DOWNTIME_PHASES = new Set(["waiting_restart", "applying", "awaiting_health", "rolling_back"]);
const DOWNTIME_MESSAGE = "服务正在重启并应用更新，期间暂时无法连接，页面会自动重试。";
const OPEN_JOB_PHASES = new Set(["preparing", "ready", "waiting_restart", "applying", "awaiting_health", "rolling_back"]);
const RUNNING_PHASES = new Set(["preparing", "waiting_restart", "applying", "awaiting_health", "rolling_back"]);
const ACTION_SCOPES: Record<string, ActionScope> = {
  check: "overview", prepare: "overview", apply: "job", cancel: "job", retry: "job", offline: "offline", upload: "offline",
};
const PACKAGE_LABELS: Record<string, string> = { installer: "Windows 安装版", portable: "Windows 绿色版", linux: "Linux", macos: "macOS" };
const SPIN = " animate-spin motion-reduce:animate-none";

function packageLabel(kind?: string) {
  return PACKAGE_LABELS[kind || ""] || "未知";
}

function normalizeVersion(version = "") {
  return version.replace(/^v/, "");
}

/** "1.5.0" and "v1.5.0" both read as "v1.5.0"; non-numeric builds are shown as-is. */
function displayVersion(version = "") {
  const normalized = normalizeVersion(version.trim());
  return /^\d/.test(normalized) ? `v${normalized}` : normalized;
}

function versionMatches(status: AppUpdateStatus) {
  return Boolean(status.currentVersion && status.job?.targetVersion)
    && normalizeVersion(status.currentVersion) === normalizeVersion(status.job?.targetVersion);
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 1024) return `${Math.max(0, Math.round(bytes || 0))} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

function formatCheckedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

type CalloutProps = {
  tone: Exclude<Tone, "accent" | "neutral">;
  icon: LucideIcon;
  role?: "alert" | "status";
  spin?: boolean;
  action?: ReactNode;
  children: ReactNode;
};

function Callout({ tone, icon: Icon, role, spin = false, action, children }: CalloutProps) {
  return (
    <div role={role} className="admin-callout update-callout" data-tone={tone}>
      <Icon className={`h-4 w-4 flex-none${spin ? SPIN : ""}`} aria-hidden="true" />
      <div className="update-callout-body">{children}</div>
      {action}
    </div>
  );
}

export function AppUpdatePanel({ client, refreshKey = 0 }: { client: WebBotClient; refreshKey?: number }) {
  const [status, setStatus] = useState<AppUpdateStatus | null>(null);
  const snapshot = useRef<AppUpdateStatus | null>(null);
  const [packages, setPackages] = useState<OfflineUpdatePackageList | null>(null);
  const [packagesLoading, setPackagesLoading] = useState(true);
  const [packageError, setPackageError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionScope, setActionScope] = useState<ActionScope>("overview");
  const [checkError, setCheckError] = useState("");
  const [toggleError, setToggleError] = useState("");
  const [action, setAction] = useState("");
  const [toggleSaving, setToggleSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const transientActionError = useRef(false);
  const [confirmJob, setConfirmJob] = useState<AppUpdateJob | null>(null);
  const [hostPath, setHostPath] = useState("");
  const [upload, setUpload] = useState<File | null>(null);
  const mutationEpoch = useRef(0);
  const mounted = useRef(false);
  const uid = useId();

  const acceptStatus = useCallback((next: AppUpdateStatus) => {
    if (!mounted.current) return;
    if (snapshot.current && next.revision < snapshot.current.revision) return;
    snapshot.current = next;
    setStatus(next);
  }, []);

  const queryStatus = useCallback(async () => {
    const epoch = mutationEpoch.current;
    try {
      const next = await client.getCurrentUpdateJob();
      if (!mounted.current || epoch !== mutationEpoch.current) return;
      acceptStatus(next);
      setConnectionError("");
      setConfirming(false);
      if (transientActionError.current) {
        setActionError("");
        transientActionError.current = false;
      }
    } catch (error) {
      if (!mounted.current || epoch !== mutationEpoch.current) return;
      setConnectionError(DOWNTIME_PHASES.has(snapshot.current?.job?.phase || "")
        ? DOWNTIME_MESSAGE : getErrorMessage(error, "无法连接升级服务"));
      setConfirming(true);
    }
  }, [client, acceptStatus]);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await queryStatus();
      if (!active) return;
      timer = setTimeout(() => void poll(), 2000);
    };
    void poll();
    return () => { active = false; mounted.current = false; clearTimeout(timer); };
  }, [queryStatus, refreshKey]);

  useEffect(() => {
    let active = true;
    setPackagesLoading(true);
    void client.listOfflineUpdatePackages().then((next) => {
      if (!active) return;
      setPackages(next);
      setPackageError("");
    }).catch((error) => {
      if (active) setPackageError(getErrorMessage(error, "离线包列表加载失败"));
    }).finally(() => { if (active) setPackagesLoading(false); });
    return () => { active = false; };
  }, [client, refreshKey]);

  async function runAction(name: string, request: () => Promise<AppUpdateStatus>) {
    mutationEpoch.current += 1;
    setAction(name);
    setActionError("");
    setActionScope(ACTION_SCOPES[name] || "overview");
    transientActionError.current = false;
    try {
      const next = await request();
      if (!mounted.current) return;
      acceptStatus(next);
      if (name === "check") setCheckError(next.lastCheck.error);
    } catch (error) {
      if (!mounted.current) return;
      const message = getErrorMessage(error, "升级操作失败");
      setActionError(message);
      transientActionError.current = error instanceof TypeError;
      if (name === "check") setCheckError(message);
      setConfirming(true);
    } finally {
      if (mounted.current) {
        setAction("");
        // A response, lost response, or conflict all resolve against persisted state.
        void queryStatus();
      }
    }
  }

  async function saveToggle(enabled: boolean) {
    setToggleSaving(true);
    setToggleError("");
    try {
      acceptStatus(await client.setUpdateEnabled(enabled));
    } catch (error) {
      if (mounted.current) setToggleError(getErrorMessage(error, "保存自动检查设置失败"));
    } finally {
      if (mounted.current) setToggleSaving(false);
    }
  }

  const job = status?.job;
  const busy = Boolean(action) || confirming || !status;
  const canPrepare = !busy && (!job || ["succeeded", "failed", "cancelled", "rolled_back"].includes(job.phase));
  const launcher = status?.launcher;
  const launcherReady = Boolean(launcher?.supported && launcher.protocol === 1);
  const confirmedSuccess = job?.phase === "succeeded" && status && versionMatches(status) && !confirming;
  const staleConfirmation = confirmJob && (job?.jobId !== confirmJob.jobId || job?.revision !== confirmJob.revision || job?.phase !== "ready");
  const percent = Number.isFinite(job?.progress.percent) ? Math.min(100, Math.max(0, job!.progress.percent!)) : undefined;
  const totalBytes = job?.progress.totalBytes;
  const notes = status?.pendingUpdateNotes || status?.latestNotes;
  const checkFailed = Boolean(status?.lastCheck.cached || checkError || status?.lastCheck.error || status?.lastCheck.ok === false);
  const updateAvailable = Boolean(status?.updateAvailable);
  const canPrepareOnline = canPrepare && Boolean(status?.latestVersion) && updateAvailable && !checkFailed;
  const targetVersion = job?.targetVersion || (updateAvailable ? status?.pendingUpdateVersion || status?.latestVersion : "") || "";
  const targetPending = Boolean(targetVersion) && normalizeVersion(targetVersion) !== normalizeVersion(status?.currentVersion);
  const staleBundle = Boolean(confirmedSuccess && normalizeVersion(APP_VERSION) !== normalizeVersion(status?.currentVersion));
  // An offline package can be newer than the last online check; never call that state up to date.
  const jobTargetsOtherVersion = Boolean(job && OPEN_JOB_PHASES.has(job.phase) && job.targetVersion
    && normalizeVersion(job.targetVersion) !== normalizeVersion(status?.currentVersion));
  const checkResult = status?.lastCheck.ok === true && !checkFailed && (updateAvailable || !jobTargetsOtherVersion)
    ? updateAvailable
      ? { tone: "accent" as const, text: `发现新版本 v${normalizeVersion(status.latestVersion)}` }
      : { tone: "success" as const, text: `已是最新版本（v${normalizeVersion(status.currentVersion)}）` }
    : null;
  const recoveryArgs = job?.result && typeof job.result === "object" && "recovery_command" in job.result
    ? (job.result as { recovery_command?: unknown }).recovery_command : null;
  const windowsCommand = ["installer", "portable"].includes(status?.currentPackageKind || "");
  const recoveryCommand = Array.isArray(recoveryArgs) && recoveryArgs.every((part) => typeof part === "string")
    ? (windowsCommand ? "& " : "") + recoveryArgs.map((part) => `'${part.replaceAll("'", windowsCommand ? "''" : "'\\''")}'`).join(" ") : "";

  const verifying = job?.phase === "succeeded" && !confirmedSuccess;
  const running = Boolean(job && (RUNNING_PHASES.has(job.phase) || verifying));
  const phaseLabel = !job ? "" : job.phase === "succeeded" ? (confirmedSuccess ? "升级成功" : "正在核对运行版本") : PHASES[job.phase] || job.phase;
  const phaseTone: Tone = !job ? "neutral" : verifying ? "accent" : PHASE_TONES[job.phase] || "neutral";
  const PhaseIcon = !job ? PackageCheck : verifying ? Activity : PHASE_ICONS[job.phase] || PackageCheck;
  const jobRoute = job
    ? [`${displayVersion(job.currentVersion) || "未知"} → ${displayVersion(job.targetVersion) || "未知"}`, PACKAGE_LABELS[job.packageKind]]
      .filter(Boolean).join(" · ")
    : "";
  const canCancel = Boolean(job && ["preparing", "ready"].includes(job.phase));
  const canRetry = Boolean(job && (RETRY_PHASES.has(job.phase) || (job.phase === "ready" && job.requiresPreparation)));
  const canApply = job?.phase === "ready" && !busy && !job.requiresPreparation && launcherReady;
  const errorScope: ActionScope = actionScope === "job" && !job ? "overview" : actionScope;
  // A failed manual check already shows its message in the cached-check callout.
  const scopedError = (scope: ActionScope) => (actionError && errorScope === scope && !(scope === "overview" && checkFailed && actionError === checkError)
    ? <Callout tone="danger" icon={TriangleAlert} role="alert">{actionError}</Callout>
    : null);
  const confirmingCallout = confirming ? (
    <Callout tone={DOWNTIME_PHASES.has(job?.phase || "") ? "info" : "warning"} icon={LoaderCircle} spin role="status">
      正在确认后台状态，连接恢复后将核对任务结果与运行版本。{connectionError}
    </Callout>
  ) : null;

  return (
    <section aria-label="升级" className="admin-stack update-center">
      {!job && confirmingCallout}

      <section aria-labelledby={`${uid}-overview`} className="admin-island orbit-island orbit-island--reading update-island">
        <header className="update-head">
          <span className="update-head-icon" aria-hidden="true"><CircleArrowUp className="h-4 w-4" /></span>
          <div className="update-head-copy">
            <h2 id={`${uid}-overview`}>程序版本</h2>
            {status ? (
              <p>{status.lastCheck.checkedAt ? `最近检查 ${formatCheckedAt(status.lastCheck.checkedAt)}` : "尚未检查更新"}</p>
            ) : confirming ? (
              <p>暂未获取升级状态</p>
            ) : (
              <p role="status">正在加载升级状态...</p>
            )}
          </div>
          {checkResult && (
            <span className="orbit-chip update-chip" data-tone={checkResult.tone}>
              <span className="update-dot" aria-hidden="true" />
              {checkResult.text}
            </span>
          )}
        </header>

        {status?.lastError && status.lastError !== job?.error && status.lastError !== actionError && (
          <Callout tone="danger" icon={TriangleAlert} role="alert">{status.lastError}</Callout>
        )}
        {scopedError("overview")}
        {checkFailed && (
          <Callout tone="warning" icon={TriangleAlert} role={checkError ? "alert" : undefined}>
            检查失败，版本信息为缓存。{checkError || status?.lastCheck.error}
          </Callout>
        )}

        <div className="update-versions" data-pending={targetPending || undefined}>
          <dl className="update-version">
            <dt>当前运行版本</dt>
            <dd className="update-version-value">{displayVersion(status?.currentVersion) || "未知"}</dd>
            <dd className="update-version-meta">{packageLabel(status?.currentPackageKind)}</dd>
          </dl>
          <ArrowRight className="update-versions-arrow" aria-hidden="true" />
          <dl className="update-version" data-emphasis={targetPending || undefined} data-empty={!targetVersion || undefined}>
            <dt>目标版本</dt>
            <dd className="update-version-value">{displayVersion(targetVersion) || "暂无"}</dd>
            {status?.latestReleaseUrl && (
              <dd className="update-version-meta">
                <a href={status.latestReleaseUrl} target="_blank" rel="noreferrer">
                  查看发布页
                  <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              </dd>
            )}
          </dl>
        </div>

        {launcher && (launcherReady ? (
          <div className="update-launcher">
            <ShieldCheck className="h-4 w-4 flex-none" aria-hidden="true" />
            <div className="update-launcher-copy">
              <p>启动器支持自动应用更新</p>
              {launcher.reason && <p className="update-launcher-reason">{launcher.reason}</p>}
            </div>
          </div>
        ) : (
          <Callout tone="warning" icon={ShieldAlert}>
            <p className="update-callout-title">当前启动方式不支持自动应用</p>
            {launcher.reason && <p>{launcher.reason}</p>}
            {launcher.command && (
              <>
                <p>在宿主机器退出当前服务后，使用以下命令启动，再返回此页面确认应用：</p>
                <pre className="update-code">{launcher.command}</pre>
              </>
            )}
          </Callout>
        ))}

        {notes && (
          <details className="update-notes">
            <summary>
              <ChevronRight className="update-notes-chevron h-4 w-4" aria-hidden="true" />
              发布说明
            </summary>
            <div className="update-notes-body">{notes}</div>
          </details>
        )}

        <div className="update-setting">
          <label className="update-setting-row">
            <span>自动检查并准备更新</span>
            <input
              type="checkbox"
              aria-describedby={`${uid}-auto-hint`}
              checked={Boolean(status?.updateEnabled)}
              disabled={toggleSaving || !status}
              onChange={(event) => void saveToggle(event.target.checked)}
            />
          </label>
          <p id={`${uid}-auto-hint`} className="update-setting-hint">宿主启动时及每 6 小时检查一次；准备完成后仍需手动确认应用。</p>
          {toggleError && <p role="alert" className="update-inline-error">{toggleError}</p>}
        </div>

        <footer className="update-foot">
          <button type="button" className="orbit-btn orbit-btn--ghost" onClick={() => void queryStatus()}>
            <Activity className="h-4 w-4" aria-hidden="true" />
            查询后台状态
          </button>
          <div className="update-foot-actions">
            <button type="button" className="orbit-btn orbit-btn--secondary" disabled={busy} onClick={() => void runAction("check", () => client.checkForUpdate())}>
              <RefreshCw className={`h-4 w-4${action === "check" ? SPIN : ""}`} aria-hidden="true" />
              {action === "check" ? "检查中..." : "检查更新"}
            </button>
            <button
              type="button"
              className={`orbit-btn ${canPrepareOnline || action === "prepare" ? "orbit-btn--primary" : "orbit-btn--secondary"}`}
              disabled={!canPrepareOnline}
              onClick={() => void runAction("prepare", () => client.downloadUpdate())}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {action === "prepare" ? "提交准备中..." : "准备更新"}
            </button>
          </div>
        </footer>
      </section>

      {job && (
        <section
          aria-labelledby={`${uid}-job`}
          data-testid="update-job"
          data-tone={phaseTone}
          data-running={running || undefined}
          className="admin-island orbit-island orbit-island--reading update-island update-job"
        >
          {running && <span className="orbit-sweep" aria-hidden="true" />}
          <header className="update-head">
            <span className="update-head-icon" data-tone={phaseTone} aria-hidden="true"><PhaseIcon className="h-4 w-4" /></span>
            <div className="update-head-copy">
              <h2 id={`${uid}-job`}>升级任务</h2>
              <p>{jobRoute}</p>
            </div>
            <span role="status" className="orbit-chip update-chip" data-tone={phaseTone}>
              <span className="update-dot" data-running={running || undefined} aria-hidden="true" />
              <span className="sr-only">任务阶段: </span>
              {phaseLabel}
            </span>
          </header>

          {confirmingCallout}
          {staleBundle && (
            <Callout
              tone="success"
              icon={CircleCheck}
              role="status"
              action={(
                <button type="button" className="orbit-btn orbit-btn--secondary orbit-btn--sm" onClick={() => window.location.reload()}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  刷新页面
                </button>
              )}
            >
              新版本已运行，当前页面仍是旧版本界面，请刷新页面以加载新版本。
            </Callout>
          )}
          {scopedError("job")}

          {(job.progress.message || percent !== undefined || totalBytes !== undefined) && (
            <div className="update-progress">
              {(job.progress.message || percent !== undefined) && (
                <div className="update-progress-head">
                  <span className="update-progress-message">{job.progress.message}</span>
                  {percent !== undefined && <span className="update-progress-percent">{Math.round(percent)}%</span>}
                </div>
              )}
              {percent !== undefined && (
                <div
                  role="progressbar"
                  aria-label="升级进度"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(percent)}
                  className="update-progress-track"
                >
                  <span className="update-progress-fill" style={{ width: `${percent}%` }} />
                </div>
              )}
              {totalBytes !== undefined && (
                <p className="update-progress-bytes">已处理 {formatBytes(job.progress.downloadedBytes)} / {formatBytes(totalBytes)}</p>
              )}
            </div>
          )}

          {job.error && <Callout tone="danger" icon={CircleX} role="alert">{job.error}</Callout>}
          {job.requiresPreparation && <Callout tone="warning" icon={RotateCcw}>该任务需要重新准备后才能应用。</Callout>}
          {job.phase === "recovery_required" && (
            <Callout tone="danger" icon={LifeBuoy}>
              <p>请保留恢复材料并按宿主日志恢复。</p>
              {recoveryCommand && <pre className="update-code">{recoveryCommand}</pre>}
            </Callout>
          )}
          {verifying && (
            <p className="update-note">目标版本 {job.targetVersion}，当前运行版本 {status?.currentVersion || "未知"}。等待服务端确认。</p>
          )}

          <dl className="update-facts">
            <div><dt>任务 ID</dt><dd>{job.jobId}</dd></div>
            {LOG_PHASES.has(job.phase) && job.preparationLog && <div><dt>准备日志</dt><dd>{job.preparationLog}</dd></div>}
            {LOG_PHASES.has(job.phase) && job.runnerLog && <div><dt>执行日志</dt><dd>{job.runnerLog}</dd></div>}
            {job.phase === "recovery_required" && (
              <>
                <div><dt>备份目录</dt><dd>{job.backupDir || "见任务目录"}</dd></div>
                <div><dt>任务目录</dt><dd>{job.jobDir}</dd></div>
              </>
            )}
          </dl>

          {(canCancel || canRetry || job.phase === "ready") && (
            <footer className="update-foot">
              <div className="update-foot-actions">
                {canCancel && (
                  <button type="button" className="orbit-btn orbit-btn--secondary" disabled={busy} onClick={() => void runAction("cancel", () => client.cancelUpdateJob(job.jobId, job.revision))}>
                    <X className="h-4 w-4" aria-hidden="true" />
                    取消准备
                  </button>
                )}
                {canRetry && (
                  <button type="button" className="orbit-btn orbit-btn--primary" disabled={busy} onClick={() => void runAction("retry", () => client.retryUpdateJob(job.jobId, job.revision))}>
                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                    重试
                  </button>
                )}
                {job.phase === "ready" && (
                  <button type="button" className={`orbit-btn ${canApply ? "orbit-btn--primary" : "orbit-btn--secondary"}`} disabled={!canApply} onClick={() => setConfirmJob(job)}>
                    <Rocket className="h-4 w-4" aria-hidden="true" />
                    应用更新
                  </button>
                )}
              </div>
            </footer>
          )}
        </section>
      )}

      <section aria-labelledby={`${uid}-offline`} className="admin-island orbit-island orbit-island--reading update-island">
        <header className="update-head">
          <span className="update-head-icon" aria-hidden="true"><HardDriveDownload className="h-4 w-4" /></span>
          <div className="update-head-copy">
            <h2 id={`${uid}-offline`}>离线升级</h2>
            <p>使用宿主机器上的离线包，或从此设备上传升级包</p>
          </div>
          {packages && <span className="orbit-chip">{packages.items.length} 个离线包</span>}
        </header>

        {scopedError("offline")}

        <div className="update-field">
          <div className="update-field-head">
            <span className="update-label">宿主离线包目录</span>
            <span className="update-path">
              <FolderOpen className="h-3.5 w-3.5 flex-none" aria-hidden="true" />
              {packages?.artifactsDir || "尚未加载"}
            </span>
          </div>
          {packagesLoading && <p role="status" className="update-muted">正在加载离线包...</p>}
          {packageError && <Callout tone="danger" icon={TriangleAlert} role="alert">{packageError}</Callout>}
          {packages && (packages.items.length > 0 ? (
            <ul className="update-packages">
              {packages.items.map((item) => (
                <li key={item.path} className="update-package" data-invalid={!item.valid || undefined}>
                  <span className="update-package-icon" aria-hidden="true">
                    {item.valid ? <FileArchive className="h-4 w-4" /> : <TriangleAlert className="h-4 w-4" />}
                  </span>
                  <div className="update-package-body">
                    <p className="update-package-name">{item.name}</p>
                    <p className="update-package-meta">
                      <span>{packageLabel(item.packageKind)}</span>
                      {item.version && <span>{displayVersion(item.version)}</span>}
                      <span>{formatBytes(item.sizeBytes)}</span>
                    </p>
                    {!item.valid && <p className="update-package-error">{item.error || "包校验失败"}</p>}
                  </div>
                  {item.valid ? (
                    <button
                      type="button"
                      aria-label={`准备离线包 ${item.name}`}
                      className="orbit-btn orbit-btn--secondary orbit-btn--sm"
                      disabled={!canPrepare}
                      onClick={() => void runAction("offline", () => client.prepareOfflineUpdate(item.path, item.version))}
                    >
                      准备
                    </button>
                  ) : (
                    <span className="orbit-chip" data-tone="danger">校验失败</span>
                  )}
                </li>
              ))}
            </ul>
          ) : !packagesLoading && (
            <div className="update-empty">
              <strong>目录中暂无离线包</strong>
              <span>将升级包放入该目录后刷新即可显示</span>
            </div>
          ))}
        </div>

        <div className="update-field">
          <label htmlFor={`${uid}-host-path`} className="update-label">宿主机器上的离线包路径</label>
          <div className="update-inline">
            <input
              id={`${uid}-host-path`}
              value={hostPath}
              onChange={(event) => setHostPath(event.target.value)}
              className="orbit-field"
              placeholder={"例如 C:\\Downloads\\update.zip"}
              spellCheck={false}
              autoComplete="off"
            />
            <button
              type="button"
              className="orbit-btn orbit-btn--secondary"
              disabled={!canPrepare || !hostPath.trim()}
              onClick={() => void runAction("offline", () => client.prepareOfflineUpdate(hostPath.trim()))}
            >
              准备宿主离线包
            </button>
          </div>
        </div>

        <div className="update-field">
          <span id={`${uid}-upload`} className="update-label">从此设备上传升级包</span>
          <div className="update-inline">
            {/* The transparent input covers the whole picker, so clicks and native file drops both reach it. */}
            <label className="update-file" data-selected={upload ? true : undefined} data-disabled={!canPrepare || undefined}>
              <input
                type="file"
                accept=".zip,.tar.gz,.tgz"
                aria-labelledby={`${uid}-upload`}
                aria-describedby={`${uid}-upload-hint`}
                disabled={!canPrepare}
                onChange={(event) => setUpload(event.target.files?.[0] || null)}
              />
              <FileUp className="h-4 w-4 flex-none" aria-hidden="true" />
              <span className="update-file-name">{upload ? upload.name : "选择或拖入升级包"}</span>
              <span id={`${uid}-upload-hint`} className="update-file-hint">{upload ? formatBytes(upload.size) : ".zip / .tar.gz / .tgz"}</span>
            </label>
            <button
              type="button"
              className="orbit-btn orbit-btn--secondary"
              disabled={!canPrepare || !upload}
              onClick={() => upload && void runAction("upload", () => client.uploadOfflineUpdate(upload))}
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              {action === "upload" ? "上传中..." : "上传并准备"}
            </button>
          </div>
        </div>
      </section>

      {/* Portalled: a fixed overlay inside a backdrop-filtered island would be clipped to that island. */}
      {confirmJob && createPortal(
        <div className="orbit-backdrop fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby={`${uid}-confirm`}
            aria-describedby={`${uid}-confirm-body`}
            className="orbit-dialog update-confirm"
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.stopPropagation();
              setConfirmJob(null);
            }}
          >
            <header className="update-head update-confirm-head">
              <span className="update-head-icon" aria-hidden="true"><Rocket className="h-4 w-4" /></span>
              <div className="update-head-copy">
                <h2 id={`${uid}-confirm`}>确认应用更新</h2>
                <p>{displayVersion(confirmJob.currentVersion) || "当前版本"} → {displayVersion(confirmJob.targetVersion) || "目标版本"}</p>
              </div>
            </header>
            <div id={`${uid}-confirm-body`} className="update-confirm-body">
              <p>即将应用 {displayVersion(confirmJob.targetVersion) || confirmJob.targetVersion}。</p>
              <ul className="update-confirm-list">
                <li><Clock3 className="h-4 w-4" aria-hidden="true" />替换文件期间服务将暂时断开（通常不超过两分钟）</li>
                <li><RefreshCw className="h-4 w-4" aria-hidden="true" />页面会自动重新连接并核对运行版本</li>
                <li><ShieldCheck className="h-4 w-4" aria-hidden="true" />新版本健康检查失败时会自动恢复旧版本</li>
              </ul>
              {staleConfirmation && <Callout tone="danger" icon={TriangleAlert} role="alert">任务状态已变化，请关闭确认框并重新确认。</Callout>}
            </div>
            <footer className="update-confirm-foot">
              <button type="button" autoFocus className="orbit-btn orbit-btn--ghost" onClick={() => setConfirmJob(null)}>暂不应用</button>
              <button
                type="button"
                className="orbit-btn orbit-btn--primary"
                disabled={busy || Boolean(staleConfirmation) || job?.requiresPreparation || !launcherReady}
                onClick={() => {
                  setConfirmJob(null);
                  void runAction("apply", () => client.applyUpdateJob(confirmJob.jobId, confirmJob.revision));
                }}
              >
                <Rocket className="h-4 w-4" aria-hidden="true" />
                确认应用并重启服务
              </button>
            </footer>
          </section>
        </div>,
        document.body,
      )}
    </section>
  );
}
