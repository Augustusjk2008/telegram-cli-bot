import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileCompressResult, FileTreeRevealResult } from "../services/types";
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

test("compressing a nested folder refreshes its parent and selects the sibling ZIP", async () => {
  const client = new MockWebBotClient();
  const list = vi.spyOn(client, "listFiles").mockImplementation(async (_alias, path) => ({
    workingDir: path || "/workspace",
    entries: path === "/workspace/docs"
      ? [{ name: "资料.v1", isDir: true }, { name: "资料.v1.zip", isDir: false }]
      : [{ name: "docs", isDir: true }],
  }));
  const compress = vi.spyOn(client, "compressDirectory").mockResolvedValue({
    sourcePath: "docs/资料.v1", path: "docs/资料.v1.zip", fileSizeBytes: 128, lastModifiedNs: "1780000000000000001",
  });
  const { result } = renderHook(() => useFileTree("main", client));
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.toggleDirectory("docs"));
  list.mockClear();
  await act(() => result.current.compressDirectory("docs/资料.v1"));
  expect(compress).toHaveBeenCalledWith("main", "docs/资料.v1");
  expect(list).toHaveBeenCalledExactlyOnceWith("main", "/workspace/docs", { includeChildCounts: true });
  expect(result.current.selectedPath).toBe("docs/资料.v1.zip");
  expect(result.current.expandedPaths).toEqual(["docs"]);
});

test("a compression finishing in the previous workspace cannot replace the current listing", async () => {
  const client = new MockWebBotClient();
  const compression = deferred<FileCompressResult>();
  const list = vi.spyOn(client, "listFiles")
    .mockResolvedValueOnce({ workingDir: "/workspace-a", entries: [{ name: "docs", isDir: true }] })
    .mockResolvedValue({ workingDir: "/workspace-b", entries: [{ name: "src", isDir: true }] });
  vi.spyOn(client, "compressDirectory").mockReturnValue(compression.promise);
  const { result, rerender } = renderHook(({ botAlias }) => useFileTree(botAlias, client), { initialProps: { botAlias: "main" } });
  await waitFor(() => expect(result.current.rootPath).toBe("/workspace-a"));
  let pending!: Promise<FileCompressResult>;
  act(() => { pending = result.current.compressDirectory("docs"); });
  rerender({ botAlias: "other" });
  await waitFor(() => expect(result.current.rootPath).toBe("/workspace-b"));
  list.mockClear();
  await act(async () => {
    compression.resolve({ sourcePath: "docs", path: "docs.zip", fileSizeBytes: 128, lastModifiedNs: "1" });
    await pending;
  });
  expect(list).not.toHaveBeenCalled();
  expect(result.current.rootEntries.map((entry) => entry.name)).toEqual(["src"]);
  expect(result.current.selectedPath).toBe("");
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

function pendingUntilAborted(signal?: AbortSignal) {
  return new Promise<void>((_resolve, reject) => {
    signal?.addEventListener("abort", () => {
      reject(new DOMException("上传已取消", "AbortError"));
    }, { once: true });
  });
}

test("file-tree uploads track batch progress, refuse an overlapping batch and can be cancelled", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: "C:\\workspace", entries: [] });
  let capturedSignal: AbortSignal | undefined;
  const upload = vi.spyOn(client, "uploadFile").mockImplementation(((_botAlias, file, onProgress, signal) => {
    if (file.name === "small.txt") {
      return Promise.resolve();
    }
    capturedSignal = signal;
    onProgress?.({ uploadedBytes: 400, totalBytes: 1000, percent: 40 });
    return pendingUntilAborted(signal);
  }) as typeof client.uploadFile);

  const { result } = renderHook(() => useFileTree("main", client));
  await waitFor(() => expect(result.current.rootPath).toBe("C:\\workspace"));

  let uploadPromise!: Promise<boolean>;
  act(() => {
    uploadPromise = result.current.uploadFiles([new File(["a"], "small.txt"), new File(["b"], "large.bin")]);
  });
  await waitFor(() => expect(result.current.uploadProgress).toEqual({
    filename: "large.bin",
    fileIndex: 2,
    fileCount: 2,
    uploadedBytes: 400,
    totalBytes: 1000,
    percent: 40,
  }));
  expect(result.current.highlightedPath).toBe("small.txt");
  await expect(result.current.uploadFiles([new File(["c"], "other.txt")])).rejects.toThrow("已有文件正在上传");

  act(() => {
    result.current.cancelUpload();
  });
  await act(async () => {
    await expect(uploadPromise).resolves.toBe(true);
  });

  expect(capturedSignal?.aborted).toBe(true);
  expect(upload).toHaveBeenCalledTimes(2);
  expect(result.current.uploadProgress).toBeNull();
  expect(result.current.error).toBe("");
});

test("switching bots stops tracking a file-tree upload without cancelling it", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: "C:\\workspace", entries: [] });
  const pendingUpload = deferred<void>();
  let capturedSignal: AbortSignal | undefined;
  vi.spyOn(client, "uploadFile").mockImplementation(((_botAlias, _file, onProgress, signal) => {
    capturedSignal = signal;
    onProgress?.({ uploadedBytes: 1, totalBytes: 2, percent: 50 });
    return pendingUpload.promise;
  }) as typeof client.uploadFile);

  const { result, rerender } = renderHook(({ botAlias }) => useFileTree(botAlias, client), {
    initialProps: { botAlias: "main" },
  });
  await waitFor(() => expect(result.current.rootPath).toBe("C:\\workspace"));

  let uploadPromise!: Promise<boolean>;
  act(() => {
    uploadPromise = result.current.uploadFiles([new File(["ab"], "report.txt")]);
  });
  await waitFor(() => expect(result.current.uploadProgress?.percent).toBe(50));

  rerender({ botAlias: "other" });
  expect(result.current.uploadProgress).toBeNull();
  expect(capturedSignal?.aborted).toBe(false);

  await act(async () => {
    pendingUpload.resolve();
    await expect(uploadPromise).resolves.toBe(false);
  });
  expect(result.current.uploadProgress).toBeNull();
});
