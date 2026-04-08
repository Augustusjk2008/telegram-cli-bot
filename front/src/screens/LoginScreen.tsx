export function LoginScreen({ onLogin }: { onLogin?: () => void }) {
  return (
    <main className="flex flex-col items-center justify-center min-h-[100dvh] bg-[var(--bg)] p-4">
      <div className="w-full max-w-sm bg-[var(--surface)] p-8 rounded-2xl shadow-[var(--shadow-card)] border border-[var(--border)]">
        <h1 className="text-3xl font-bold text-center mb-8 text-[var(--text)]">Web Bot</h1>
        <form 
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            const formData = new FormData(e.currentTarget);
            const password = String(formData.get("password") || "").trim();
            if (password) {
              onLogin?.();
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
          <button 
            type="submit"
            className="w-full py-3 mt-4 bg-[var(--accent)] text-white rounded-xl font-medium hover:opacity-90 transition-opacity active:scale-[0.98]"
          >
            登录
          </button>
        </form>
      </div>
    </main>
  );
}
