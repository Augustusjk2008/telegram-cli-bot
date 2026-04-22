import type { PluginRenderResult } from "../../services/types";
import { WaveformView } from "./WaveformView";

type Props = {
  view: PluginRenderResult;
};

export function PluginViewSurface({ view }: Props) {
  if (view.renderer === "waveform") {
    return <WaveformView title={view.title} payload={view.payload} />;
  }

  return (
    <div className="flex h-full min-h-0 items-center justify-center p-6 text-sm text-[var(--muted)]">
      未知插件视图
    </div>
  );
}
