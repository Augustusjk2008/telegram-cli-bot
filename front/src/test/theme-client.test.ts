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

test("a held theme list is reused when the server reports its digest unchanged", async () => {
  const full = { ...builtinLibrary(), themesDigest: "digest-1" };
  const { themes: _themes, ...accountState } = full;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => new Response(JSON.stringify({
    ok: true,
    data: String(input).includes("themes_digest=digest-1")
      ? { ...accountState, revision: 5, selectedThemeId: "paper-daylight", themesUnchanged: true }
      : full,
  }), { headers: { "Content-Type": "application/json" } }));
  const client = new RealWebBotClient();

  const first = await client.listUiThemes();
  expect(fetch.mock.calls[0][0]).toMatch(/\/api\/ui\/themes$/);
  const second = await client.listUiThemes(first);
  expect(fetch.mock.calls[1][0]).toMatch(/\/api\/ui\/themes\?themes_digest=digest-1$/);
  expect(second.themes).toBe(first.themes);
  expect(second.revision).toBe(5);
  expect(second).not.toHaveProperty("themesUnchanged");

  const selected = await client.selectUiTheme("paper-daylight", 5, second);
  expect(fetch.mock.calls[2][0]).toMatch(/\/api\/ui\/theme-selection\?themes_digest=digest-1$/);
  expect(selected.themes).toBe(first.themes);

  // A library without a digest (older host) is requested in full, as before.
  await client.listPublicUiThemes(builtinLibrary());
  expect(fetch.mock.calls[3][0]).toMatch(/\/api\/public\/ui\/themes$/);
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

test("mock accounts keep their own selected theme", async () => {
  const alice = new MockWebBotClient();
  await alice.login({ username: "alice", password: "password" });
  const initial = await alice.listUiThemes();
  const id = initial.themes.at(-1)!.id;
  const selected = await alice.selectUiTheme(id, initial.revision);
  expect((await alice.listUiThemes()).selectedThemeId).toBe(id);
  const anonymous = new MockWebBotClient();
  await anonymous.logout();
  expect((await anonymous.listPublicUiThemes()).selectedThemeId).toBe("paper-daylight");
  await expect(anonymous.listUiThemes()).rejects.toMatchObject({ status: 401 });
  await expect(anonymous.selectUiTheme("paper-daylight", selected.revision)).rejects.toMatchObject({ status: 401 });
  const bob = new MockWebBotClient();
  await bob.login({ username: "bob", password: "password" });
  expect((await bob.listUiThemes()).selectedThemeId).toBe("paper-daylight");
  const bobSelected = await bob.selectUiTheme("theme_92ba863d3714c089235dfcef47ce3415", selected.revision);
  expect(bobSelected.selectedThemeId).toBe("theme_92ba863d3714c089235dfcef47ce3415");
  expect((await alice.listUiThemes()).selectedThemeId).toBe(id);
  await expect(bob.updateUiTheme(id, { schemaVersion: 1, expectedRevision: selected.revision, name: "共同编辑" })).rejects.toMatchObject({ status: 403 });
  const guest = new MockWebBotClient();
  await guest.loginGuest();
  expect((await guest.listUiThemes()).selectedThemeId).toBe("paper-daylight");
  await expect(guest.deleteUiTheme(id, bobSelected.revision)).rejects.toMatchObject({ status: 403 });
});
