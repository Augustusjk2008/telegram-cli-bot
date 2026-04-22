import type { WebBotClient } from "../../services/webBotClient";
import type {
  PluginRenderResult,
  WaveformViewSummary,
  WaveformWindowPayload,
} from "../../services/types";
import { WaveformView } from "./WaveformView";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: PluginRenderResult;
};

function snapshotSummary(view: Extract<PluginRenderResult, { mode: "snapshot" }>): WaveformViewSummary {
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

function snapshotWindow(view: Extract<PluginRenderResult, { mode: "snapshot" }>): WaveformWindowPayload {
  return {
    startTime: view.payload.startTime,
    endTime: view.payload.endTime,
    tracks: view.payload.tracks,
  };
}

export function PluginViewSurface({ botAlias, client, view }: Props) {
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

  return (
    <div className="flex h-full min-h-0 items-center justify-center p-6 text-sm text-[var(--muted)]">
      未知插件视图
    </div>
  );
}
