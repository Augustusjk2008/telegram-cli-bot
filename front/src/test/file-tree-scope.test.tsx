import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileTreeRevealResult } from "../services/types";
import { useFileTree } from "../workbench/useFileTree";


function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}


test("an old workspace reveal cannot mutate the new workspace tree", async () => {
  const client = new MockWebBotClient();
  const oldReveal = deferred<FileTreeRevealResult>();
  vi.spyOn(client, "listFiles")
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace-a",
      entries: [{ name: "old", isDir: true }],
    })
    .mockResolvedValueOnce({
      workingDir: "C:\\workspace-b",
      entries: [{ name: "new", isDir: true }],
    });
  vi.spyOn(client, "revealFileTreePath").mockReturnValue(oldReveal.promise);

  const { result } = renderHook(() => useFileTree("main", client));
  await waitFor(() => expect(result.current.rootPath).toBe("C:\\workspace-a"));

  let revealPromise!: Promise<void>;
  act(() => {
    revealPromise = result.current.revealPath("old/main.py");
  });
  await waitFor(() => expect(client.revealFileTreePath).toHaveBeenCalledTimes(1));

  await act(async () => {
    await result.current.refreshRoot({ rootPath: "C:\\workspace-b" });
  });
  expect(result.current.rootPath).toBe("C:\\workspace-b");

  await act(async () => {
    oldReveal.resolve({
      rootPath: "C:\\workspace-a",
      highlightPath: "old/main.py",
      expandedPaths: ["old"],
      branches: {
        old: [{ name: "main.py", isDir: false }],
      },
    });
    await revealPromise;
  });

  expect(result.current.rootPath).toBe("C:\\workspace-b");
  expect(result.current.rootEntries.map((entry) => entry.name)).toEqual(["new"]);
  expect(result.current.expandedPaths).toEqual([]);
  expect(result.current.selectedPath).toBe("");
  expect(result.current.highlightedPath).toBe("");
  expect(result.current.branches.old).toBeUndefined();
});

test("an active file-tree download can be cancelled without surfacing an error", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "C:\\workspace",
    entries: [{ name: "large.bin", isDir: false, size: 1024 }],
  });
  let capturedSignal: AbortSignal | undefined;
  vi.spyOn(client, "downloadFile").mockImplementation(((_botAlias, _filename, onProgress, signal) => {
    capturedSignal = signal;
    onProgress?.({ downloadedBytes: 128, totalBytes: 1024, percent: 13 });
    return new Promise<void>((resolve, reject) => {
      signal?.addEventListener("abort", () => {
        reject(new DOMException("下载已取消", "AbortError"));
      }, { once: true });
      if (signal?.aborted) {
        reject(new DOMException("下载已取消", "AbortError"));
      }
      void resolve;
    });
  }) as typeof client.downloadFile);

  const { result } = renderHook(() => useFileTree("main", client));
  await waitFor(() => expect(result.current.rootPath).toBe("C:\\workspace"));

  let downloadPromise!: Promise<void>;
  act(() => {
    downloadPromise = result.current.downloadFile("large.bin");
  });
  await waitFor(() => expect(result.current.downloadProgress?.percent).toBe(13));

  act(() => {
    (result.current as typeof result.current & { cancelDownload: () => void }).cancelDownload();
  });
  await act(async () => {
    await downloadPromise;
  });

  expect(capturedSignal?.aborted).toBe(true);
  expect(result.current.downloadProgress).toBeNull();
  expect(result.current.error).toBe("");
});

test("unmounting the file tree aborts its active download", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: "C:\\workspace", entries: [] });
  let capturedSignal: AbortSignal | undefined;
  vi.spyOn(client, "downloadFile").mockImplementation(((_botAlias, _filename, _onProgress, signal) => {
    capturedSignal = signal;
    return new Promise<void>((_resolve, reject) => {
      signal?.addEventListener("abort", () => {
        reject(new DOMException("下载已取消", "AbortError"));
      }, { once: true });
    });
  }) as typeof client.downloadFile);

  const { result, unmount } = renderHook(() => useFileTree("main", client));
  await waitFor(() => expect(result.current.rootPath).toBe("C:\\workspace"));

  act(() => {
    void result.current.downloadFile("large.bin");
  });
  await waitFor(() => expect(result.current.downloadProgress?.path).toBe("large.bin"));
  unmount();

  expect(capturedSignal?.aborted).toBe(true);
});
