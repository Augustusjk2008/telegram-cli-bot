import { clsx } from "clsx";
import { ChevronDown, Search, Settings2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type { HostEffect, PluginAction, PluginSummary, PluginUpdateInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DirectoryPickerDialog } from "./DirectoryPickerDialog";
import { toolbarButtonClass } from "./ToolbarButton";
import { PluginActionBar } from "./plugin-renderers/PluginActionBar";
import { PluginConfigForm } from "./plugins/PluginConfigForm";
import { PluginIcon } from "./plugins/PluginIcon";
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
  onApplyHostEffects?: (effects: HostEffect[], pluginId?: string) => Promise<void> | void;
  onOpenPluginView?: (target: {
    pluginId: string;
    viewId: string;
    title: string;
    input: Record<string, unknown>;
  }) => Promise<void> | void;
  onNotice?: (message: string) => void;
  renderPluginActions?: (plugin: PluginSummary) => ReactNode;
};

type StatusFilter = "all" | "enabled" | "disabled";

const STATUS_FILTERS: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "enabled", label: "已启用" },
  { value: "disabled", label: "已禁用" },
];

const MAX_EXTENSION_CHIPS = 6;

const RENDERER_LABELS: Record<string, string> = {
  table: "表格",
  tree: "树视图",
  document: "文档",
  hex: "十六进制",
  media: "媒体",
  waveform: "波形",
};

function pluginExtensions(plugin: PluginSummary) {
  return Array.from(new Set(plugin.fileHandlers.flatMap((handler) => handler.extensions)));
}

function describeRenderers(plugin: PluginSummary) {
  const labels = Array.from(new Set(plugin.views.map((view) => RENDERER_LABELS[view.renderer] || view.renderer)));
  return labels.join(" / ");
}

function describePermissions(plugin: PluginSummary) {
  const permissions = plugin.runtime?.permissions;
  if (!permissions) {
    return "";
  }
  const labels = [
    permissions.workspaceRead ? "读取工作区" : "",
    permissions.workspaceList ? "列出目录" : "",
    permissions.workspaceWrite ? "写入工作区" : "",
    permissions.tempArtifacts ? "临时产物" : "",
  ].filter(Boolean);
  return labels.join("、");
}

function matchesQuery(plugin: PluginSummary, query: string) {
  if (!query) {
    return true;
  }
  const haystack = [plugin.id, plugin.name, plugin.description, ...pluginExtensions(plugin)].join(" ").toLowerCase();
  return query.split(/\s+/).every((term) => haystack.includes(term));
}

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
    "min-w-0 overflow-hidden rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] shadow-[var(--shadow-surface)]",
    extra,
  );
}

function sectionBodyClass(extra = "") {
  return clsx("px-3", extra);
}

function buttonClass(extra = "") {
  return toolbarButtonClass("plain", "sm", extra);
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
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const normalizedQuery = query.trim().toLowerCase();
  const statusCounts = useMemo(() => {
    const enabled = plugins.filter((plugin) => plugin.enabled !== false).length;
    return { all: plugins.length, enabled, disabled: plugins.length - enabled };
  }, [plugins]);
  const visiblePlugins = useMemo(() => plugins.filter((plugin) => {
    const enabled = plugin.enabled !== false;
    if (statusFilter === "enabled" && !enabled) {
      return false;
    }
    if (statusFilter === "disabled" && enabled) {
      return false;
    }
    return matchesQuery(plugin, normalizedQuery);
  }), [plugins, statusFilter, normalizedQuery]);

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
      applyHostEffects: (effects) => onApplyHostEffects?.(effects, plugin.id),
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

      <div data-testid="plugins-catalog-toolbar" className={sectionBodyClass("flex flex-wrap items-center gap-2 border-b border-[var(--workbench-hairline)] py-2")}>
        <label className="relative flex min-w-[12rem] flex-1 items-center">
          <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-[var(--muted)]" aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索名称、描述或扩展名"
            aria-label="搜索插件"
            className="h-8 w-full rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] pl-8 pr-2 text-xs text-[var(--text)] outline-none placeholder:text-[var(--muted)] focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]"
          />
        </label>
        <div role="radiogroup" aria-label="按状态筛选" className="inline-flex h-8 items-center rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] p-0.5">
          {STATUS_FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="radio"
              aria-checked={statusFilter === item.value}
              onClick={() => setStatusFilter(item.value)}
              className={clsx(
                "h-full rounded-[calc(var(--radius-control)-2px)] px-2.5 text-xs font-medium transition-colors",
                statusFilter === item.value
                  ? "bg-[var(--workbench-hover-bg)] text-[var(--text)]"
                  : "text-[var(--muted)] hover:text-[var(--text)]",
              )}
            >
              {item.label}
              <span className="ml-1 tabular-nums opacity-70">{statusCounts[item.value]}</span>
            </button>
          ))}
        </div>
      </div>

      <div className={sectionBodyClass("py-3")}>
        {visiblePlugins.length === 0 ? (
          <div className="py-6 text-center text-sm text-[var(--muted)]">没有匹配的插件</div>
        ) : null}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,19rem),1fr))] gap-3">
          {visiblePlugins.map((plugin) => {
            const primaryAction = client && botAlias ? getPrimaryCatalogAction(plugin) : null;
            const extraActions = primaryAction
              ? (plugin.catalogActions || []).filter((action) => action.id !== primaryAction.id)
              : (plugin.catalogActions || []);
            const pluginEnabled = plugin.enabled !== false;
            const expanded = expandedPluginIds.includes(plugin.id);
            const extensions = pluginExtensions(plugin);
            const shownExtensions = extensions.slice(0, MAX_EXTENSION_CHIPS);
            const hiddenExtensionCount = extensions.length - shownExtensions.length;
            const rendererLabel = describeRenderers(plugin);
            const updating = updatingPluginId === plugin.id;

            return (
              <article
                key={plugin.id}
                data-testid={`plugin-catalog-item-${plugin.id}`}
                data-enabled={pluginEnabled ? "true" : "false"}
                className={clsx(
                  "group flex min-w-0 flex-col rounded-lg border bg-[var(--workbench-panel-elevated-bg)] shadow-[var(--shadow-surface)] transition-colors",
                  expanded
                    ? "border-[var(--workbench-hover-border)] [grid-column:1/-1]"
                    : "border-[var(--workbench-hairline)] hover:border-[var(--workbench-hover-border)]",
                )}
              >
                <div className="flex min-w-0 flex-1 flex-col gap-2.5 px-3 pb-2.5 pt-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <PluginIcon plugin={plugin} muted={!pluginEnabled} />
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-2">
                        <h3 className={clsx("truncate text-sm font-semibold", pluginEnabled ? "text-[var(--text)]" : "text-[var(--muted)]")} title={pluginEnabled ? plugin.name : `${plugin.name}（已禁用）`}>
                          {plugin.name}
                        </h3>
                      </div>
                      <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--muted)]">
                        <span className="tabular-nums">v{plugin.version}</span>
                        {rendererLabel ? <><span aria-hidden="true">·</span><span className="truncate">{rendererLabel}</span></> : null}
                      </div>
                    </div>
                    {onUpdatePlugin ? (
                      <button
                        type="button"
                        role="switch"
                        aria-checked={pluginEnabled}
                        disabled={updating}
                        onClick={() => onUpdatePlugin(plugin.id, { enabled: !pluginEnabled })}
                        aria-label={`${pluginEnabled ? "禁用" : "启用"} ${plugin.name}`}
                        title={pluginEnabled ? "已启用，点击禁用" : "已禁用，点击启用"}
                        className={clsx(
                          "relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:opacity-55",
                          pluginEnabled
                            ? "border-transparent bg-[var(--accent)]"
                            : "border-[var(--workbench-hairline)] bg-[var(--workbench-hover-bg)]",
                        )}
                      >
                        <span
                          className={clsx(
                            "inline-block h-3.5 w-3.5 rounded-full shadow-sm transition-transform",
                            pluginEnabled ? "translate-x-[18px] bg-[var(--accent-foreground)]" : "translate-x-[3px] bg-[var(--muted)]",
                          )}
                        />
                      </button>
                    ) : null}
                  </div>

                  {plugin.description ? (
                    <p className={clsx("text-xs leading-5 text-[var(--muted)]", expanded ? "" : "line-clamp-2")} title={expanded ? undefined : plugin.description}>
                      {plugin.description}
                    </p>
                  ) : null}

                  {shownExtensions.length > 0 ? (
                    <div className="flex min-w-0 flex-wrap gap-1" aria-label="支持的文件类型">
                      {shownExtensions.map((extension) => (
                        <span key={extension} className="rounded border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-1.5 py-px font-mono text-[10.5px] text-[var(--muted)]">
                          {extension}
                        </span>
                      ))}
                      {hiddenExtensionCount > 0 ? (
                        <span className="px-1 py-px text-[10.5px] text-[var(--muted)]" title={extensions.slice(MAX_EXTENSION_CHIPS).join(", ")}>
                          +{hiddenExtensionCount}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div className="flex min-w-0 items-center gap-1.5 border-t border-[var(--workbench-hairline)] px-3 py-2">
                  {primaryAction ? (
                    <button
                      type="button"
                      disabled={!pluginEnabled}
                      onClick={() => runCatalogAction(plugin, primaryAction)}
                      className={toolbarButtonClass("primary", "sm", "min-w-0")}
                    >
                      <span className="truncate">{primaryAction.label}</span>
                    </button>
                  ) : null}
                  <div className="ml-auto flex shrink-0 items-center gap-1">
                    {renderPluginActions ? renderPluginActions(plugin) : null}
                    <button
                      type="button"
                      aria-expanded={expanded}
                      aria-label={`${expanded ? "收起" : "展开"} ${plugin.name}`}
                      onClick={() => togglePluginExpanded(plugin.id)}
                      className={toolbarButtonClass("ghost", "sm")}
                    >
                      {plugin.configSchema ? <Settings2 className="h-3.5 w-3.5" aria-hidden="true" /> : null}
                      {plugin.configSchema ? "设置" : "详情"}
                      <ChevronDown className={clsx("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
                    </button>
                  </div>
                </div>

                {expanded ? (
                  <div className="border-t border-[var(--workbench-hairline)] px-3 pb-3 pt-3">
                    {client && botAlias && extraActions.length > 0 ? (
                      <div className="mb-3 overflow-hidden rounded-md border border-[var(--workbench-hairline)]">
                        <PluginActionBar actions={extraActions} onRunAction={(action) => runCatalogAction(plugin, action)} />
                      </div>
                    ) : null}

                    {onUpdatePlugin ? (
                      <PluginConfigForm
                        plugin={plugin}
                        disabled={updating}
                        onSubmit={(input) => onUpdatePlugin(plugin.id, input)}
                      />
                    ) : null}

                    <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
                      <dt className="text-[var(--muted)]">插件 ID</dt>
                      <dd className="min-w-0 truncate font-mono text-[var(--text)]">{plugin.id}</dd>
                      {plugin.views.length > 0 ? (
                        <>
                          <dt className="text-[var(--muted)]">视图</dt>
                          <dd className="min-w-0 text-[var(--text)]">{plugin.views.map((view) => view.title || view.id).join("、")}</dd>
                        </>
                      ) : null}
                      {extensions.length > 0 ? (
                        <>
                          <dt className="text-[var(--muted)]">文件类型</dt>
                          <dd className="min-w-0 break-words font-mono text-[var(--text)]">{extensions.join(" ")}</dd>
                        </>
                      ) : null}
                      {describePermissions(plugin) ? (
                        <>
                          <dt className="text-[var(--muted)]">权限</dt>
                          <dd className="min-w-0 text-[var(--text)]">{describePermissions(plugin)}</dd>
                        </>
                      ) : null}
                    </dl>
                  </div>
                ) : null}
              </article>
            );
          })}
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
