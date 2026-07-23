import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileReadResult } from "../services/types";
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


describe("editor tabs workspace scope", () => {
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
