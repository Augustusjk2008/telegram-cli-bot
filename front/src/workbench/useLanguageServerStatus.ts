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
    setState({ provider, status: null, loading: true, error: "" });
    void client.getLanguageServerCatalog(botAlias)
      .then((catalog) => {
        if (cancelled) return;
        setState({
          provider,
          status: catalog.providers.find((item) => item.provider === provider) || missingStatus(provider),
          loading: false,
          error: "",
        });
      })
      .catch(() => {
        if (cancelled) return;
        const error = "无法读取语言服务状态";
        setState({ provider, status: unavailableStatus(provider, error), loading: false, error });
      });
    return () => {
      cancelled = true;
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
