import { HtmlPreview } from "./HtmlPreview";
import type { HtmlPreviewHandle } from "../utils/filePreview";
import { clsx } from "clsx";
import { LoaderCircle } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import type { FileReadResult, RemoteWorkspace } from "../services/types";
import { buildFileDownloadUrl, isExternalHref, isSafeMarkdownHref, resolveMarkdownImagePath } from "../utils/fileLinks";
import { MarkdownPreview } from "./MarkdownPreview";
import { isFilePreviewFullyLoaded, isJsonPreviewPath } from "../utils/filePreview";

const JsonPreview = lazy(() => import("./JsonPreview").then((module) => ({ default: module.JsonPreview })));

export type FilePreviewSurfaceProps = {
  title: string;
  result: FileReadResult | null;
  htmlPreview?: HtmlPreviewHandle | null;
  loading?: boolean;
  error?: string;
  onRetry?: () => void;
  botAlias?: string;
  remotePlatform?: RemoteWorkspace["platform"];
  className?: string;
  desktop?: boolean;
  onFileLinkClick?: (href: string) => void;
};

export function FilePreviewSurface({
  title,
  result,
  htmlPreview,
  loading = false,
  error = "",
  onRetry,
  botAlias = "",
  remotePlatform,
  className = "",
  desktop = false,
  onFileLinkClick,
}: FilePreviewSurfaceProps) {
  const content = result?.content || "";
  const isMarkdownPreview = /\.(md|markdown)$/i.test(title);
  const isSvgPreview = /\.svg$/i.test(title);
  const isRasterPreview = result?.previewKind === "image" && Boolean(result.contentType) && Boolean(result.contentBase64);
  const isHtmlPreview = result?.previewKind === "html";
  const [imagePreviewUrl, setImagePreviewUrl] = useState("");

  useEffect(() => {
    if (isRasterPreview && result?.contentType && result.contentBase64) {
      setImagePreviewUrl(`data:${result.contentType};base64,${result.contentBase64}`);
      return undefined;
    }

    if (!isSvgPreview || !result) {
      setImagePreviewUrl("");
      return undefined;
    }

    if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
      const objectUrl = URL.createObjectURL(new Blob([content], { type: "image/svg+xml" }));
      setImagePreviewUrl(objectUrl);
      return () => {
        URL.revokeObjectURL(objectUrl);
      };
    }

    setImagePreviewUrl(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(content)}`);
    return undefined;
  }, [content, isRasterPreview, isSvgPreview, result]);

  const resolveMarkdownImageSrc = useMemo(() => {
    const normalizedBotAlias = botAlias.trim();
    return (src: string) => {
      if (isSafeMarkdownHref(src) && isExternalHref(src)) {
        return src;
      }
      if (!normalizedBotAlias) {
        return "";
      }
      const imagePath = resolveMarkdownImagePath(src, title, remotePlatform);
      return imagePath ? buildFileDownloadUrl(normalizedBotAlias, imagePath) : "";
    };
  }, [botAlias, title, remotePlatform]);

  function renderContent() {
    if (htmlPreview) return <HtmlPreview key={title} title={title} preview={htmlPreview} desktop={desktop} />;

    if (loading && !result) {
      return (
        <div className={clsx("flex items-center justify-center gap-2 text-sm text-[var(--muted)]", desktop ? "h-full" : "min-h-40")}>
          <LoaderCircle className="h-4 w-4 animate-spin" />
          加载预览...
        </div>
      );
    }

    if (error && !result) {
      return <div role="alert" className="flex items-center gap-3 p-4 text-sm text-red-600">
        {error}
        {onRetry ? <button type="button" className="shrink-0 rounded-md border border-[var(--border)] px-2 py-1 text-[var(--text)]" onClick={onRetry}>重试</button> : null}
      </div>;
    }

    if (!result) {
      return (
        <div className={clsx("flex items-center justify-center px-4 text-sm text-[var(--muted)]", desktop ? "h-full" : "min-h-40")}>
          选择聊天中的文件链接查看预览
        </div>
      );
    }

    if (isJsonPreviewPath(title)) {
      return (
        <Suspense fallback={<div className="p-4 text-sm text-[var(--muted)]">加载预览...</div>}>
          <JsonPreview content={content} isFullContent={isFilePreviewFullyLoaded(result)} desktop={desktop} />
        </Suspense>
      );
    }

    if (!content && !isRasterPreview) {
      return <div className="p-4 text-sm text-[var(--muted)]">文件为空</div>;
    }

    if (isMarkdownPreview) {
      return (
        <MarkdownPreview
          content={content}
          variant={desktop ? "desktop-preview" : undefined}
          onFileLinkClick={onFileLinkClick}
          resolveImageSrc={resolveMarkdownImageSrc}
        />
      );
    }

    if (imagePreviewUrl) {
      return (
        <div className={clsx(desktop ? "h-full" : "max-h-[50vh]", "flex items-start justify-center overflow-auto rounded-xl bg-[var(--surface-strong)] p-4")}>
          <img src={imagePreviewUrl} alt={title} className="block h-auto max-w-full" />
        </div>
      );
    }

    if (isHtmlPreview) {
      return (
        <iframe
          title={title}
          sandbox=""
          referrerPolicy="no-referrer"
          srcDoc={content}
          className={clsx(desktop ? "h-full" : "h-[50vh]", "w-full rounded-xl border border-[var(--border)] bg-white")}
        />
      );
    }

    return (
      <pre className={clsx(desktop ? "h-full" : "max-h-[50vh]", "overflow-auto rounded-xl bg-[var(--surface-strong)] p-4 text-sm whitespace-pre-wrap break-all")}>
        {content}
      </pre>
    );
  }

  return (
    <div className={clsx("min-h-0", desktop ? "h-full" : "", className)}>
      {renderContent()}
    </div>
  );
}
