import type { PluginSummary } from "../services/types";

type Props = {
  plugins: PluginSummary[];
  loading?: boolean;
  error?: string;
  emptyText?: string;
  showUsageHint?: boolean;
};

export function PluginCatalog({
  plugins,
  loading = false,
  error = "",
  emptyText = "未检测到插件",
  showUsageHint = false,
}: Props) {
  if (loading) {
    return <p className="text-sm text-[var(--muted)]">正在检测插件...</p>;
  }

  if (error) {
    return <p className="text-sm text-[var(--danger)]">{error}</p>;
  }

  if (plugins.length === 0) {
    return <p className="text-sm text-[var(--muted)]">{emptyText}</p>;
  }

  return (
    <div className="space-y-3">
      {showUsageHint ? (
        <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-sm text-[var(--muted)]">
          打开匹配文件会自动进入对应插件视图。
        </p>
      ) : null}

      {plugins.map((plugin) => (
        <article key={plugin.id} className="rounded-xl border border-[var(--border)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="font-medium text-[var(--text)]">{plugin.name}</div>
            <div className="text-xs text-[var(--muted)]">v{plugin.version}</div>
          </div>
          <p className="mt-1 text-sm text-[var(--muted)]">{plugin.description}</p>

          {plugin.views.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
              {plugin.views.map((view) => (
                <span key={view.id} className="rounded-full bg-[var(--surface-strong)] px-2 py-1">
                  视图 {view.title}
                </span>
              ))}
            </div>
          ) : null}

          {plugin.fileHandlers.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
              {plugin.fileHandlers.map((handler) => (
                <span key={handler.id} className="rounded-full bg-[var(--surface-strong)] px-2 py-1">
                  支持 {handler.extensions.join(", ")}
                </span>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
