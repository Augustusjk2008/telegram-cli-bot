import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { PluginOpenTarget, PluginRenderResult } from "../services/types";
import { useEditorTabs } from "../workbench/useEditorTabs";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
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

describe("plugin view sessions", () => {
  test("a late response for a closed plugin tab is discarded and its server session is disposed", async () => {
    const client = new MockWebBotClient();
    const response = deferred<PluginRenderResult>();
    vi.spyOn(client, "openPluginView").mockReturnValue(response.promise);
    const dispose = vi.spyOn(client, "disposePluginViewSession");
    const { result } = renderHook(() => useEditorTabs({
      botAlias: "main",
      client,
      scopeKey: "main\nworkspace-a",
    }));

    let opening!: Promise<void>;
    act(() => {
      opening = result.current.openPluginView(pluginTarget);
    });
    await waitFor(() => expect(client.openPluginView).toHaveBeenCalledTimes(1));
    act(() => result.current.closeTab("plugin://demo-plugin/report/src/index.py"));
    await act(async () => {
      response.resolve(pluginSession("late-session"));
      await opening;
    });

    expect(result.current.tabs).toEqual([]);
    expect(dispose).toHaveBeenCalledWith("main", "demo-plugin", "late-session");
  });

  test("a plugin response from an old workspace scope cannot reappear in the current one", async () => {
    const client = new MockWebBotClient();
    const response = deferred<PluginRenderResult>();
    vi.spyOn(client, "openPluginView").mockReturnValue(response.promise);
    const dispose = vi.spyOn(client, "disposePluginViewSession");
    const { result, rerender } = renderHook(
      ({ scopeKey }) => useEditorTabs({ botAlias: "main", client, scopeKey }),
      { initialProps: { scopeKey: "main\nworkspace-a" } },
    );

    let opening!: Promise<void>;
    act(() => {
      opening = result.current.openPluginView(pluginTarget);
    });
    await waitFor(() => expect(client.openPluginView).toHaveBeenCalledTimes(1));
    rerender({ scopeKey: "main\nworkspace-b" });
    await act(async () => {
      response.resolve(pluginSession("old-scope-session"));
      await opening;
    });

    expect(result.current.tabs).toEqual([]);
    expect(dispose).toHaveBeenCalledWith("main", "demo-plugin", "old-scope-session");
  });
});
