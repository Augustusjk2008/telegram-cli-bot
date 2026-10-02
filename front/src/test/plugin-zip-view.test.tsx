import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TreeView } from "../components/plugin-renderers/TreeView";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { TreeNode, TreeWindowPayload } from "../services/types";

async function openZip(client: MockWebBotClient, path = "docs/sample.zip") {
  const view = await client.openPluginView("main", "zip-preview", "archive-tree", { path });
  if (view.renderer !== "tree" || view.mode !== "session") {
    throw new Error("Expected a ZIP tree session");
  }
  return view;
}

function expectShallowDisplayNodes(nodes: TreeNode[]) {
  for (const node of nodes) {
    expect(node.children).toBeUndefined();
    expect(node.actions || []).toEqual([]);
  }
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ZIP mock tree sessions", () => {
  it("opens shallow roots and returns only direct children with unique archive member IDs", async () => {
    const client = new MockWebBotClient();
    const view = await openZip(client);
    expect(view.summary).toMatchObject({
      path: "docs/sample.zip",
      searchable: false,
      emptySearchText: "压缩包为空",
      statsText: expect.any(String),
    });
    expect(view.initialWindow).toEqual({ op: "children", nodeId: null, nodes: view.summary.roots });
    const roots = view.initialWindow.nodes!;
    expectShallowDisplayNodes(roots);
    expect(roots.map((node) => node.id)).toEqual(["dir:docs", "dir:src", "file:0:README.md", "file:1:README.md"]);
    expect(roots.filter((node) => node.label === "README.md")).toHaveLength(2);
    expect(new Set(roots.map((node) => node.id)).size).toBe(roots.length);

    const children = await client.queryPluginViewWindow("main", "zip-preview", view.sessionId, {
      op: "children", nodeId: "dir:docs",
    }) as TreeWindowPayload;
    expect(children).toMatchObject({ op: "children", nodeId: "dir:docs" });
    expect(children.nodes!.map((node) => node.id)).toEqual(["dir:docs/guides", "file:2:docs/readme.txt"]);
    expectShallowDisplayNodes(children.nodes!);

    const deeper = await client.queryPluginViewWindow("main", "zip-preview", view.sessionId, {
      op: "children", nodeId: "dir:docs/guides",
    }) as TreeWindowPayload;
    expect(deeper).toMatchObject({ op: "children", nodeId: "dir:docs/guides" });
    expect(deeper.nodes!.map((node) => node.id)).toEqual(["file:3:docs/guides/setup.txt"]);
    expectShallowDisplayNodes(deeper.nodes!);
    expect(await client.queryPluginViewWindow("main", "zip-preview", view.sessionId, { op: "children", nodeId: null }))
      .toEqual(view.initialWindow);
  });

  it("rejects unsupported operations, unknown directories and unknown or foreign sessions", async () => {
    const client = new MockWebBotClient();
    const view = await openZip(client);
    for (const request of [{}, { op: "search", query: "README" }, { op: "inspect" }, { kind: "children" }]) {
      await expect(client.queryPluginViewWindow("main", "zip-preview", view.sessionId, request))
        .rejects.toThrow("ZIP 视图仅支持 children 请求");
    }
    for (const nodeId of ["", "dir:missing", "dir:../outside", "C:\\workspace\\docs", "file:0:README.md", 1]) {
      await expect(client.queryPluginViewWindow("main", "zip-preview", view.sessionId, { op: "children", nodeId }))
        .rejects.toThrow("ZIP 目录不存在");
    }
    const foreign = await client.openPluginView("main", "rtl-hierarchy", "hierarchy", {});
    if (foreign.mode !== "session") throw new Error("Expected a tree session");
    for (const sessionId of ["zip-session-999", "session-999", "tree-session-999", "timing-session-999", "repo-tree-session-999", foreign.sessionId]) {
      await expect(client.queryPluginViewWindow("main", "zip-preview", sessionId, { op: "children", nodeId: null }))
        .rejects.toThrow("插件会话不存在");
    }
  });

  it("disposes idempotently without resurrection and keeps other ZIP sessions usable", async () => {
    const client = new MockWebBotClient();
    const first = await openZip(client, "first.zip");
    const second = await openZip(client, "second.zip");
    await client.disposePluginViewSession("main", "rtl-hierarchy", second.sessionId);
    await client.disposePluginViewSession("main", "zip-preview", first.sessionId);
    await client.disposePluginViewSession("main", "zip-preview", first.sessionId);
    await client.disposePluginViewSession("main", "zip-preview", "tree-session-999");
    await expect(client.queryPluginViewWindow("main", "zip-preview", first.sessionId, { op: "children", nodeId: null }))
      .rejects.toThrow("插件会话不存在");
    expect(await client.queryPluginViewWindow("main", "zip-preview", second.sessionId, { op: "children", nodeId: null }))
      .toEqual(second.initialWindow);
    const third = await openZip(client, "third.zip");
    const ordinal = (id: string) => Number(id.split("-").at(-1));
    expect(ordinal(second.sessionId)).toBeGreaterThan(ordinal(first.sessionId));
    expect(ordinal(third.sessionId)).toBeGreaterThan(ordinal(second.sessionId));
  });
});

describe("ZIP TreeView", () => {
  it("shows a failed expansion and retries that directory successfully", async () => {
    const user = userEvent.setup();
    const client = new MockWebBotClient();
    const view = await openZip(client);
    const query = vi.spyOn(client, "queryPluginViewWindow").mockRejectedValueOnce(new Error("目录加载失败"));
    render(<TreeView botAlias="main" client={client} view={view} />);

    await user.click(screen.getByRole("button", { name: "展开 docs" }));
    expect(await screen.findByText("目录加载失败")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "readme.txt" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("button", { name: "readme.txt" })).toBeInTheDocument();
    expect(screen.queryByText("目录加载失败")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
    expect(query.mock.calls).toEqual([
      ["main", "zip-preview", view.sessionId, { op: "children", nodeId: "dir:docs" }],
      ["main", "zip-preview", view.sessionId, { op: "children", nodeId: "dir:docs" }],
    ]);
  });
});
