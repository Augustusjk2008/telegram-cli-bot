import { afterEach, expect, test, vi } from "vitest";
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
