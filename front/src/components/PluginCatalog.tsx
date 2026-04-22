import type { PluginSummary, PluginUpdateInput } from "../services/types";

type Props = {
  plugins: PluginSummary[];
  loading?: boolean;
  error?: string;
  emptyText?: string;
  showUsageHint?: boolean;
  updatingPluginId?: string;
  onUpdatePlugin?: (pluginId: string, input: PluginUpdateInput) => void;
};

export function PluginCatalog({
  plugins,
  loading = false,
  error = "",
  emptyText = "未检测到插件",
  showUsageHint = false,
  updatingPluginId = "",
  onUpdatePlugin,
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
        <article key={plugin.id} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="font-medium text-[var(--text)]">{plugin.name}</div>
              {onUpdatePlugin ? (
                <div className="mt-1 text-xs text-[var(--muted)]">
                  {plugin.enabled === false ? "已禁用" : "已启用"} · v{plugin.version}
                </div>
              ) : null}
            </div>
            {onUpdatePlugin ? (
              <button
                type="button"
                disabled={updatingPluginId === plugin.id}
                onClick={() => onUpdatePlugin(plugin.id, { enabled: plugin.enabled === false })}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
                aria-label={`${plugin.enabled === false ? "启用" : "禁用"} ${plugin.name}`}
              >
                {plugin.enabled === false ? "启用" : "禁用"}
              </button>
            ) : (
              <div className="text-xs text-[var(--muted)]">v{plugin.version}</div>
            )}
          </div>
          <p className="mt-1 text-sm text-[var(--muted)]">{plugin.description}</p>

          {onUpdatePlugin && typeof plugin.config?.lodEnabled === "boolean" ? (
            <label className="mt-3 flex items-center gap-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={plugin.config.lodEnabled}
                disabled={updatingPluginId === plugin.id}
                onChange={(event) => onUpdatePlugin(plugin.id, { config: { lodEnabled: event.currentTarget.checked } })}
                aria-label={`${plugin.name} 启用 LOD`}
              />
              启用 LOD
            </label>
          ) : null}

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
