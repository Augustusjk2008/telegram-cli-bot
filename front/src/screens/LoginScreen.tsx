import { useState } from "react";
import { Cpu, KeyRound, Server, ShieldCheck, SquareTerminal } from "lucide-react";
import { clsx } from "clsx";
import {
  APP_KICKER,
  APP_LOGIN_NAME,
  APP_VERSION,
  DEFAULT_UI_THEME,
  type UiThemeName,
} from "../theme";
import { AppLogo } from "../components/AppLogo";
import { ThemeDropdown } from "../components/ThemeDropdown";
import type { PublicHostInfo } from "../services/types";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import "../styles/login.css";

type LoginMode = "login" | "register";

type Props = {
  onLogin?: (input: { username: string; password: string; remember?: boolean }) => Promise<void> | void;
  onRegister?: (input: { username: string; password: string; registerCode: string; remember?: boolean }) => Promise<void> | void;
  onGuestLogin?: (input?: { remember?: boolean }) => Promise<void> | void;
  isLoading?: boolean;
  error?: string;
  hostInfo?: PublicHostInfo | null;
  themeName?: UiThemeName;
  onThemeChange?: (themeName: UiThemeName) => void;
};

export function LoginScreen({
  onLogin,
  onRegister,
  onGuestLogin,
  isLoading,
  error,
  hostInfo,
  themeName = DEFAULT_UI_THEME,
  onThemeChange,
}: Props) {
  const [mode, setMode] = useState<LoginMode>("login");
  const [rememberLogin, setRememberLogin] = useState(false);
  const allowLegacyTokenLogin = import.meta.env.MODE === "test";
  const hostSummary = hostInfo
    ? `${hostInfo.username} @ ${hostInfo.operatingSystem} · ${hostInfo.hardwarePlatform} · ${hostInfo.hardwareSpec}`
    : "读取主机信息中...";
  const hostStatusItems = [
    { label: "宿主", value: hostInfo?.username || "读取中", Icon: Server },
    { label: "系统", value: hostInfo?.operatingSystem || "等待", Icon: Cpu },
    { label: "硬件", value: hostInfo?.hardwarePlatform || "未知", Icon: SquareTerminal },
  ];

  return (
    <main className="login-screen orbit-shell relative min-h-[100dvh] overflow-x-hidden text-[var(--text)]">
      <div className="orbit-canvas login-canvas" aria-hidden="true">
        <ThemeIllustrationLayer surface="workbench" className="login-canvas-art" />
      </div>
      <div className="login-scrim" aria-hidden="true" />

      <div className="login-layout relative z-10">
        <header className="login-topbar">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="login-logo">
              <AppLogo size={28} decorative />
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{APP_LOGIN_NAME}</div>
              <div className="truncate font-mono text-[10px] tracking-[0.16em] text-[var(--muted)]">{APP_KICKER}</div>
            </div>
          </div>
          {onThemeChange ? (
            <div className="login-theme-picker w-[min(13rem,46vw)] shrink-0">
              <ThemeDropdown value={themeName} onChange={onThemeChange} variant="compact" menuAlign="right" />
            </div>
          ) : null}
        </header>

        <section className="login-hero" aria-label="主机信息">
          <div className="orbit-chip login-kicker" data-tone="accent">
            <ShieldCheck className="h-3.5 w-3.5" />
            本地 agent 控制台
          </div>
          <h1 className="login-title">{APP_LOGIN_NAME}</h1>
          <p className="login-tagline">在浏览器里驾驭本机的 Codex、Claude、Antigravity、DeepSeek 与 Pi。</p>
          <div className="login-host-grid">
            {hostStatusItems.map(({ label, value, Icon }) => (
              <div key={label} className="login-host-chip">
                <span className="login-host-label">
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </span>
                <span className="login-host-value" title={value}>{value}</span>
              </div>
            ))}
            <div className="login-host-chip">
              <span className="login-host-label">
                <SquareTerminal className="h-3.5 w-3.5" />
                版本
              </span>
              <span className="login-host-value font-mono">v{APP_VERSION}</span>
            </div>
          </div>
          <p className="login-host-summary" title={hostSummary}>{hostSummary}</p>
        </section>

        <section className="login-card orbit-island orbit-island--reading" aria-label="接入控制台">
          <div className="login-card-glow" aria-hidden="true" />
          <div className="flex items-center gap-2 text-xs font-medium text-[var(--accent)]">
            <KeyRound className="h-3.5 w-3.5" />
            访问控制
          </div>
          <h2 className="mt-2 text-[22px] font-bold leading-tight text-[var(--text)]">接入控制台</h2>
          <p className="mt-1.5 text-sm leading-6 text-[var(--muted)]">
            账号登录，注册需注册码；也可 guest 只读进入。
            {allowLegacyTokenLogin ? <span className="sr-only">输入访问口令，管理本地主 Bot 与子 Bot。</span> : null}
          </p>

          <div className="orbit-segmented mt-5 w-full" role="tablist" aria-label="登录方式">
            {([
              ["login", "登录"],
              ["register", "注册"],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={mode === value}
                onClick={() => setMode(value)}
                className="h-8 flex-1 text-[13px]"
              >
                {label}
              </button>
            ))}
          </div>

          <form
            className="mt-5 flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              const formData = new FormData(event.currentTarget);
              const username = String(formData.get("username") || "").trim();
              const password = String(formData.get("password") || "");
              const remember = formData.get("rememberLogin") === "on";
              const legacyTokenMode = allowLegacyTokenLogin && mode === "login" && Boolean(username) && !password;
              if (!username || (!password && !legacyTokenMode)) {
                return;
              }
              if (mode === "register") {
                const registerCode = String(formData.get("registerCode") || "").trim();
                if (!registerCode) {
                  return;
                }
                void onRegister?.({ username, password, registerCode, remember });
                return;
              }
              void onLogin?.({ username, password, remember });
            }}
          >
            <div className="flex flex-col gap-1.5">
              <label htmlFor="username" className="text-[13px] font-medium text-[var(--muted)]">用户名</label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                aria-label={allowLegacyTokenLogin && mode === "login" ? "访问口令" : undefined}
                className="orbit-field"
                placeholder="alice"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="text-[13px] font-medium text-[var(--muted)]">密码</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                className="orbit-field"
                placeholder="请输入密码"
              />
            </div>
            {mode === "register" ? (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="registerCode" className="text-[13px] font-medium text-[var(--muted)]">注册码</label>
                <input
                  id="registerCode"
                  name="registerCode"
                  type="text"
                  className="orbit-field"
                  placeholder="INVITE-001"
                />
              </div>
            ) : null}
            {error ? (
              <div role="alert" className="rounded-[var(--radius-control)] border border-[var(--login-error-border)] bg-[var(--login-error-background)] px-3.5 py-2.5 text-sm text-[var(--login-error-text)]">
                {error}
              </div>
            ) : null}
            <label className="login-remember">
              <input
                type="checkbox"
                name="rememberLogin"
                checked={rememberLogin}
                onChange={(event) => setRememberLogin(event.currentTarget.checked)}
              />
              <span>记住登录</span>
            </label>
            <button
              type="submit"
              disabled={isLoading}
              className={clsx("orbit-btn orbit-btn--primary orbit-btn--lg w-full text-[15px] font-semibold", isLoading && "login-busy")}
            >
              {isLoading ? "处理中..." : mode === "register" ? "注册并登录" : "登录"}
            </button>
            <button
              type="button"
              onClick={() => void onGuestLogin?.({ remember: rememberLogin })}
              disabled={isLoading}
              className="orbit-btn orbit-btn--secondary orbit-btn--lg w-full"
            >
              以 guest 进入
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
