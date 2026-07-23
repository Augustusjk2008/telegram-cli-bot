import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import {
  EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS,
  useEditorTabs,
} from "../workbench/useEditorTabs";

describe("editor language document sync", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  test("increments document versions and sends the latest content", async () => {
    vi.useFakeTimers();
    const client = new MockWebBotClient();
    const sync = vi.spyOn(client, "syncWorkspaceDocuments");
    const { result } = renderHook(() => useEditorTabs({ botAlias: "main", client }));

    act(() => {
      result.current.openCreatedFile("main.py", "name = 1\n");
      result.current.updateActiveContent("name = 2\n");
      result.current.updateActiveContent("name = 3\n");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS + 1);
    });

    expect(result.current.activeTab?.documentVersion).toBe(3);
    expect(sync).toHaveBeenCalled();
    const latest = sync.mock.calls.at(-1)?.[1];
    expect(latest?.documents[0]).toMatchObject({
      path: "main.py",
      version: 3,
      content: "name = 3\n",
    });
  });

  test("closes documents when a tab is closed and replays on client replacement", async () => {
    const client = new MockWebBotClient();
    const close = vi.spyOn(client, "closeWorkspaceDocuments");
    const { result, rerender } = renderHook(
      ({ currentClient }) => useEditorTabs({ botAlias: "main", client: currentClient }),
      { initialProps: { currentClient: client } },
    );

    act(() => {
      result.current.openCreatedFile("main.py", "name = 1\n");
    });
    act(() => {
      result.current.closePath("main.py");
    });
    await waitFor(() => expect(close).toHaveBeenCalledWith("main", { documents: [{ path: "main.py", version: 1 }] }));

    const replacement = new MockWebBotClient();
    const replacementSync = vi.spyOn(replacement, "syncWorkspaceDocuments");
    act(() => {
      result.current.openCreatedFile("main.py", "name = 2\n");
    });
    rerender({ currentClient: replacement });
    await waitFor(() => expect(replacementSync).toHaveBeenCalled());
  });

  test("replays dirty draft snapshots with their persisted document version", async () => {
    vi.useFakeTimers();
    const client = new MockWebBotClient();
    const sync = vi.spyOn(client, "syncWorkspaceDocuments");
    const { result } = renderHook(() => useEditorTabs({ botAlias: "main", client }));

    await act(async () => {
      await result.current.restoreFromSnapshot(
        [{
          path: "draft.py",
          dirty: true,
          documentVersion: 7,
          savedContent: "old_name = 1\n",
          draftContent: "new_name = 1\n",
          contentPersistence: "dirty_snapshot",
        }],
        "draft.py",
      );
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS + 1);
    });

    expect(sync).toHaveBeenCalled();
    expect(sync.mock.calls.at(-1)?.[1]).toMatchObject({
      event: "didOpen",
      documents: [{
        path: "draft.py",
        version: 7,
        content: "new_name = 1\n",
      }],
    });
  });

  test("aborts an older sync request when a newer document version is sent", async () => {
    vi.useFakeTimers();
    const client = new MockWebBotClient();
    let firstSignal: AbortSignal | undefined;
    const sync = vi.spyOn(client, "syncWorkspaceDocuments")
      .mockImplementationOnce((_botAlias, _input, signal) => {
        firstSignal = signal;
        return new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
          if (signal?.aborted) {
            reject(new Error("aborted"));
          }
        });
      })
      .mockResolvedValue({ accepted: 1 });
    const { result } = renderHook(() => useEditorTabs({ botAlias: "main", client }));

    act(() => {
      result.current.openCreatedFile("main.py", "name = 1\n");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS + 1);
    });
    act(() => {
      result.current.updateActiveContent("name = 2\n");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS + 1);
    });

    expect(sync).toHaveBeenCalledTimes(2);
    expect(firstSignal?.aborted).toBe(true);
    expect(sync.mock.calls[1]?.[1].documents[0]?.version).toBe(2);
  });

  test("does not replay old tabs when the bot scope and client change together", async () => {
    vi.useFakeTimers();
    const firstClient = new MockWebBotClient();
    const nextClient = new MockWebBotClient();
    const nextSync = vi.spyOn(nextClient, "syncWorkspaceDocuments");
    const { result, rerender } = renderHook(
      ({ botAlias, client }) => useEditorTabs({ botAlias, client }),
      { initialProps: { botAlias: "main", client: firstClient } },
    );

    act(() => {
      result.current.openCreatedFile("private.py", "private = 1\n");
    });
    rerender({ botAlias: "other", client: nextClient });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EDITOR_DOCUMENT_SYNC_DEBOUNCE_MS + 1);
    });

    expect(result.current.tabs).toEqual([]);
    expect(nextSync).not.toHaveBeenCalled();
  });
});
