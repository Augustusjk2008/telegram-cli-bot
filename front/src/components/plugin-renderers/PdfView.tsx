import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions, TextLayer } from "pdfjs-dist";
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { DocumentViewPayload } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { withPublicBase } from "../../utils/publicBase";
import "./PdfView.css";

GlobalWorkerOptions.workerSrc = import.meta.env.DEV
  ? workerUrl
  : withPublicBase(`/assets/${workerUrl.split("/").pop()}`);
// Resolve beside the bundled worker so /node/<id>/ deployments stay portable.
const assets = new URL(import.meta.env.DEV ? "../" : "./pdfjs/", new URL(GlobalWorkerOptions.workerSrc, window.location.href));

function PdfPage({ pdf, pageNumber, zoom, width }: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  zoom: string;
  width: number;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!width) return;
    let active = true;
    let renderTask: RenderTask | undefined;
    let textLayer: TextLayer | undefined;
    const host = surface.current!;
    setBusy(true);
    setError("");
    host.replaceChildren();
    void (async () => {
      const page = await pdf.getPage(pageNumber);
      if (!active) return;
      const original = page.getViewport({ scale: 1 });
      const scale = zoom === "fit" ? Math.max(1, width - 32) / original.width : Number(zoom) * 96 / 72;
      const viewport = page.getViewport({ scale });
      // Bound canvas memory even for large sheets and high-DPI displays.
      const ratio = Math.min(window.devicePixelRatio || 1, 2,
        8192 / Math.max(viewport.width, viewport.height),
        Math.sqrt(16_000_000 / (viewport.width * viewport.height)));
      const canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", `第 ${pageNumber} 页`);
      canvas.width = Math.max(1, Math.floor(viewport.width * ratio));
      canvas.height = Math.max(1, Math.floor(viewport.height * ratio));
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const text = document.createElement("div");
      text.className = "pdf-text-layer";
      host.style.width = `${viewport.width}px`;
      host.style.height = `${viewport.height}px`;
      host.style.setProperty("--total-scale-factor", String(viewport.scale * viewport.userUnit));
      host.append(canvas, text);
      renderTask = page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
      textLayer = new TextLayer({ container: text, viewport, textContentSource: page.streamTextContent() });
      await Promise.all([renderTask.promise, textLayer.render()]);
      if (active) setBusy(false);
    })().catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "PDF 页面渲染失败");
        setBusy(false);
      }
    });
    return () => {
      active = false;
      renderTask?.cancel();
      textLayer?.cancel();
      host.replaceChildren();
    };
  }, [pdf, pageNumber, zoom, width]);

  return (
    <div className="min-w-full w-max p-4">
      {busy ? <div role="status" className="mb-2 text-sm text-[var(--muted)]">页面加载中...</div> : null}
      {error ? <div role="alert" className="mb-2 text-sm text-[var(--danger)]">{error}</div> : null}
      <div ref={surface} data-testid="pdf-page" aria-busy={busy} className="pdf-page relative mx-auto bg-white shadow-md" />
    </div>
  );
}

export default function PdfView({ botAlias, client, payload }: {
  botAlias: string;
  client: WebBotClient;
  payload: DocumentViewPayload;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [zoom, setZoom] = useState("fit");
  const [width, setWidth] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);
  const artifactId = payload.pdf!.artifactId;

  useEffect(() => {
    let active = true;
    let task: PDFDocumentLoadingTask | undefined;
    setPdf(null);
    setError("");
    void (async () => {
      const blob = await client.getPluginArtifactBlob(botAlias, artifactId);
      const data = new Uint8Array(await blob.arrayBuffer());
      if (!active) return;
      task = getDocument({
        data,
        cMapUrl: new URL("cmaps/", assets).href,
        standardFontDataUrl: new URL("standard_fonts/", assets).href,
        wasmUrl: new URL("wasm/", assets).href,
        iccUrl: new URL("iccs/", assets).href,
      });
      const loaded = await task.promise;
      if (active) {
        setPageNumber(1);
        setPageInput("1");
        setPdf(loaded);
      }
    })().catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "PDF 加载失败");
    });
    return () => {
      active = false;
      void task?.destroy().catch(() => undefined);
    };
  }, [botAlias, client, artifactId]);

  useEffect(() => {
    const element = scroller.current!;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    setWidth(element.clientWidth);
    return () => observer.disconnect();
  }, []);

  function goToPage(value: number) {
    const next = Math.max(1, Math.min(pdf?.numPages ?? 1, Number.isFinite(value) ? Math.trunc(value) : pageNumber));
    setPageNumber(next);
    setPageInput(String(next));
    if (scroller.current) scroller.current.scrollTop = 0;
  }

  const buttonClass = "rounded border border-[var(--border)] px-2 py-1 disabled:opacity-40";
  return (
    <div data-testid="pdf-view" className="flex h-full min-h-0 min-w-0 flex-col text-[var(--text)]">
      <div className="shrink-0 border-b border-[var(--border)] p-3">
        <div className="truncate text-sm font-medium" title={payload.path}>{payload.title || payload.path}</div>
        <div role="toolbar" aria-label="PDF 阅读工具" className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <button className={buttonClass} disabled={!pdf || pageNumber <= 1} onClick={() => goToPage(pageNumber - 1)}>上一页</button>
          <form className="flex items-center gap-1" onSubmit={(event) => { event.preventDefault(); goToPage(Number(pageInput)); }}>
            <input aria-label="页码" type="number" min={1} max={pdf?.numPages ?? 1} disabled={!pdf}
              value={pageInput} onChange={(event) => setPageInput(event.target.value)} onBlur={() => goToPage(Number(pageInput))}
              className="w-16 rounded border border-[var(--border)] bg-[var(--surface)] px-1 py-1" />
            <span>/ {pdf?.numPages ?? "—"}</span>
          </form>
          <button className={buttonClass} disabled={!pdf || pageNumber >= pdf.numPages} onClick={() => goToPage(pageNumber + 1)}>下一页</button>
          <select aria-label="缩放" value={zoom} onChange={(event) => setZoom(event.target.value)} disabled={!pdf}
            className="rounded border border-[var(--border)] bg-[var(--surface)] px-1 py-1">
            <option value="fit">适合宽度</option>
            {[0.5, 0.75, 1, 1.25, 1.5, 2, 3].map((scale) => <option key={scale} value={scale}>{scale * 100}%</option>)}
          </select>
        </div>
      </div>
      <div ref={scroller} className="min-h-0 min-w-0 flex-1 overflow-auto bg-[var(--surface-strong)]">
        {error ? <div role="alert" className="p-4 text-sm text-[var(--danger)]">{error}</div>
          : pdf ? <PdfPage pdf={pdf} pageNumber={pageNumber} zoom={zoom} width={width} />
          : <div role="status" className="p-4 text-sm text-[var(--muted)]">PDF 加载中...</div>}
      </div>
    </div>
  );
}
