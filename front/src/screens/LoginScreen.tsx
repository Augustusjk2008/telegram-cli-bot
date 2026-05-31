import { useState } from "react";
import { Cpu, KeyRound, Server, ShieldCheck, SquareTerminal } from "lucide-react";
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
    <main className="relative min-h-[100dvh] overflow-x-hidden bg-[var(--workbench-shell-bg)] px-3 py-3 text-[var(--text)] sm:px-5 sm:py-5">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute inset-0 opacity-55"
          style={{
            backgroundImage: [
              "linear-gradient(to right, var(--hero-grid) 1px, transparent 1px)",
              "linear-gradient(to bottom, var(--hero-grid) 1px, transparent 1px)",
            ].join(","),
            backgroundSize: "32px 32px, 32px 32px",
            maskImage: "linear-gradient(180deg, rgba(0,0,0,0.9), rgba(0,0,0,0.62) 72%, transparent 100%)",
          }}
        />
        <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-[var(--hero-glow)] to-transparent" />
        <div className="absolute right-[-5rem] top-[-2rem] h-72 w-72" style={{ background: "radial-gradient(circle, var(--bg-glow-strong) 0, transparent 66%)" }} />
      </div>

      <div className="relative z-10 mx-auto flex min-h-[calc(100dvh-1.5rem)] w-full max-w-6xl flex-col gap-4 sm:min-h-[calc(100dvh-2.5rem)]">
        <div className="flex min-h-10 items-center justify-between gap-3 border border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2.5 py-2 shadow-[var(--shadow-soft)]">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--surface-glass)]">
              <AppLogo size={22} decorative />
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{APP_LOGIN_NAME}</div>
              <div className="truncate font-mono text-[10px] tracking-[0.16em] text-[var(--muted)]">{APP_KICKER}</div>
            </div>
          </div>
          {onThemeChange ? (
            <div className="w-[min(12rem,44vw)] shrink-0">
              <ThemeDropdown value={themeName} onChange={onThemeChange} variant="compact" menuAlign="right" />
            </div>
          ) : null}
        </div>

        <div className="grid flex-1 items-center gap-4 lg:grid-cols-[1fr_25rem]">
          <section className="min-w-0 border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 shadow-[var(--shadow-card)] sm:p-5">
            <div className="flex min-w-0 items-start justify-between gap-3 border-b border-[var(--workbench-hairline)] pb-4">
              <div className="min-w-0">
                <div className="mb-2 inline-flex items-center gap-2 rounded-md border border-[var(--accent-outline)] bg-[var(--workbench-active-bg)] px-2 py-1 text-xs font-medium text-[var(--accent)]">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  本地 agent 控制台
                </div>
                <h1 className="text-xl font-bold text-[var(--text)] sm:text-2xl">{APP_LOGIN_NAME}</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">
                  登录后接入本机 bot、文件、终端、Git 和插件视图。当前入口只处理身份校验，不改变本地运行状态。
                </p>
              </div>
              <div className="hidden rounded-md border border-[var(--border)] bg-[var(--surface-glass)] px-2 py-1 font-mono text-[11px] text-[var(--muted)] sm:block">
                v{APP_VERSION}
              </div>
            </div>

            <div className="mt-4 grid gap-2 sm:grid-cols-3">
              {hostStatusItems.map(({ label, value, Icon }) => (
                <div key={label} className="min-w-0 border border-[var(--border)] bg-[var(--surface-glass)] p-3">
                  <div className="mb-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                    <Icon className="h-3.5 w-3.5 text-[var(--accent)]" />
                    {label}
                  </div>
                  <div className="truncate text-sm font-semibold text-[var(--text)]" title={value}>{value}</div>
                </div>
              ))}
            </div>

            <div className="mt-4 border border-[var(--border)] bg-[var(--surface-glass)] p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium text-[var(--accent-strong)]">
                <SquareTerminal className="h-3.5 w-3.5" />
                主机摘要
              </div>
              <p className="break-all text-sm leading-6 text-[var(--muted)]">{hostSummary}</p>
            </div>
          </section>

          <section className="relative min-w-0 overflow-hidden border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-4 shadow-[var(--shadow-card)] sm:p-5">
            <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,var(--accent),transparent)] opacity-80" />
            <div className="relative">
              <div className="flex items-center gap-2 text-xs font-medium text-[var(--accent-strong)]">
                <KeyRound className="h-3.5 w-3.5" />
                访问控制
              </div>
              <h2 className="mt-2 text-xl font-bold text-[var(--text)]">接入控制台</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                账号登录，注册需注册码；也可 guest 只读进入。
                {allowLegacyTokenLogin ? <span className="sr-only">输入访问口令，管理本地主 Bot 与子 Bot。</span> : null}
              </p>

              <div className="mt-5 inline-flex rounded-md border border-[var(--border)] bg-[var(--surface-glass)] p-0.5">
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
                    className={mode === value
                      ? "rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)]"
                      : "rounded-md px-4 py-2 text-sm text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"}
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
                <div className="flex flex-col gap-2">
                  <label htmlFor="username" className="text-sm font-medium text-[var(--muted)]">用户名</label>
                  <input
                    id="username"
                    name="username"
                    type="text"
                    aria-label={allowLegacyTokenLogin && mode === "login" ? "访问口令" : undefined}
                    className="w-full rounded-md border border-[var(--accent-outline)] bg-[var(--surface-glass)] px-4 py-3 text-[var(--text)] shadow-sm transition-colors focus:border-[var(--accent)] focus:outline-none"
                    placeholder="alice"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <label htmlFor="password" className="text-sm font-medium text-[var(--muted)]">密码</label>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    className="w-full rounded-md border border-[var(--accent-outline)] bg-[var(--surface-glass)] px-4 py-3 text-[var(--text)] shadow-sm transition-colors focus:border-[var(--accent)] focus:outline-none"
                    placeholder="请输入密码"
                  />
                </div>
                {mode === "register" ? (
                  <div className="flex flex-col gap-2">
                    <label htmlFor="registerCode" className="text-sm font-medium text-[var(--muted)]">注册码</label>
                    <input
                      id="registerCode"
                      name="registerCode"
                      type="text"
                      className="w-full rounded-md border border-[var(--accent-outline)] bg-[var(--surface-glass)] px-4 py-3 text-[var(--text)] shadow-sm transition-colors focus:border-[var(--accent)] focus:outline-none"
                      placeholder="INVITE-001"
                    />
                  </div>
                ) : null}
                {error ? (
                  <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                    {error}
                  </div>
                ) : null}
                <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <input
                    type="checkbox"
                    name="rememberLogin"
                    checked={rememberLogin}
                    onChange={(event) => setRememberLogin(event.currentTarget.checked)}
                    className="h-4 w-4 accent-[var(--accent)]"
                  />
                  <span>记住登录</span>
                </label>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full rounded-md border border-[var(--accent-outline)] bg-[var(--accent)] px-4 py-3 text-base font-semibold text-[var(--accent-foreground)] shadow-[0_14px_32px_var(--accent-soft-strong)] transition hover:opacity-90 active:scale-[0.98] disabled:opacity-60"
                >
                  {isLoading ? "处理中..." : mode === "register" ? "注册并登录" : "登录"}
                </button>
                <button
                  type="button"
                  onClick={() => void onGuestLogin?.({ remember: rememberLogin })}
                  disabled={isLoading}
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-glass)] px-4 py-3 text-sm font-medium text-[var(--text)] hover:bg-[var(--workbench-hover-bg)] disabled:opacity-60"
                >
                  以 guest 进入
                </button>
              </form>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
