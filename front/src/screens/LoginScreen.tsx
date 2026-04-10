type Props = {
  onLogin?: (token: string) => Promise<void> | void;
  isLoading?: boolean;
  error?: string;
};

export function LoginScreen({ onLogin, isLoading, error }: Props) {
  return (
    <main className="flex flex-col items-center justify-center min-h-[100dvh] bg-[var(--bg)] p-4">
      <div className="w-full max-w-sm bg-[var(--surface)] p-8 rounded-2xl shadow-[var(--shadow-card)] border border-[var(--border)]">
        <h1 className="text-3xl font-bold text-center mb-8 text-[var(--text)]">🦞Safe Claw</h1>
        <form
          className="flex flex-col gap-4"
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
              className="w-full px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] focus:outline-none focus:border-[var(--accent)] transition-colors"
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
            className="w-full py-3 mt-4 bg-[var(--accent)] text-white rounded-xl font-medium hover:opacity-90 transition-opacity active:scale-[0.98] disabled:opacity-60"
          >
            {isLoading ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </main>
  );
}
