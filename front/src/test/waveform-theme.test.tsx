import { act, cleanup, render } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { WaveformCanvas } from "../components/plugin-renderers/waveform/WaveformCanvas";
import { applyResolvedAppearance, getCurrentAppearance } from "../theme/appearanceRuntime";
import type { WaveformTrack } from "../services/types";

const initialAppearance = getCurrentAppearance();

afterEach(() => {
  cleanup();
  applyResolvedAppearance(initialAppearance);
  vi.restoreAllMocks();
});

test("an existing canvas redraws same-ID colors and alpha while keeping its signal data", () => {
  const strokes: Array<[string, number]> = [];
  const fills: Array<[string, number]> = [];
  const text: Array<[string, string]> = [];
  const context = {
    strokeStyle: "", fillStyle: "", globalAlpha: 1,
    clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), save: vi.fn(), restore: vi.fn(),
    stroke() { strokes.push([this.strokeStyle, this.globalAlpha]); },
    fillRect() { fills.push([this.fillStyle, this.globalAlpha]); },
    fillText(value: string) { text.push([value, this.fillStyle]); },
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  const track: WaveformTrack = { signalId: "counter", label: "counter", width: 8, segments: [
    { start: 0, end: 50, value: "2A" },
    { start: 50, end: 100, value: "mixed", kind: "dense", transitionCount: 120 },
  ] };
  const snapshot = (revision: string, line: string, dense: string) => ({
    ...initialAppearance, themeId: "theme_waveform", revision,
    cssVariables: { ...initialAppearance.cssVariables,
      "--waveform-line": line, "--waveform-text": line,
      "--waveform-dense-fill": dense, "--waveform-dense-line": dense,
    },
  });
  applyResolvedAppearance(snapshot("waveform-1", "#25313DFF", "#123456FF"));
  const { container } = render(<WaveformCanvas track={track} width={240} height={32} startTime={0} endTime={100} />);
  const canvas = container.querySelector("canvas");
  expect(strokes).toEqual([["#25313DFF", 1], ["#123456FF", 0.75]]);
  expect(fills).toEqual([["#123456FF", 0.18]]);
  expect(text).toEqual([["2A", "#25313DFF"], ["120 changes", "#25313DFF"]]);
  act(() => applyResolvedAppearance(snapshot("waveform-2", "#D0E0F0FF", "#AABBCC80")));
  expect(container.querySelector("canvas")).toBe(canvas);
  expect(context.clearRect).toHaveBeenCalledTimes(2);
  expect(strokes.slice(2)).toEqual([["#D0E0F0FF", 1], ["#AABBCC80", 0.75]]);
  expect(fills[1]).toEqual(["#AABBCC80", 0.18]);
  expect(text.slice(2)).toEqual([["2A", "#D0E0F0FF"], ["120 changes", "#D0E0F0FF"]]);
  expect(context.globalAlpha).toBe(1);
});
