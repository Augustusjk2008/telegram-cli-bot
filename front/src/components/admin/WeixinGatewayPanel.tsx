import { QrCode, RefreshCw, Save, Trash2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import type { EnvConfigItem, EnvConfigPatchValue, EnvConfigValue, WeixinGatewayStatus, WeixinSetup } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { getErrorMessage } from "../../utils/errorMessage";

type Props = {
  client: WebBotClient;
  refreshKey?: number;
  onNotice?: (message: string) => void;
  onError?: (message: string) => void;
};

const STATUS_LABELS: Record<WeixinSetup["status"], string> = {
  idle: "未开始",
  waiting_scan: "等待扫码",
  scanned: "已扫码，等待确认",
  confirmed: "已确认",
  expired: "二维码已过期",
  cancelled: "已取消",
  failed: "失败",
};

function statusLabel(status: string) {
  return STATUS_LABELS[status as WeixinSetup["status"]] || status || "未知";
}

const GATEWAY_KEYS = new Set([
  "TELEGRAM_ENABLED",
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_ALLOWED_USER_IDS",
  "TELEGRAM_BROADCAST_COMPLETIONS",
  "WEIXIN_ENABLED",
  "WEIXIN_ACCOUNT_ID",
  "WEIXIN_TOKEN",
  "WEIXIN_BASE_URL",
  "WEIXIN_ALLOWED_USER_IDS",
]);

function formatGatewayValue(value: EnvConfigValue | undefined, masked = false) {
  if (masked) return "********";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return value || "";
}

function normalizeGatewayValue(item: EnvConfigItem, value: string | boolean): EnvConfigValue {
  if (item.type === "boolean") return Boolean(value);
  if (item.type === "csv") return String(value).split(",").map((part) => part.trim()).filter(Boolean);
  if (item.type === "number") return Number(value || 0);
  return String(value);
}

export function WeixinGatewayPanel({ client, refreshKey = 0, onNotice, onError }: Props) {
  const [status, setStatus] = useState<WeixinGatewayStatus | null>(null);
  const [setup, setSetup] = useState<WeixinSetup | null>(null);
  const [gatewayItems, setGatewayItems] = useState<EnvConfigItem[]>([]);
  const [gatewayDraft, setGatewayDraft] = useState<Record<string, EnvConfigValue>>({});
  const [gatewaySecretEditing, setGatewaySecretEditing] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [gatewaySaving, setGatewaySaving] = useState(false);
  const [error, setError] = useState("");

  async function loadStatus() {
    setError("");
    try {
      const [next, envConfig] = await Promise.all([
        client.getWeixinStatus(),
        client.getEnvConfig(),
      ]);
      setStatus(next);
      setSetup(next.setup);
      const items = envConfig.items.filter((item) => GATEWAY_KEYS.has(item.key));
      setGatewayItems(items);
      setGatewayDraft(Object.fromEntries(items.map((item) => [item.key, item.value])));
      setGatewaySecretEditing({});
    } catch (nextError) {
      const message = getErrorMessage(nextError, "加载消息网关配置失败");
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, [client, refreshKey]);

  useEffect(() => {
    if (!setup?.setupId || !["waiting_scan", "scanned"].includes(setup.status)) {
      return undefined;
    }
    let active = true;
    const timer = window.setInterval(() => {
      void client.getWeixinSetup(setup.setupId).then((next) => {
        if (!active) return;
        setSetup(next);
        setStatus((previous) => previous
          ? {
            ...previous,
            setup: next,
            enabled: next.enabled || previous.enabled,
            configured: next.configured || previous.configured,
            accountId: next.accountId || previous.accountId,
          }
          : previous);
        if (next.status === "confirmed") {
          onNotice?.("微信扫码成功，配置已保存，需要重启应用。");
        } else if (["expired", "failed", "cancelled"].includes(next.status)) {
          if (next.errorMessage) setError(next.errorMessage);
        }
      }).catch((nextError) => {
        if (!active) return;
        const message = getErrorMessage(nextError, "查询微信扫码状态失败");
        setError(message);
        onError?.(message);
      });
    }, 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [client, setup?.setupId, setup?.status]);

  async function startSetup() {
    setBusy(true);
    setError("");
    try {
      const next = await client.startWeixinSetup();
      setSetup(next);
      onNotice?.("二维码已生成，请使用微信扫码并确认。");
    } catch (nextError) {
      const message = getErrorMessage(nextError, "开始微信扫码失败");
      setError(message);
      onError?.(message);
    } finally {
      setBusy(false);
    }
  }

  async function cancelSetup() {
    if (!setup?.setupId) return;
    setBusy(true);
    try {
      const next = await client.cancelWeixinSetup(setup.setupId);
      setSetup(next);
      onNotice?.("微信扫码已取消。");
    } catch (nextError) {
      const message = getErrorMessage(nextError, "取消微信扫码失败");
      setError(message);
      onError?.(message);
    } finally {
      setBusy(false);
    }
  }

  async function saveGatewayConfig() {
    setGatewaySaving(true);
    setError("");
    try {
      const values: Record<string, EnvConfigPatchValue> = {};
      for (const item of gatewayItems) {
        const value = gatewayDraft[item.key] ?? item.value;
        if (item.sensitive && item.masked && !gatewaySecretEditing[item.key]) {
          values[item.key] = { masked: true };
        } else {
          values[item.key] = value;
        }
      }
      await client.updateEnvConfig({ values });
      onNotice?.("消息网关配置已保存，需要重启应用。");
      await loadStatus();
    } catch (nextError) {
      const message = getErrorMessage(nextError, "保存消息网关配置失败");
      setError(message);
      onError?.(message);
    } finally {
      setGatewaySaving(false);
    }
  }

  const activeSetup = setup && ["waiting_scan", "scanned"].includes(setup.status);

  return (
    <section className="admin-island orbit-island orbit-island--reading space-y-4" aria-label="消息网关">
      <div className="flex items-start gap-2">
        <QrCode className="mt-0.5 h-5 w-5 text-[var(--accent)]" />
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">消息网关</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">管理 Telegram 与个人微信的接入配置、扫码和连接状态。</p>
        </div>
      </div>

      {error ? <div role="alert" className="admin-callout" data-tone="danger">{error}</div> : null}
      {loading ? <p className="text-sm text-[var(--muted)]">加载中...</p> : null}

      {!loading ? (
        <>
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <p className="admin-well px-3 py-2">微信启用：<span className="font-medium text-[var(--text)]">{status?.enabled ? "是" : "否"}</span></p>
            <p className="admin-well px-3 py-2">微信账号：<span className="font-medium text-[var(--text)]">{status?.accountId || "未绑定"}</span></p>
            <p className="admin-well px-3 py-2">微信连接：<span className="font-medium text-[var(--text)]">{status?.connectionStatus || "未知"}</span></p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void startSetup()} disabled={busy || Boolean(activeSetup)} className="orbit-btn orbit-btn--primary">
              <QrCode className="h-4 w-4" />
              {busy ? "处理中..." : activeSetup ? "扫码进行中" : "开始扫码"}
            </button>
            {activeSetup ? (
              <button type="button" onClick={() => void cancelSetup()} disabled={busy} className="orbit-btn orbit-btn--secondary">
                <XCircle className="h-4 w-4" />
                取消扫码
              </button>
            ) : null}
            <button type="button" onClick={() => void loadStatus()} disabled={busy} className="orbit-btn orbit-btn--ghost orbit-btn--sm">
              <RefreshCw className="h-3.5 w-3.5" />
              刷新
            </button>
          </div>

          {setup ? (
            <div className="admin-well flex flex-col gap-4 p-4 sm:flex-row">
              {setup.qrCodeImage ? <img src={setup.qrCodeImage} alt="微信扫码二维码" className="h-40 w-40 rounded-lg bg-white p-2" /> : null}
              <div className="space-y-2 text-sm text-[var(--muted)]">
                <p>扫码状态：<span className="font-medium text-[var(--text)]">{statusLabel(setup.status)}</span></p>
                {setup.qrCodeUrl && !setup.qrCodeImage ? <p className="break-all">二维码内容：{setup.qrCodeUrl}</p> : null}
                {setup.status === "confirmed" ? <p className="text-[var(--feedback-success-text)]">微信配置已保存，需要重启应用。</p> : null}
                {setup.status === "expired" ? <p>二维码已过期，请重新开始扫码。</p> : null}
                {setup.status === "cancelled" ? <p>扫码任务已取消。</p> : null}
                {setup.status === "failed" ? <p>{setup.errorMessage || "扫码失败，请重试。"}</p> : null}
              </div>
            </div>
          ) : null}

          <p className="text-sm text-[var(--muted)]">微信白名单用户：{status?.allowedUserCount ?? 0} 个。</p>

          <div className="space-y-4 border-t border-[var(--border)] pt-4">
            {(["telegram", "weixin"] as const).map((category) => {
              const items = gatewayItems.filter((item) => item.category === category);
              if (!items.length) return null;
              return (
                <div key={category} className="space-y-3">
                  <h3 className="text-sm font-semibold text-[var(--text)]">{category === "telegram" ? "Telegram 配置" : "个人微信配置"}</h3>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {items.map((item) => {
                      const draftValue = gatewayDraft[item.key] ?? item.value;
                      const editingSecret = Boolean(gatewaySecretEditing[item.key]);
                      const masked = item.sensitive && item.masked && !editingSecret;
                      return (
                        <article key={item.key} className="space-y-2 admin-well p-3">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                              <h4 className="font-medium text-[var(--text)]">{item.label}</h4>
                              <p className="text-xs text-[var(--muted)]">{item.description}</p>
                            </div>
                            {item.sensitive ? (
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setGatewaySecretEditing((previous) => ({ ...previous, [item.key]: true }));
                                    setGatewayDraft((previous) => ({ ...previous, [item.key]: "" }));
                                  }}
                                  className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                                >
                                  编辑
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setGatewaySecretEditing((previous) => ({ ...previous, [item.key]: true }));
                                    setGatewayDraft((previous) => ({ ...previous, [item.key]: "" }));
                                  }}
                                  className="orbit-btn orbit-btn--sm admin-btn--danger-quiet"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                  清空
                                </button>
                              </div>
                            ) : null}
                          </div>
                          {item.type === "boolean" ? (
                            <label className="inline-flex items-center gap-2 text-sm">
                              <input
                                type="checkbox"
                                checked={Boolean(draftValue)}
                                onChange={(event) => setGatewayDraft((previous) => ({ ...previous, [item.key]: event.target.checked }))}
                              />
                              启用
                            </label>
                          ) : (
                            <input
                              aria-label={item.label}
                              type={item.type === "password" ? "password" : "text"}
                              value={formatGatewayValue(draftValue, masked)}
                              disabled={masked || gatewaySaving}
                              onChange={(event) => setGatewayDraft((previous) => ({
                                ...previous,
                                [item.key]: normalizeGatewayValue(item, event.target.value),
                              }))}
                              className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-70"
                            />
                          )}
                        </article>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            <button type="button" onClick={() => void saveGatewayConfig()} disabled={gatewaySaving || loading} className="orbit-btn orbit-btn--primary">
              <Save className="h-4 w-4" />
              {gatewaySaving ? "保存中..." : "保存消息网关配置"}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
