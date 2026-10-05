import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import type { HtmlPreviewSession } from "../services/types";
import type { HtmlPreviewHandle } from "../utils/filePreview";

export function HtmlPreview({ title, preview, desktop = false }: { title: string; preview: HtmlPreviewHandle; desktop?: boolean }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const bridgeReportedRef = useRef(false);
  const loadedWithoutBridgeRef = useRef(false);
  const [session, setSession] = useState<HtmlPreviewSession | null>(null);
  const [revision, setRevision] = useState(0);
  const [entryRevision, setEntryRevision] = useState(0);
  const [path, setPath] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "expired">("loading");
  const [error, setError] = useState("");
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const startLoading = () => {
    setStatus("loading");
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => { setError("预览加载失败，请重试"); setStatus("error"); }, 15000);
  };

  useEffect(() => {
    let active = true;
    setSession(null);
    bridgeReportedRef.current = false;
    loadedWithoutBridgeRef.current = false;
    setError("");
    startLoading();
    void preview.acquire().then((value) => {
      if (!active) return;
      setSession(value);
      setPath(value.entryPath);
    }).catch((reason: unknown) => {
      if (!active) return;
      clearTimeout(timeoutRef.current);
      setError(reason instanceof Error ? reason.message : "预览加载失败");
      setStatus("error");
    });
    return () => { active = false; clearTimeout(timeoutRef.current); preview.release(); };
  }, [preview, revision]);

  useEffect(() => {
    if (!session) return;
    const expire = () => { clearTimeout(timeoutRef.current); setStatus("expired"); preview.release(); };
    const remaining = Date.parse(session.expiresAt) - Date.now();
    if (!(remaining > 0)) { expire(); return; }
    const expiryTimer = setTimeout(expire, Math.min(remaining, 2147483647));
    const onMessage = (event: MessageEvent) => {
      const data = event.data;
      if (event.source !== iframeRef.current?.contentWindow || !data || data.type !== "orbit-html-preview" || data.sessionId !== session.sessionId) return;
      if (data.event === "ready" || data.event === "path") {
        if (data.event === "ready") {
          bridgeReportedRef.current = !loadedWithoutBridgeRef.current;
          loadedWithoutBridgeRef.current = false;
        }
        if (typeof data.path === "string") setPath(data.path);
        clearTimeout(timeoutRef.current);
        setStatus("ready");
      } else if (data.event === "error") {
        bridgeReportedRef.current = !loadedWithoutBridgeRef.current;
        loadedWithoutBridgeRef.current = false;
        clearTimeout(timeoutRef.current);
        setError(typeof data.message === "string" ? data.message : "预览加载失败");
        setStatus("error");
      }
    };
    window.addEventListener("message", onMessage);
    return () => { clearTimeout(expiryTimer); window.removeEventListener("message", onMessage); };
  }, [preview, session]);

  const buttonClass = "shrink-0 rounded-md border border-[var(--border)] px-2 py-1 text-xs disabled:opacity-50";
  return (
    <div className={clsx("flex min-h-0 flex-col gap-2", desktop ? "h-full" : "h-[50vh]")}>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <button type="button" className={buttonClass} disabled={!session || status !== "ready"} onClick={() => {
          bridgeReportedRef.current = false;
          loadedWithoutBridgeRef.current = false;
          startLoading();
          iframeRef.current?.contentWindow?.postMessage({ type: "orbit-html-preview", sessionId: session?.sessionId, command: "refresh" }, "*");
        }}>刷新</button>
        <button type="button" className={buttonClass} disabled={!session || status === "expired"} onClick={() => {
          bridgeReportedRef.current = false;
          loadedWithoutBridgeRef.current = false;
          setPath(session?.entryPath || "");
          startLoading();
          setEntryRevision((value) => value + 1);
        }}>返回入口</button>
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--muted)]" title={`当前页面：${path}`}>{path}</span>
      </div>
      {status !== "ready" ? <div role="status" className="flex shrink-0 items-center gap-2 text-sm text-[var(--muted)]">
        {status === "loading" ? "加载预览..." : status === "expired" ? "预览已过期" : error}
        {status === "error" || status === "expired" ? <button type="button" className={buttonClass} onClick={() => setRevision((value) => value + 1)}>重试</button> : null}
      </div> : null}
      {session && status !== "expired" ? <iframe
        key={`${session.sessionId}:${entryRevision}`}
        ref={iframeRef}
        title={title}
        src={session.entryUrl}
        sandbox="allow-scripts allow-forms allow-downloads"
        referrerPolicy="no-referrer"
        onLoad={() => {
          loadedWithoutBridgeRef.current = !bridgeReportedRef.current;
          if (loadedWithoutBridgeRef.current) startLoading();
          bridgeReportedRef.current = false;
        }}
        onError={() => { clearTimeout(timeoutRef.current); setError("预览加载失败"); setStatus("error"); }}
        className="min-h-0 w-full flex-1 rounded-xl border border-[var(--border)] bg-white"
      /> : null}
    </div>
  );
}
