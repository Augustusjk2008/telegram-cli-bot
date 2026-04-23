import { useState } from "react";
import type { HostEffect, PluginAction, PluginSummary, PluginUpdateInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { PluginActionBar } from "./plugin-renderers/PluginActionBar";
import { PluginConfigForm } from "./plugins/PluginConfigForm";
import { runPluginAction } from "./plugins/pluginActions";

type Props = {
  plugins: PluginSummary[];
  botAlias?: string;
  client?: WebBotClient;
  loading?: boolean;
  error?: string;
  emptyText?: string;
  showUsageHint?: boolean;
  updatingPluginId?: string;
  onUpdatePlugin?: (pluginId: string, input: PluginUpdateInput) => void;
  onApplyHostEffects?: (effects: HostEffect[]) => Promise<void> | void;
  onOpenPluginView?: (target: {
    pluginId: string;
    viewId: string;
    title: string;
    input: Record<string, unknown>;
  }) => Promise<void> | void;
  onNotice?: (message: string) => void;
};

function getPrimaryCatalogAction(plugin: PluginSummary): PluginAction | null {
  const directAction = (plugin.catalogActions || []).find((action) =>
    action.location === "catalog"
    && action.target === "host"
    && action.hostAction?.type === "open_plugin_view",
  );
  if (directAction) {
    return directAction;
  }
  if (plugin.fileHandlers.length === 0 && plugin.views.length > 0) {
    const view = plugin.views[0];
    return {
      id: `open-${plugin.id}`,
      label: `打开${view.title || plugin.name}`,
      target: "host",
      location: "catalog",
      variant: "primary",
      hostAction: {
        type: "open_plugin_view",
        pluginId: plugin.id,
        viewId: view.id,
        title: view.title || plugin.name,
        input: {},
      },
    };
  }
  return null;
}

export function PluginCatalog({
  plugins,
  botAlias = "",
  client,
  loading = false,
  error = "",
  emptyText = "未检测到插件",
  showUsageHint = false,
  updatingPluginId = "",
  onUpdatePlugin,
  onApplyHostEffects,
  onOpenPluginView,
  onNotice,
}: Props) {
  const [actionError, setActionError] = useState("");

  function runCatalogAction(plugin: PluginSummary, action: PluginAction) {
    const defaultView = plugin.views[0];
    const openViewAction = action.hostAction?.type === "open_plugin_view" ? action.hostAction : null;
    if (action.target === "plugin" && !defaultView) {
      setActionError("插件未提供默认视图");
      return;
    }
    if (client && botAlias && openViewAction) {
      setActionError("");
      if (onOpenPluginView) {
        void onOpenPluginView({
          pluginId: openViewAction.pluginId,
          viewId: openViewAction.viewId,
          title: openViewAction.title,
          input: openViewAction.input,
        });
        return;
      }
      void client.openPluginView(
        botAlias,
        openViewAction.pluginId,
        openViewAction.viewId,
        openViewAction.input,
      ).catch((nextError: unknown) => {
        setActionError(nextError instanceof Error ? nextError.message : "插件动作执行失败");
      });
      return;
    }
    setActionError("");
    void runPluginAction(action, {
      client: client as WebBotClient,
      botAlias,
      pluginId: plugin.id,
      viewId: openViewAction?.viewId || defaultView?.id || "",
      title: openViewAction?.title || defaultView?.title || plugin.name,
      inputPayload: openViewAction?.input || action.payload || {},
      applyHostEffects: onApplyHostEffects,
      reopenView: onOpenPluginView,
      pushToast: onNotice,
    }).catch((nextError: unknown) => {
      setActionError(nextError instanceof Error ? nextError.message : "插件动作执行失败");
    });
  }

  if (loading) {
    return <p className="text-sm text-[var(--muted)]">正在检测插件...</p>;
  }

  if (error || actionError) {
    return <p className="text-sm text-[var(--danger)]">{error || actionError}</p>;
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
          {(() => {
            const primaryAction = client && botAlias ? getPrimaryCatalogAction(plugin) : null;
            const extraActions = primaryAction
              ? (plugin.catalogActions || []).filter((action) => action.id !== primaryAction.id)
              : (plugin.catalogActions || []);

            return (
              <>
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

          {client && botAlias && primaryAction ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => runCatalogAction(plugin, primaryAction)}
                className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm text-white hover:opacity-90"
              >
                {primaryAction.label}
              </button>
              {extraActions.length > 0 ? <PluginActionBar actions={extraActions} onRunAction={(action) => runCatalogAction(plugin, action)} /> : null}
            </div>
          ) : null}

          {client && botAlias && !primaryAction && extraActions.length > 0 ? (
            <div className="mt-3">
              <PluginActionBar actions={extraActions} onRunAction={(action) => runCatalogAction(plugin, action)} />
            </div>
          ) : null}

          {onUpdatePlugin ? (
            <PluginConfigForm
              plugin={plugin}
              disabled={updatingPluginId === plugin.id}
              onSubmit={(input) => onUpdatePlugin(plugin.id, input)}
            />
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
              </>
            );
          })()}
        </article>
      ))}
    </div>
  );
}
