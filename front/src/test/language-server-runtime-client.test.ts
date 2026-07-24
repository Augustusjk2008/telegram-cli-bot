import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";


afterEach(() => {
  vi.unstubAllGlobals();
});


test("workspace language status requests Pyright prewarm and maps runtime state", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      data: {
        providers: [{
          id: "pyright",
          status: "available",
          source: "path",
          version: "1.1.410",
          runtimeState: "starting",
          runtimeMessage: "正在初始化工作区",
          implementationSupported: false,
        }],
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new RealWebBotClient();

  const catalog = await client.getLanguageServerCatalog("main", "pyright");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/bots/main/workspace/language-servers?provider=pyright&prewarm=1",
    expect.objectContaining({ cache: "no-store" }),
  );
  expect(catalog.providers[0]).toEqual(expect.objectContaining({
    provider: "pyright",
    runtimeState: "starting",
    runtimeMessage: "正在初始化工作区",
    implementationSupported: false,
  }));
});

test("workspace language status preserves the TypeScript implementation capability", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      data: {
        providers: [{
          id: "typescript",
          status: "available",
          source: "managed",
          version: "4.4.1",
          runtimeState: "ready",
          implementationSupported: true,
        }],
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new RealWebBotClient();

  const catalog = await client.getLanguageServerCatalog("main", "typescript");

  expect(catalog.providers[0]).toEqual(expect.objectContaining({
    provider: "typescript",
    runtimeState: "ready",
    implementationSupported: true,
  }));
});

test("workspace language status maps restarting and degraded runtime states", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      data: {
        providers: [
          {
            id: "pyright",
            status: "available",
            source: "managed",
            runtime_state: "restarting",
            runtime_message: "正在重启 Python 语言服务",
          },
          {
            id: "typescript",
            status: "available",
            source: "path",
            runtimeState: "degraded",
            runtimeMessage: "连续故障，等待手动重启",
          },
        ],
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new RealWebBotClient();

  const catalog = await client.getLanguageServerCatalog("main", "pyright");

  expect(catalog.providers).toEqual(expect.arrayContaining([
    expect.objectContaining({ provider: "pyright", runtimeState: "restarting" }),
    expect.objectContaining({ provider: "typescript", runtimeState: "degraded" }),
  ]));
});

test("restart request only targets the current scoped language server", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      data: {
        provider: "typescript",
        restarted: true,
        runtimeState: "restarting",
        runtimeMessage: "正在重启 TypeScript 语言服务",
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new RealWebBotClient();

  const result = await client.restartLanguageServer("main", "typescript");

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/bots/main/workspace/language-servers/typescript/restart",
    expect.objectContaining({ method: "POST", cache: "no-store" }),
  );
  expect(result).toEqual({
    provider: "typescript",
    restarted: true,
    runtimeState: "restarting",
    runtimeMessage: "正在重启 TypeScript 语言服务",
  });
});

test("restart request preserves the backend failure for the status-bar feedback", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({
      ok: false,
      error: {
        code: "language_server_restart_failed",
        message: "语言服务重启失败，请稍后重试",
      },
    }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new RealWebBotClient();

  await expect(client.restartLanguageServer("main", "pyright")).rejects.toMatchObject({
    code: "language_server_restart_failed",
    message: "语言服务重启失败，请稍后重试",
    status: 503,
  });
});

test("mock restart exposes one restarting poll before the scoped server is ready", async () => {
  const client = new MockWebBotClient();

  const restart = await client.restartLanguageServer("main", "typescript");
  const restarting = await client.getLanguageServerCatalog("main", "typescript");
  const ready = await client.getLanguageServerCatalog("main", "typescript");

  expect(restarting.providers.find((item) => item.provider === "typescript")?.runtimeState).toBe("restarting");
  expect(ready.providers.find((item) => item.provider === "typescript")?.runtimeState).toBe("ready");
  expect(ready.providers.find((item) => item.provider === "pyright")?.runtimeState).toBeUndefined();
  expect(restart).toEqual(expect.objectContaining({
    provider: "typescript",
    restarted: true,
    runtimeState: "restarting",
  }));
});
