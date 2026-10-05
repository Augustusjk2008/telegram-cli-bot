import { useEffect, useMemo, useRef } from "react";
import type { WebBotClient } from "../services/webBotClient";
import { loadFilePreview, type FilePreviewOptions, type HtmlPreviewHandle } from "../utils/filePreview";

export function useFilePreviewLoader(client: WebBotClient, botAlias: string, scope: string) {
  const identity = `${botAlias}\n${scope}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const loader = useMemo(() => {
    let active = true;
    const requests = new Map<string, { htmlPreview?: HtmlPreviewHandle | null; displayed?: boolean }>();
    const cancel = (path: string) => {
      requests.get(path)?.htmlPreview?.dispose();
      requests.delete(path);
    };
    const clear = () => { for (const path of requests.keys()) cancel(path); };
    return {
      cancel,
      clear,
      mount() {
        active = true;
        return () => { active = false; clear(); };
      },
      reconcile(paths: string[], activePath: string) {
        for (const [path, request] of requests) {
          if (!paths.includes(path)) {
            if (request.displayed) cancel(path);
          } else {
            request.displayed = true;
            if (path !== activePath) request.htmlPreview?.release();
          }
        }
      },
      async load(path: string, options: FilePreviewOptions = {}) {
        if (!active || identityRef.current !== identity) return null;
        cancel(path);
        const request: { htmlPreview?: HtmlPreviewHandle | null; displayed?: boolean } = {};
        requests.set(path, request);
        const isCurrent = () => active && identityRef.current === identity && requests.get(path) === request;
        try {
          const data = await loadFilePreview(client, botAlias, path, options);
          if (!isCurrent()) { data.htmlPreview?.dispose(); return null; }
          request.htmlPreview = data.htmlPreview;
          return data;
        } catch (error) {
          if (!isCurrent()) return null;
          throw error;
        }
      },
    };
  }, [client, botAlias, identity]);
  useEffect(() => loader.mount(), [loader]);
  return loader;
}
