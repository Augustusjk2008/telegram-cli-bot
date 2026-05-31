import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Puzzle } from "lucide-react";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { PluginCatalog } from "../components/PluginCatalog";
import { SectionHeader } from "../components/SectionHeader";
import { SurfacePanel } from "../components/SurfacePanel";
import { ToolbarButton, toolbarButtonClass } from "../components/ToolbarButton";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { HostEffect, PluginSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client?: WebBotClient;
  botAlias?: string;
  canOperate?: boolean;
  embedded?: boolean;
  onApplyHostEffects?: (effects: HostEffect[]) => Promise<void> | void;
  onOpenPluginView?: (target: {
    pluginId: string;
    viewId: string;
    title: string;
    input: Record<string, unknown>;
  }) => Promise<void> | void;
};

function sectionStackClass(extra = "") {
  return clsx("min-w-0 space-y-3 bg-[var(--workbench-titlebar-bg)]", extra);
}

function sectionBodyClass(extra = "") {
  return clsx("px-3", extra);
}

function buttonClass(extra = "") {
  return toolbarButtonClass("plain", "sm", extra);
}

export function PluginsScreen({
  client = new MockWebBotClient(),
  botAlias = "main",
  canOperate = true,
  embedded = false,
  onApplyHostEffects,
  onOpenPluginView,
}: Props) {
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [updatingPluginId, setUpdatingPluginId] = useState("");
  const [pendingUninstallPlugin, setPendingUninstallPlugin] = useState("");
  const [installPickerOpen, setInstallPickerOpen] = useState(false);
  const [installingPlugin, setInstallingPlugin] = useState(false);
  const requestIdRef = useRef(0);

  function loadData(refresh = false, nextNotice = "") {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setError("");
    if (!nextNotice) {
      setNotice("");
    }

    client.listPlugins(refresh)
      .then((pluginData) => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setPlugins(pluginData);
        if (nextNotice) {
          setNotice(nextNotice);
        }
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setError(err instanceof Error && err.message ? err.message : "插件列表加载失败");
        setLoading(false);
      });
  }

  useEffect(() => {
    loadData();
    return () => {
      requestIdRef.current += 1;
    };
  }, [client]);

  function updatePlugin(pluginId: string, input: Parameters<WebBotClient["updatePlugin"]>[1]) {
    if (!canOperate) {
      return;
    }
    setUpdatingPluginId(pluginId);
    setError("");
    setNotice("");
    client.updatePlugin(pluginId, input)
      .then((updated) => {
        setPlugins((current) => current.map((plugin) => (plugin.id === updated.id ? updated : plugin)));
        setNotice(`${updated.name} 设置已保存`);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error && err.message ? err.message : "插件配置保存失败");
      })
      .finally(() => {
        setUpdatingPluginId("");
      });
  }

  function installPluginFromPath(sourcePath: string) {
    if (!canOperate) {
      return;
    }
    setInstallingPlugin(true);
    setError("");
    setNotice("");
    client.installPlugin({ sourcePath, force: true, allowDevSourcePath: true })
      .then((installed) => {
        loadData(false, `${installed.name} 已安装`);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error && err.message ? err.message : "插件安装失败");
      })
      .finally(() => {
        setInstallingPlugin(false);
      });
  }

  function uninstallPlugin(pluginId: string) {
    if (!canOperate) {
      return;
    }
    setUpdatingPluginId(pluginId);
    setError("");
    setNotice("");
    client.uninstallPlugin(pluginId)
      .then(() => {
        setPendingUninstallPlugin("");
        loadData(true, "插件已卸载");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error && err.message ? err.message : "卸载插件失败");
      })
      .finally(() => {
        setUpdatingPluginId("");
      });
  }

  const headerActions = (
    <div className="flex shrink-0 items-center gap-1.5">
      <ToolbarButton
        type="button"
        onClick={() => setInstallPickerOpen(true)}
        disabled={!canOperate || loading || installingPlugin}
      >
        安装插件
      </ToolbarButton>
      <ToolbarButton
        type="button"
        onClick={() => loadData(true)}
        disabled={loading}
      >
        刷新
      </ToolbarButton>
    </div>
  );

  const uninstallDialog = pendingUninstallPlugin ? (
    <div role="dialog" aria-modal="true" aria-labelledby="plugin-uninstall-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <SurfacePanel className="w-full max-w-md p-4">
        <h2 id="plugin-uninstall-title" className="text-base font-semibold text-[var(--text)]">卸载插件</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">卸载后会停止插件运行时并清理视图缓存。</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={() => setPendingUninstallPlugin("")} className={buttonClass()}>取消</button>
          <button type="button" disabled={!canOperate || updatingPluginId === pendingUninstallPlugin} onClick={() => uninstallPlugin(pendingUninstallPlugin)} className={buttonClass("border-red-200 text-red-700 hover:bg-red-50")}>确认卸载</button>
        </div>
      </SurfacePanel>
    </div>
  ) : null;
  const renderedUninstallDialog = uninstallDialog && typeof document !== "undefined"
    ? createPortal(uninstallDialog, document.body)
    : uninstallDialog;
  const installPickerDialog = installPickerOpen && canOperate ? (
    <DirectoryPickerDialog
      title="选择含 plugin.json 的插件根目录"
      botAlias={botAlias}
      client={client}
      onPick={(path) => installPluginFromPath(path)}
      onClose={() => setInstallPickerOpen(false)}
    />
  ) : null;
  const renderedInstallPickerDialog = installPickerDialog && typeof document !== "undefined"
    ? createPortal(installPickerDialog, document.body)
    : installPickerDialog;

  return (
    <>
      <main className={clsx("flex h-full min-h-0 flex-col", embedded ? "bg-[var(--workbench-titlebar-bg)]" : "bg-[var(--workbench-panel-bg)]")}>
        {embedded ? null : (
          <header className="border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Puzzle className="h-4 w-4 text-[var(--accent)]" aria-hidden="true" />
                  <h1 className="text-lg font-semibold">插件</h1>
                </div>
                <p className="mt-1 truncate text-xs text-[var(--muted)]">安装时选直接包含 plugin.json 的插件根目录。</p>
              </div>
              {headerActions}
            </div>
          </header>
        )}

        <section
          data-testid="plugins-scroll-region"
          className={clsx(
            "min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto",
            embedded ? "bg-[var(--workbench-titlebar-bg)] py-0.5" : "bg-[var(--workbench-panel-bg)] p-3",
          )}
        >
          <div className={sectionStackClass("mx-auto w-full max-w-6xl")}>
            {embedded ? (
              <SurfacePanel data-testid="plugins-overview-panel">
                <div data-testid="plugins-overview-header">
                  <SectionHeader
                    title="插件"
                    icon={<Puzzle className="h-4 w-4" aria-hidden="true" />}
                    actions={headerActions}
                    className="gap-3"
                  />
                </div>
                <div className={sectionBodyClass("py-2")}>
                  <p className="text-sm text-[var(--muted)]">安装时选直接包含 plugin.json 的插件根目录。</p>
                  {!canOperate ? <p className="mt-1 text-xs text-[var(--muted)]">只读模式</p> : null}
                </div>
              </SurfacePanel>
            ) : (
              <SurfacePanel data-testid="plugins-overview-panel">
                <div className={sectionBodyClass("py-2")}>
                  <p className="text-sm text-[var(--muted)]">打开匹配文件会自动进入对应插件视图。</p>
                  {!canOperate ? <p className="mt-1 text-xs text-[var(--muted)]">只读模式</p> : null}
                </div>
              </SurfacePanel>
            )}

            <PluginCatalog
              plugins={plugins}
              botAlias={botAlias}
              client={client}
              loading={loading}
              error={error}
              updatingPluginId={updatingPluginId}
              onUpdatePlugin={canOperate ? updatePlugin : undefined}
              onApplyHostEffects={onApplyHostEffects}
              onOpenPluginView={onOpenPluginView}
              onNotice={setNotice}
              renderPluginActions={(plugin) => (
                <button
                  type="button"
                  onClick={() => setPendingUninstallPlugin(plugin.id)}
                  disabled={!canOperate || updatingPluginId === plugin.id}
                  className={buttonClass("border-red-200 text-red-700 hover:bg-red-50")}
                >
                  卸载
                </button>
              )}
            />
            {notice ? (
              <SurfacePanel className="border-emerald-200 bg-emerald-50 shadow-[var(--shadow-soft)]">
                <div className={sectionBodyClass("py-2 text-sm text-emerald-700")}>{notice}</div>
              </SurfacePanel>
            ) : null}
          </div>
        </section>
      </main>
      {renderedInstallPickerDialog}
      {renderedUninstallDialog}
    </>
  );
}
