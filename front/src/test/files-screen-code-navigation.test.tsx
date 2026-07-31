import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import * as filesScreen from "../screens/FilesScreen";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";

function navigationItem(path: string, line: number, column: number) {
  return {
    targetType: "workspace" as const,
    path,
    provider: "test-semantic",
    range: {
      start: { line, column: 1 },
      end: { line, column: 20 },
    },
    selectionRange: {
      start: { line, column },
      end: { line, column: column + 6 },
    },
  };
}

async function openMobileEditor(user: ReturnType<typeof userEvent.setup>, client: MockWebBotClient) {
  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "进入 src" }));
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  editor.focus();
  editor.setSelectionRange(2, 2);
  return editor;
}

async function requestDefinition(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "编辑器操作" }));
  await user.click(screen.getByRole("menuitem", { name: "转到定义" }));
}

async function requestImplementation(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "编辑器操作" }));
  const implementation = screen.getByRole("menuitem", { name: "转到实现" });
  await waitFor(() => expect(implementation).toBeEnabled());
  await user.click(implementation);
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function fullFile(content: string) {
  return {
    content,
    mode: "cat" as const,
    isFullContent: true,
    lastModifiedNs: "1",
  };
}

function createRootScopedClient() {
  const client = new MockWebBotClient();
  let cwd = "/workspace-a";
  const listFiles = vi.spyOn(client, "listFiles").mockImplementation(async () => ({
    workingDir: cwd,
    entries: cwd === "/workspace-a"
      ? [{ name: "next", isDir: true }, { name: "server.ts", isDir: false }]
      : [{ name: "server.ts", isDir: false }],
  }));
  const changeDirectory = vi.spyOn(client, "changeDirectory").mockImplementation(async (_alias, path) => {
    if (cwd === "/workspace-a" && path === "next") {
      cwd = "/workspace-b";
      return cwd;
    }
    throw new Error(`不支持的目录切换: ${cwd} -> ${path}`);
  });
  vi.spyOn(client, "readFileFull").mockImplementation(async (_alias, path) => fullFile(`${cwd}/${path}`));
  return { client, listFiles, changeDirectory, getCwd: () => cwd };
}

test("mobile files editor exposes semantic navigation and applies the exact reveal position", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [navigationItem("server.ts", 1, 6)],
  }));

  const editor = await openMobileEditor(user, client);
  await requestDefinition(user);

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledWith(
    "main",
    expect.objectContaining({
      kind: "definition",
      document: expect.objectContaining({
        path: "server.ts",
        languageId: "typescript",
        content: expect.stringContaining("Mock full content for server.ts"),
      }),
      position: { line: 1, column: 3 },
    }),
    expect.anything(),
  ));
  await waitFor(() => {
    expect(editor.selectionStart).toBe(5);
    expect(editor.selectionEnd).toBe(5);
    expect(editor).toHaveFocus();
  });
});

test("mobile files editor enables implementation navigation when TypeScript reports the capability", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [],
  }));

  await openMobileEditor(user, client);
  await requestImplementation(user);

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledWith(
    "main",
    expect.objectContaining({
      kind: "implementation",
      document: expect.objectContaining({
        path: "server.ts",
        languageId: "typescript",
      }),
    }),
    expect.anything(),
  ));
});

test("mobile files editor shows multiple semantic destinations and an empty-result message", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  let invocation = 0;
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    invocation += 1;
    return {
      requestId: request.requestId,
      message: "",
      items: invocation === 1
        ? [
          navigationItem("pkg/one.py", 3, 5),
          navigationItem("pkg/two.py", 8, 2),
        ]
        : [],
    };
  });

  await openMobileEditor(user, client);
  await requestDefinition(user);

  const dialog = await screen.findByRole("dialog", { name: "代码跳转" });
  expect(dialog).toHaveTextContent("pkg/one.py");
  expect(dialog).toHaveTextContent("pkg/two.py");
  await user.click(screen.getByRole("button", { name: "关闭代码跳转" }));

  await requestDefinition(user);

  expect(await screen.findByRole("dialog", { name: "代码跳转" })).toHaveTextContent("未找到语义定义");
});

test("mobile files editor cancels a superseded navigation request without showing an error", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const signals: AbortSignal[] = [];
  let invocation = 0;
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation((_alias, request, signal) => {
    invocation += 1;
    if (signal) {
      signals.push(signal);
    }
    if (invocation === 1) {
      return new Promise((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new DOMException("请求已取消", "AbortError"));
        }, { once: true });
      });
    }
    return Promise.resolve({
      requestId: request.requestId,
      message: "",
      items: [],
    });
  });

  await openMobileEditor(user, client);
  await requestDefinition(user);
  await requestDefinition(user);

  await waitFor(() => expect(signals[0]?.aborted).toBe(true));
  expect(await screen.findByRole("dialog", { name: "代码跳转" })).toHaveTextContent("未找到语义定义");
  expect(screen.queryByText("代码导航失败")).not.toBeInTheDocument();
});

test("mobile files editor preserves a document version after returning to a path", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const cachedDocuments = new Map<string, { version: number; content: string }>();
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    const previous = cachedDocuments.get(request.document.path);
    if (previous && request.document.version < previous.version) {
      throw new Error(`文档版本回退: ${request.document.path} ${request.document.version} < ${previous.version}`);
    }
    if (previous && request.document.version === previous.version && request.document.content !== previous.content) {
      throw new Error(`同版本文档内容不一致: ${request.document.path}`);
    }
    cachedDocuments.set(request.document.path, {
      version: request.document.version,
      content: request.document.content,
    });
    return {
      requestId: request.requestId,
      message: "",
      items: [navigationItem(request.document.path === "server.ts" ? "client.ts" : "server.ts", 1, 1)],
    };
  });

  const editor = await openMobileEditor(user, client);
  const originalContent = editor.value;
  fireEvent.change(editor, { target: { value: `${originalContent}\nconst changed = true;` } });
  fireEvent.change(editor, { target: { value: originalContent } });

  await requestDefinition(user);
  await screen.findByRole("heading", { name: "client.ts" });
  await requestDefinition(user);
  await screen.findByRole("heading", { name: "server.ts" });
  await requestDefinition(user);

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledTimes(3));
  const serverRequests = resolveCodeNavigation.mock.calls
    .map(([, request]) => request.document)
    .filter((document) => document.path === "server.ts");
  expect(serverRequests).toEqual([
    expect.objectContaining({ version: 3, content: originalContent }),
    expect.objectContaining({ version: 3, content: originalContent }),
  ]);
  expect(await screen.findByRole("heading", { name: "client.ts" })).toBeInTheDocument();
});

test("mobile files editor closes old-cwd documents before entering another directory", async () => {
  const user = userEvent.setup();
  const { client, changeDirectory, getCwd } = createRootScopedClient();
  const operationOrder: string[] = [];
  const closeRoots: string[] = [];
  const navigationRequests: Array<{ path: string; version: number }> = [];
  const originalChangeDirectory = changeDirectory.getMockImplementation();
  changeDirectory.mockImplementation(async (alias, path) => {
    operationOrder.push("change-directory");
    return originalChangeDirectory!(alias, path);
  });
  const closeWorkspaceDocuments = vi.spyOn(client, "closeWorkspaceDocuments").mockImplementation(async (_alias, input) => {
    operationOrder.push("close-documents");
    closeRoots.push(getCwd());
    return { closed: input.documents.length };
  });
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    navigationRequests.push({ path: request.document.path, version: request.document.version });
    return { requestId: request.requestId, message: "", items: [] };
  });
  vi.spyOn(client, "writeFile").mockResolvedValue({ path: "server.ts", fileSizeBytes: 1, lastModifiedNs: "2" });

  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  fireEvent.change(editor, { target: { value: `${editor.value}\nconst changed = true;` } });
  editor.focus();
  editor.setSelectionRange(2, 2);
  await requestDefinition(user);
  await waitFor(() => expect(navigationRequests).toEqual([{ path: "server.ts", version: 2 }]));
  await user.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByText("已保存");

  await user.click(screen.getByRole("button", { name: "返回" }));
  await user.click(screen.getByRole("button", { name: "进入 next" }));

  await waitFor(() => expect(changeDirectory).toHaveBeenCalledWith("main", "next"));
  expect(closeWorkspaceDocuments).toHaveBeenCalledWith("main", {
    documents: [{ path: "server.ts", version: 2 }],
  });
  expect(closeRoots).toEqual(["/workspace-a"]);
  expect(operationOrder).toEqual(["close-documents", "change-directory"]);

  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const nextEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  nextEditor.focus();
  nextEditor.setSelectionRange(2, 2);
  await requestDefinition(user);

  await waitFor(() => expect(navigationRequests).toEqual([
    { path: "server.ts", version: 2 },
    { path: "server.ts", version: 1 },
  ]));
});

test("mobile files editor keeps the old-cwd ledger when a directory close fails", async () => {
  const user = userEvent.setup();
  const { client, changeDirectory } = createRootScopedClient();
  let closeAttempts = 0;
  const closeWorkspaceDocuments = vi.spyOn(client, "closeWorkspaceDocuments").mockImplementation(async (_alias, input) => {
    closeAttempts += 1;
    if (closeAttempts === 1) {
      throw new Error("关闭服务不可用");
    }
    return { closed: input.documents.length };
  });
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [],
  }));
  vi.spyOn(client, "writeFile").mockResolvedValue({ path: "server.ts", fileSizeBytes: 1, lastModifiedNs: "2" });

  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  fireEvent.change(editor, { target: { value: `${editor.value}\nconst changed = true;` } });
  editor.focus();
  editor.setSelectionRange(2, 2);
  await requestDefinition(user);
  await user.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByText("已保存");
  await user.click(screen.getByRole("button", { name: "返回" }));

  await user.click(screen.getByRole("button", { name: "进入 next" }));

  expect(changeDirectory).not.toHaveBeenCalled();
  expect(await screen.findByText(/关闭代码导航文档失败/)).toHaveTextContent("关闭服务不可用");
  expect(closeWorkspaceDocuments).toHaveBeenLastCalledWith("main", {
    documents: [{ path: "server.ts", version: 2 }],
  });

  await user.click(screen.getByRole("button", { name: "进入 next" }));

  await waitFor(() => expect(changeDirectory).toHaveBeenCalledWith("main", "next"));
  expect(closeWorkspaceDocuments).toHaveBeenCalledTimes(2);
  expect(closeWorkspaceDocuments).toHaveBeenLastCalledWith("main", {
    documents: [{ path: "server.ts", version: 2 }],
  });
});

test("workspace document closes are split into batches of at most 64", async () => {
  type CloseInBatches = (
    client: Pick<MockWebBotClient, "closeWorkspaceDocuments">,
    botAlias: string,
    documents: Array<{ path: string; version?: number }>,
  ) => Promise<void>;
  const closeInBatches = (filesScreen as unknown as {
    closeWorkspaceDocumentsInBatches?: CloseInBatches;
  }).closeWorkspaceDocumentsInBatches;
  expect(closeInBatches).toEqual(expect.any(Function));
  if (!closeInBatches) {
    return;
  }

  const client = new MockWebBotClient();
  const closeWorkspaceDocuments = vi.spyOn(client, "closeWorkspaceDocuments").mockImplementation(async (_alias, input) => ({
    closed: input.documents.length,
  }));
  const documents = Array.from({ length: 65 }, (_, index) => ({
    path: `file-${index + 1}.ts`,
    version: index + 1,
  }));

  await closeInBatches(client, "main", documents);

  expect(closeWorkspaceDocuments).toHaveBeenCalledTimes(2);
  expect(closeWorkspaceDocuments.mock.calls.map(([, input]) => input.documents)).toEqual([
    documents.slice(0, 64),
    documents.slice(64),
  ]);
});

test("mobile files editor waits for an unmount close before reopening the same document", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const cachedDocuments = new Map<string, { version: number; content: string }>();
  const closeGate = createDeferred<void>();
  let closeCalls = 0;
  const closeWorkspaceDocuments = vi.spyOn(client, "closeWorkspaceDocuments").mockImplementation(async (_alias, input) => {
    closeCalls += 1;
    if (closeCalls === 1) {
      await closeGate.promise;
    }
    input.documents.forEach((document) => cachedDocuments.delete(document.path));
    return { closed: input.documents.length };
  });
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    const previous = cachedDocuments.get(request.document.path);
    if (previous && request.document.version < previous.version) {
      throw new Error(`文档版本回退: ${request.document.path} ${request.document.version} < ${previous.version}`);
    }
    if (previous && request.document.version === previous.version && request.document.content !== previous.content) {
      throw new Error(`同版本文档内容不一致: ${request.document.path}`);
    }
    cachedDocuments.set(request.document.path, {
      version: request.document.version,
      content: request.document.content,
    });
    return { requestId: request.requestId, message: "", items: [] };
  });

  const firstScreen = render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "进入 src" }));
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const firstEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  const originalContent = firstEditor.value;
  fireEvent.change(firstEditor, { target: { value: `${firstEditor.value}\nconst changed = true;` } });
  firstEditor.focus();
  firstEditor.setSelectionRange(2, 2);
  await requestDefinition(user);
  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledTimes(1));

  firstScreen.unmount();

  await waitFor(() => expect(closeWorkspaceDocuments).toHaveBeenCalledWith("main", {
    documents: [{ path: "server.ts", version: 2 }],
  }));

  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const secondEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  secondEditor.focus();
  secondEditor.setSelectionRange(2, 2);
  await requestDefinition(user);

  await Promise.resolve();
  expect(resolveCodeNavigation).toHaveBeenCalledTimes(1);
  closeGate.resolve();

  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledTimes(2));
  expect(resolveCodeNavigation.mock.calls[1]?.[1].document).toMatchObject({
    path: "server.ts",
    version: 3,
    content: originalContent,
  });
  expect(screen.queryByText(/文档版本回退|同版本文档内容不一致/)).not.toBeInTheDocument();
});

test("mobile files editor does not reopen a stale navigation target after returning", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const originalReadFileFull = client.readFileFull.bind(client);
  const targetRead = createDeferred<Awaited<ReturnType<typeof client.readFileFull>>>();
  const readFileFull = vi.spyOn(client, "readFileFull").mockImplementation(async (alias, path) => {
    if (path === "client.ts") {
      return targetRead.promise;
    }
    return originalReadFileFull(alias, path);
  });
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [navigationItem("client.ts", 1, 1)],
  }));

  await openMobileEditor(user, client);
  await requestDefinition(user);
  await waitFor(() => expect(readFileFull).toHaveBeenCalledWith("main", "client.ts"));

  await user.click(screen.getByRole("button", { name: "返回" }));
  await act(async () => {
    targetRead.resolve(await originalReadFileFull("main", "client.ts"));
    await Promise.resolve();
  });

  expect(screen.queryByRole("heading", { name: "client.ts" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "编辑 server.ts" })).toBeInTheDocument();
});

test("mobile files editor closes the old URI before a reachable rename and starts the new URI at v1", async () => {
  const user = userEvent.setup();
  const { client, listFiles } = createRootScopedClient();
  let renamed = false;
  listFiles.mockImplementation(async () => ({
    workingDir: "/workspace-a",
    entries: [{ name: "next", isDir: true }, { name: renamed ? "renamed.ts" : "server.ts", isDir: false }],
  }));
  const operationOrder: string[] = [];
  const navigationRequests: Array<{ path: string; version: number }> = [];
  const closeWorkspaceDocuments = vi.spyOn(client, "closeWorkspaceDocuments").mockImplementation(async (_alias, input) => {
    operationOrder.push("close-documents");
    return { closed: input.documents.length };
  });
  const renamePath = vi.spyOn(client, "renamePath").mockImplementation(async (_alias, path, name) => {
    operationOrder.push("rename-path");
    renamed = true;
    return { oldPath: path, path: name };
  });
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    navigationRequests.push({ path: request.document.path, version: request.document.version });
    return { requestId: request.requestId, message: "", items: [] };
  });
  vi.spyOn(client, "writeFile").mockResolvedValue({ path: "server.ts", fileSizeBytes: 1, lastModifiedNs: "2" });

  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const editor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  fireEvent.change(editor, { target: { value: `${editor.value}\nconst changed = true;` } });
  editor.focus();
  editor.setSelectionRange(2, 2);
  await requestDefinition(user);
  await user.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByText("已保存");
  await user.click(screen.getByRole("button", { name: "返回" }));

  await user.click(screen.getByRole("button", { name: "重命名 server.ts" }));
  const renameDialog = await screen.findByRole("dialog", { name: "重命名文件" });
  const input = renameDialog.querySelector("input") as HTMLInputElement;
  await user.clear(input);
  await user.type(input, "renamed.ts");
  await user.click(screen.getByRole("button", { name: "重命名" }));

  await waitFor(() => expect(renamePath).toHaveBeenCalledWith("main", "server.ts", "renamed.ts"));
  expect(closeWorkspaceDocuments).toHaveBeenCalledWith("main", {
    documents: [{ path: "server.ts", version: 2 }],
  });
  expect(operationOrder.indexOf("close-documents")).toBeLessThan(operationOrder.indexOf("rename-path"));

  await user.click(await screen.findByRole("button", { name: "编辑 renamed.ts" }));
  const renamedEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  renamedEditor.focus();
  renamedEditor.setSelectionRange(2, 2);
  await requestDefinition(user);

  await waitFor(() => expect(navigationRequests).toEqual([
    { path: "server.ts", version: 2 },
    { path: "renamed.ts", version: 1 },
  ]));
});

test("mobile files editor blocks a rename when closing its old URI fails", async () => {
  const user = userEvent.setup();
  const { client } = createRootScopedClient();
  const renamePath = vi.spyOn(client, "renamePath").mockResolvedValue({ oldPath: "server.ts", path: "renamed.ts" });
  vi.spyOn(client, "closeWorkspaceDocuments").mockRejectedValue(new Error("关闭服务不可用"));
  vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => ({
    requestId: request.requestId,
    message: "",
    items: [],
  }));

  render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  await requestDefinition(user);
  await user.click(screen.getByRole("button", { name: "返回" }));
  await user.click(screen.getByRole("button", { name: "重命名 server.ts" }));
  const renameDialog = await screen.findByRole("dialog", { name: "重命名文件" });
  const input = renameDialog.querySelector("input") as HTMLInputElement;
  await user.clear(input);
  await user.type(input, "renamed.ts");
  await user.click(screen.getByRole("button", { name: "重命名" }));

  expect(renamePath).not.toHaveBeenCalled();
  expect(await screen.findByText(/关闭重命名前的代码导航文档失败/)).toHaveTextContent("关闭服务不可用");
});

test("mobile files editor keeps the old client ledger through a rapid bot switch", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const replacementClient = new MockWebBotClient();
  const cachedDocuments = new Map<string, { version: number; content: string }>();
  const closeGate = createDeferred<void>();
  const closeWorkspaceDocuments = vi.spyOn(client, "closeWorkspaceDocuments").mockImplementation(async (_alias, input) => {
    await closeGate.promise;
    input.documents.forEach((document) => cachedDocuments.delete(document.path));
    return { closed: input.documents.length };
  });
  const resolveCodeNavigation = vi.spyOn(client, "resolveCodeNavigation").mockImplementation(async (_alias, request) => {
    const previous = cachedDocuments.get(request.document.path);
    if (previous && request.document.version < previous.version) {
      throw new Error(`文档版本回退: ${request.document.path} ${request.document.version} < ${previous.version}`);
    }
    if (previous && request.document.version === previous.version && request.document.content !== previous.content) {
      throw new Error(`同版本文档内容不一致: ${request.document.path}`);
    }
    cachedDocuments.set(request.document.path, {
      version: request.document.version,
      content: request.document.content,
    });
    return { requestId: request.requestId, message: "", items: [] };
  });

  const view = render(<FilesScreen botAlias="main" client={client} />);
  await user.click(await screen.findByRole("button", { name: "进入 src" }));
  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const firstEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  fireEvent.change(firstEditor, { target: { value: `${firstEditor.value}\nconst changed = true;` } });
  firstEditor.focus();
  firstEditor.setSelectionRange(2, 2);
  await requestDefinition(user);
  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledTimes(1));
  await user.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByText("已保存");
  await user.click(screen.getByRole("button", { name: "返回" }));

  view.rerender(<FilesScreen botAlias="team2" client={replacementClient} />);
  await waitFor(() => expect(closeWorkspaceDocuments).toHaveBeenCalledWith("main", {
    documents: [{ path: "server.ts", version: 2 }],
  }));
  view.rerender(<FilesScreen botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "编辑 server.ts" }));
  const secondEditor = await screen.findByRole("textbox", { name: "文件内容" }) as HTMLTextAreaElement;
  secondEditor.focus();
  secondEditor.setSelectionRange(2, 2);
  await requestDefinition(user);

  await Promise.resolve();
  expect(resolveCodeNavigation).toHaveBeenCalledTimes(1);
  closeGate.resolve();
  await waitFor(() => expect(resolveCodeNavigation).toHaveBeenCalledTimes(2));
  expect(resolveCodeNavigation.mock.calls[1]?.[1].document).toMatchObject({
    path: "server.ts",
    version: 2,
    content: firstEditor.value,
  });
});
