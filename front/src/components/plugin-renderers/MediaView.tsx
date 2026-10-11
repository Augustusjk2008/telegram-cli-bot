import { buildFileDownloadUrl } from "../../utils/fileLinks";
import type { PluginRenderResult } from "../../services/types";

type Props = {
  botAlias: string;
  view: Extract<PluginRenderResult, { renderer: "media" }>;
  inputPayload?: Record<string, unknown>;
};

export function MediaView({ botAlias, view, inputPayload = {} }: Props) {
  const { path, mediaType } = view.payload;
  const sourcePath = typeof inputPayload.path === "string" && inputPayload.path.trim()
    ? inputPayload.path
    : path;
  const src = buildFileDownloadUrl(botAlias, sourcePath, true);

  return (
    <div data-testid="plugin-media-view" className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-4">
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-[var(--text)]">{view.title}</div>
        <div className="truncate text-xs text-[var(--muted)]" title={path}>{path}</div>
      </div>
      {mediaType === "video" ? (
        <video
          data-testid="plugin-video"
          className="max-h-full w-full rounded-lg bg-black object-contain"
          controls
          playsInline
          preload="metadata"
          src={src}
        >
          当前浏览器不支持视频播放。
        </video>
      ) : (
        <div className="flex min-h-32 items-center justify-center rounded-lg bg-[var(--surface-strong)] p-6">
          <audio data-testid="plugin-audio" className="w-full" controls preload="metadata" src={src}>
            当前浏览器不支持音频播放。
          </audio>
        </div>
      )}
    </div>
  );
}
