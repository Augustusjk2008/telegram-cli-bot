import { useEffect, useRef, useState } from "react";
import { Puzzle } from "lucide-react";
import { PluginCatalog } from "../components/PluginCatalog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { HostEffect, PluginSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client?: WebBotClient;
  botAlias?: string;
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
  embedded = false,
  onApplyHostEffects,
  onOpenPluginView,
}: Props) {
  const [plugins, setPlugins] = useState<PluginSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [updatingPluginId, setUpdatingPluginId] = useState("");
  const requestIdRef = useRef(0);

  function loadPlugins(refresh = false) {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    setError("");
    setNotice("");

    client.listPlugins(refresh)
      .then((data) => {
        if (requestIdRef.current !== requestId) {
          return;
        }
        setPlugins(data);
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
    loadPlugins();
    return () => {
      requestIdRef.current += 1;
    };
  }, [client]);

  function updatePlugin(pluginId: string, input: Parameters<WebBotClient["updatePlugin"]>[1]) {
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

  return (
    <div className={embedded ? "space-y-4 p-4" : "h-full overflow-y-auto p-4 sm:p-6"}>
      <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-base font-semibold text-[var(--text)]">
              <Puzzle className="h-4 w-4 text-[var(--accent)]" aria-hidden="true" />
              插件
            </h1>
            <p className="mt-1 text-sm text-[var(--muted)]">点击刷新后重新扫描</p>
          </div>
          <button
            type="button"
            onClick={() => loadPlugins(true)}
            disabled={loading}
            className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-60"
          >
            刷新
          </button>
        </div>
      </section>

      <PluginCatalog
        plugins={plugins}
        botAlias={botAlias}
        client={client}
        loading={loading}
        error={error}
        updatingPluginId={updatingPluginId}
        onUpdatePlugin={updatePlugin}
        onApplyHostEffects={onApplyHostEffects}
        onOpenPluginView={onOpenPluginView}
        onNotice={setNotice}
      />
      {notice ? <p className="text-sm text-[var(--muted)]">{notice}</p> : null}
    </div>
  );
}
