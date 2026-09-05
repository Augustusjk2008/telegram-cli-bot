import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { WebApiClientError, type ExternalSourceReadResult } from "../services/types";
import { EditorPane } from "../workbench/EditorPane";
import { useEditorTabs } from "../workbench/useEditorTabs";

function externalSourceResult(overrides: Partial<ExternalSourceReadResult> = {}): ExternalSourceReadResult {
  return {
    sourceId: "source-token-1",
    displayPath: "依赖 / site-packages / package.py",
    content: "def external_symbol():\n    return 1\n",
    encoding: "utf-8",
    languageId: "python",
    ...overrides,
  };
}

test("外部源码标签只读且不会进入工作台草稿持久化", async () => {
  const client = new MockWebBotClient();
  const readExternalSource = vi.spyOn(client, "readExternalSource").mockResolvedValue(externalSourceResult());
  const writeFile = vi.spyOn(client, "writeFile");
  const { result } = renderHook(() => useEditorTabs({ botAlias: "main", client, scopeKey: "account\nworkspace" }));

  await act(async () => {
    expect(await result.current.openExternalSource({
      sourceId: "source-token-1",
      displayPath: "依赖 / site-packages / package.py",
    })).toBe(true);
  });

  expect(readExternalSource).toHaveBeenCalledWith("main", "source-token-1");
  expect(result.current.activeTab).toMatchObject({
    kind: "external-source",
    sourceId: "source-token-1",
    displayPath: "依赖 / site-packages / package.py",
    readOnly: true,
    dirty: false,
    contentPersistence: "none",
  });

  act(() => {
    result.current.updateActiveContent("mutated");
  });
  await act(async () => {
    await result.current.saveActiveTab();
  });

  expect(result.current.activeTab?.content).toBe("def external_symbol():\n    return 1\n");
  expect(writeFile).not.toHaveBeenCalled();
  expect(result.current.buildPersistenceSnapshot()).toEqual([]);
});

test("过期外部源码令牌打开失败并保留只读标签", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "readExternalSource").mockRejectedValue(
    new WebApiClientError("source expired", { status: 410, code: "external_source_expired" }),
  );
  const { result } = renderHook(() => useEditorTabs({ botAlias: "main", client, scopeKey: "account\nworkspace" }));

  await act(async () => {
    expect(await result.current.openExternalSource("expired-source-token")).toBe(false);
  });

  expect(result.current.activeTab).toMatchObject({
    kind: "external-source",
    sourceId: "expired-source-token",
    readOnly: true,
  });
});

test("外部源码标签显示只读标识且不提供文件树定位", () => {
  const tab = {
    path: "external-source:source-token-1",
    basename: "package.py",
    displayPath: "依赖 / site-packages / package.py",
    sourceId: "source-token-1",
    content: "def external_symbol():\n    return 1\n",
    documentVersion: 1,
    savedContent: "def external_symbol():\n    return 1\n",
    kind: "external-source" as const,
    readOnly: true,
    dirty: false,
    loading: false,
    saving: false,
    statusText: "外部依赖 · 只读",
    error: "",
    cold: false,
    missing: false,
    contentPersistence: "none" as const,
  };
  const onRevealInTree = vi.fn();
  render(
    <EditorPane
      botAlias="main"
      client={new MockWebBotClient()}
      tabs={[tab]}
      activeTab={tab}
      activeTabPath={tab.path}
      focused={false}
      onActivateTab={vi.fn()}
      onCloseTab={vi.fn(() => true)}
      onChangeActiveContent={vi.fn()}
      onSaveActiveTab={vi.fn()}
      onCloseAll={vi.fn()}
      onCloseOthers={vi.fn()}
      onCloseTabsToRight={vi.fn()}
      onReopenLastClosed={vi.fn()}
      onRevealInTree={onRevealInTree}
      onToggleFocus={vi.fn()}
    />,
  );

  fireEvent.contextMenu(screen.getByRole("tab", { name: /package\.py/ }));
  expect(screen.queryByRole("button", { name: "在文件树中定位" })).not.toBeInTheDocument();
  expect(onRevealInTree).not.toHaveBeenCalled();
});
