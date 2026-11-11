import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, KeyRound, LoaderCircle, Server, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { WebApiClientError, type RemoteWorkspace } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import "./RemoteConnectionForm.css";

export const remoteInputClass = "orbit-field min-w-0 text-sm";
export const remoteButtonClass = "orbit-btn orbit-btn--secondary";

export function RemoteConnectionForm({ client, botAlias, initial, onConnected }: {
  client: WebBotClient;
  botAlias?: string;
  initial?: RemoteWorkspace;
  onConnected: (remote: RemoteWorkspace) => void;
}) {
  const [platform, setPlatform] = useState<NonNullable<RemoteWorkspace["platform"]>>(initial?.platform || "posix");
  const [host, setHost] = useState(initial?.host || "");
  const [port, setPort] = useState(String(initial?.port || 22));
  const [username, setUsername] = useState(initial?.username || "");
  const [auth, setAuth] = useState(initial?.keyFilename ? "key" : "password");
  const [password, setPassword] = useState("");
  const [rememberPassword, setRememberPassword] = useState(false);
  const [passwordSaved, setPasswordSaved] = useState(false);
  const [loadingCredentials, setLoadingCredentials] = useState(Boolean(botAlias));
  const [keyFilename, setKeyFilename] = useState(initial?.keyFilename || "");
  const [passphrase, setPassphrase] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ids = useId();

  useEffect(() => {
    let active = true;
    setPasswordSaved(false);
    setRememberPassword(false);
    setLoadingCredentials(Boolean(botAlias));
    if (botAlias) {
      void client.getRemoteCredentialStatus(botAlias).then((status) => {
        if (!active) return;
        setPasswordSaved(status.passwordSaved);
        setRememberPassword(status.passwordSaved);
      }).catch(() => {
        if (active) setError("读取已保存密码状态失败，请重新输入密码连接。");
      }).finally(() => {
        if (active) setLoadingCredentials(false);
      });
    }
    return () => { active = false; };
  }, [client, botAlias, initial?.connectionId]);

  async function connect(confirmedFingerprint?: string) {
    if (busy || (auth === "password" && loadingCredentials)) return;
    const sshPort = Number(port);
    if (!host.trim() || !username.trim() || !Number.isInteger(sshPort) || sshPort < 1 || sshPort > 65535) {
      setError("请填写主机、用户名和有效端口（1–65535）");
      return;
    }
    const useSavedPassword = auth === "password" && passwordSaved && !password;
    if (auth === "password" && !password && !useSavedPassword) {
      setError("请输入 SSH 密码");
      return;
    }
    setBusy(true);
    setError("");
    setFingerprint("");
    try {
      const result = await client.connectRemote({
        host: host.trim(), port: sshPort, username: username.trim(),
        platform,
        rememberPassword: auth === "password" && rememberPassword,
        ...(auth === "password" ? { ...(password ? { password } : {}), ...(useSavedPassword ? { useSavedPassword: true } : {}) } : {}),
        ...(auth === "key" ? { keyFilename: keyFilename.trim(), passphrase } : {}),
        ...(confirmedFingerprint ? { hostKeyFingerprint: confirmedFingerprint } : {}),
      }, botAlias);
      setPassword("");
      setPassphrase("");
      setPasswordSaved(auth === "password" && rememberPassword);
      onConnected(result);
    } catch (err) {
      if (err instanceof WebApiClientError && err.code === "remote_host_key_unknown") {
        const data = err.data as { fingerprint?: string } | undefined;
        if (data?.fingerprint) setFingerprint(data.fingerprint);
        else setError(err.message);
      } else if (useSavedPassword && err instanceof WebApiClientError && err.status === 401) {
        setPasswordSaved(false);
        setError("已保存的密码不可用，请重新输入 SSH 密码。");
      } else setError(err instanceof Error ? err.message : "SSH 连接失败");
    } finally {
      setBusy(false);
    }
  }

  return <form className="remote-connect-form" autoComplete="off" onSubmit={(event) => { event.preventDefault(); void connect(); }}>
    <fieldset disabled={busy || Boolean(fingerprint)} className="remote-connect-fields">
      <div className="remote-connect-group">
        <p className="remote-connect-caption"><Server size={14} aria-hidden="true" />连接信息</p>
        <label className="remote-connect-label">目标系统<select className={remoteInputClass} value={platform} disabled={Boolean(botAlias)} onChange={(e) => setPlatform(e.target.value as typeof platform)}>
          <option value="posix">Linux / POSIX</option><option value="windows">Windows</option>
        </select></label>
        {platform === "windows" && <p className="remote-connect-hint">远程命令使用 Windows PowerShell（powershell.exe）；Agent 仍在本机运行。</p>}
        <div className="remote-connect-host">
          <label className="remote-connect-label">SSH 主机<input className={remoteInputClass} placeholder="主机名或 IP 地址" spellCheck={false} value={host} onChange={(e) => setHost(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
          <label className="remote-connect-label">端口<input className={remoteInputClass} type="number" min="1" max="65535" value={port} onChange={(e) => setPort(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
        </div>
        <label className="remote-connect-label">SSH 用户名<input className={remoteInputClass} placeholder="远程登录用户名" spellCheck={false} value={username} onChange={(e) => setUsername(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
      </div>
      <div className="remote-connect-group remote-connect-auth">
        <p className="remote-connect-caption"><KeyRound size={14} aria-hidden="true" />身份验证</p>
        <label className="remote-connect-label">认证方式<select className={remoteInputClass} value={auth} disabled={Boolean(botAlias && initial?.keyFilename)} onChange={(e) => { setAuth(e.target.value); setPassword(""); setPassphrase(""); }}>
          <option value="password">密码</option><option value="key" disabled={Boolean(botAlias && !initial?.keyFilename)}>本地私钥文件</option><option value="agent">SSH agent / 默认密钥</option>
        </select></label>
        {auth === "password" && <>
          <label className="remote-connect-label">SSH 密码<input type="password" autoComplete="new-password" className={remoteInputClass} placeholder={passwordSaved ? "留空使用已保存的密码" : "输入 SSH 登录密码"} value={password} onChange={(e) => setPassword(e.target.value)} required={!passwordSaved} disabled={loadingCredentials} aria-describedby={passwordSaved ? `${ids}-saved` : undefined} /></label>
          {loadingCredentials && <p role="status" className="remote-connect-hint">正在读取密码保存状态…</p>}
          {passwordSaved && <p id={`${ids}-saved`} className="remote-connect-saved"><ShieldCheck size={14} aria-hidden="true" />已保存密码，输入新密码可更新。</p>}
          <div className="remote-connect-remember">
            <label className="remote-connect-check">
              <input type="checkbox" checked={rememberPassword} disabled={loadingCredentials} onChange={(e) => setRememberPassword(e.target.checked)} aria-describedby={`${ids}-remember`} />
              <span>记住密码</span>
            </label>
            <p id={`${ids}-remember`} className="remote-connect-hint">{passwordSaved && !rememberPassword ? "本次连接成功后清除已保存的密码。" : "加密保存在服务端，重启后仍可连接。"}</p>
          </div>
        </>}
        {auth === "key" && <>
          <label className="remote-connect-label">私钥文件路径（服务所在电脑）<input className={remoteInputClass} value={keyFilename} onChange={(e) => setKeyFilename(e.target.value)} readOnly={Boolean(botAlias)} required /></label>
          <label className="remote-connect-label">私钥口令（可选）<input type="password" autoComplete="new-password" className={remoteInputClass} value={passphrase} onChange={(e) => setPassphrase(e.target.value)} /></label>
        </>}
        {auth === "agent" && <p className="remote-connect-hint">使用服务所在电脑的 SSH agent 或默认密钥连接。</p>}
      </div>
      <div className="remote-connect-actions"><button className="orbit-btn orbit-btn--primary remote-primary-action" type="submit" disabled={auth === "password" && loadingCredentials}>
        {busy ? <LoaderCircle size={15} className="animate-spin" aria-hidden="true" /> : <ArrowRight size={15} aria-hidden="true" />}
        {busy ? "正在连接…" : "测试并连接 SSH"}
      </button></div>
    </fieldset>
    {fingerprint && <div role="alert" className="remote-fingerprint">
      <p className="remote-connect-caption"><ShieldCheck size={15} aria-hidden="true" />确认主机密钥</p>
      <p>首次连接 {username}@{host}:{port}。请核对服务器主机密钥指纹：</p>
      <code>{fingerprint}</code>
      <div className="flex flex-wrap gap-2">
        <button className={remoteButtonClass} type="button" disabled={busy} onClick={() => void connect(fingerprint)}>信任此主机密钥并连接</button>
        <button className={remoteButtonClass} type="button" disabled={busy} onClick={() => setFingerprint("")}>取消</button>
      </div>
    </div>}
    {error && <p role="alert" className="remote-connect-error"><TriangleAlert size={15} aria-hidden="true" />{error}</p>}
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
    {open && <RemoteReconnectDialog client={client} botAlias={botAlias} remote={remote} onClose={() => setOpen(false)} onConnected={(next) => { setConnected(true); setOpen(false); onConnected?.(next); }} />}
  </>;
}

export function RemoteReconnectDialog({ client, botAlias, remote, onClose, onConnected }: {
  client: WebBotClient; botAlias: string; remote: RemoteWorkspace;
  onClose: () => void;
  onConnected: (remote: RemoteWorkspace) => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => { previousFocus?.focus(); };
  }, []);

  const dialog = <div className="orbit-backdrop fixed inset-0 z-[1000] flex items-end justify-center sm:items-center sm:p-4" onClick={(e) => e.stopPropagation()}>
    <section ref={panelRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label="SSH 重新登录" className="orbit-dialog remote-connect-dialog" onKeyDown={(event) => {
      if (event.key === "Escape") { event.stopPropagation(); onClose(); }
      if (event.key === "Tab") {
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)')).filter((control) => control.getClientRects().length > 0);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }}>
      <header className="remote-connect-header">
        <span className="remote-connect-icon"><Server size={18} aria-hidden="true" /></span>
        <div className="remote-connect-heading"><h2>SSH 重新登录</h2><p>{botAlias} · 远程工作区</p></div>
        <button type="button" className="orbit-btn orbit-btn--ghost orbit-btn--icon" aria-label="关闭" title="关闭" onClick={onClose}><X size={17} aria-hidden="true" /></button>
      </header>
      <div className="remote-connect-body"><RemoteConnectionForm client={client} botAlias={botAlias} initial={remote} onConnected={onConnected} /></div>
    </section>
  </div>;
  return typeof document === "undefined" ? null : createPortal(dialog, document.body);
}
