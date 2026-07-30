import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileReadResult, PluginOpenTarget, PluginRenderResult } from "../services/types";
import { useEditorTabs } from "../workbench/useEditorTabs";


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}


function fileResult(content: string): FileReadResult {
  return {
    content,
    mode: "cat",
    fileSizeBytes: content.length,
    isFullContent: true,
    lastModifiedNs: content,
  };
}


const pluginTarget: PluginOpenTarget = {
  pluginId: "demo-plugin",
  viewId: "report",
  title: "插件报告",
  input: { path: "src/index.py" },
};


function pluginSession(sessionId: string): PluginRenderResult {
  return {
    pluginId: "demo-plugin",
    viewId: "report",
    title: "插件报告",
    renderer: "table",
    mode: "session",
    sessionId,
    summary: {},
    initialWindow: {},
  } as PluginRenderResult;
}


describe("editor tabs workspace scope", () => {
  test("file preview tabs stay transient while editable tabs are persisted", () => {
    const client = new MockWebBotClient();
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    act(() => {
      result.current.openCreatedFile("src/index.py", "print('workspace')\n");
      result.current.openFilePreview({
        path: "README.md",
        result: fileResult("# Preview\n"),
      });
    });

    expect(result.current.tabs.map((tab) => tab.kind)).toEqual(["file", "file-preview"]);
    expect(result.current.buildPersistenceSnapshot().map((tab) => tab.path)).toEqual(["src/index.py"]);
  });

  test("a preview response preserves tabs opened while it was loading", async () => {
    const client = new MockWebBotClient();
    const fileRead = deferred<FileReadResult>();
    vi.spyOn(client, "readFileFull").mockReturnValue(fileRead.promise);
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    act(() => {
      result.current.openFilePreview({ path: "README.md", loading: true });
    });
    let openPromise!: Promise<void>;
    act(() => {
      openPromise = result.current.openFile("src/index.py");
      result.current.openFilePreview({
        path: "README.md",
        result: fileResult("# Preview\n"),
        loading: false,
        activate: false,
      });
    });
    expect(result.current.tabs.map((tab) => tab.path)).toEqual([
      "file-preview:README.md",
      "src/index.py",
    ]);

    await act(async () => {
      fileRead.resolve(fileResult("print('workspace')\n"));
      await openPromise;
    });
  });

  test("a closed preview cannot be recreated by a late response", () => {
    const client = new MockWebBotClient();
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    act(() => {
      result.current.openFilePreview({ path: "README.md", loading: true });
    });
    act(() => {
      result.current.closeTab("file-preview:README.md");
      result.current.openFilePreview({
        path: "README.md",
        result: fileResult("late result"),
        loading: false,
        activate: false,
      });
    });

    expect(result.current.tabs).toEqual([]);
  });

  test("deleting a source path closes its preview and descendants", () => {
    const client = new MockWebBotClient();
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    act(() => {
      result.current.openCreatedFile("src/index.py", "print('workspace')\n");
      result.current.openFilePreview({ path: "src/index.py", result: fileResult("# Preview\n") });
      result.current.openCreatedFile("src/nested/readme.md", "draft\n");
      result.current.openFilePreview({ path: "src/nested/readme.md", result: fileResult("# Nested\n") });
    });

    act(() => {
      result.current.closeDeletedPath("src");
    });

    expect(result.current.tabs).toEqual([]);
  });

  test("renaming a directory migrates file and preview tab paths", () => {
    const client = new MockWebBotClient();
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    act(() => {
      result.current.openCreatedFile("src/index.py", "print('workspace')\n");
      result.current.openFilePreview({ path: "src/index.py", result: fileResult("# Preview\n") });
      result.current.syncRenamedPath("src", "lib");
    });

    expect(result.current.tabs.map((tab) => tab.path)).toEqual([
      "lib/index.py",
      "file-preview:lib/index.py",
    ]);
    expect(result.current.tabs[1]?.sourcePath).toBe("lib/index.py");
  });

  test("a plugin session response cannot recreate a closed tab", async () => {
    const client = new MockWebBotClient();
    const pluginRead = deferred<PluginRenderResult>();
    vi.spyOn(client, "openPluginView").mockReturnValue(pluginRead.promise);
    const disposeSession = vi.spyOn(client, "disposePluginViewSession");
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    let openPromise!: Promise<void>;
    act(() => {
      openPromise = result.current.openPluginView(pluginTarget);
    });
    await waitFor(() => expect(client.openPluginView).toHaveBeenCalledTimes(1));
    act(() => {
      result.current.closeTab("plugin://demo-plugin/report/src/index.py");
    });

    await act(async () => {
      pluginRead.resolve(pluginSession("late-session"));
      await openPromise;
    });

    expect(result.current.tabs).toEqual([]);
    expect(disposeSession).toHaveBeenCalledWith("main", "demo-plugin", "late-session");
  });

  test("plugin responses from an old scope are discarded and disposed", async () => {
    const client = new MockWebBotClient();
    const pluginRead = deferred<PluginRenderResult>();
    vi.spyOn(client, "openPluginView").mockReturnValue(pluginRead.promise);
    const disposeSession = vi.spyOn(client, "disposePluginViewSession");
    const { result, rerender } = renderHook(
      ({ scopeKey }) => useEditorTabs({ botAlias: "main", client, scopeKey }),
      { initialProps: { scopeKey: "main\nworkspace-a" } },
    );

    let openPromise!: Promise<void>;
    act(() => {
      openPromise = result.current.openPluginView(pluginTarget);
    });
    await waitFor(() => expect(client.openPluginView).toHaveBeenCalledTimes(1));

    rerender({ scopeKey: "main\nworkspace-b" });
    await waitFor(() => expect(result.current.tabs).toEqual([]));
    await act(async () => {
      pluginRead.resolve(pluginSession("old-scope-session"));
      await openPromise;
    });

    expect(result.current.tabs).toEqual([]);
    expect(disposeSession).toHaveBeenCalledWith("main", "demo-plugin", "old-scope-session");
  });

  test("only the latest concurrent plugin response is accepted", async () => {
    const client = new MockWebBotClient();
    const firstRead = deferred<PluginRenderResult>();
    const secondRead = deferred<PluginRenderResult>();
    vi.spyOn(client, "openPluginView")
      .mockReturnValueOnce(firstRead.promise)
      .mockReturnValueOnce(secondRead.promise);
    const disposeSession = vi.spyOn(client, "disposePluginViewSession");
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    let firstOpen!: Promise<void>;
    let secondOpen!: Promise<void>;
    act(() => {
      firstOpen = result.current.openPluginView(pluginTarget);
      secondOpen = result.current.openPluginView(pluginTarget);
    });
    await waitFor(() => expect(client.openPluginView).toHaveBeenCalledTimes(2));

    await act(async () => {
      secondRead.resolve(pluginSession("latest-session"));
      await secondOpen;
      firstRead.resolve(pluginSession("stale-session"));
      await firstOpen;
    });

    expect(result.current.tabs).toHaveLength(1);
    expect(result.current.tabs[0]?.pluginView).toMatchObject({ sessionId: "latest-session" });
    expect(disposeSession).toHaveBeenCalledWith("main", "demo-plugin", "stale-session");
  });

  test("renaming a loading plugin view restarts it with the migrated source path", async () => {
    const client = new MockWebBotClient();
    const oldRead = deferred<PluginRenderResult>();
    const renamedRead = deferred<PluginRenderResult>();
    vi.spyOn(client, "openPluginView")
      .mockReturnValueOnce(oldRead.promise)
      .mockReturnValueOnce(renamedRead.promise);
    const disposeSession = vi.spyOn(client, "disposePluginViewSession");
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    let oldOpen!: Promise<void>;
    act(() => {
      oldOpen = result.current.openPluginView(pluginTarget);
    });
    await waitFor(() => expect(client.openPluginView).toHaveBeenCalledTimes(1));

    let renamedOpen!: Promise<void>;
    act(() => {
      const renamed = result.current.syncRenamedPath("src", "lib");
      expect(renamed.pluginTargets).toEqual([{
        ...pluginTarget,
        input: { path: "lib/index.py" },
      }]);
      renamedOpen = result.current.openPluginView(renamed.pluginTargets[0], { activate: false });
    });

    await act(async () => {
      oldRead.resolve(pluginSession("old-path-session"));
      await oldOpen;
      renamedRead.resolve(pluginSession("renamed-session"));
      await renamedOpen;
    });

    expect(result.current.tabs).toHaveLength(1);
    expect(result.current.tabs[0]).toMatchObject({
      path: "plugin://demo-plugin/report/lib/index.py",
      sourcePath: "lib/index.py",
      pluginInput: { path: "lib/index.py" },
      pluginView: { sessionId: "renamed-session" },
    });
    expect(result.current.activeTabPath).toBe("plugin://demo-plugin/report/lib/index.py");
    expect(disposeSession).toHaveBeenCalledWith("main", "demo-plugin", "old-path-session");
  });

  test("closing tabs to the right moves an invalid active path to the retained tab", () => {
    const client = new MockWebBotClient();
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    act(() => {
      result.current.openCreatedFile("src/index.py", "print('workspace')\n");
      result.current.openFilePreview({ path: "README.md", result: fileResult("# Preview\n") });
      result.current.closeTabsToRight("src/index.py");
    });

    expect(result.current.tabs.map((tab) => tab.path)).toEqual(["src/index.py"]);
    expect(result.current.activeTabPath).toBe("src/index.py");
    expect(result.current.activeTab?.path).toBe("src/index.py");
  });

  test("an old workspace read cannot overwrite the same relative path in a new workspace", async () => {
    const client = new MockWebBotClient();
    const oldRead = deferred<FileReadResult>();
    const newRead = deferred<FileReadResult>();
    vi.spyOn(client, "readFileFull")
      .mockImplementationOnce(() => oldRead.promise)
      .mockImplementationOnce(() => newRead.promise);

    const { result, rerender } = renderHook(
      ({ scopeKey }) => useEditorTabs({
        botAlias: "main",
        client,
        scopeKey,
      }),
      { initialProps: { scopeKey: "main\nworkspace-a" } },
    );

    let oldOpen!: Promise<void>;
    act(() => {
      oldOpen = result.current.openFile("src/index.py");
    });
    await waitFor(() => expect(client.readFileFull).toHaveBeenCalledTimes(1));

    rerender({ scopeKey: "main\nworkspace-b" });
    await waitFor(() => expect(result.current.tabs).toHaveLength(0));

    let newOpen!: Promise<void>;
    act(() => {
      newOpen = result.current.openFile("src/index.py");
    });
    await waitFor(() => expect(client.readFileFull).toHaveBeenCalledTimes(2));
    await act(async () => {
      newRead.resolve(fileResult("new workspace"));
      await newOpen;
    });
    expect(result.current.activeTab?.content).toBe("new workspace");

    await act(async () => {
      oldRead.resolve(fileResult("old workspace"));
      await oldOpen;
    });
    expect(result.current.activeTab?.content).toBe("new workspace");
  });
});
