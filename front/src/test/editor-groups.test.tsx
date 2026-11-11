import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { useEditorTabs } from "../workbench/useEditorTabs";
import { normalizePersistedWorkbenchSession } from "../workbench/workbenchSession";

afterEach(() => vi.restoreAllMocks());

function setup() {
  const client = new MockWebBotClient();
  const read = vi.spyOn(client, "readFileFull").mockImplementation(async (_bot, path) => ({
    mode: "cat", content: `original ${path}`, isFullContent: true, lastModifiedNs: "1",
  }));
  const write = vi.spyOn(client, "writeFile").mockImplementation(async (_bot, path, content) => ({ path, fileSizeBytes: content.length, lastModifiedNs: "2" }));
  const close = vi.spyOn(client, "closeWorkspaceDocuments").mockResolvedValue({ closed: 1 });
  const hook = renderHook(() => useEditorTabs({ botAlias: "main", client }));
  return { ...hook, client, read, write, close };
}

test("two views share one document, save once, and closing one keeps the unsaved document open", async () => {
  const { result, read, write, close } = setup();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await act(() => result.current.openFile("a.ts"));
  act(() => result.current.updateContent("a.ts", "draft"));
  await act(() => result.current.openFile("a.ts", undefined, "right"));
  expect(read).toHaveBeenCalledTimes(1);
  expect(result.current.tabs).toHaveLength(1);
  expect(result.current.groups.left.activePath).toBe("a.ts");
  expect(result.current.groups.right.activePath).toBe("a.ts");
  expect(result.current.activeTab).toMatchObject({ content: "draft", dirty: true });
  await act(async () => { await Promise.all([result.current.saveTab("a.ts"), result.current.saveTab("a.ts")]); });
  expect(write).toHaveBeenCalledExactlyOnceWith("main", "a.ts", "draft", "1", undefined);
  expect(result.current.activeTab).toMatchObject({ savedContent: "draft", dirty: false });

  act(() => result.current.updateContent("a.ts", "next draft"));
  act(() => { expect(result.current.closeTab("a.ts", "right")).toBe(true); });
  expect(confirm).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
  expect(result.current.activeTab).toMatchObject({ content: "next draft", dirty: true });
  act(() => { expect(result.current.closeTab("a.ts", "left")).toBe(false); });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(result.current.tabs).toHaveLength(1);
});

test("updates and saves target their file even after focus moves to the other group", async () => {
  const { result, write } = setup();
  await act(() => result.current.openFile("left.ts"));
  await act(() => result.current.openFile("right.ts", undefined, "right"));
  act(() => {
    result.current.updateContent("left.ts", "left draft");
    result.current.updateContent("right.ts", "right draft");
  });
  await act(() => result.current.saveTab("left.ts"));
  expect(write).toHaveBeenCalledExactlyOnceWith("main", "left.ts", "left draft", "1", undefined);
  expect(result.current.activeTab).toMatchObject({ path: "right.ts", content: "right draft", dirty: true });
  act(() => result.current.closeRightGroup());
  expect(result.current.groups.left.paths).toEqual(["left.ts", "right.ts"]);
  expect(result.current.groups.right.paths).toEqual([]);
  expect(result.current.activeTab).toMatchObject({ path: "right.ts", content: "right draft", dirty: true });
});

test("an edit arriving during save stays dirty and a failed save retains both views' draft", async () => {
  const { result, write } = setup();
  await act(() => result.current.openFile("a.ts"));
  await act(() => result.current.openFile("a.ts", undefined, "right"));
  act(() => result.current.updateContent("a.ts", "first edit"));
  let complete!: (value: { path: string; fileSizeBytes: number; lastModifiedNs: string }) => void;
  write.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
  let saving!: Promise<void>;
  act(() => { saving = result.current.saveTab("a.ts"); });
  act(() => result.current.updateContent("a.ts", "second edit"));
  await act(async () => {
    complete({ path: "a.ts", fileSizeBytes: 10, lastModifiedNs: "2" });
    await saving;
  });
  expect(result.current.activeTab).toMatchObject({ content: "second edit", savedContent: "first edit", dirty: true, lastModifiedNs: "2" });
  write.mockRejectedValueOnce(new Error("文件已被修改"));
  await act(() => result.current.saveActiveTab());
  expect(result.current.activeTab).toMatchObject({ content: "second edit", dirty: true, saving: false, error: "文件已被修改" });
});

test.each(["unsaved", ""])("shared-file groups restore the %j draft and its saved baseline, and renames update both groups", async (draft) => {
  const { result } = setup();
  await act(() => result.current.openFile("dir/a.ts"));
  await act(() => result.current.openFile("dir/a.ts", undefined, "right"));
  act(() => {
    result.current.updateContent("dir/a.ts", draft);
    result.current.setSplitRatio(0.65);
  });
  const snapshot = normalizePersistedWorkbenchSession({
    version: 1, botAlias: "main", workspaceRoot: "C:/workspace", sidebarView: "files", expandedPaths: [],
    activeTabPath: result.current.activeTabPath, editorGroups: result.current.groups,
    tabs: result.current.buildPersistenceSnapshot(),
  })!;
  await act(() => result.current.restoreFromSnapshot([], ""));
  await act(() => result.current.restoreFromSnapshot(snapshot.tabs, snapshot.activeTabPath, { groups: snapshot.editorGroups }));
  expect(result.current.groups).toEqual(snapshot.editorGroups);
  expect(result.current.tabs).toHaveLength(1);
  expect(result.current.activeTab).toMatchObject({ content: draft, savedContent: "original dir/a.ts", dirty: true });
  act(() => result.current.syncRenamedPath("dir", "renamed"));
  expect(result.current.groups.left.activePath).toBe("renamed/a.ts");
  expect(result.current.groups.right.activePath).toBe("renamed/a.ts");
  act(() => result.current.closeDeletedPath("renamed"));
  expect(result.current.tabs).toHaveLength(0);
  expect(result.current.groups.right.paths).toEqual([]);
});

test("a closed read cannot overwrite a new opening of the same path", async () => {
  const { result, read } = setup();
  let complete!: (value: { mode: "cat"; content: string; isFullContent: boolean }) => void;
  read.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
  let first!: Promise<void>;
  act(() => { first = result.current.openFile("a.ts"); });
  act(() => { result.current.closeTab("a.ts", "left"); });
  read.mockResolvedValueOnce({ mode: "cat", content: "new disk content", isFullContent: true });
  await act(() => result.current.openFile("a.ts", undefined, "right"));
  await act(async () => {
    complete({ mode: "cat", content: "old disk content", isFullContent: true });
    await first;
  });
  expect(result.current.activeTab?.content).toBe("new disk content");
  expect(result.current.groups.right.activePath).toBe("a.ts");
});

test("external navigation reports the existing group and a closed source stays closed after its read completes", async () => {
  const { result, client } = setup();
  const read = vi.spyOn(client, "readExternalSource").mockResolvedValue({ sourceId: "dep", displayPath: "library.ts", content: "library" });
  await act(() => result.current.openExternalSource("dep", "left"));
  await act(() => result.current.openFile("a.ts", undefined, "right"));
  await act(() => result.current.openExternalSource("dep", "right"));
  expect(result.current.groupForPath("external-source:dep", "right")).toBe("left");
  expect(result.current.groups.activeGroupId).toBe("left");
  let complete!: (value: Awaited<ReturnType<typeof client.readExternalSource>>) => void;
  read.mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
  let pending!: Promise<boolean>;
  act(() => { pending = result.current.openExternalSource("loading", "right"); });
  act(() => { result.current.closeTab("external-source:loading", "right"); });
  await act(async () => {
    complete({ sourceId: "loading", displayPath: "other.ts", content: "late" });
    expect(await pending).toBe(false);
  });
  expect(result.current.tabs.some((tab) => tab.path === "external-source:loading")).toBe(false);
});
