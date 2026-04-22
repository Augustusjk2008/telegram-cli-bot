import { useState } from "react";
import {
  APP_LOGIN_NAME,
  APP_TAGLINE,
  APP_VERSION,
} from "../theme";
import type { PublicHostInfo } from "../services/types";

type LoginMode = "login" | "register";

type Props = {
  onLogin?: (input: { username: string; password: string }) => Promise<void> | void;
  onRegister?: (input: { username: string; password: string; registerCode: string }) => Promise<void> | void;
  onGuestLogin?: () => Promise<void> | void;
  isLoading?: boolean;
  error?: string;
  hostInfo?: PublicHostInfo | null;
};

export function LoginScreen({
  onLogin,
  onRegister,
  onGuestLogin,
  isLoading,
  error,
  hostInfo,
}: Props) {
  const [mode, setMode] = useState<LoginMode>("login");
  const allowLegacyTokenLogin = import.meta.env.MODE === "test";
  const hostSummary = hostInfo
    ? `${hostInfo.username} @ ${hostInfo.operatingSystem} · ${hostInfo.hardwarePlatform} · ${hostInfo.hardwareSpec}`
    : "读取主机信息中...";

  return (
    <main className="relative min-h-[100dvh] overflow-hidden bg-[var(--bg)] px-4 py-5 sm:px-6 sm:py-6">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute inset-0 opacity-60"
          style={{
            backgroundImage: [
              "linear-gradient(to right, var(--hero-grid) 1px, transparent 1px)",
              "linear-gradient(to bottom, var(--hero-grid) 1px, transparent 1px)",
              "repeating-linear-gradient(180deg, rgba(255,255,255,0.035) 0 2px, transparent 2px 6px)",
            ].join(","),
            backgroundSize: "32px 32px, 32px 32px, auto",
            maskImage: "linear-gradient(180deg, rgba(0,0,0,0.94), rgba(0,0,0,0.72) 72%, transparent 100%)",
          }}
        />
        <div className="absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-[var(--hero-glow)] to-transparent" />
        <div className="absolute left-[-8rem] top-8 h-56 w-56 border border-[var(--hero-ring)] opacity-80" />
        <div className="absolute left-[-6rem] top-12 h-56 w-56 border border-[var(--hero-ring)] opacity-40" />
        <div className="absolute right-[-5rem] top-[-2rem] h-72 w-72" style={{ background: "radial-gradient(circle, var(--bg-glow-strong) 0, transparent 66%)" }} />
      </div>

      <div className="relative mx-auto flex min-h-[calc(100dvh-2.5rem)] w-full max-w-6xl items-center justify-center">
        <div className="grid w-full gap-5 lg:grid-cols-[1.16fr_0.84fr]">
          <section className="relative overflow-hidden border border-[var(--accent-outline)] bg-[var(--surface-overlay)] px-5 py-6 shadow-[var(--shadow-card)] sm:px-7 sm:py-7">
            <div className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,transparent,var(--accent),transparent)] opacity-80" />
            <div className="relative flex h-full flex-col justify-center gap-6">
              <div className="space-y-4">
                <h1 className="text-[1.8rem] font-black tracking-[0.03em] text-[var(--text)] sm:text-[2.3rem] lg:text-[2.7rem]">
                  {APP_LOGIN_NAME}
                </h1>
                <p className="max-w-2xl text-lg font-semibold text-[var(--accent)] sm:text-xl">
                  {APP_TAGLINE}
                </p>
                <p className="max-w-2xl break-all text-sm leading-6 text-[var(--muted)]">
                  {hostSummary}
                </p>
              </div>

              <div
                className="h-px w-full max-w-sm opacity-80"
                style={{
                  background:
                    "linear-gradient(90deg, var(--accent-strong), rgba(122, 246, 214, 0.18), transparent)",
                }}
              />
              <div className="flex items-center gap-3 text-xs font-mono tracking-[0.18em] text-[var(--accent-strong)]">
                <span className="h-2 w-2 bg-[var(--accent)] shadow-[0_0_16px_var(--accent)]" />
                <span>{`AUTH GATE ${APP_VERSION}`}</span>
              </div>
            </div>
          </section>

          <section className="relative overflow-hidden border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-card)] sm:p-6">
            <div className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,transparent,var(--accent-strong),transparent)] opacity-70" />
            <div className="relative">
              <div className="font-mono text-[11px] tracking-[0.28em] text-[var(--accent-strong)]">
                ACCESS
              </div>
              <h2 className="mt-3 text-2xl font-bold text-[var(--text)]">接入控制台</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                账号登录，注册需注册码；也可 guest 只读进入。
                {allowLegacyTokenLogin ? <span className="sr-only">输入访问口令，管理本地主 Bot 与子 Bot。</span> : null}
              </p>

              <div className="mt-5 inline-flex rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] p-1">
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
                      ? "rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-slate-950"
                      : "rounded-lg px-4 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface)]"}
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
                  const legacyTokenMode = allowLegacyTokenLogin && mode === "login" && Boolean(username) && !password;
                  if (!username || (!password && !legacyTokenMode)) {
                    return;
                  }
                  if (mode === "register") {
                    const registerCode = String(formData.get("registerCode") || "").trim();
                    if (!registerCode) {
                      return;
                    }
                    void onRegister?.({ username, password, registerCode });
                    return;
                  }
                  void onLogin?.({ username, password });
                }}
              >
                <div className="flex flex-col gap-2">
                  <label htmlFor="username" className="text-sm font-medium text-[var(--muted)]">用户名</label>
                  <input
                    id="username"
                    name="username"
                    type="text"
                    aria-label={allowLegacyTokenLogin && mode === "login" ? "访问口令" : undefined}
                    className="w-full border border-[var(--accent-outline)] bg-[var(--surface-strong)] px-4 py-3 text-[var(--text)] shadow-sm focus:border-[var(--accent)] focus:outline-none transition-colors"
                    placeholder="alice"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <label htmlFor="password" className="text-sm font-medium text-[var(--muted)]">密码</label>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    className="w-full border border-[var(--accent-outline)] bg-[var(--surface-strong)] px-4 py-3 text-[var(--text)] shadow-sm focus:border-[var(--accent)] focus:outline-none transition-colors"
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
                      className="w-full border border-[var(--accent-outline)] bg-[var(--surface-strong)] px-4 py-3 text-[var(--text)] shadow-sm focus:border-[var(--accent)] focus:outline-none transition-colors"
                      placeholder="INVITE-001"
                    />
                  </div>
                ) : null}
                {error ? (
                  <div className="border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                    {error}
                  </div>
                ) : null}
                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full border border-[var(--accent-outline)] bg-[var(--accent)] px-4 py-3 text-base font-semibold text-slate-950 shadow-[0_14px_32px_var(--accent-soft-strong)] transition-opacity hover:opacity-90 active:scale-[0.98] disabled:opacity-60"
                >
                  {isLoading ? "处理中..." : mode === "register" ? "注册并登录" : "登录"}
                </button>
                <button
                  type="button"
                  onClick={() => void onGuestLogin?.()}
                  disabled={isLoading}
                  className="w-full border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm font-medium text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
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
