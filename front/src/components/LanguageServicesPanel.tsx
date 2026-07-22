import { Download, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { WebApiClientError } from "../services/types";
import type {
  LanguageServerAvailability,
  LanguageServerCatalog,
  LanguageServerProviderId,
  LanguageServerProviderStatus,
  LanguageServerSource,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import { toolbarButtonClass } from "./ToolbarButton";

type Props = {
  botAlias: string;
  client: WebBotClient;
  canManage: boolean;
  onCatalogChanged?: () => void;
};

const PROVIDERS: Array<{ id: LanguageServerProviderId; label: string; shortLabel: string }> = [
  { id: "pyright", label: "Python · Pyright", shortLabel: "Pyright" },
  { id: "typescript", label: "TypeScript / JavaScript · TypeScript Language Server", shortLabel: "TypeScript Language Server" },
  { id: "clangd", label: "C / C++ · clangd", shortLabel: "clangd" },
];

function sourceLabel(source: LanguageServerSource | null) {
  if (source === "custom") return "自定义命令";
  if (source === "path") return "PATH";
  if (source === "managed") return "托管安装";
  return "未发现";
}

function statusLabel(status: LanguageServerAvailability) {
  if (status === "available") return "可用";
  if (status === "missing") return "缺失";
  if (status === "installing") return "安装中";
  return "错误";
}

function statusClassName(status: LanguageServerAvailability) {
  if (status === "available") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "installing") return "border-sky-200 bg-sky-50 text-sky-700";
  if (status === "missing") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-red-200 bg-red-50 text-red-700";
}

function missingProviderStatus(provider: LanguageServerProviderId): LanguageServerProviderStatus {
  return {
    provider,
    status: "missing",
    source: null,
    version: "",
    commandSummary: "",
    canInstall: false,
    canUpdate: false,
    message: "后端未返回该服务状态",
    error: "后端未返回该服务状态",
  };
}

function isForbidden(error: unknown) {
  if (error instanceof WebApiClientError) {
    return error.status === 403 || error.code === "forbidden";
  }
  if (!error || typeof error !== "object") {
    return false;
  }
  const candidate = error as { status?: unknown; code?: unknown };
  return candidate.status === 403 || candidate.code === "forbidden";
}

function panelErrorMessage(error: unknown, fallback: string) {
  return isForbidden(error) ? "当前账号没有此操作权限，请联系管理员" : getErrorMessage(error, fallback);
}

function catalogChanged(previous: LanguageServerCatalog | null, next: LanguageServerCatalog) {
  if (!previous || previous.providers.length !== next.providers.length) {
    return true;
  }
  return next.providers.some((item) => {
    const current = previous.providers.find((candidate) => candidate.provider === item.provider);
    return !current
      || current.status !== item.status
      || current.source !== item.source
      || current.version !== item.version
      || current.error !== item.error;
  });
}

export function LanguageServicesPanel({ botAlias, client, canManage, onCatalogChanged }: Props) {
  const [catalog, setCatalog] = useState<LanguageServerCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actionProvider, setActionProvider] = useState<LanguageServerProviderId | null>(null);
  const [error, setError] = useState("");
  const catalogRequestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const requestId = catalogRequestRef.current + 1;
    catalogRequestRef.current = requestId;
    setLoading(true);
    setError("");
    void client.getLanguageServerCatalog(botAlias)
      .then((next) => {
        if (!cancelled && catalogRequestRef.current === requestId) {
          setCatalog(next);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled && catalogRequestRef.current === requestId) {
          setError(panelErrorMessage(reason, "读取语言服务状态失败"));
        }
      })
      .finally(() => {
        if (!cancelled && catalogRequestRef.current === requestId) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

  useEffect(() => {
    if (!catalog?.providers.some((item) => item.status === "installing")) {
      return undefined;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      const requestId = catalogRequestRef.current + 1;
      catalogRequestRef.current = requestId;
      void client.getLanguageServerCatalog(botAlias)
        .then((next) => {
          if (cancelled || catalogRequestRef.current !== requestId) return;
          const changed = catalogChanged(catalog, next);
          setCatalog(next);
          if (changed) {
            onCatalogChanged?.();
          }
        })
        .catch(() => {
          // 安装任务仍可在后端继续，保留当前可恢复状态，用户可手动重新检测。
        });
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [botAlias, catalog, client, onCatalogChanged]);

  const providers = useMemo(() => PROVIDERS.map((meta) => ({
    ...meta,
    status: catalog?.providers.find((item) => item.provider === meta.id) || missingProviderStatus(meta.id),
  })), [catalog]);
  const canRefresh = canManage && (catalog?.canRefresh ?? true);

  const refresh = async () => {
    if (!canManage || refreshing || !canRefresh) return;
    const requestId = catalogRequestRef.current + 1;
    catalogRequestRef.current = requestId;
    setRefreshing(true);
    setError("");
    try {
      const next = await client.refreshLanguageServerCatalog();
      if (catalogRequestRef.current !== requestId) return;
      setCatalog(next);
      onCatalogChanged?.();
    } catch (reason) {
      if (catalogRequestRef.current !== requestId) return;
      setError(panelErrorMessage(reason, "重新检测语言服务失败"));
    } finally {
      if (catalogRequestRef.current === requestId) {
        setRefreshing(false);
      }
    }
  };

  const install = async (provider: LanguageServerProviderId, update: boolean) => {
    if (actionProvider) return;
    const requestId = catalogRequestRef.current + 1;
    catalogRequestRef.current = requestId;
    setActionProvider(provider);
    setRefreshing(false);
    setError("");
    try {
      const next = await client.installLanguageServer(provider, { update });
      if (catalogRequestRef.current !== requestId) return;
      setCatalog(next);
      setLoading(false);
      onCatalogChanged?.();
    } catch (reason) {
      if (catalogRequestRef.current !== requestId) return;
      setError(panelErrorMessage(reason, update ? "更新语言服务失败" : "安装语言服务失败"));
    } finally {
      if (catalogRequestRef.current === requestId) {
        setActionProvider(null);
      }
    }
  };

  return (
    <section
      aria-labelledby="language-services-title"
      className="space-y-4 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-4 shadow-[var(--shadow-soft)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 id="language-services-title" className="text-base font-semibold text-[var(--text)]">语言服务</h2>
          <p className="text-sm text-[var(--muted)]">用于 Python、TypeScript / JavaScript 与 C / C++ 的语义代码导航。</p>
        </div>
        {canManage ? (
          <button
            type="button"
            aria-label="重新检测语言服务"
            onClick={() => void refresh()}
            disabled={loading || refreshing || Boolean(actionProvider) || !canRefresh}
            className={toolbarButtonClass("plain", "md")}
          >
            <RefreshCw className="h-4 w-4" />
            {refreshing ? "检测中..." : "重新检测"}
          </button>
        ) : null}
      </div>

      {error ? (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {loading ? <div className="text-sm text-[var(--muted)]">正在读取语言服务状态...</div> : null}

      <div className="space-y-3">
        {providers.map(({ id, label, shortLabel, status }) => {
          const updating = status.canUpdate && (status.status === "available" || !status.canInstall);
          const canManageItem = canManage && (status.canInstall || status.canUpdate);
          const operating = actionProvider === id;
          return (
            <article key={id} data-testid={`language-service-${id}`} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-medium text-[var(--text)]">{label}</h3>
                    <span
                      data-testid={`language-service-status-${id}`}
                      className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusClassName(status.status)}`}
                    >
                      {statusLabel(status.status)}
                    </span>
                  </div>
                  <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-[var(--muted)]">来源</dt>
                    <dd className="text-[var(--text)]">{sourceLabel(status.source)}</dd>
                    <dt className="text-[var(--muted)]">版本</dt>
                    <dd className="text-[var(--text)]">{status.version || "-"}</dd>
                    <dt className="text-[var(--muted)]">命令</dt>
                    <dd className="break-all font-mono text-xs text-[var(--text)]">{status.commandSummary || "-"}</dd>
                  </dl>
                  {status.message ? (
                    <p className={status.status === "error" ? "text-sm text-red-700" : "text-sm text-[var(--muted)]"}>
                      {status.message}
                    </p>
                  ) : null}
                  {!canManage && (status.canInstall || status.canUpdate) ? (
                    <p className="text-sm text-[var(--muted)]">仅管理员可以安装或更新语言服务。</p>
                  ) : null}
                </div>

                {canManageItem ? (
                  <button
                    type="button"
                    aria-label={`${updating ? "更新" : "安装"} ${shortLabel}`}
                    onClick={() => void install(id, updating)}
                    disabled={Boolean(actionProvider) || status.status === "installing"}
                    className={toolbarButtonClass("primary", "md")}
                  >
                    <Download className="h-4 w-4" />
                    {operating ? (updating ? "更新中..." : "安装中...") : (updating ? "更新" : "安装")}
                  </button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
