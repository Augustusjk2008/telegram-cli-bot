import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AppearanceProvider, useAppearance } from "../theme/AppearanceProvider";
import { BUILTIN_THEME, builtinLibrary } from "../theme/resolveAppearance";
import type { ThemeLibrary } from "../theme/types";
import type { WebBotClient } from "../services/webBotClient";

let state: ReturnType<typeof useAppearance>;
function Probe() { state = useAppearance(); return null; }
function library(id: string, revision = 1): ThemeLibrary {
  return { ...builtinLibrary(), revision, selectedThemeId: id, themes: [BUILTIN_THEME, { ...BUILTIN_THEME, id, readonly: false,
    appearance: { colors: { scheme: "dark", overrides: { accent: "#123456" } } } }] };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });

test("authenticated sessions restore the global library and reject late responses after session changes", async () => {
  const pending = deferred<ThemeLibrary>();
  const alice = { listUiThemes: vi.fn(() => pending.promise) } as unknown as WebBotClient;
  const bob = { listUiThemes: vi.fn(async () => library("theme_bob")) } as unknown as WebBotClient;
  localStorage.setItem("web-ui-theme", "theme_alice");
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  expect(state.appearance.themeId).toBe("paper-daylight");
  expect(state.canManage).toBe(false);
  act(() => state.bindSession({ key: "alice", client: alice }));
  act(() => state.bindSession({ key: "bob", client: bob }));
  await waitFor(() => expect(state.appearance.themeId).toBe("theme_bob"));
  await act(async () => pending.resolve(library("theme_alice")));
  expect(state.appearance.themeId).toBe("theme_bob");
  act(() => state.bindSession(null));
  expect(state.appearance.themeId).toBe("paper-daylight");
  expect(document.documentElement.dataset.theme).toBe("paper-daylight");
});

test("failed mutations keep the saved selection and use the draft revision", async () => {
  const update = vi.fn(async () => { throw new Error("主题库已更新，请重新加载（409）"); });
  const client = { listUiThemes: vi.fn(async () => library("theme_alice", 3)), updateUiTheme: update } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "alice", client }));
  await waitFor(() => expect(state.library.revision).toBe(3));
  await act(async () => {
    await expect(state.updateTheme("theme_alice", { schemaVersion: 1, name: "草稿", expectedRevision: 2, activate: true })).rejects.toThrow("409");
  });
  expect(update).toHaveBeenCalledWith("theme_alice", expect.objectContaining({ expectedRevision: 2, activate: true }));
  expect(state.library.revision).toBe(3);
  expect(state.appearance.themeId).toBe("theme_alice");
});

test("global notifications reload the library and logout clears the current appearance", async () => {
  const list = vi.fn(async () => library("theme_alice"));
  const client = { listUiThemes: list } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "alice", client }));
  await waitFor(() => expect(state.appearance.themeId).toBe("theme_alice"));
  const key = Object.keys(localStorage).find((item) => item.startsWith("web-ui-themes:"))!;
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: `${key}-other` })));
  expect(list).toHaveBeenCalledTimes(1);
  list.mockResolvedValue(builtinLibrary());
  act(() => window.dispatchEvent(new StorageEvent("storage", { key })));
  await waitFor(() => expect(state.appearance.themeId).toBe("paper-daylight"));
  expect(list).toHaveBeenCalledTimes(2);
});

test("all accounts reuse one global cache while obsolete personal caches are ignored", async () => {
  const pending = deferred<ThemeLibrary>();
  localStorage.setItem("web-ui-themes:/:alice", JSON.stringify({ ...library("theme_private"), scope: undefined, accountId: "alice" }));
  const alice = { listUiThemes: vi.fn(async () => library("theme_shared", 4)) } as unknown as WebBotClient;
  const bob = { listUiThemes: vi.fn(() => pending.promise) } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "alice", client: alice }));
  await waitFor(() => expect(state.appearance.themeId).toBe("theme_shared"));
  const cache = Object.keys(localStorage).find((key) => key.startsWith("web-ui-themes:global:"))!;
  act(() => state.bindSession({ key: "bob", client: bob }));
  expect(state.appearance.themeId).toBe("theme_shared");
  await act(async () => pending.resolve(library("theme_shared", 4)));
  expect(Object.keys(localStorage).filter((key) => key.startsWith("web-ui-themes:global:"))).toEqual([cache]);
});

test("guest sessions display the global selection and cannot write", async () => {
  const select = vi.fn();
  const client = { listUiThemes: vi.fn(async () => library("theme_shared")), selectUiTheme: select } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "guest", client, canManage: false }));
  await waitFor(() => expect(state.appearance.themeId).toBe("theme_shared"));
  expect(state.canManage).toBe(false);
  await expect(state.selectTheme("paper-daylight")).rejects.toThrow("正式账户");
  expect(select).not.toHaveBeenCalled();
});

test("an obsolete account-scoped service cannot receive writes from the global UI", async () => {
  const { scope: _scope, ...oldLibrary } = library("theme_private");
  const create = vi.fn();
  const client = { listUiThemes: vi.fn(async () => ({ ...oldLibrary, accountId: "alice" })), createUiTheme: create } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "alice", client }));
  await waitFor(() => expect(state.error).toContain("重载宿主"));
  expect(state.appearance.themeId).toBe("paper-daylight");
  await expect(state.createTheme({ schemaVersion: 1, sourceId: "paper-daylight", name: "共享配色" })).rejects.toThrow("全局主题库尚未加载成功");
  expect(create).not.toHaveBeenCalled();
  expect(Object.keys(localStorage).filter((key) => key.startsWith("web-ui-themes:global:"))).toEqual([]);
});

test("an older reload failure cannot replace a newer successful response of the same revision", async () => {
  const old = deferred<ThemeLibrary>();
  const list = vi.fn(async () => library("theme_alice", 7));
  const client = { listUiThemes: list } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "alice", client }));
  await waitFor(() => expect(state.library.revision).toBe(7));
  list.mockImplementationOnce(() => old.promise);
  let pending!: Promise<void>;
  act(() => { pending = state.reload(); });
  await act(async () => { await state.reload(); });
  await act(async () => { old.reject(new Error("过期网络错误")); await pending; });
  expect(state.library.revision).toBe(7);
  expect(state.appearance.themeId).toBe("theme_alice");
  expect(state.error).toBe("");
  expect(state.loading).toBe(false);
});

test("a delayed mutation response cannot roll back a newer library or its cache", async () => {
  const delayed = deferred<ThemeLibrary>();
  const list = vi.fn(async () => library("theme_alice", 10));
  const client = { listUiThemes: list, updateUiTheme: vi.fn(() => delayed.promise) } as unknown as WebBotClient;
  render(<AppearanceProvider><Probe /></AppearanceProvider>);
  act(() => state.bindSession({ key: "alice", client }));
  await waitFor(() => expect(state.library.revision).toBe(10));
  let failure = "";
  let mutation!: Promise<unknown>;
  act(() => { mutation = state.updateTheme("theme_alice", { schemaVersion: 1, name: "延迟保存" }).catch((error) => { failure = error.message; }); });
  list.mockResolvedValue(library("theme_alice", 12));
  await act(async () => { await state.reload(); });
  await act(async () => { delayed.resolve(library("theme_alice", 11)); await mutation; });
  expect(state.library.revision).toBe(12);
  expect(failure).toContain("主题已提交");
  const key = Object.keys(localStorage).find((item) => item.startsWith("web-ui-themes:"))!;
  expect(JSON.parse(localStorage.getItem(key)!).revision).toBe(12);
});
