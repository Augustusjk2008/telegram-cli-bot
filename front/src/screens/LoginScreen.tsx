import { APP_NAME, APP_YEAR } from "../theme";

type Props = {
  onLogin?: (token: string) => Promise<void> | void;
  isLoading?: boolean;
  error?: string;
};

function LoginRocketBadge() {
  return (
    <span
      role="img"
      aria-label="火箭徽标"
      className="text-[1.9rem] leading-none"
    >
      🚀
    </span>
  );
}

export function LoginScreen({ onLogin, isLoading, error }: Props) {
  return (
    <main className="relative min-h-[100dvh] overflow-hidden bg-[var(--bg)] px-4 py-5 sm:py-6">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute inset-0 opacity-70"
          style={{
            backgroundImage: [
              "linear-gradient(to right, var(--hero-grid) 1px, transparent 1px)",
              "linear-gradient(to bottom, var(--hero-grid) 1px, transparent 1px)",
            ].join(","),
            backgroundSize: "56px 56px",
            maskImage: "linear-gradient(180deg, rgba(0,0,0,0.82), transparent 88%)",
          }}
        />
        <div className="absolute -left-28 top-10 h-72 w-72 rounded-full border" style={{ borderColor: "var(--hero-ring)" }} />
        <div className="absolute -left-14 top-24 h-[24rem] w-[24rem] rounded-full border" style={{ borderColor: "var(--hero-ring)" }} />
        <div className="absolute right-[-6rem] top-[-3rem] h-80 w-80 rounded-full" style={{ background: "radial-gradient(circle, var(--hero-glow) 0, transparent 68%)" }} />
        <div className="absolute left-[18%] top-[14%] h-2 w-2 rounded-full bg-[var(--accent)] shadow-[0_0_18px_var(--accent)]" />
        <div className="absolute right-[16%] top-[28%] h-1.5 w-1.5 rounded-full bg-[var(--accent-strong)] shadow-[0_0_16px_var(--accent-strong)]" />
        <div className="absolute left-[72%] top-[12%] h-1.5 w-1.5 rounded-full bg-white/80" />
      </div>

      <div className="relative mx-auto flex min-h-[calc(100dvh-2.5rem)] w-full max-w-xl items-center justify-center">
        <div className="w-full space-y-5">
          <section className="rounded-[30px] border border-[var(--border)] bg-[var(--surface-overlay)] px-5 py-5 text-center shadow-[var(--shadow-card)] backdrop-blur sm:px-7">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-[var(--accent-outline)] bg-[var(--accent-soft)] text-2xl shadow-[0_0_28px_var(--accent-soft-strong)]">
              <LoginRocketBadge />
            </div>
            <div className="mt-4 space-y-2">
              <div className="text-[11px] tracking-[0.32em] text-[var(--accent-strong)]">SECURE ACCESS CONSOLE</div>
              <h1 className="text-3xl font-black tracking-tight text-[var(--text)] sm:text-4xl">{APP_NAME}</h1>
              <div className="text-xs font-semibold tracking-[0.34em] text-[var(--muted)]">{APP_YEAR}</div>
            </div>
          </section>

          <section className="relative overflow-hidden rounded-[30px] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-card)] backdrop-blur sm:p-6">
            <div className="absolute right-[-4rem] top-[-4rem] h-40 w-40 rounded-full" style={{ background: "radial-gradient(circle, var(--hero-glow) 0, transparent 70%)" }} />
            <div className="relative">
              <h2 className="text-xl font-bold text-[var(--text)] sm:text-2xl">安全接入</h2>

              <form
                className="mt-5 flex flex-col gap-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  const formData = new FormData(event.currentTarget);
                  const token = String(formData.get("password") || "").trim();
                  if (token) {
                    void onLogin?.(token);
                  }
                }}
              >
                <div className="flex flex-col gap-2">
                  <label htmlFor="password" className="text-sm font-medium text-[var(--muted)]">访问口令</label>
                  <input
                    id="password"
                    name="password"
                    type="password"
                    className="w-full rounded-2xl border border-[var(--border)] bg-[var(--surface-strong)] px-4 py-3 text-[var(--text)] shadow-sm focus:outline-none focus:border-[var(--accent)] transition-colors"
                    placeholder="请输入访问口令"
                  />
                </div>
                {error ? (
                  <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {error}
                  </div>
                ) : null}
                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full rounded-2xl bg-[var(--accent)] px-4 py-3 text-base font-semibold text-white shadow-[0_14px_32px_var(--accent-soft-strong)] hover:opacity-90 transition-opacity active:scale-[0.98] disabled:opacity-60"
                >
                  {isLoading ? "登录中..." : "登录"}
                </button>
              </form>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
