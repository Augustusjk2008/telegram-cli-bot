import { useCallback, useEffect, useRef, useState } from "react";
import type { AppUpdateJob, AppUpdatePhase, AppUpdateStatus, OfflineUpdatePackageList } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { getErrorMessage } from "../../utils/errorMessage";

const PHASES: Record<AppUpdatePhase, string> = {
  preparing: "正在准备", ready: "准备完成，等待确认", waiting_restart: "等待服务重启",
  applying: "正在应用文件", awaiting_health: "等待新版本健康确认", succeeded: "升级成功",
  failed: "升级失败", cancelled: "已取消", rolling_back: "正在恢复旧版本",
  rolled_back: "已恢复旧版本", recovery_required: "需要人工恢复",
};
const RETRY_PHASES = new Set(["failed", "cancelled"]);
const buttonClass = "rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60";
const errorClass = "whitespace-pre-wrap break-words text-sm text-[var(--feedback-error-text-deep)]";

function packageLabel(kind?: string) {
  return ({ installer: "Windows 安装版", portable: "Windows 绿色版", linux: "Linux", macos: "macOS" } as Record<string, string>)[kind || ""] || "未知";
}

function versionMatches(status: AppUpdateStatus) {
  return Boolean(status.currentVersion && status.job?.targetVersion)
    && status.currentVersion.replace(/^v/, "") === status.job?.targetVersion.replace(/^v/, "");
}

export function AppUpdatePanel({ client, refreshKey = 0 }: { client: WebBotClient; refreshKey?: number }) {
  const [status, setStatus] = useState<AppUpdateStatus | null>(null);
  const snapshot = useRef<AppUpdateStatus | null>(null);
  const [packages, setPackages] = useState<OfflineUpdatePackageList | null>(null);
  const [packagesLoading, setPackagesLoading] = useState(true);
  const [packageError, setPackageError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [actionError, setActionError] = useState("");
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
      setConnectionError(getErrorMessage(error, "无法连接升级服务"));
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
      if (mounted.current) setToggleError(getErrorMessage(error, "保存自动下载设置失败"));
    } finally {
      if (mounted.current) setToggleSaving(false);
    }
  }

  const job = status?.job;
  const busy = Boolean(action) || confirming || !status;
  const canPrepare = !busy && (!job || ["succeeded", "failed", "cancelled", "rolled_back"].includes(job.phase));
  const launcher = status?.launcher;
  const confirmedSuccess = job?.phase === "succeeded" && status && versionMatches(status) && !confirming;
  const staleConfirmation = confirmJob && (job?.jobId !== confirmJob.jobId || job?.revision !== confirmJob.revision || job?.phase !== "ready");
  const percent = Number.isFinite(job?.progress.percent) ? Math.min(100, Math.max(0, job!.progress.percent!)) : undefined;
  const notes = status?.pendingUpdateNotes || status?.latestNotes;
  const recoveryArgs = job?.result && typeof job.result === "object" && "recovery_command" in job.result
    ? (job.result as { recovery_command?: unknown }).recovery_command : null;
  const windowsCommand = ["installer", "portable"].includes(status?.currentPackageKind || "");
  const recoveryCommand = Array.isArray(recoveryArgs) && recoveryArgs.every((part) => typeof part === "string")
    ? (windowsCommand ? "& " : "") + recoveryArgs.map((part) => `'${part.replaceAll("'", windowsCommand ? "''" : "'\\''")}'`).join(" ") : "";

  return (
    <section aria-labelledby="update-center-title" className="min-w-0 space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-[var(--text)]">
      <h2 id="update-center-title" className="text-base font-semibold">升级</h2>
      {!status && !confirming && <p role="status">正在加载升级状态...</p>}
      <div className="grid grid-cols-1 gap-3 break-words text-sm sm:grid-cols-2">
        <p>当前运行版本: {status?.currentVersion || "未知"}</p>
        <p>当前包: {packageLabel(status?.currentPackageKind)}</p>
        <p>目标版本: {job?.targetVersion || status?.pendingUpdateVersion || status?.latestVersion || "暂无"}</p>
        <p>最近检查: {status?.lastCheck.checkedAt || "尚未检查"}</p>
      </div>
      {(status?.lastCheck.cached || checkError || status?.lastCheck.error || status?.lastCheck.ok === false) && (
        <p className={errorClass}>检查失败，版本信息为缓存。{checkError || status?.lastCheck.error}</p>
      )}
      {status?.lastCheck.ok === true && !checkError && <p className="text-sm">最近检查成功</p>}
      {notes && <details className="text-sm"><summary>发布说明</summary><div className="mt-2 whitespace-pre-wrap break-words">{notes}</div></details>}
      {launcher && <div className="space-y-2 text-sm">
        <p>{launcher.supported && launcher.protocol === 1 ? "启动器支持自动应用更新" : "当前启动方式不支持自动应用"}</p>
        {launcher.reason && <p className="break-words">{launcher.reason}</p>}
        {(!launcher.supported || launcher.protocol !== 1) && launcher.command && <>
          <p>在宿主机器退出当前服务后，使用以下命令启动，再返回此页面确认应用：</p>
          <pre className="whitespace-pre-wrap break-all rounded-lg bg-[var(--bg)] p-3">{launcher.command}</pre>
        </>}
      </div>}
      {confirming && <p role="status" className="text-sm">正在确认后台状态，连接恢复后将核对任务结果与运行版本。{connectionError}</p>}
      {actionError && <p role="alert" className={errorClass}>{actionError}</p>}
      {status?.lastError && status.lastError !== job?.error && status.lastError !== actionError && <p role="alert" className={errorClass}>{status.lastError}</p>}
      {job && <div data-testid="update-job" className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 text-sm">
        <p role="status">任务阶段: {job.phase === "succeeded" ? (confirmedSuccess ? "升级成功" : "正在核对运行版本") : PHASES[job.phase] || job.phase}</p>
        <p className="break-all">任务: {job.jobId} · 修订: {job.revision}</p>
        {job.progress.message && <p className="whitespace-pre-wrap break-words">{job.progress.message}</p>}
        {percent !== undefined && <div className="flex items-center gap-2"><progress aria-label="升级进度" className="min-w-0 flex-1" max={100} value={percent} /><span>{Math.round(percent)}%</span></div>}
        {job.progress.totalBytes !== undefined && <p>已处理: {job.progress.downloadedBytes} / {job.progress.totalBytes} 字节</p>}
        {job.error && <p role="alert" className={errorClass}>{job.error}</p>}
        {job.requiresPreparation && <p>该任务需要重新准备后才能应用。</p>}
        {job.phase === "recovery_required" && <div className="space-y-2">
          <p className="break-all">请保留恢复材料并按宿主日志恢复。备份: {job.backupDir || "见任务目录"}；任务目录: {job.jobDir}</p>
          {recoveryCommand && <pre className="whitespace-pre-wrap break-all">{recoveryCommand}</pre>}
        </div>}
        {job.phase === "succeeded" && !confirmedSuccess && <p>目标版本 {job.targetVersion}，当前运行版本 {status?.currentVersion || "未知"}。等待服务端确认。</p>}
        <div className="flex flex-wrap gap-2">
          {job.phase === "ready" && <button className={buttonClass} disabled={busy || job.requiresPreparation || !launcher?.supported || launcher.protocol !== 1} onClick={() => setConfirmJob(job)}>应用更新</button>}
          {["preparing", "ready"].includes(job.phase) && <button className={buttonClass} disabled={busy} onClick={() => void runAction("cancel", () => client.cancelUpdateJob(job.jobId, job.revision))}>取消准备</button>}
          {(RETRY_PHASES.has(job.phase) || (job.phase === "ready" && job.requiresPreparation)) && <button className={buttonClass} disabled={busy} onClick={() => void runAction("retry", () => client.retryUpdateJob(job.jobId, job.revision))}>重试</button>}
        </div>
      </div>}
      <label className="flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] px-3 py-3 text-sm">
        自动下载更新
        <input type="checkbox" checked={Boolean(status?.updateEnabled)} disabled={toggleSaving || !status} onChange={(event) => void saveToggle(event.target.checked)} />
      </label>
      {toggleError && <p role="alert" className={errorClass}>{toggleError}</p>}
      <div className="flex flex-wrap gap-2">
        <button className={buttonClass} disabled={busy} onClick={() => void runAction("check", () => client.checkForUpdate())}>{action === "check" ? "检查中..." : "检查更新"}</button>
        <button className={buttonClass} disabled={!canPrepare || !status?.latestVersion || Boolean(checkError || status.lastCheck.error || status.lastCheck.cached || status.lastCheck.ok === false)} onClick={() => void runAction("prepare", () => client.downloadUpdate())}>{action === "prepare" ? "提交准备中..." : "准备更新"}</button>
        <button className={buttonClass} onClick={() => void queryStatus()}>查询后台状态</button>
      </div>
      <div className="min-w-0 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 text-sm">
        <h3 className="font-semibold">离线升级</h3>
        <p className="break-all">宿主离线包目录: {packages?.artifactsDir || "尚未加载"}</p>
        {packagesLoading && <p role="status">正在加载离线包...</p>}
        {packageError && <p role="alert" className={errorClass}>{packageError}</p>}
        {packages?.items.map((item) => <div key={item.path} className="space-y-1">
          <button className={`${buttonClass} max-w-full break-all text-left`} disabled={!canPrepare || !item.valid} onClick={() => void runAction("offline", () => client.prepareOfflineUpdate(item.path, item.version))}>{item.name} · {packageLabel(item.packageKind)}</button>
          {!item.valid && <p className={errorClass}>{item.error || "包校验失败"}</p>}
        </div>)}
        <label className="block space-y-1">宿主机器上的离线包路径
          <input value={hostPath} onChange={(event) => setHostPath(event.target.value)} className="block w-full min-w-0 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2" placeholder="例如 C:\\Downloads\\update.zip" />
        </label>
        <button className={buttonClass} disabled={!canPrepare || !hostPath.trim()} onClick={() => void runAction("offline", () => client.prepareOfflineUpdate(hostPath.trim()))}>准备宿主离线包</button>
        <label className="block space-y-1">从此设备上传升级包
          <input type="file" accept=".zip,.tar.gz,.tgz" className="block w-full min-w-0" disabled={!canPrepare} onChange={(event) => setUpload(event.target.files?.[0] || null)} />
        </label>
        <button className={buttonClass} disabled={!canPrepare || !upload} onClick={() => upload && void runAction("upload", () => client.uploadOfflineUpdate(upload))}>{action === "upload" ? "上传中..." : "上传并准备"}</button>
      </div>
      {confirmJob && <div role="dialog" aria-modal="true" aria-labelledby="update-confirm-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
        <div className="w-full max-w-lg space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <h3 id="update-confirm-title" className="font-semibold">确认应用更新</h3>
          <p className="break-words text-sm">即将应用 {confirmJob.targetVersion}。服务将暂时断开，页面会重新查询后台任务，核对运行版本和健康检查结果。</p>
          {staleConfirmation && <p role="alert" className={errorClass}>任务状态已变化，请关闭确认框并重新确认。</p>}
          <div className="flex flex-wrap gap-2">
            <button autoFocus className={buttonClass} onClick={() => setConfirmJob(null)}>暂不应用</button>
            <button className={buttonClass} disabled={busy || Boolean(staleConfirmation) || job?.requiresPreparation || !launcher?.supported || launcher.protocol !== 1} onClick={() => {
              setConfirmJob(null);
              void runAction("apply", () => client.applyUpdateJob(confirmJob.jobId, confirmJob.revision));
            }}>确认应用并重启服务</button>
          </div>
        </div>
      </div>}
    </section>
  );
}
