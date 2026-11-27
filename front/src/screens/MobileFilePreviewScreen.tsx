import { lazy, Suspense, useLayoutEffect, useRef } from "react";
import { ArrowLeft, Download, Pencil } from "lucide-react";
import { FilePreviewPane } from "../components/FilePreviewPane";
import { TransferProgressBar } from "../components/TransferProgressBar";
import type { MobileFilePreviewController } from "../hooks/useMobileFilePreview";
import type { RemoteWorkspace } from "../services/types";
import { getFilePreviewStatusText, isFilePreviewFullyLoaded, isFilePreviewTooLarge } from "../utils/filePreview";
import { buildFileDownloadUrl } from "../utils/fileLinks";
import { formatTransferDetail } from "../utils/transferProgress";

const PluginViewSurface = lazy(() => import("../components/plugin-renderers/PluginViewSurface")
  .then(module => ({ default: module.PluginViewSurface })));

type Props = {
  controller: MobileFilePreviewController;
  foreground: boolean;
  remote?: RemoteWorkspace;
  canWrite: boolean;
};

export function MobileFilePreviewScreen({ controller, foreground, remote, canWrite }: Props) {
  const { preview } = controller;
  const back = useRef<HTMLButtonElement>(null);
  const visible = useRef(foreground);
  useLayoutEffect(() => {
    visible.current = foreground;
    if (foreground) back.current?.focus({ preventScroll: true });
  }, [foreground, preview?.id]);
  if (!preview) return null;
  const { request, data, download, view, choices, operation, error, loading } = preview;
  const title = preview.path.split("/").pop() || preview.path;
  const result = data?.result ?? null;
  const canEdit = canWrite && request.onEdit && operation.kind === "file" && data && result?.previewKind !== "image";
  const canReadFull = result && !isFilePreviewFullyLoaded(result) && !isFilePreviewTooLarge(result);
  const status = getFilePreviewStatusText(result) || (data?.htmlPreview ? "HTML 预览" : result ? "已读取文件开头" : "");

  return (
    <section
      data-testid="mobile-file-preview" aria-label={`文件预览 ${title}`}
      aria-hidden={!foreground} inert={!foreground}
      className={`mobile-file-preview absolute inset-0 flex min-h-0 min-w-0 flex-col overflow-hidden ${foreground ? "" : "invisible"}`}
    >
      <header className="mobile-file-preview-header">
        <button ref={back} type="button" className="mobile-preview-control" onClick={controller.close}>
          <ArrowLeft size={16} aria-hidden="true" />返回
        </button>
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold" title={title}>{title}</h2>
        <div className="flex flex-wrap gap-1">
          {canEdit ? (
            <button type="button" className="mobile-preview-control" disabled={preview.editing} aria-label="在编辑器中打开" onClick={() => void controller.edit(() => visible.current)}>
              <Pencil size={15} aria-hidden="true" />编辑
            </button>
          ) : null}
          {download ? (
            <button type="button" className="mobile-preview-control" onClick={controller.cancelDownload}>取消下载</button>
          ) : (
            <button type="button" className="mobile-preview-control" onClick={() => void controller.download()}>
              <Download size={15} aria-hidden="true" />下载
            </button>
          )}
        </div>
        <p className="basis-full overflow-x-auto whitespace-nowrap text-xs text-[var(--muted)]" title={preview.path}>
          {preview.path}
        </p>
      </header>
      {download ? (
        <div role="status" aria-label="下载进度" className="shrink-0 px-3 py-1 text-xs text-[var(--muted)]">
          {formatTransferDetail(download.downloadedBytes, download.totalBytes)}
          {typeof download.percent === "number" ? ` · ${download.percent}%` : ""}
          <TransferProgressBar label="文件下载进度" className="mt-1 h-1" percent={download.percent} />
        </div>
      ) : null}
      {choices ? (
        <div className="min-h-0 flex-1 overflow-auto p-3">
          <h3 className="mb-2 text-sm font-medium">选择打开方式</h3>
          <div className="flex flex-wrap gap-2">
            <button className="mobile-preview-control" type="button" onClick={() => controller.readFile("preview")}>普通预览</button>
            {choices.map(target => (
              <button key={`${target.pluginId}/${target.viewId}`} className="mobile-preview-control" type="button" onClick={() => controller.choosePlugin(target)}>
                {target.title === title ? target.pluginId : target.title || target.pluginId}
              </button>
            ))}
          </div>
        </div>
      ) : view && operation.kind === "plugin" ? (
        <>
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            <Suspense fallback={<p role="status" className="p-3 text-sm">加载预览...</p>}>
              <PluginViewSurface
                client={request.client} botAlias={request.botAlias} view={view} inputPayload={operation.target.input}
                mediaUrl={view.renderer === "media" ? buildFileDownloadUrl(request.botAlias, preview.filename, true, preview.fileOptions) : undefined}
                onApplyHostEffects={controller.applyHostEffects} onNotice={controller.pluginNotice}
                onClosePluginSession={controller.closePlugin}
                onRefreshPluginSession={controller.retry} onReopenPluginView={controller.reopenPlugin}
              />
            </Suspense>
          </div>
          <footer className="mobile-preview-status">插件视图 · {view.pluginId}</footer>
        </>
      ) : (
        <div className="min-h-0 min-w-0 flex-1">
          <FilePreviewPane
            title={preview.filename} botAlias={request.botAlias}
            remotePlatform={remote && !request.hostAttachment ? remote.platform || "posix" : undefined}
            fileOptions={preview.fileOptions}
            result={result} htmlPreview={data?.htmlPreview} loading={loading} error={error} statusText={status}
            onRetry={controller.retry} onLoadFull={canReadFull ? () => controller.readFile("full") : undefined}
            onFileLinkClick={controller.requestLink}
          />
        </div>
      )}
    </section>
  );
}
