import { describe, expect, test } from "vitest";
import {
  compactMotionStagger,
  delightMotion,
  delightMotionDurations,
  delightMotionStagger,
  premiumMotion,
  premiumMotionDurations,
  resolveMotionProps,
} from "../motion/premiumMotion";

describe("premium motion presets", () => {
  test("keeps all durations within the 200ms budget", () => {
    expect(Math.max(...Object.values(premiumMotionDurations))).toBeLessThanOrEqual(0.2);
    for (const preset of Object.values(premiumMotion)) {
      expect(preset.transition.duration).toBeLessThanOrEqual(0.2);
    }
  });

  test("exports the surfaces used by the workbench", () => {
    expect(Object.keys(premiumMotion).sort()).toEqual([
      "anchoredPopover",
      "detailSwap",
      "dialogPanel",
      "messageRow",
      "paletteBackdrop",
      "palettePanel",
      "popoverBackdrop",
      "shell",
      "sidebarContent",
      "statusSettle",
      "tracePanel",
    ]);
  });

  test("preserves baseline premium motion keys", () => {
    expect(Object.keys(premiumMotion).sort()).toEqual([
      "anchoredPopover",
      "detailSwap",
      "dialogPanel",
      "messageRow",
      "paletteBackdrop",
      "palettePanel",
      "popoverBackdrop",
      "shell",
      "sidebarContent",
      "statusSettle",
      "tracePanel",
    ]);
  });

  test("keeps delight motion within the expressive budget", () => {
    expect(Math.max(...Object.values(delightMotionDurations))).toBeLessThanOrEqual(0.32);
    for (const preset of Object.values(delightMotion)) {
      expect(preset.transition.duration).toBeLessThanOrEqual(0.32);
    }
  });

  test("limits staggered delight animation to visible UI scale", () => {
    expect(delightMotionStagger.itemDelaySeconds).toBeLessThanOrEqual(0.03);
    expect(delightMotionStagger.maxAnimatedItems).toBeLessThanOrEqual(12);
  });

  test("keeps compact motion stagger bounded", () => {
    expect(compactMotionStagger.itemDelaySeconds).toBeLessThanOrEqual(0.02);
    expect(compactMotionStagger.maxAnimatedItems).toBeLessThanOrEqual(8);
  });

  test("removes timed animation when reduced motion is requested", () => {
    const props = resolveMotionProps(premiumMotion.palettePanel, true);
    expect(props.initial).toBe(false);
    expect(props.transition.duration).toBe(0);
  });
});
