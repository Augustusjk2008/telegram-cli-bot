import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import { builtinLibrary } from "../theme/resolveAppearance";
import { defaultIllustrations } from "../theme/illustrationPresets";
import { portableTheme, readThemeFile } from "../theme/themeTransfer";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

test("theme requests use the global API without account-specific headers", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
    ok: true, data: builtinLibrary(),
  }), { headers: { "Content-Type": "application/json" } }));
  const client = new RealWebBotClient();
  await client.listPublicUiThemes();
  await client.listUiThemes();
  await client.createUiTheme({ schemaVersion: 1, expectedRevision: 0, sourceId: "paper-daylight", name: "配色" });
  await client.updateUiTheme("theme_test", { schemaVersion: 1, expectedRevision: 1, name: "重命名" });
  await client.deleteUiTheme("theme_test", 2);
  await client.selectUiTheme("paper-daylight", 3);
  const input = { expectedRevision: 4, document: portableTheme(builtinLibrary().themes[0]) };
  await client.importUiThemes(input);
  expect(fetch).toHaveBeenCalledTimes(7);
  expect(fetch.mock.calls[6][0]).toMatch(/\/api\/ui\/themes\/import$/);
  expect(fetch.mock.calls[6][1]?.method).toBe("POST");
  expect(JSON.parse(fetch.mock.calls[6][1]?.body as string)).toEqual(input);
  expect(fetch.mock.calls[0][0]).toMatch(/\/api\/public\/ui\/themes$/);
  for (const [, options] of fetch.mock.calls) {
    expect(new Headers(options?.headers).get("X-UI-Account-ID")).toBeNull();
  }
});

test("exported single themes and packs can be imported as editable copies", async () => {
  const client = new MockWebBotClient();
  await client.login({ username: "alice", password: "password" });
  const document = portableTheme(builtinLibrary().themes[0]);
  expect(Object.keys(document).sort()).toEqual(["appearance", "baseId", "name", "schemaVersion"]);
  const single = await client.importUiThemes({ expectedRevision: 0, document });
  const pack = { schemaVersion: 1, themes: single.themes.map(portableTheme) };
  const result = await client.importUiThemes({ expectedRevision: 1, document: pack });
  expect(result.revision).toBe(2);
  expect(result.themes).toHaveLength(4);
  expect(new Set(result.themes.map((theme) => theme.id)).size).toBe(4);
  expect(result.selectedThemeId).toBe("paper-daylight");
  expect(result.themes.slice(1).every((theme) => !theme.readonly)).toBe(true);
  expect(result.themes[2].appearance).toEqual(document.appearance);
  await expect(client.importUiThemes({ expectedRevision: 2, document: { ...pack, themes: [...pack.themes, { ...document, baseId: "unknown" }] } })).rejects.toMatchObject({ status: 400 });
  expect(await client.listUiThemes()).toEqual(result);
});

test("legacy imported themes receive the default illustration configuration", async () => {
  const document = await readThemeFile({
    text: async () => JSON.stringify({
      schemaVersion: 1,
      name: "旧主题",
      baseId: "paper-daylight",
      appearance: { colors: { scheme: "light", overrides: {} } },
    }),
  } as File);
  expect((document as { appearance: { illustrations: unknown } }).appearance.illustrations).toEqual({
    ...defaultIllustrations(),
  });
});

test("legacy uploaded illustrations keep their inline data until the server migrates them", async () => {
  const legacy = {
    setId: "upload",
    upload: {
      mimeType: "image/png",
      data: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    },
    opacity: 0.12,
    surfaces: { workbench: true, chat: false, topbar: false, management: false },
  };
  const document = await readThemeFile({
    text: async () => JSON.stringify({
      schemaVersion: 1,
      name: "旧上传主题",
      baseId: "paper-daylight",
      appearance: { colors: { scheme: "light", overrides: {} }, illustrations: legacy },
    }),
  } as File);
  expect((document as { appearance: { illustrations: unknown } }).appearance.illustrations).toEqual(legacy);
});

test("theme export keeps a theme-owned uploaded illustration", () => {
  const uploaded = {
    kind: "uploaded" as const,
    assetId: "asset_431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460",
    mimeType: "image/png" as const,
    width: 1,
    height: 1,
    sha256: "431ced6916a2a21a156e38701afe55bbd7f88969fbbfc56d7fe099d47f265460",
  };
  const theme = {
    ...builtinLibrary().themes[0],
    appearance: {
      ...builtinLibrary().themes[0].appearance,
      illustrations: {
        opacity: 0.12,
        surfaces: { workbench: true, adminCenter: false, agentManager: false },
        scenes: {
          workbench: { layers: [{ id: "workbench-upload", asset: uploaded, anchor: "center" as const, width: 100, height: 100, enabled: true }] },
          adminCenter: { layers: [{ id: "admin-upload", asset: uploaded, anchor: "center" as const, width: 100, height: 100, enabled: true }] },
          agentManager: { layers: [{ id: "agent-upload", asset: uploaded, anchor: "center" as const, width: 100, height: 100, enabled: true }] },
        },
      },
    },
  };
  expect(portableTheme(theme).appearance.illustrations).toEqual(theme.appearance.illustrations);
});


test("mock accounts and guests share the theme library and selected theme", async () => {
  const alice = new MockWebBotClient();
  await alice.login({ username: "alice", password: "password" });
  const created = await alice.createUiTheme({ schemaVersion: 1, expectedRevision: 0, sourceId: "paper-daylight", name: "共享主题", activate: true });
  const id = created.selectedThemeId;
  const anonymous = new MockWebBotClient();
  await anonymous.logout();
  expect(await anonymous.listPublicUiThemes()).toEqual(created);
  await expect(anonymous.listUiThemes()).rejects.toMatchObject({ status: 401 });
  await expect(anonymous.selectUiTheme("paper-daylight", created.revision)).rejects.toMatchObject({ status: 401 });
  const bob = new MockWebBotClient();
  await bob.login({ username: "bob", password: "password" });
  expect(await bob.listUiThemes()).toEqual(created);
  await bob.updateUiTheme(id, { schemaVersion: 1, expectedRevision: created.revision, name: "共同编辑" });
  expect((await alice.listUiThemes()).themes.find((theme) => theme.id === id)?.name).toBe("共同编辑");
  const guest = new MockWebBotClient();
  await guest.loginGuest();
  expect((await guest.listUiThemes()).selectedThemeId).toBe(id);
  await expect(guest.deleteUiTheme(id, 2)).rejects.toMatchObject({ status: 403 });
});
