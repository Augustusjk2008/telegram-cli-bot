import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Copy,
  Globe,
  HeartPulse,
  Info,
  Lightbulb,
  LoaderCircle,
  Play,
  RefreshCw,
  RotateCw,
  Server,
  Settings2,
  Square,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { TunnelSnapshot } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { copyText } from "../../utils/clipboard";
import { getErrorMessage } from "../../utils/errorMessage";
import "./PublicAccessPanel.css";

type Tone = "accent" | "success" | "warning" | "danger" | "neutral";
type Source = TunnelSnapshot["source"];
type TunnelAction = "start" | "stop" | "restart";

const STATUS: Record<TunnelSnapshot["status"], { text: string; tone: Tone }> = {
  running: { text: "运行中", tone: "success" },
  connected: { text: "公网地址已创建", tone: "accent" },
  verifying_public: { text: "正在验证公网地址", tone: "accent" },
  starting: { text: "启动中", tone: "accent" },
  waiting_local: { text: "等待本地服务", tone: "accent" },
  waiting_url: { text: "等待公网地址", tone: "accent" },
  error: { text: "异常", tone: "danger" },
  stopped: { text: "已停止", tone: "neutral" },
};
/** States the backend leaves on its own; the panel re-reads them until they settle. */
const SETTLING = new Set<string>(["starting", "waiting_local", "waiting_url", "connected", "verifying_public"]);
const POLL_INTERVAL_MS = 2000;
const SOURCE_TEXT: Record<Source, string> = {
  quick_tunnel: "Cloudflare Quick Tunnel",
  fixed_public_forward: "固定公网转发",
  manual_config: "手工配置地址",
  disabled: "未配置隧道、公网 URL 或固定公网转发",
};
const SOURCE_NOTE: Record<Source, string> = {
  quick_tunnel: "Quick Tunnel 是临时地址，重启 Tunnel 后会更换。",
  fixed_public_forward: "固定公网转发通过环境配置维护。",
  manual_config: "公网地址由 WEB_PUBLIC_URL 手工配置。",
  disabled: "可在环境配置的 Tunnel 分类中启用公网访问。",
};
const ACTION_PENDING: Record<TunnelAction, string> = { start: "启动中...", stop: "停止中...", restart: "重启中..." };
const ACTION_FAILED: Record<TunnelAction, string> = { start: "启动 Tunnel 失败", stop: "停止 Tunnel 失败", restart: "重启 Tunnel 失败" };
const SPIN = " animate-spin motion-reduce:animate-none";

function sourceOf(tunnel: TunnelSnapshot): Source {
  if (tunnel.source === "fixed_public_forward" || tunnel.mode === "fixed_public_forward") return "fixed_public_forward";
  if (tunnel.source === "quick_tunnel" || tunnel.source === "manual_config") return tunnel.source;
  return "disabled";
}

function normalizeServiceStatus(value: string | null | undefined) {
  return String(value || "").trim().toLowerCase();
}

const HEALTHY_STATES = ["running", "connected", "online", "ok", "healthy", "success"];
const FAILED_TOKENS = ["error", "failed", "timeout", "forbidden"];

function serviceTone(value: string | null | undefined): Tone {
  const status = normalizeServiceStatus(value);
  if (!status || ["stopped", "disabled", "offline"].includes(status)) return "neutral";
  if (HEALTHY_STATES.includes(status)) return "success";
  if (["starting", "pending", "waiting", "verifying"].some((token) => status.includes(token))) return "warning";
  if (FAILED_TOKENS.some((token) => status.includes(token))) return "danger";
  return "accent";
}

function frpcStatusText(value: string | null | undefined, fallback: string) {
  const status = normalizeServiceStatus(value) || normalizeServiceStatus(fallback);
  if (!status || status === "stopped") return "已停止";
  if (HEALTHY_STATES.includes(status)) return "运行中";
  if (status === "starting") return "启动中";
  if (["waiting", "pending"].some((token) => status.includes(token))) return "等待中";
  if (FAILED_TOKENS.some((token) => status.includes(token))) return "异常";
  return value || STATUS[fallback as TunnelSnapshot["status"]]?.text || "已停止";
}

function heartbeatStatusText(value: string | null | undefined) {
  const status = normalizeServiceStatus(value);
  if (!status || ["stopped", "disabled", "offline"].includes(status)) return "未上报";
  if (HEALTHY_STATES.includes(status)) return "正常";
  if (status === "starting") return "启动中";
  if (["waiting", "pending"].some((token) => status.includes(token))) return "等待中";
  if (FAILED_TOKENS.some((token) => status.includes(token))) return "异常";
  return value || "未上报";
}

/** Maps common fixed-forward failures to the likely misconfiguration. */
function fixedForwardErrorHint(value: string | null | undefined) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "";
  if (normalized.includes("403") || (normalized.includes("node") && normalized.includes("token"))) {
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

function isSameNameFrpcProxyMessage(value: string | null | undefined) {
  const text = String(value || "").trim().toLowerCase();
  return Boolean(text) && (
    (text.includes("同名") && text.includes("proxy"))
    || (text.includes("proxy [") && text.includes("already exists"))
  );
}

function formatReportedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function ErrorCallout({ role, action, children }: { role?: "alert"; action?: ReactNode; children: ReactNode }) {
  return (
    <div role={role} className="admin-callout access-callout" data-tone="danger">
      <TriangleAlert className="h-4 w-4 flex-none" aria-hidden="true" />
      <div className="access-callout-body">{children}</div>
      {action}
    </div>
  );
}

type StatusChipProps = {
  tone: Tone;
  running?: boolean;
  role?: "status";
  srLabel?: string;
  children: ReactNode;
};

function StatusChip({ tone, running = false, role, srLabel, children }: StatusChipProps) {
  return (
    <span role={role} className="orbit-chip" data-tone={tone === "neutral" ? undefined : tone}>
      <span className="access-dot" data-running={running || undefined} aria-hidden="true" />
      {srLabel && <span className="sr-only">{srLabel}</span>}
      {children}
    </span>
  );
}

type ServiceTileProps = {
  name: string;
  icon: LucideIcon;
  tone: Tone;
  status: string;
  facts: Array<[string, string]>;
  error?: string;
  note?: string;
  hint?: string;
};

function ServiceTile({ name, icon: Icon, tone, status, facts, error, note, hint }: ServiceTileProps) {
  return (
    <div className="access-service" data-tone={tone}>
      <div className="access-service-head">
        <span className="access-service-icon" aria-hidden="true"><Icon className="h-3.5 w-3.5" /></span>
        <span className="access-service-name">{name}</span>
        <StatusChip tone={tone}>{status}</StatusChip>
      </div>
      <dl className="access-service-facts">
        {facts.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}
      </dl>
      {error && <p className="access-service-error">{error}</p>}
      {note && <p className="access-service-note">{note}</p>}
      {hint && (
        <p className="access-hint">
          <Lightbulb className="h-3.5 w-3.5" aria-hidden="true" />
          可能原因：{hint}
        </p>
      )}
    </div>
  );
}

type Props = {
  client: WebBotClient;
  refreshKey?: number;
  /** Opens the environment configuration at the Tunnel category; omitted when the account cannot manage it. */
  onOpenEnvConfig?: () => void;
};

/** Admin Center → 网络与升级: how this console is reached from the public internet. */
export function PublicAccessPanel({ client, refreshKey = 0, onOpenEnvConfig }: Props) {
  const [tunnel, setTunnel] = useState<TunnelSnapshot | null>(null);
  const [loadError, setLoadError] = useState("");
  const [action, setAction] = useState<TunnelAction | "">("");
  const [actionError, setActionError] = useState("");
  const [copied, setCopied] = useState(false);
  const mounted = useRef(false);
  /** Bumped by refreshes and actions, so a slower older read never overwrites newer state. */
  const epoch = useRef(0);
  const uid = useId();

  const readStatus = useCallback(async (reportErrors: boolean) => {
    const requestEpoch = epoch.current;
    try {
      const next = await client.getTunnelStatus();
      if (!mounted.current || requestEpoch !== epoch.current) return;
      setTunnel(next);
      setLoadError("");
    } catch (error) {
      if (reportErrors && mounted.current && requestEpoch === epoch.current) {
        setLoadError(getErrorMessage(error, "公网访问状态加载失败"));
      }
    }
  }, [client]);

  const reload = useCallback(() => {
    epoch.current += 1;
    setActionError("");
    void readStatus(true);
  }, [readStatus]);

  useEffect(() => {
    mounted.current = true;
    reload();
    return () => { mounted.current = false; };
  }, [reload, refreshKey]);

  const settling = Boolean(tunnel && SETTLING.has(tunnel.status));
  useEffect(() => {
    if (!settling || action) return undefined;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(async () => {
        await readStatus(false);
        if (active) schedule();
      }, POLL_INTERVAL_MS);
    };
    schedule();
    return () => { active = false; clearTimeout(timer); };
  }, [settling, action, readStatus]);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function runAction(name: TunnelAction, fixedForward: boolean) {
    epoch.current += 1;
    setAction(name);
    setActionError("");
    try {
      const next = name === "start"
        ? await client.startTunnel()
        : name === "stop" ? await client.stopTunnel() : await client.restartTunnel();
      if (!mounted.current) return;
      setTunnel(next);
      setLoadError("");
      // The snapshot's own errors render below; only a failed recovery that says nothing needs a message.
      if (fixedForward && next.status === "error" && !next.lastError && !next.frpcLastError) {
        setActionError("固定公网转发恢复失败");
      }
    } catch (error) {
      if (mounted.current) {
        setActionError(getErrorMessage(error, fixedForward ? "固定公网转发恢复失败" : ACTION_FAILED[name]));
      }
    } finally {
      if (mounted.current) setAction("");
    }
  }

  async function copyPublicUrl(url: string) {
    setActionError("");
    if (await copyText(url)) {
      if (mounted.current) setCopied(true);
    } else if (mounted.current) {
      setActionError("复制失败，请手动选择公网地址复制");
    }
  }

  const source = tunnel ? sourceOf(tunnel) : "disabled";
  const fixedForward = source === "fixed_public_forward";
  const status = tunnel
    ? STATUS[tunnel.status] ?? { text: tunnel.status || "已停止", tone: (tunnel.status ? "accent" : "neutral") as Tone }
    : null;
  const tone: Tone = !status || source === "disabled" ? "neutral" : status.tone;
  const publicUrl = tunnel?.publicUrl || "";
  const live = Boolean(publicUrl) && tunnel?.status === "running";

  const externalSameNameProxy = Boolean(tunnel?.frpcExternal && (
    isSameNameFrpcProxyMessage(tunnel.frpcLastError) || isSameNameFrpcProxyMessage(tunnel.lastError)
  ));
  // In fixed-forward mode frpc's error doubles as the tunnel error; show it once, in the frpc tile.
  const tunnelError = tunnel?.lastError && !externalSameNameProxy && !(fixedForward && tunnel.lastError === tunnel.frpcLastError)
    ? tunnel.lastError
    : "";

  let publicMeta = "";
  if (tunnel && fixedForward) {
    publicMeta = tunnel.nodeId ? `节点 ID ${tunnel.nodeId}` : "经 Hub 固定入口转发";
  } else if (tunnel && source === "quick_tunnel" && publicUrl) {
    if (tunnel.status === "running") publicMeta = tunnel.verified ? "已验证可从公网访问" : "";
    else if (!tunnel.lastError) publicMeta = "公网地址已创建，正在验证";
  }

  const busy = Boolean(action);
  const canStart = !busy && !["running", "starting", "connected", "verifying_public", "waiting_url"].includes(tunnel?.status || "");
  const envButton = onOpenEnvConfig ? (
    <button type="button" className="orbit-btn orbit-btn--ghost" onClick={onOpenEnvConfig}>
      <Settings2 className="h-4 w-4" aria-hidden="true" />
      打开环境配置
    </button>
  ) : null;
  const actionIcon = (name: TunnelAction, Icon: LucideIcon) => (action === name
    ? <LoaderCircle className={`h-4 w-4${SPIN}`} aria-hidden="true" />
    : <Icon className="h-4 w-4" aria-hidden="true" />);

  return (
    <section
      aria-labelledby={`${uid}-title`}
      data-tone={tone}
      className="admin-island orbit-island orbit-island--reading access-island"
    >
      {settling && <span className="orbit-sweep" aria-hidden="true" />}
      <header className="access-head">
        <span className="access-head-icon" aria-hidden="true"><Globe className="h-4 w-4" /></span>
        <div className="access-head-copy">
          <h2 id={`${uid}-title`}>公网访问</h2>
          {tunnel ? (
            <p>{SOURCE_TEXT[source]}</p>
          ) : loadError ? (
            <p>暂未获取公网访问状态</p>
          ) : (
            <p role="status">正在加载公网访问状态...</p>
          )}
        </div>
        {tunnel && status && (
          <StatusChip role="status" srLabel="公网访问状态: " tone={tone} running={settling}>
            {source === "disabled" ? "未启用" : status.text}
          </StatusChip>
        )}
      </header>

      {loadError && (
        <ErrorCallout
          role="alert"
          action={(
            <button type="button" className="orbit-btn orbit-btn--secondary orbit-btn--sm" onClick={reload}>
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              重新加载
            </button>
          )}
        >
          {loadError}
        </ErrorCallout>
      )}
      {actionError && <ErrorCallout role="alert">{actionError}</ErrorCallout>}
      {tunnelError && <ErrorCallout>{tunnelError}</ErrorCallout>}

      {tunnel && (
        <>
          <div className="access-route" data-live={live || undefined}>
            <dl className="access-endpoint">
              <dt>本地服务</dt>
              <dd className="access-endpoint-value">{tunnel.localUrl || "未知"}</dd>
              {fixedForward && tunnel.basePath && <dd className="access-endpoint-meta">Web 子路径 {tunnel.basePath}</dd>}
            </dl>
            <ArrowRight className="access-route-arrow" aria-hidden="true" />
            <dl className="access-endpoint" data-emphasis={live || undefined} data-empty={!publicUrl || undefined}>
              <dt>公网地址</dt>
              <dd className="access-endpoint-value">{publicUrl || (source === "disabled" ? "未配置" : "未建立公网地址")}</dd>
              {publicMeta && <dd className="access-endpoint-meta">{publicMeta}</dd>}
              {publicUrl && (
                <dd className="access-endpoint-actions">
                  <button
                    type="button"
                    aria-label={copied ? "已复制公网地址" : "复制公网地址"}
                    className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                    onClick={() => void copyPublicUrl(publicUrl)}
                  >
                    {copied ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
                    {copied ? "已复制" : "复制"}
                  </button>
                  {/^https?:\/\//i.test(publicUrl) && (
                    <a
                      href={publicUrl}
                      target="_blank"
                      rel="noreferrer"
                      aria-label="在新标签页打开公网地址"
                      title="在新标签页打开"
                      className="orbit-btn orbit-btn--ghost orbit-btn--sm orbit-btn--icon"
                    >
                      <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  )}
                </dd>
              )}
            </dl>
          </div>

          {fixedForward && (
            <div className="access-services">
              <ServiceTile
                name="frpc"
                icon={Server}
                tone={externalSameNameProxy ? "neutral" : serviceTone(tunnel.frpcStatus || tunnel.status)}
                status={externalSameNameProxy ? "复用外部进程" : frpcStatusText(tunnel.frpcStatus, tunnel.status)}
                facts={[["PID", tunnel.frpcExternal ? "外部进程" : String(tunnel.frpcPid ?? tunnel.pid ?? "未启动")]]}
                error={externalSameNameProxy ? "" : tunnel.frpcLastError}
                note={externalSameNameProxy ? "外部 frpc 已占用同名 proxy，当前配置按复用处理。" : ""}
                hint={externalSameNameProxy ? "" : fixedForwardErrorHint(tunnel.frpcLastError || tunnel.lastError)}
              />
              <ServiceTile
                name="Heartbeat"
                icon={HeartPulse}
                tone={serviceTone(tunnel.heartbeatStatus)}
                status={heartbeatStatusText(tunnel.heartbeatStatus)}
                facts={[["最近上报", tunnel.heartbeatLastAt ? formatReportedAt(tunnel.heartbeatLastAt) : "暂无"]]}
                error={tunnel.heartbeatLastError}
                hint={fixedForwardErrorHint(tunnel.heartbeatLastError)}
              />
            </div>
          )}

          <footer className="access-foot">
            <p className="access-foot-note">
              <Info className="h-3.5 w-3.5" aria-hidden="true" />
              {SOURCE_NOTE[source]}
            </p>
            <div className="access-foot-actions">
              {source === "quick_tunnel" ? (
                <>
                  <button
                    type="button"
                    className="orbit-btn orbit-btn--secondary"
                    disabled={busy || tunnel.status === "stopped"}
                    onClick={() => void runAction("stop", false)}
                  >
                    {actionIcon("stop", Square)}
                    {action === "stop" ? ACTION_PENDING.stop : "停止 Tunnel"}
                  </button>
                  <button
                    type="button"
                    className="orbit-btn orbit-btn--secondary"
                    disabled={busy}
                    onClick={() => void runAction("restart", false)}
                  >
                    {actionIcon("restart", RotateCw)}
                    {action === "restart" ? ACTION_PENDING.restart : "重启 Tunnel"}
                  </button>
                  <button
                    type="button"
                    className={`orbit-btn ${canStart ? "orbit-btn--primary" : "orbit-btn--secondary"}`}
                    disabled={!canStart}
                    onClick={() => void runAction("start", false)}
                  >
                    {actionIcon("start", Play)}
                    {action === "start" ? ACTION_PENDING.start : "启动 Tunnel"}
                  </button>
                </>
              ) : fixedForward ? (
                <>
                  {envButton}
                  <button
                    type="button"
                    className={`orbit-btn ${tunnel.status === "error" ? "orbit-btn--primary" : "orbit-btn--secondary"}`}
                    disabled={busy}
                    onClick={() => void runAction("restart", true)}
                  >
                    {actionIcon("restart", RefreshCw)}
                    {action === "restart" ? "恢复中..." : "尝试恢复"}
                  </button>
                </>
              ) : envButton}
            </div>
          </footer>
        </>
      )}
    </section>
  );
}
