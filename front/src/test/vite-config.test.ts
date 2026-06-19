// @vitest-environment node

import { expect, test } from "vitest";
import viteConfig, { shouldBypassNodeProxy } from "../../vite.config";

function request(url: string) {
  return { url } as Parameters<typeof shouldBypassNodeProxy>[0];
}

test("dev proxy forwards websocket routes", async () => {
  const resolved = typeof viteConfig === "function"
    ? await viteConfig({ mode: "test", command: "serve" })
    : viteConfig;
  const proxy = resolved.server?.proxy as Record<string, { ws?: boolean }>;

  for (const path of ["/api", "/terminal", "/debug", "/lan-chat", "/node"]) {
    expect(proxy[path]?.ws).toBe(true);
  }
});

test("dev proxy keeps node base path available for vite app routes", () => {
  const basePath = "/node/nanjing-laptop/";

  expect(shouldBypassNodeProxy(request("/node/nanjing-laptop/"), basePath)).toBe(true);
  expect(shouldBypassNodeProxy(request("/node/nanjing-laptop/assets/app-logo.svg"), basePath)).toBe(true);
  expect(shouldBypassNodeProxy(request("/node/nanjing-laptop/@vite/client"), basePath)).toBe(true);
  expect(shouldBypassNodeProxy(request("/node/nanjing-laptop/src/main.tsx"), basePath)).toBe(true);

  expect(shouldBypassNodeProxy(request("/node/nanjing-laptop/api/health"), basePath)).toBe(false);
  expect(shouldBypassNodeProxy(request("/node/nanjing-laptop/terminal/ws"), basePath)).toBe(false);
  expect(shouldBypassNodeProxy(request("/node/other/"), basePath)).toBe(false);
});
