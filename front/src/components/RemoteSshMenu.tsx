import { useEffect, useRef, useState } from "react";
import { ChevronDown, Server } from "lucide-react";
import type { RemoteWorkspace } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { RemoteReconnectDialog, remoteButtonClass } from "./RemoteConnectionForm";

export function RemoteSshMenu({ client, botAlias, remote, compact = false, disabled = false, onConnected }: {
  client: WebBotClient;
  botAlias: string;
  remote: RemoteWorkspace;
  compact?: boolean;
  disabled?: boolean;
  onConnected?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setOpen(false);
    setReconnecting(false);
    setDisconnected(false);
    setError("");
  }, [botAlias, remote.connectionId]);

  useEffect(() => {
    if (!open) return;
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnPointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  async function disconnect() {
    setBusy(true);
    setError("");
    try {
      await client.disconnectRemote(botAlias);
      setDisconnected(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "断开 SSH 失败");
    } finally {
      setBusy(false);
    }
  }

  const pathLabel = `${remote.username}@${remote.host}:${remote.port} ${remote.root}`;
  return <>
    <div ref={rootRef} className={compact ? "relative shrink-0" : "relative min-w-0 max-w-[22rem]"}>
      <button
        ref={triggerRef}
        type="button"
        aria-label="SSH 连接"
        aria-expanded={open}
        aria-haspopup="dialog"
        title={pathLabel}
        onClick={() => setOpen((value) => !value)}
        className={compact
          ? "inline-flex h-8 items-center gap-1 rounded-md border border-[var(--border)] px-1.5 text-xs text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
          : "workbench-status-chip min-w-0 max-w-full text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)]"}
      >
        <Server className="h-3.5 w-3.5 shrink-0 text-[var(--accent-strong)]" aria-hidden="true" />
        <span className={compact ? "" : "min-w-0 truncate"}>{compact ? "SSH" : `SSH ${remote.host}:${remote.root}`}</span>
        <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />
      </button>
      {open && <div role="dialog" aria-label="SSH 连接" className={`absolute top-full z-40 mt-1 w-[min(20rem,calc(100vw-1rem))] rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] p-3 text-sm text-[var(--text)] shadow-[var(--shadow-card)] ${compact ? "right-0" : "left-0"}`}>
        <p className="text-xs text-[var(--muted)]">远程工作区</p>
        <p className="mt-1 break-all font-mono text-xs">{remote.username}@{remote.host}:{remote.port}</p>
        <p className="break-all font-mono text-xs">{remote.root}</p>
        <p className="mt-2 text-xs text-[var(--muted)]">仅支持聊天、文件和终端</p>
        {disconnected && <p role="status" className="mt-2 text-xs text-[var(--danger)]">SSH 已断开，请重新登录后继续使用远程工作区。</p>}
        {error && <p role="alert" className="mt-2 text-xs text-[var(--danger)]">{error}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={remoteButtonClass} disabled={disabled || busy} onClick={() => { setOpen(false); setReconnecting(true); }}>SSH 重新登录</button>
          <button type="button" className={remoteButtonClass} disabled={disabled || busy || disconnected} onClick={() => void disconnect()}>{busy ? "正在断开…" : "断开 SSH"}</button>
        </div>
      </div>}
    </div>
    {reconnecting && <RemoteReconnectDialog client={client} botAlias={botAlias} remote={remote} onClose={() => { setReconnecting(false); triggerRef.current?.focus(); }} onConnected={() => { setReconnecting(false); setDisconnected(false); setError(""); onConnected?.(); triggerRef.current?.focus(); }} />}
  </>;
}
