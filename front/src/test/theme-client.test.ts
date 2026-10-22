import { afterEach, expect, test, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";
import { builtinLibrary } from "../theme/resolveAppearance";

afterEach(() => vi.restoreAllMocks());

test("every theme request binds the confirmed account independently of mutable cookies", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
    ok: true, data: { ...builtinLibrary(), accountId: "alice" },
  }), { headers: { "Content-Type": "application/json" } }));
  const client = new RealWebBotClient();
  client.bindThemeAccount("alice");
  await client.listUiThemes();
  await client.createUiTheme({ schemaVersion: 1, expectedRevision: 0, sourceId: "paper-daylight", name: "配色" });
  await client.updateUiTheme("theme_test", { schemaVersion: 1, expectedRevision: 1, name: "重命名" });
  await client.deleteUiTheme("theme_test", 2);
  await client.selectUiTheme("paper-daylight", 3);
  expect(fetch).toHaveBeenCalledTimes(5);
  for (const [, options] of fetch.mock.calls) {
    expect(new Headers(options?.headers).get("X-UI-Account-ID")).toBe("alice");
  }
});
