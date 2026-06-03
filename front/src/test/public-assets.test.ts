import { afterEach, describe, expect, test, vi } from "vitest";

describe("public asset urls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  test("prefixes app logos with the frontend base path", async () => {
    vi.stubGlobal("__PUBLIC_ENV__", {
      VITE_BASE_PATH: "/node/nanjing-laptop",
    });
    vi.resetModules();

    const { APP_LOGO_CLASSIC_SRC, APP_LOGO_SRC } = await import("../components/AppLogo");

    expect(APP_LOGO_SRC).toBe("/node/nanjing-laptop/assets/app-logo.svg");
    expect(APP_LOGO_CLASSIC_SRC).toBe("/node/nanjing-laptop/assets/app-logo-classic.svg");
  });

  test("prefixes default and generated avatar urls with the frontend base path", async () => {
    vi.stubGlobal("__PUBLIC_ENV__", {
      VITE_BASE_PATH: "/node/nanjing-laptop",
    });
    vi.resetModules();

    const { DEFAULT_AVATAR_ASSETS, buildAvatarUrl } = await import("../utils/avatar");

    expect(DEFAULT_AVATAR_ASSETS[0].url).toBe("/node/nanjing-laptop/assets/avatars/avatar_01.png");
    expect(buildAvatarUrl("avatar_02.png", "bot")).toBe(
      "/node/nanjing-laptop/assets/avatars/avatar_02.png",
    );
  });
});
