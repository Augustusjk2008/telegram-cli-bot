import { clsx } from "clsx";
import { useState, type ReactNode } from "react";
import type { HostEffect, PluginAction, PluginSummary, PluginUpdateInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DirectoryPickerDialog } from "./DirectoryPickerDialog";
import { toolbarButtonClass } from "./ToolbarButton";
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
  renderPluginActions?: (plugin: PluginSummary) => ReactNode;
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

function getOpenPluginViewAction(action: PluginAction) {
  return action.hostAction?.type === "open_plugin_view" ? action.hostAction : null;
}

function shouldPickFolder(action: PluginAction) {
  return Boolean(action.payload?.folderPicker);
}

function getFolderInputKey(action: PluginAction) {
  const key = action.payload?.folderInputKey;
  return typeof key === "string" && key.trim() ? key.trim() : "path";
}

function getFolderDialogTitle(action: PluginAction) {
  const title = action.payload?.folderTitle;
  return typeof title === "string" && title.trim() ? title.trim() : "选择文件夹";
}

function sectionClass(extra = "") {
  return clsx(
    "min-w-0 overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-soft)]",
    extra,
  );
}

function sectionBodyClass(extra = "") {
  return clsx("px-3", extra);
}

function buttonClass(extra = "") {
  return toolbarButtonClass("plain", "sm", extra);
}

function statusBadgeClass(enabled: boolean) {
  return enabled
    ? "inline-flex rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700"
    : "inline-flex rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700";
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
  renderPluginActions,
}: Props) {
  const [actionError, setActionError] = useState("");
  const [folderAction, setFolderAction] = useState<{ plugin: PluginSummary; action: PluginAction } | null>(null);
  const [expandedPluginIds, setExpandedPluginIds] = useState<string[]>([]);

  function togglePluginExpanded(pluginId: string) {
    setExpandedPluginIds((current) => (
      current.includes(pluginId)
        ? current.filter((id) => id !== pluginId)
        : [...current, pluginId]
    ));
  }

  function openCatalogPluginView(action: PluginAction, inputOverride?: Record<string, unknown>) {
    const openViewAction = getOpenPluginViewAction(action);
    if (!client || !botAlias || !openViewAction) {
      return false;
    }
    const input = inputOverride || openViewAction.input;
    setActionError("");
    if (onOpenPluginView) {
      void Promise.resolve(onOpenPluginView({
        pluginId: openViewAction.pluginId,
        viewId: openViewAction.viewId,
        title: openViewAction.title,
        input,
      })).catch((nextError: unknown) => {
        setActionError(nextError instanceof Error ? nextError.message : "插件动作执行失败");
      });
      return true;
    }
    void client.openPluginView(
      botAlias,
      openViewAction.pluginId,
      openViewAction.viewId,
      input,
    ).catch((nextError: unknown) => {
      setActionError(nextError instanceof Error ? nextError.message : "插件动作执行失败");
    });
    return true;
  }

  function runCatalogAction(plugin: PluginSummary, action: PluginAction) {
    const defaultView = plugin.views[0];
    const openViewAction = getOpenPluginViewAction(action);
    if (action.target === "plugin" && !defaultView) {
      setActionError("插件未提供默认视图");
      return;
    }
    if (client && botAlias && openViewAction) {
      if (shouldPickFolder(action)) {
        setFolderAction({ plugin, action });
        return;
      }
      openCatalogPluginView(action);
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
    return (
      <section className={sectionClass()}>
        <div className={sectionBodyClass("py-2 text-sm text-[var(--muted)]")}>正在检测插件...</div>
      </section>
    );
  }

  if (error || actionError) {
    return (
      <section className={sectionClass()}>
        <div className={sectionBodyClass("py-2 text-sm text-[var(--danger)]")}>{error || actionError}</div>
      </section>
    );
  }

  if (plugins.length === 0) {
    return (
      <section className={sectionClass()}>
        <div className={sectionBodyClass("py-2 text-sm text-[var(--muted)]")}>{emptyText}</div>
      </section>
    );
  }

  return (
    <section data-testid="plugins-catalog" className={sectionClass()}>
      {showUsageHint ? (
        <div className={sectionBodyClass("border-b border-[var(--workbench-hairline)] py-2 text-sm text-[var(--muted)]")}>打开匹配文件会自动进入对应插件视图。</div>
      ) : null}

      <div className={sectionBodyClass("py-3")}>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] gap-3">
          {plugins.map((plugin) => (
            <article
              key={plugin.id}
              data-testid={`plugin-catalog-item-${plugin.id}`}
              className="min-w-0 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] shadow-[var(--shadow-soft)]"
            >
              {(() => {
                const primaryAction = client && botAlias ? getPrimaryCatalogAction(plugin) : null;
                const extraActions = primaryAction
                  ? (plugin.catalogActions || []).filter((action) => action.id !== primaryAction.id)
                  : (plugin.catalogActions || []);
                const pluginEnabled = plugin.enabled !== false;
                const expanded = expandedPluginIds.includes(plugin.id);
                const toggleButtonClassName = pluginEnabled
                  ? buttonClass("border-red-500 text-red-600")
                  : buttonClass("border-emerald-500 text-emerald-600");
                const expandButtonClassName = buttonClass("border-[var(--workbench-hairline)] text-[var(--muted)]");

                return (
                  <>
                    <div className="flex min-w-0 flex-col gap-3 px-3 py-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-[var(--text)]">{plugin.name}</div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                          <span className={statusBadgeClass(pluginEnabled)}>{pluginEnabled ? "已启用" : "已禁用"}</span>
                          <span>v{plugin.version}</span>
                          {plugin.views.length > 0 ? <span>{plugin.views.length} 个视图</span> : null}
                          {plugin.fileHandlers.length > 0 ? <span>{plugin.fileHandlers.length} 个文件处理器</span> : null}
                        </div>
                      </div>
                      <div className="flex w-full max-w-full min-w-0 flex-wrap items-center gap-1.5 sm:w-auto sm:justify-end">
                        {renderPluginActions ? (
                          <span className="inline-flex max-w-full min-w-0 [&>*]:max-w-full">
                            {renderPluginActions(plugin)}
                          </span>
                        ) : null}
                        {onUpdatePlugin ? (
                          <button
                            type="button"
                            disabled={updatingPluginId === plugin.id}
                            onClick={() => onUpdatePlugin(plugin.id, { enabled: plugin.enabled === false })}
                            className={toggleButtonClassName}
                            aria-label={`${plugin.enabled === false ? "启用" : "禁用"} ${plugin.name}`}
                          >
                            {plugin.enabled === false ? "启用" : "禁用"}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-label={`${expanded ? "收起" : "展开"} ${plugin.name}`}
                          onClick={() => togglePluginExpanded(plugin.id)}
                          className={expandButtonClassName}
                        >
                          {expanded ? "收起" : "展开"}
                        </button>
                      </div>
                    </div>

                    {expanded ? (
                      <div className="border-t border-[var(--workbench-hairline)] px-3 pb-3 pt-3">
                        <p className="text-sm leading-6 text-[var(--muted)]">{plugin.description}</p>

                        {client && botAlias && primaryAction ? (
                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={() => runCatalogAction(plugin, primaryAction)}
                              className={toolbarButtonClass("primary", "sm")}
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
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
                            {plugin.views.map((view) => (
                              <span key={view.id} className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 py-1">
                                视图 {view.title}
                              </span>
                            ))}
                          </div>
                        ) : null}

                        {plugin.fileHandlers.length > 0 ? (
                          <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
                            {plugin.fileHandlers.map((handler) => (
                              <span key={handler.id} className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 py-1">
                                支持 {handler.extensions.join(", ")}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </>
                );
              })()}
            </article>
          ))}
        </div>
      </div>
      {folderAction && client && botAlias ? (
        <DirectoryPickerDialog
          title={getFolderDialogTitle(folderAction.action)}
          botAlias={botAlias}
          client={client}
          initialPath={String(getOpenPluginViewAction(folderAction.action)?.input?.[getFolderInputKey(folderAction.action)] || "")}
          onPick={(path) => {
            const openViewAction = getOpenPluginViewAction(folderAction.action);
            if (!openViewAction) {
              return;
            }
            const key = getFolderInputKey(folderAction.action);
            openCatalogPluginView(folderAction.action, {
              ...openViewAction.input,
              [key]: path,
            });
          }}
          onClose={() => setFolderAction(null)}
        />
      ) : null}
    </section>
  );
}
