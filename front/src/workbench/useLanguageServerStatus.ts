import { useEffect, useState } from "react";
import type { LanguageServerProviderId, LanguageServerProviderStatus } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { inferLanguageServerProviderId } from "../utils/fileEditorLanguage";

export type ActiveLanguageServerStatus = {
  provider: LanguageServerProviderId | null;
  status: LanguageServerProviderStatus | null;
  loading: boolean;
};

type State = ActiveLanguageServerStatus & {
  error: string;
};

const RUNTIME_STATUS_POLL_INTERVAL_MS = 1000;

function unavailableStatus(provider: LanguageServerProviderId, error: string): LanguageServerProviderStatus {
  return {
    provider,
    status: "error",
    source: null,
    version: "",
    commandSummary: "",
    canInstall: false,
    canUpdate: false,
    message: error,
    error,
  };
}

function missingStatus(provider: LanguageServerProviderId): LanguageServerProviderStatus {
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

export function useLanguageServerStatus(
  client: WebBotClient,
  botAlias: string,
  activeFilePath: string,
  refreshKey = 0,
): ActiveLanguageServerStatus {
  const provider = inferLanguageServerProviderId(activeFilePath);
  const [state, setState] = useState<State>({ provider: null, status: null, loading: false, error: "" });

  useEffect(() => {
    if (!provider) {
      setState({ provider: null, status: null, loading: false, error: "" });
      return undefined;
    }
    let cancelled = false;
    let pollTimer: number | null = null;
    setState({ provider, status: null, loading: true, error: "" });
    const loadStatus = async () => {
      try {
        const catalog = await client.getLanguageServerCatalog(botAlias, provider);
        if (cancelled) return;
        const status = catalog.providers.find((item) => item.provider === provider) || missingStatus(provider);
        setState({ provider, status, loading: false, error: "" });
        if (status.runtimeState === "starting" || status.runtimeState === "indexing") {
          pollTimer = window.setTimeout(() => {
            pollTimer = null;
            void loadStatus();
          }, RUNTIME_STATUS_POLL_INTERVAL_MS);
        }
      } catch {
        if (cancelled) return;
        const error = "无法读取语言服务状态";
        setState({ provider, status: unavailableStatus(provider, error), loading: false, error });
      }
    };
    void loadStatus();
    return () => {
      cancelled = true;
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
      }
    };
  }, [botAlias, client, provider, refreshKey]);

  if (!provider) {
    return { provider: null, status: null, loading: false };
  }
  if (state.provider !== provider) {
    return { provider, status: null, loading: true };
  }
  return state;
}
