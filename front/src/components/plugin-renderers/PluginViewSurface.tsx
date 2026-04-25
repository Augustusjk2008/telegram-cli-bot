import type { WebBotClient } from "../../services/webBotClient";
import type {
  HostEffect,
  PluginAction,
  PluginRenderResult,
  WaveformSnapshotRenderResult,
  WaveformViewSummary,
  WaveformWindowPayload,
} from "../../services/types";
import { runPluginAction } from "../plugins/pluginActions";
import { DocumentView } from "./DocumentView";
import { HexView } from "./HexView";
import { TableView } from "./TableView";
import { TreeView } from "./TreeView";
import { WaveformView } from "./WaveformView";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: PluginRenderResult;
  inputPayload?: Record<string, unknown>;
  onApplyHostEffects?: (effects: HostEffect[]) => Promise<void> | void;
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
      applyHostEffects: onApplyHostEffects,
      closeSession: onClosePluginSession,
      refreshSession: onRefreshPluginSession,
      reopenView: onReopenPluginView,
      pushToast: onNotice,
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
    return <DocumentView view={view} />;
  }

  if (view.renderer === "hex") {
    return <HexView title={view.title} payload={view.payload} />;
  }

  return (
    <div className="flex h-full min-h-0 items-center justify-center p-6 text-sm text-[var(--muted)]">
      未知插件视图
    </div>
  );
}
