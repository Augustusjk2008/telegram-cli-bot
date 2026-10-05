import type { FileReadResult, HtmlPreviewSession } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

export type HtmlPreviewHandle = {
  acquire: () => Promise<HtmlPreviewSession>;
  release: () => void;
  dispose: () => void;
};

export type FilePreviewData = {
  result: FileReadResult | null;
  htmlPreview: HtmlPreviewHandle | null;
};

export type FilePreviewOptions = {
  remote?: boolean;
  agentId?: string;
  mode?: "preview" | "full";
};

// One owner per preview, including sessions whose creation finishes after it closes.
function createHtmlPreviewHandle(client: WebBotClient, botAlias: string, filename: string, agentId?: string): HtmlPreviewHandle {
  let pending: Promise<HtmlPreviewSession> | undefined;
  let session: HtmlPreviewSession | undefined;
  let generation = 0;
  let disposed = false;
  const closed = new Set<string>();
  const options = agentId ? { agentId } : undefined;
  const close = (value: HtmlPreviewSession) => {
    if (closed.has(value.sessionId)) return;
    closed.add(value.sessionId);
    void client.closeHtmlPreview(botAlias, value.sessionId, options).catch(() => undefined);
  };
  const release = () => {
    generation += 1;
    pending = undefined;
    if (session) close(session);
    session = undefined;
  };
  const handle: HtmlPreviewHandle = {
    acquire() {
      if (disposed) return Promise.reject(new Error("预览已关闭"));
      if (!pending) {
        const requestGeneration = generation;
        pending = client.createHtmlPreview(botAlias, filename, options).then((value) => {
          if (disposed || requestGeneration !== generation) {
            close(value);
            throw new Error("预览已关闭");
          }
          session = value;
          return value;
        });
      }
      return pending;
    },
    release,
    dispose() { disposed = true; release(); },
  };
  void handle.acquire().catch(() => undefined);
  return handle;
}

export async function loadFilePreview(
  client: WebBotClient,
  botAlias: string,
  filename: string,
  options: FilePreviewOptions = {},
): Promise<FilePreviewData> {
  if (options.mode !== "full" && isHtmlPreviewPath(filename)) {
    const remote = options.remote ?? Boolean((await client.getBotOverview(botAlias, options.agentId ? { agentId: options.agentId } : undefined)).remoteWorkspace);
    if (!remote) return { result: null, htmlPreview: createHtmlPreviewHandle(client, botAlias, filename, options.agentId) };
  }
  let result = options.mode === "full" ? await client.readFileFull(botAlias, filename) : await client.readFile(botAlias, filename);
  if (options.mode !== "full" && shouldAutoLoadFullPreview(filename, result)) result = await client.readFileFull(botAlias, filename);
  return { result: withDetectedPreviewKind(filename, result), htmlPreview: null };
}

export const FILE_PREVIEW_FULL_READ_LIMIT_BYTES = 1024 * 1024;

export function isHtmlPreviewPath(path: string) {
  return /\.(?:html?|xhtml)$/i.test(String(path || "").trim());
}

export function isFilePreviewTooLarge(result: FileReadResult | null) {
  return Boolean(
    result
    && result.previewKind !== "image"
    && typeof result.fileSizeBytes === "number"
    && result.fileSizeBytes > FILE_PREVIEW_FULL_READ_LIMIT_BYTES,
  );
}

export function isFilePreviewFullyLoaded(result: FileReadResult | null) {
  if (!result) {
    return false;
  }
  if (result.previewKind === "image") {
    return true;
  }
  if (typeof result.isFullContent === "boolean") {
    return result.isFullContent;
  }
  return result.mode === "cat";
}

export function isJsonPreviewPath(path: string) {
  return /\.json$/i.test(String(path || "").trim());
}

export function shouldAutoLoadFullPreview(path: string, result: FileReadResult | null) {
  return Boolean(
    (isHtmlPreviewPath(path) || isJsonPreviewPath(path))
    && result
    && !isFilePreviewFullyLoaded(result)
    && !isFilePreviewTooLarge(result),
  );
}

export function withDetectedPreviewKind(path: string, result: FileReadResult): FileReadResult {
  if (result.previewKind || !isHtmlPreviewPath(path) || !isFilePreviewFullyLoaded(result)) {
    return result;
  }
  return {
    ...result,
    previewKind: "html",
  };
}

export function getFilePreviewStatusText(result: FileReadResult | null) {
  if (!result) {
    return "";
  }
  if (result.previewKind === "image") {
    return "已加载图片预览";
  }
  if (result.previewKind === "html") {
    return "已加载 HTML 预览";
  }
  if (isFilePreviewTooLarge(result)) {
    return "文件超过1MB，请下载后读取全文";
  }
  if (isFilePreviewFullyLoaded(result)) {
    return "已加载全文";
  }
  return "";
}
