import { describe, expect, it } from "vitest";
import { readFeatureFlag } from "../app/featureFlags";

describe("frontend feature flags", () => {
  it("defaults to enabled", () => {
    expect(readFeatureFlag({}, "FLAG")).toBe(true);
  });

  it("accepts explicit disable values", () => {
    expect(readFeatureFlag({ FLAG: "false" }, "FLAG")).toBe(false);
    expect(readFeatureFlag({ FLAG: "0" }, "FLAG")).toBe(false);
  });
});
