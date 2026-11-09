import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { Copy, ExternalLink, Github, KeyRound, LoaderCircle, LogOut, RefreshCw } from "lucide-react";
import {
  gitButtonClassName,
  gitIconButtonClassName,
  gitInputClassName,
  gitPrimaryButtonClassName,
} from "../screens/gitStyles";
import type { GitHubAccountStatus, GitHubDeviceFlow } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client: WebBotClient;
  account: GitHubAccountStatus | null;
  loading: boolean;
  loadError: string;
  disabled?: boolean;
  onAccountChange: (account: GitHubAccountStatus) => void;
  onReload: () => void;
};

type PendingDeviceFlow = GitHubDeviceFlow & { message: string };

function authMethodLabel(account: GitHubAccountStatus) {
  if (account.authMethod === "device") {
    return "浏览器授权";
  }
  return account.tokenKind === "fine_grained" ? "细粒度令牌" : "访问令牌";
}

function scopeSummary(account: GitHubAccountStatus) {
  if (account.scopes.length > 0) {
    return account.scopes.join(", ");
  }
  return account.tokenKind === "fine_grained" ? "按令牌配置的仓库权限" : "未报告权限范围";
}

export function GitHubAccountPanel({ client, account, loading, loadError, disabled = false, onAccountChange, onReload }: Props) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [deviceFlow, setDeviceFlow] = useState<PendingDeviceFlow | null>(null);
  const [copied, setCopied] = useState(false);
  const mountedRef = useRef(true);
  // Parent re-renders must not restart the device-flow poll timer.
  const onAccountChangeRef = useRef(onAccountChange);
  onAccountChangeRef.current = onAccountChange;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!deviceFlow) {
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await client.pollGitHubDeviceLogin(deviceFlow.flowId);
        if (cancelled || !mountedRef.current) return;
        if (result.status === "connected" && result.account) {
          setDeviceFlow(null);
          onAccountChangeRef.current(result.account);
          return;
        }
        if (result.status === "expired" || result.status === "denied") {
          setDeviceFlow(null);
          setError(result.status === "expired" ? "授权码已过期，请重新登录" : "已在 GitHub 拒绝授权");
          return;
        }
        setDeviceFlow((current) => (current && current.flowId === deviceFlow.flowId
          ? { ...current, interval: result.interval, message: "等待在 GitHub 完成授权…" }
          : current));
      } catch (err) {
        if (cancelled || !mountedRef.current) return;
        setDeviceFlow(null);
        setError(err instanceof Error ? err.message : "查询 GitHub 授权状态失败");
      }
    }, Math.max(1, deviceFlow.interval) * 1000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [client, deviceFlow]);

  async function runAction(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError("");
    try {
      await action();
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : "GitHub 操作失败");
      }
    } finally {
      if (mountedRef.current) {
        setBusy("");
      }
    }
  }

  function startDeviceLogin() {
    void runAction("device", async () => {
      const flow = await client.startGitHubDeviceLogin();
      if (mountedRef.current) {
        setCopied(false);
        setDeviceFlow({ ...flow, message: "在 GitHub 输入下方授权码" });
      }
    });
  }

  function connectWithToken() {
    const value = token.trim();
    if (!value) {
      setError("请输入 GitHub 个人访问令牌");
      return;
    }
    void runAction("token", async () => {
      const next = await client.connectGitHubWithToken(value);
      if (mountedRef.current) {
        setToken("");
        onAccountChange(next);
      }
    });
  }

  function disconnect() {
    if (!window.confirm("确定断开 GitHub 账号吗？Orbit 会删除保存的令牌；如需彻底撤销授权，请在 GitHub 设置中操作。")) {
      return;
    }
    void runAction("disconnect", async () => {
      const next = await client.disconnectGitHub();
      if (mountedRef.current) {
        onAccountChange(next);
      }
    });
  }

  async function copyUserCode() {
    if (!deviceFlow) return;
    try {
      await navigator.clipboard.writeText(deviceFlow.userCode);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const controlsDisabled = disabled || busy !== "";

  if (!account) {
    return (
      <div data-testid="github-account-panel" className="space-y-1.5 text-xs">
        {loading ? (
          <p className="flex items-center gap-1.5 text-[var(--muted)]">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            读取 GitHub 账号…
          </p>
        ) : null}
        {loadError ? (
          <div className="flex items-center gap-1.5 text-[var(--status-danger)]">
            <span className="min-w-0 flex-1 break-words">{loadError}</span>
            <button type="button" aria-label="重新读取 GitHub 账号" title="重新读取" onClick={onReload} className={gitIconButtonClassName}>
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  if (account.connected) {
    return (
      <div data-testid="github-account-panel" className="space-y-1.5 text-xs">
        <div className="flex min-w-0 items-center gap-2">
          {account.avatarUrl ? (
            <img src={account.avatarUrl} alt="" className="h-6 w-6 shrink-0 rounded-full border border-[var(--workbench-hairline)]" />
          ) : (
            <Github className="h-5 w-5 shrink-0 text-[var(--muted)]" />
          )}
          <div className="min-w-0 flex-1">
            <a
              href={account.htmlUrl || `https://github.com/${account.login}`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex max-w-full items-center gap-1 font-semibold text-[var(--text)] hover:underline"
            >
              <span className="truncate">@{account.login}</span>
              <ExternalLink className="h-3 w-3 shrink-0 text-[var(--muted)]" />
            </a>
            <p className="truncate text-[11px] text-[var(--muted)]" title={scopeSummary(account)}>
              {authMethodLabel(account)} · {scopeSummary(account)}
            </p>
          </div>
          <button
            type="button"
            onClick={disconnect}
            disabled={controlsDisabled}
            title="断开 GitHub 账号"
            className={gitButtonClassName}
          >
            {busy === "disconnect" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <LogOut className="h-3.5 w-3.5" />}
            断开
          </button>
        </div>
        {error ? <p className="break-words text-[var(--status-danger)]">{error}</p> : null}
      </div>
    );
  }

  return (
    <div data-testid="github-account-panel" className="space-y-2 text-xs">
      {account.deviceFlowAvailable ? (
        deviceFlow ? (
          <div data-testid="github-device-flow" className="space-y-1.5 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-2">
            <p className="flex items-center gap-1.5 text-[var(--muted)]">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />
              {deviceFlow.message}
            </p>
            <div className="flex items-center gap-1.5">
              <code aria-label="GitHub 授权码" className="select-all rounded bg-[var(--bg)] px-2 py-1 font-mono text-sm font-semibold tracking-widest text-[var(--text)]">
                {deviceFlow.userCode}
              </code>
              <button type="button" aria-label="复制授权码" title={copied ? "已复制" : "复制授权码"} onClick={() => void copyUserCode()} className={gitIconButtonClassName}>
                <Copy className="h-3.5 w-3.5" />
              </button>
              <a href={deviceFlow.verificationUri} target="_blank" rel="noreferrer" className={clsx(gitPrimaryButtonClassName, "ml-auto")}>
                <ExternalLink className="h-3.5 w-3.5" />
                打开 GitHub
              </a>
            </div>
            <button type="button" onClick={() => setDeviceFlow(null)} className="text-[11px] text-[var(--muted)] underline">
              取消
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={startDeviceLogin}
            disabled={controlsDisabled}
            className={clsx(gitPrimaryButtonClassName, "w-full")}
          >
            {busy === "device" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Github className="h-3.5 w-3.5" />}
            通过浏览器登录 GitHub
          </button>
        )
      ) : null}
      <div className="space-y-1">
        <p className="text-[11px] text-[var(--muted)]">
          {account.deviceFlowAvailable ? "或使用个人访问令牌：" : "使用个人访问令牌连接："}
          需要 {account.requiredScopes.join("、") || "repo"} 权限
          {account.tokenCreateUrl ? (
            <>
              {" · "}
              <a href={account.tokenCreateUrl} target="_blank" rel="noreferrer" className="text-[var(--accent)] underline">
                创建令牌
              </a>
            </>
          ) : null}
        </p>
        <div className="flex min-w-0 items-center gap-1">
          <label className="min-w-0 flex-1">
            <span className="sr-only">GitHub 个人访问令牌</span>
            <input
              aria-label="GitHub 个人访问令牌"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(event) => setToken(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  connectWithToken();
                }
              }}
              placeholder="ghp_… 或 github_pat_…"
              disabled={controlsDisabled}
              className={gitInputClassName}
            />
          </label>
          <button
            type="button"
            onClick={connectWithToken}
            disabled={controlsDisabled || !token.trim()}
            className={gitButtonClassName}
          >
            {busy === "token" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
            连接
          </button>
        </div>
        <p className="text-[11px] leading-4 text-[var(--muted)]">
          令牌按当前 Orbit 账号加密保存在本机，仅用于 GitHub API 与本地工作区的 HTTPS 同步，不会返回浏览器。细粒度令牌需授予 Contents 读写；创建仓库还需 Administration 写权限。
        </p>
      </div>
      {error ? <p className="break-words text-[var(--status-danger)]">{error}</p> : null}
    </div>
  );
}
