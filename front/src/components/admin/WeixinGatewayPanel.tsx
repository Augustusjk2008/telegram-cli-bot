import { QrCode, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import type { WeixinGatewayStatus, WeixinSetup } from "../../services/types";
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

export function WeixinGatewayPanel({ client, refreshKey = 0, onNotice, onError }: Props) {
  const [status, setStatus] = useState<WeixinGatewayStatus | null>(null);
  const [setup, setSetup] = useState<WeixinSetup | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function loadStatus() {
    setError("");
    try {
      const next = await client.getWeixinStatus();
      setStatus(next);
      setSetup(next.setup);
    } catch (nextError) {
      const message = getErrorMessage(nextError, "加载微信接入状态失败");
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

  const activeSetup = setup && ["waiting_scan", "scanned"].includes(setup.status);

  return (
    <section className="admin-island orbit-island orbit-island--reading space-y-4" aria-label="微信接入">
      <div className="flex items-start gap-2">
        <QrCode className="mt-0.5 h-5 w-5 text-[var(--accent)]" />
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">个人微信接入</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">通过 Tencent iLink Bot 接收私聊文本，使用 HTTP 长轮询，不需要公网 Webhook。</p>
        </div>
      </div>

      {error ? <div role="alert" className="admin-callout" data-tone="danger">{error}</div> : null}
      {loading ? <p className="text-sm text-[var(--muted)]">加载中...</p> : null}

      {!loading ? (
        <>
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <p className="admin-well px-3 py-2">启用：<span className="font-medium text-[var(--text)]">{status?.enabled ? "是" : "否"}</span></p>
            <p className="admin-well px-3 py-2">账号：<span className="font-medium text-[var(--text)]">{status?.accountId || "未绑定"}</span></p>
            <p className="admin-well px-3 py-2">连接：<span className="font-medium text-[var(--text)]">{status?.connectionStatus || "未知"}</span></p>
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
                {setup.status === "confirmed" ? <p className="text-[var(--feedback-success-text)]">配置已保存，需要重启应用。</p> : null}
                {setup.status === "expired" ? <p>二维码已过期，请重新开始扫码。</p> : null}
                {setup.status === "cancelled" ? <p>扫码任务已取消。</p> : null}
                {setup.status === "failed" ? <p>{setup.errorMessage || "扫码失败，请重试。"}</p> : null}
              </div>
            </div>
          ) : null}

          <p className="text-sm text-[var(--muted)]">当前白名单人数：{status?.allowedUserCount ?? 0}。请在环境配置中填写 <code>WEIXIN_ALLOWED_USER_IDS</code>；普通微信群、图片、视频、语音、文件和卡片暂不支持。</p>
        </>
      ) : null}
    </section>
  );
}
