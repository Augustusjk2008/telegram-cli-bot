import { useState } from "react";
import { WebApiClientError, type RemoteWorkspace } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

export const remoteInputClass = "w-full min-w-0 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm";
export const remoteButtonClass = "rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-50";

export function RemoteConnectionForm({ client, botAlias, initial, onConnected }: {
  client: WebBotClient;
  botAlias?: string;
  initial?: RemoteWorkspace;
  onConnected: (remote: RemoteWorkspace) => void;
}) {
  const [host, setHost] = useState(initial?.host || "");
  const [port, setPort] = useState(String(initial?.port || 22));
  const [username, setUsername] = useState(initial?.username || "");
  const [auth, setAuth] = useState(initial?.keyFilename ? "key" : "password");
  const [password, setPassword] = useState("");
  const [keyFilename, setKeyFilename] = useState(initial?.keyFilename || "");
  const [passphrase, setPassphrase] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function connect(confirmedFingerprint?: string) {
    if (busy) return;
    const sshPort = Number(port);
    if (!host.trim() || !username.trim() || !Number.isInteger(sshPort) || sshPort < 1 || sshPort > 65535) {
      setError("请填写主机、用户名和有效端口（1–65535）");
      return;
    }
    setBusy(true);
    setError("");
    setFingerprint("");
    try {
      const result = await client.connectRemote({
        host: host.trim(), port: sshPort, username: username.trim(),
        ...(auth === "password" ? { password } : {}),
        ...(auth === "key" ? { keyFilename: keyFilename.trim(), passphrase } : {}),
        ...(confirmedFingerprint ? { hostKeyFingerprint: confirmedFingerprint } : {}),
      }, botAlias);
      setPassword("");
      setPassphrase("");
      onConnected(result);
    } catch (err) {
      if (err instanceof WebApiClientError && err.code === "remote_host_key_unknown") {
        const data = err.data as { fingerprint?: string } | undefined;
        if (data?.fingerprint) setFingerprint(data.fingerprint);
        else setError(err.message);
      } else setError(err instanceof Error ? err.message : "SSH 连接失败");
    } finally {
      setBusy(false);
    }
  }

  return <form className="space-y-3" autoComplete="off" onSubmit={(event) => { event.preventDefault(); void connect(); }}>
    <fieldset disabled={busy || Boolean(fingerprint)} className="space-y-3">
      <div className="grid grid-cols-[minmax(0,1fr)_6rem] gap-2">
        <label className="text-sm">SSH 主机<input className={remoteInputClass} value={host} onChange={(e) => setHost(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
        <label className="text-sm">端口<input className={remoteInputClass} type="number" min="1" max="65535" value={port} onChange={(e) => setPort(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
      </div>
      <label className="block text-sm">SSH 用户名<input className={remoteInputClass} value={username} onChange={(e) => setUsername(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
      <label className="block text-sm">认证方式<select className={remoteInputClass} value={auth} disabled={Boolean(botAlias && initial?.keyFilename)} onChange={(e) => { setAuth(e.target.value); setPassword(""); setPassphrase(""); }}>
        <option value="password">密码</option><option value="key" disabled={Boolean(botAlias && !initial?.keyFilename)}>本地私钥文件</option><option value="agent">SSH agent / 默认密钥</option>
      </select></label>
      {auth === "password" && <label className="block text-sm">SSH 密码<input type="password" autoComplete="new-password" className={remoteInputClass} value={password} onChange={(e) => setPassword(e.target.value)} required /></label>}
      {auth === "key" && <>
        <label className="block text-sm">私钥文件路径（服务所在电脑）<input className={remoteInputClass} value={keyFilename} onChange={(e) => setKeyFilename(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
        <label className="block text-sm">私钥口令（可选）<input type="password" autoComplete="new-password" className={remoteInputClass} value={passphrase} onChange={(e) => setPassphrase(e.target.value)} /></label>
      </>}
      <button className={remoteButtonClass} type="submit">{busy ? "正在连接…" : "测试并连接 SSH"}</button>
    </fieldset>
    {fingerprint && <div role="alert" className="space-y-2 rounded-md border border-[var(--border)] p-3 text-sm">
      <p>首次连接 {username}@{host}:{port}。请核对服务器主机密钥指纹：</p>
      <code className="block break-all">{fingerprint}</code>
      <div className="flex flex-wrap gap-2">
        <button className={remoteButtonClass} type="button" disabled={busy} onClick={() => void connect(fingerprint)}>信任此主机密钥并连接</button>
        <button className={remoteButtonClass} type="button" onClick={() => setFingerprint("")}>取消</button>
      </div>
    </div>}
    {error && <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>}
  </form>;
}

export function RemoteReconnectButton({ client, botAlias, remote, onConnected, disabled = false }: {
  client: WebBotClient; botAlias: string; remote: RemoteWorkspace; disabled?: boolean;
  onConnected?: (remote: RemoteWorkspace) => void;
}) {
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  return <>
    <button type="button" className={remoteButtonClass} disabled={disabled} onClick={() => setOpen(true)}>{connected ? "SSH 已连接 · 重新登录" : "SSH 重新登录"}</button>
    {open && <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.stopPropagation()}>
      <section role="dialog" aria-modal="true" aria-label="SSH 重新登录" className="max-h-[90dvh] w-full max-w-lg space-y-4 overflow-y-auto rounded-xl bg-[var(--bg)] p-5 text-[var(--text)]">
        <div className="flex items-center justify-between"><h2 className="font-semibold">SSH 重新登录 · {botAlias}</h2><button type="button" className={remoteButtonClass} onClick={() => setOpen(false)}>关闭</button></div>
        <RemoteConnectionForm client={client} botAlias={botAlias} initial={remote} onConnected={(next) => { setConnected(true); setOpen(false); onConnected?.(next); }} />
      </section>
    </div>}
  </>;
}
