// @vitest-environment node

import { expect, test } from "vitest";
import viteConfig from "../../vite.config";

test("dev proxy forwards websocket routes", async () => {
  const resolved = typeof viteConfig === "function"
    ? await viteConfig({ mode: "test", command: "serve" })
    : viteConfig;
  const proxy = resolved.server?.proxy as Record<string, { ws?: boolean }>;

  for (const path of ["/api", "/terminal", "/debug", "/lan-chat", "/node"]) {
    expect(proxy[path]?.ws).toBe(true);
  }
});
