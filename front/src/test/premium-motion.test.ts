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
  test("keeps motion presets within interaction budgets", () => {
    expect(Math.max(...Object.values(premiumMotionDurations))).toBeLessThanOrEqual(0.2);
    for (const preset of Object.values(premiumMotion)) {
      expect(preset.transition.duration).toBeLessThanOrEqual(0.2);
    }

    expect(Math.max(...Object.values(delightMotionDurations))).toBeLessThanOrEqual(0.32);
    for (const preset of Object.values(delightMotion)) {
      expect(preset.transition.duration).toBeLessThanOrEqual(0.32);
    }

    expect(delightMotionStagger.itemDelaySeconds).toBeLessThanOrEqual(0.03);
    expect(delightMotionStagger.maxAnimatedItems).toBeLessThanOrEqual(12);

    expect(compactMotionStagger.itemDelaySeconds).toBeLessThanOrEqual(0.02);
    expect(compactMotionStagger.maxAnimatedItems).toBeLessThanOrEqual(8);
  });

  test("removes timed animation when reduced motion is requested", () => {
    const props = resolveMotionProps(premiumMotion.palettePanel, true);
    expect(props.initial).toBe(false);
    expect(props.transition.duration).toBe(0);
  });
});
