import { describe, expect, it } from "vitest";
import { fitSignalsRange, overviewBinToX, rangeToContentWidth, timeToX, xToTime, zoomRange } from "../components/plugin-renderers/waveform/timelineMath";

describe("waveform timeline math", () => {
  it("round trips time and pixel coordinates and keeps fit-all bounded", () => {
    expect(timeToX(0, 100, 500, 25)).toBe(125);
    expect(xToTime(0, 100, 500, 125)).toBe(25);
    expect(rangeToContentWidth(0, 1_000_000, 18, 1, 840)).toBe(16000);
  });

  it("maps overview bins and zooms within the full range", () => {
    expect(overviewBinToX({ start: 25, end: 50 }, 0, 100, 400)).toEqual({ startX: 100, endX: 200 });
    expect(zoomRange({ startTime: 0, endTime: 100 }, { startTime: 0, endTime: 100 }, 2)).toEqual({ startTime: 25, endTime: 75 });
  });

  it("fits selected signal activity and falls back for unrecorded signals", () => {
    expect(fitSignalsRange([
      { firstChangeTime: 10, lastChangeTime: 30 },
      { firstChangeTime: 50, lastChangeTime: 80 },
    ], { startTime: 0, endTime: 100 })).toEqual({ startTime: 10, endTime: 80 });
    expect(fitSignalsRange([{ firstChangeTime: null, lastChangeTime: null }], { startTime: 0, endTime: 100 })).toEqual({ startTime: 0, endTime: 100 });
  });
});
