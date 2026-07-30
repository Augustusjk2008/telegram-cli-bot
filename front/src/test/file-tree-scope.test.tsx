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
