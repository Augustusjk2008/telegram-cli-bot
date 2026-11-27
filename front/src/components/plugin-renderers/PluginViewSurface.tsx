import type { WebBotClient } from "../../services/webBotClient";
import type {
  PluginAction,
  PluginRenderResult,
  WaveformSnapshotRenderResult,
  WaveformViewSummary,
  WaveformWindowPayload,
} from "../../services/types";
import { runPluginAction, type ApplyPluginHostEffects } from "../plugins/pluginActions";
import { DocumentView } from "./DocumentView";
import { HexView } from "./HexView";
import { MediaView } from "./MediaView";
import { TableView } from "./TableView";
import { TreeView } from "./TreeView";
import { WaveformView } from "./WaveformView";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: PluginRenderResult;
  inputPayload?: Record<string, unknown>;
  mediaUrl?: string;
  onApplyHostEffects?: ApplyPluginHostEffects;
  onClosePluginSession?: (pluginId: string, sessionId: string) => Promise<void> | void;
  onRefreshPluginSession?: (pluginId: string, sessionId: string) => Promise<void> | void;
  onReopenPluginView?: (target: {
    pluginId: string;
    viewId: string;
    title: string;
    input: Record<string, unknown>;
  }) => Promise<void> | void;
  onNotice?: (message: string) => void;
};

function snapshotSummary(view: WaveformSnapshotRenderResult): WaveformViewSummary {
  return {
    path: view.payload.path,
    timescale: view.payload.timescale,
    startTime: view.payload.startTime,
    endTime: view.payload.endTime,
    display: view.payload.display,
    signals: view.payload.tracks.map((track) => ({
      signalId: track.signalId,
      label: track.label,
      width: track.width,
      kind: track.width > 1 ? "bus" : "scalar",
    })),
    defaultSignalIds: view.payload.tracks.map((track) => track.signalId),
  };
}

function snapshotWindow(view: WaveformSnapshotRenderResult): WaveformWindowPayload {
  return {
    startTime: view.payload.startTime,
    endTime: view.payload.endTime,
    tracks: view.payload.tracks,
  };
}

export function PluginViewSurface({
  botAlias,
  client,
  view,
  inputPayload = {},
  mediaUrl,
  onApplyHostEffects,
  onClosePluginSession,
  onRefreshPluginSession,
  onReopenPluginView,
  onNotice,
}: Props) {
  async function handleAction(action: PluginAction, payload?: Record<string, unknown>) {
    await runPluginAction(action, {
      client,
      botAlias,
      pluginId: view.pluginId,
      viewId: view.viewId,
      title: view.title,
      sessionId: view.mode === "session" ? view.sessionId : undefined,
      inputPayload,
      payload,
      applyHostEffects: (effects) => onApplyHostEffects?.(effects, view.pluginId),
      closeSession: onClosePluginSession,
      refreshSession: onRefreshPluginSession,
      reopenView: onReopenPluginView,
      pushToast: onNotice,
    }).catch((error: unknown) => {
      if (!onNotice) throw error;
      onNotice(error instanceof Error ? error.message : "插件操作失败");
    });
  }

  if (view.renderer === "waveform") {
    const summary = view.mode === "snapshot" ? snapshotSummary(view) : view.summary;
    const initialWindow = view.mode === "snapshot" ? snapshotWindow(view) : view.initialWindow;
    return (
      <WaveformView
        title={view.title}
        botAlias={botAlias}
        client={client}
        pluginId={view.pluginId}
        sessionId={view.mode === "session" ? view.sessionId : undefined}
        summary={summary}
        initialWindow={initialWindow}
        onApplyHostEffects={async (effects) => { await onApplyHostEffects?.(effects, view.pluginId); }}
      />
    );
  }

  if (view.renderer === "table") {
    return (
      <TableView
        botAlias={botAlias}
        client={client}
        view={view}
        onRunAction={handleAction}
      />
    );
  }

  if (view.renderer === "tree") {
    return (
      <TreeView
        botAlias={botAlias}
        client={client}
        view={view}
        onRunAction={handleAction}
      />
    );
  }

  if (view.renderer === "document") {
    return <DocumentView botAlias={botAlias} client={client} view={view} onRunAction={handleAction} />;
  }

  if (view.renderer === "hex") {
    return <HexView title={view.title} payload={view.payload} />;
  }

  if (view.renderer === "media") {
    return <MediaView mediaUrl={mediaUrl} botAlias={botAlias} view={view} inputPayload={inputPayload} />;
  }

  return (
    <div className="flex h-full min-h-0 items-center justify-center p-6 text-sm text-[var(--muted)]">
      未知插件视图
    </div>
  );
}
