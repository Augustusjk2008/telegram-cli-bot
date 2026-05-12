import { useEffect, useRef, useState } from "react";
import { Puzzle } from "lucide-react";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { PluginCatalog } from "../components/PluginCatalog";
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
    client.installPlugin({ sourcePath })
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

  function reinstallPlugin(pluginId: string) {
    if (!canOperate) {
      return;
    }
    setUpdatingPluginId(pluginId);
    setError("");
    setNotice("");
    client.installPlugin({ pluginId, force: true })
      .then(() => {
        loadData(true, "插件已覆盖安装");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error && err.message ? err.message : "覆盖安装失败");
      })
      .finally(() => {
        setUpdatingPluginId("");
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

  return (
    <div className={embedded ? "space-y-4 p-4" : "h-full overflow-y-auto p-4 sm:p-6"}>
      <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-base font-semibold text-[var(--text)]">
              <Puzzle className="h-4 w-4 text-[var(--accent)]" aria-hidden="true" />
              插件
            </h1>
            <p className="mt-1 text-sm text-[var(--muted)]">安装时选直接包含 plugin.json 的插件根目录。</p>
            {!canOperate ? <p className="mt-1 text-xs text-[var(--muted)]">只读模式</p> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setInstallPickerOpen(true)}
              disabled={!canOperate || loading || installingPlugin}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              安装插件
            </button>
            <button
              type="button"
              onClick={() => loadData(true)}
              disabled={loading}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
            >
              刷新
            </button>
          </div>
        </div>
      </section>

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
      />
      {plugins.length ? (
        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
          <h2 className="text-sm font-semibold text-[var(--text)]">安装管理</h2>
          <div className="mt-3 space-y-2">
            {plugins.map((plugin) => (
              <div key={`manage-${plugin.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                <span className="text-sm text-[var(--text)]">{plugin.id}</span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => reinstallPlugin(plugin.id)}
                    disabled={!canOperate || updatingPluginId === plugin.id}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-60"
                  >
                    覆盖安装
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingUninstallPlugin(plugin.id)}
                    disabled={!canOperate || updatingPluginId === plugin.id}
                    className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                  >
                    卸载
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      {notice ? <p className="text-sm text-[var(--muted)]">{notice}</p> : null}
      {installPickerOpen && canOperate ? (
        <DirectoryPickerDialog
          title="选择含 plugin.json 的插件根目录"
          botAlias={botAlias}
          client={client}
          onPick={(path) => installPluginFromPath(path)}
          onClose={() => setInstallPickerOpen(false)}
        />
      ) : null}
      {pendingUninstallPlugin ? (
        <div role="dialog" aria-modal="true" aria-labelledby="plugin-uninstall-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <h2 id="plugin-uninstall-title" className="text-base font-semibold text-[var(--text)]">卸载插件</h2>
            <p className="mt-2 text-sm text-[var(--muted)]">卸载后会停止插件运行时并清理视图缓存。</p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setPendingUninstallPlugin("")} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]">取消</button>
              <button type="button" disabled={!canOperate || updatingPluginId === pendingUninstallPlugin} onClick={() => uninstallPlugin(pendingUninstallPlugin)} className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60">确认卸载</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
