import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { BotListScreen } from "../screens/BotListScreen";
import { RemoteConnectionForm } from "../components/RemoteConnectionForm";
import { RemoteSshMenu } from "../components/RemoteSshMenu";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import { WebApiClientError, type RemoteWorkspace } from "../services/types";
import { PersistentTerminalProvider, usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import { readTerminalTabs } from "../terminal/terminalStorage";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import { RemoteWorkspacePicker } from "../components/RemoteWorkspacePicker";
import { joinRemotePath, normalizeRemotePath, parentRemotePath, relativeRemotePath } from "../services/remoteWorkspace";
import { resolveMarkdownImagePath, resolvePreviewFilePath } from "../utils/fileLinks";
import { useEditorTabs } from "../workbench/useEditorTabs";

const remote: RemoteWorkspace = { connectionId: "ssh-1", host: "linux.test", port: 22, username: "dev", root: "/home/dev", hostKeyFingerprint: "SHA256:abc" };
const wire = { connection_id: "ssh-1", host: "linux.test", port: 22, username: "dev", root: "/srv/project", host_key_fingerprint: "SHA256:abc", key_filename: "C:/keys/id_ed25519" };
const rawBot = { alias: "remote", cli_type: "codex", status: "running", working_dir: "C:/control/remote", remote_workspace: wire };
const windowsRemote: RemoteWorkspace = { ...remote, platform: "windows", host: "windows.test", root: "/C:/Users/dev" };
const ok = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });

beforeEach(() => localStorage.clear());
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test.each([remote, windowsRemote])("remote create on $host requires explicit host key trust and a chosen directory, without local workingDir or secrets", async (target) => {
  const selectedRoot = target.platform === "windows" ? "/D:/Project" : "/srv/project";
  const client = new MockWebBotClient();
  const connect = vi.spyOn(client, "connectRemote").mockRejectedValueOnce(new WebApiClientError("Unknown host", { code: "remote_host_key_unknown", status: 409, data: { fingerprint: target.hostKeyFingerprint } })).mockResolvedValue(target);
  const browse = vi.spyOn(client, "listRemoteDirectories").mockImplementation(async (_id, path) => ({ workingDir: path, entries: [] }));
  const add = vi.spyOn(client, "addBot").mockResolvedValue({ alias: "remote", cliType: "codex", status: "running", workingDir: "C:/control", remoteWorkspace: remote, lastActiveText: "" });
  render(<BotListScreen client={client} onSelect={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("新智能体别名"), { target: { value: "remote" } });
  fireEvent.change(screen.getByLabelText("工作区位置"), { target: { value: "remote" } });
  expect(screen.getByLabelText("目标系统")).toHaveValue("posix");
  if (target.platform) fireEvent.change(screen.getByLabelText("目标系统"), { target: { value: target.platform } });
  expect(screen.queryByLabelText("新智能体工作目录")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建智能体" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("SSH 主机"), { target: { value: target.host } });
  fireEvent.change(screen.getByLabelText("SSH 用户名"), { target: { value: remote.username } });
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "secret-value" } });
  fireEvent.click(screen.getByRole("button", { name: "测试并连接 SSH" }));
  expect(await screen.findByText("SHA256:abc")).toBeInTheDocument();
  expect(connect).toHaveBeenCalledTimes(1);
  expect(browse).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "信任此主机密钥并连接" }));
  await screen.findByLabelText("远程目录路径");
  expect(connect).toHaveBeenLastCalledWith(expect.objectContaining({ platform: target.platform || "posix", password: "secret-value", hostKeyFingerprint: "SHA256:abc" }), undefined);
  expect(screen.queryByLabelText("SSH 密码")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("远程目录路径"), { target: { value: target.platform === "windows" ? "d:\\Project" : selectedRoot } });
  fireEvent.click(screen.getByRole("button", { name: "打开" }));
  await waitFor(() => expect(browse).toHaveBeenLastCalledWith("ssh-1", selectedRoot));
  await waitFor(() => expect(screen.getByRole("button", { name: "选择此远程工作目录" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "选择此远程工作目录" }));
  fireEvent.click(screen.getByRole("button", { name: "创建智能体" }));
  await waitFor(() => expect(add).toHaveBeenCalledWith(expect.objectContaining({ remoteWorkspace: { connectionId: "ssh-1", root: selectedRoot }, workingDir: undefined })));
  expect(JSON.stringify(add.mock.calls)).not.toContain("secret-value");
  expect(JSON.stringify(localStorage)).not.toContain("secret-value");
});

test("maps public remote config and exact wire payloads, preserving local runtime path", async () => {
  const fetch = vi.fn().mockResolvedValue(ok(wire));
  vi.stubGlobal("fetch", fetch);
  const client = new RealWebBotClient();
  expect(await client.connectRemote({ ...remote, keyFilename: "C:/keys/id_ed25519", passphrase: "key-secret" })).toMatchObject({ connectionId: "ssh-1", keyFilename: "C:/keys/id_ed25519" });
  expect(JSON.parse(fetch.mock.lastCall![1].body)).toEqual({ host: "linux.test", port: 22, username: "dev", key_filename: "C:/keys/id_ed25519", passphrase: "key-secret", host_key_fingerprint: "SHA256:abc" });
  await client.connectRemote({ ...remote, password: "temporary" }, "remote/name");
  expect(fetch.mock.lastCall![0]).toBe("/api/bots/remote%2Fname/remote/connect");
  expect(JSON.parse(fetch.mock.lastCall![1].body)).toEqual({ password: "temporary", host_key_fingerprint: "SHA256:abc" });
  await client.disconnectRemote("remote/name");
  expect(fetch.mock.lastCall![0]).toBe("/api/bots/remote%2Fname/remote/disconnect");
  expect(fetch.mock.lastCall![1].method).toBe("POST");
  fetch.mockResolvedValue(ok({ bot: rawBot }));
  const created = await client.addBot({ alias: "remote", cliType: "codex", cliPath: "codex", remoteWorkspace: { connectionId: "ssh-1", root: "/srv/project" } });
  const body = JSON.parse(fetch.mock.lastCall![1].body);
  expect(body.remote_workspace).toEqual({ connection_id: "ssh-1", root: "/srv/project" });
  expect(body).not.toHaveProperty("working_dir");
  expect(created).toMatchObject({ workingDir: "C:/control/remote", remoteWorkspace: { root: "/srv/project", host: "linux.test" } });
  fetch.mockResolvedValue(ok({ bot: rawBot, session: { working_dir: "C:/control/remote", message_count: 0, history_count: 0, is_processing: false } }));
  expect(await client.getBotOverview("remote")).toMatchObject({ remoteWorkspace: created.remoteWorkspace, workingDir: created.workingDir });
  fetch.mockResolvedValue(ok({ working_dir: "/srv/a b", entries: [{ name: "src", is_dir: true }] }));
  expect((await client.listRemoteDirectories("ssh/1", "/srv/a b")).entries[0].isDir).toBe(true);
  expect(fetch.mock.lastCall![0]).toBe("/api/remote/connections/ssh%2F1/directories?path=%2Fsrv%2Fa+b");
  fetch.mockResolvedValue(ok({}));
  await client.createTerminalSession("owner", "/srv/project", "auto", "remote");
  expect(JSON.parse(fetch.mock.lastCall![1].body)).toEqual({ owner_id: "owner", cwd: "/srv/project", shell: "auto", bot_alias: "remote" });
});

test("SSH key login clears passphrase after connecting", async () => {
  const client = new MockWebBotClient();
  const connect = vi.spyOn(client, "connectRemote").mockResolvedValue(remote);
  const done = vi.fn();
  render(<RemoteConnectionForm client={client} botAlias="remote" initial={{ ...windowsRemote, keyFilename: "C:/keys/id" }} onConnected={done} />);
  expect(screen.getByLabelText("目标系统")).toHaveValue("windows");
  expect(screen.getByLabelText("目标系统")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("私钥口令（可选）"), { target: { value: "passphrase" } });
  fireEvent.click(screen.getByRole("button", { name: "测试并连接 SSH" }));
  await waitFor(() => expect(done).toHaveBeenCalled());
  expect(connect).toHaveBeenCalledWith(expect.objectContaining({ keyFilename: "C:/keys/id", passphrase: "passphrase" }), "remote");
  expect(screen.getByLabelText("私钥口令（可选）")).toHaveValue("");
});

test("compact SSH control shows the remote path and disconnects until re-login", async () => {
  const client = new MockWebBotClient();
  const disconnect = vi.spyOn(client, "disconnectRemote").mockResolvedValue();
  const connect = vi.spyOn(client, "connectRemote").mockResolvedValue(remote);
  const onConnected = vi.fn();
  render(<RemoteSshMenu client={client} botAlias="remote" remote={remote} compact onConnected={onConnected} />);
  fireEvent.click(screen.getByRole("button", { name: "SSH 连接" }));
  expect(screen.getByText("dev@linux.test:22")).toBeInTheDocument();
  expect(screen.getByText("/home/dev")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "断开 SSH" }));
  await waitFor(() => expect(disconnect).toHaveBeenCalledWith("remote"));
  expect(screen.getByRole("status")).toHaveTextContent("SSH 已断开");
  expect(screen.getByRole("button", { name: "断开 SSH" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "SSH 重新登录" }));
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "fresh" } });
  fireEvent.click(screen.getByRole("button", { name: "测试并连接 SSH" }));
  await waitFor(() => expect(onConnected).toHaveBeenCalledOnce());
  expect(connect).toHaveBeenCalledWith(expect.objectContaining({ password: "fresh" }), "remote");
  fireEvent.click(screen.getByRole("button", { name: "SSH 连接" }));
  expect(screen.getByRole("button", { name: "断开 SSH" })).toBeEnabled();
});

function TerminalHarness() {
  const terminal = usePersistentTerminal();
  return <><button onClick={() => void terminal.createTab({ cwd: "/srv/project", botAlias: "remote", shell: "auto" })}>SSH tab</button><button onClick={() => void terminal.restartTab(terminal.activeTabId)}>Restart</button></>;
}

test("restored terminal tab reconnects with its remote alias, cwd and owner", async () => {
  const client = new MockWebBotClient();
  const create = vi.spyOn(client, "createTerminalSession");
  localStorage.setItem("web-terminal-tabs:v1", "[]");
  const view = render(<PersistentTerminalProvider client={client}><TerminalHarness /></PersistentTerminalProvider>);
  fireEvent.click(screen.getByText("SSH tab"));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  const tab = readTerminalTabs()[0];
  expect(tab).toMatchObject({ cwd: "/srv/project", botAlias: "remote" });
  view.unmount();
  render(<PersistentTerminalProvider client={client}><TerminalHarness /></PersistentTerminalProvider>);
  fireEvent.click(screen.getByText("Restart"));
  await waitFor(() => expect(create).toHaveBeenLastCalledWith(tab.ownerId, "/srv/project", "auto", "remote"));
  expect(create).toHaveBeenCalledTimes(2);
});

test("shared mobile files screen edits remote text and hides unsupported file actions", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: remote.root, entries: [{ name: "Case\\Name.txt", isDir: false }] });
  const read = vi.spyOn(client, "readFileFull").mockResolvedValue({ mode: "cat", content: "before", isFullContent: true, lastModifiedNs: "123", encoding: "utf-8" });
  const write = vi.spyOn(client, "writeFile").mockResolvedValue({ path: "", fileSizeBytes: 5, lastModifiedNs: "124" });
  render(<FilesScreen client={client} botAlias="remote" remoteWorkspace={remote} />);
  fireEvent.click(await screen.findByRole("button", { name: "更多操作 Case\\Name.txt" }));
  expect(screen.queryByRole("menuitem", { name: /重命名|下载|删除/ })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("上传文件")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("menuitem", { name: "编辑 Case\\Name.txt" }));
  await waitFor(() => expect(read).toHaveBeenCalledWith("remote", "Case\\Name.txt"));
  expect(screen.getByText("before")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "文件内容" }), { target: { value: "after" } });
  // The editor save path retains the remote file's concurrency token.
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(write).toHaveBeenCalledWith("remote", "Case\\Name.txt", "after", "123", "utf-8"));
});

test("read-only remote browsing keeps backslashes inside POSIX directory names", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCurrentPath").mockResolvedValue(remote.root);
  const list = vi.spyOn(client, "listFiles").mockImplementation(async (_alias, path) => ({
    workingDir: path || remote.root,
    entries: path === remote.root ? [{ name: "dir\\name", isDir: true }] : [],
  }));
  render(<FilesScreen client={client} botAlias="remote" remoteWorkspace={remote} structureOnly />);
  fireEvent.click(await screen.findByRole("button", { name: "进入 dir\\name" }));
  await waitFor(() => expect(list).toHaveBeenCalledWith("remote", "/home/dev/dir\\name"));
  fireEvent.click(screen.getByRole("button", { name: "返回上级目录" }));
  await waitFor(() => expect(list).toHaveBeenLastCalledWith("remote", remote.root));
});

test("shared desktop workbench opens remote files without local-only APIs", async () => {
  const client = new MockWebBotClient();
  const entries = [{ name: "README.md", isDir: false }, { name: "Case\\Name.txt", isDir: false }];
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: remote.root, entries });
  vi.spyOn(client, "revealFileTreePath").mockResolvedValue({ rootPath: remote.root, highlightPath: "README.md", expandedPaths: [], branches: { "": entries } });
  const read = vi.spyOn(client, "readFileFull").mockResolvedValue({ mode: "cat", content: "remote text", isFullContent: true, lastModifiedNs: "123", encoding: "utf-8" });
  const create = vi.spyOn(client, "createTextFile").mockResolvedValue({ path: "/home/dev/new.txt", fileSizeBytes: 0, lastModifiedNs: "sha256:new" });
  const resolve = vi.spyOn(client, "resolveFileOpenTarget");
  const git = vi.spyOn(client, "getGitOverview");
  const sync = vi.spyOn(client, "syncWorkspaceDocuments");
  render(<PersistentTerminalProvider client={client}><DesktopWorkbench botAlias="remote" client={client} remoteWorkspace={remote} chatPaneContent={<div>Remote chat</div>} /></PersistentTerminalProvider>);
  expect(screen.getByTestId("desktop-workbench-root")).toBeInTheDocument();
  expect(screen.getByText("Remote chat")).toBeInTheDocument();
  expect(screen.getByTestId("desktop-workbench-root")).toHaveStyle({ gridTemplateRows: "auto minmax(0,1fr) auto" });
  fireEvent.click(screen.getByRole("button", { name: "SSH 连接" }));
  expect(screen.getByRole("button", { name: "SSH 重新登录" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "SSH 连接" }));
  fireEvent.click(await screen.findByRole("button", { name: "打开 README.md" }));
  await waitFor(() => expect(read).toHaveBeenCalledWith("remote", "README.md"));
  const posixFile = await screen.findByRole("button", { name: "打开 Case\\Name.txt" });
  expect(posixFile).toHaveAttribute("title", "/home/dev/Case\\Name.txt");
  fireEvent.click(posixFile);
  await waitFor(() => expect(read).toHaveBeenCalledWith("remote", "Case\\Name.txt"));
  expect(resolve).not.toHaveBeenCalled();
  expect(git).not.toHaveBeenCalled();
  expect(sync).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "搜索" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "新建文件" }));
  fireEvent.change(screen.getByRole("textbox", { name: "文件名" }), { target: { value: "new.txt" } });
  fireEvent.click(screen.getByRole("button", { name: "创建" }));
  await waitFor(() => expect(create).toHaveBeenCalledWith("remote", "new.txt", "", remote.root));
  expect(await screen.findByRole("tab", { name: "new.txt" })).toBeInTheDocument();
});

test("desktop tree preserves a trailing backslash in the remote root", async () => {
  const client = new MockWebBotClient();
  const remoteRoot = { ...remote, root: "/home/dev\\" };
  const list = vi.spyOn(client, "listFiles").mockImplementation(async (_alias, path) => ({
    workingDir: path || remoteRoot.root,
    entries: path === `${remoteRoot.root}/sub` ? [] : [{ name: "sub", isDir: true }],
  }));
  render(<PersistentTerminalProvider client={client}><DesktopWorkbench botAlias="remote" client={client} remoteWorkspace={remoteRoot} chatPaneContent={<div>Remote chat</div>} /></PersistentTerminalProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "展开 sub" }));
  await waitFor(() => expect(list).toHaveBeenCalledWith("remote", `${remoteRoot.root}/sub`, expect.anything()));
});

test("Windows connection payload carries platform only on initial connection and maps returned config", async () => {
  const windowsWire = { ...wire, platform: "windows", root: "/C:/Users/dev" };
  const fetch = vi.fn().mockResolvedValue(ok(windowsWire));
  vi.stubGlobal("fetch", fetch);
  const client = new RealWebBotClient();
  const connected = await client.connectRemote({ host: "windows.test", port: 22, username: "dev", platform: "windows", password: "secret" });
  expect(JSON.parse(fetch.mock.lastCall![1].body)).toEqual({ host: "windows.test", port: 22, username: "dev", platform: "windows", password: "secret" });
  expect(connected).toMatchObject({ platform: "windows", root: windowsRemote.root });
  await client.connectRemote({ ...windowsRemote, password: "again" }, "remote");
  expect(JSON.parse(fetch.mock.lastCall![1].body)).toEqual({ password: "again", host_key_fingerprint: "SHA256:abc" });
  fetch.mockResolvedValue(ok({ bot: { ...rawBot, remote_workspace: windowsWire } }));
  const bot = await client.addBot({ alias: "remote", cliType: "codex", cliPath: "codex", remoteWorkspace: connected });
  expect(JSON.parse(fetch.mock.lastCall![1].body).remote_workspace).toEqual({ connection_id: "ssh-1", root: windowsRemote.root });
  expect(bot.remoteWorkspace?.platform).toBe("windows");
});

test("Windows directory picker stops at drive roots and accepts a different drive", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "connectRemote").mockResolvedValue({ ...windowsRemote, root: "/C:/Users" });
  const browse = vi.spyOn(client, "listRemoteDirectories").mockImplementation(async (_id, path) => ({
    workingDir: path, entries: path === "/D:/" ? [{ name: "Project", isDir: true }] : [],
  }));
  const pick = vi.fn();
  render(<RemoteWorkspacePicker client={client} onPick={pick} />);
  fireEvent.change(screen.getByLabelText("目标系统"), { target: { value: "windows" } });
  fireEvent.change(screen.getByLabelText("SSH 主机"), { target: { value: windowsRemote.host } });
  fireEvent.change(screen.getByLabelText("SSH 用户名"), { target: { value: "dev" } });
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "测试并连接 SSH" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "上级目录" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "上级目录" }));
  await waitFor(() => expect(screen.getByLabelText("远程目录路径")).toHaveValue("/C:/"));
  expect(screen.getByRole("button", { name: "上级目录" })).toBeDisabled();
  for (const path of ["c:", "//C:/Users"]) {
    browse.mockRejectedValueOnce(new Error("Invalid Windows path"));
    fireEvent.change(screen.getByLabelText("远程目录路径"), { target: { value: path } });
    fireEvent.click(screen.getByRole("button", { name: "打开" }));
    await screen.findByText("Invalid Windows path");
    expect(browse).toHaveBeenLastCalledWith("ssh-1", path);
    expect(screen.getByRole("button", { name: "选择此远程工作目录" })).toBeDisabled();
  }
  fireEvent.change(screen.getByLabelText("远程目录路径"), { target: { value: "d:\\" } });
  fireEvent.click(screen.getByRole("button", { name: "打开" }));
  fireEvent.click(await screen.findByRole("button", { name: "📁 Project" }));
  await waitFor(() => expect(screen.getByLabelText("远程目录路径")).toHaveValue("/D:/Project"));
  fireEvent.click(screen.getByRole("button", { name: "选择此远程工作目录" }));
  expect(pick).toHaveBeenCalledWith(expect.objectContaining({ platform: "windows", root: "/D:/Project" }));
  expect(browse.mock.calls.some(([, path]) => path === "/")).toBe(false);
});

test("remote path helpers normalize Windows separators and drive letters while preserving path casing", () => {
  for (const path of ["c:\\Users\\dev\\Code\\Main.ts", "c:/Users/dev/Code/Main.ts", "/c:/Users/dev/Code/Main.ts"]) {
    expect(normalizeRemotePath(path, "windows")).toBe("/C:/Users/dev/Code/Main.ts");
    expect(relativeRemotePath(path, windowsRemote.root, "windows")).toBe("Code/Main.ts");
    expect(relativeRemotePath(path, "/C:/users/DEV", "windows")).toBe("/C:/Users/dev/Code/Main.ts");
    expect(resolvePreviewFilePath(`${path}:12:3`, windowsRemote.root, "windows")).toBe("Code/Main.ts");
  }
  expect(parentRemotePath("c:\\", "windows")).toBe("/C:/");
  expect(parentRemotePath("/C:/Users", "windows")).toBe("/C:/");
  expect(joinRemotePath("/D:/", "Project\\Main.ts", "windows")).toBe("/D:/Project/Main.ts");
  expect(resolvePreviewFilePath("C:\\Main.ts:3", "/C:/", "windows")).toBe("Main.ts");
  expect(resolvePreviewFilePath("D:\\Elsewhere\\Main.ts", windowsRemote.root, "windows")).toBe("/D:/Elsewhere/Main.ts");
  expect(resolvePreviewFilePath("c:\\Users\\DEV\\Main.ts:3", windowsRemote.root, "windows")).toBe("/C:/Users/DEV/Main.ts");
  expect(resolveMarkdownImagePath(".\\Image.png", "C:\\Project\\Doc.md", "windows")).toBe("/C:/Project/./Image.png");
  expect(resolveMarkdownImagePath("d:\\Image.png", "Doc.md", "windows")).toBe("/D:/Image.png");
  expect(joinRemotePath("/home/dev\\", "Case\\Name.txt")).toBe("/home/dev\\/Case\\Name.txt");
  expect(parentRemotePath("/home/dev\\/Case\\Name.txt")).toBe("/home/dev\\");
  expect(resolvePreviewFilePath("/home/dev/Case\\Name.txt:3", remote.root, "posix")).toBe("Case\\Name.txt");
  expect(resolvePreviewFilePath("/HOME/dev/Case.txt", remote.root, "posix")).toBe("/HOME/dev/Case.txt");
  expect(resolveMarkdownImagePath("Image\\Name.png", "Docs\\Notes/Readme.md", "posix")).toBe("Docs\\Notes/Image\\Name.png");
});

test("Windows normalization preserves UNC, device and drive-relative input for backend rejection", () => {
  for (const path of ["C:", "c:Code\\Main.ts", "//C:/Users/dev", "//server/share", "\\\\server\\share", "\\\\?\\C:\\Users\\dev", "\\\\.\\C:\\Users\\dev", "\\??\\C:\\Users\\dev"]) {
    expect(normalizeRemotePath(path, "windows")).toBe(path);
  }
});

test("Windows editor shares slash/drive variants but keeps differently cased files independent", async () => {
  const client = new MockWebBotClient();
  const read = vi.spyOn(client, "readFileFull").mockResolvedValue({ mode: "cat", content: "before", isFullContent: true, lastModifiedNs: "123" });
  const write = vi.spyOn(client, "writeFile").mockResolvedValue({ path: "Code/Main.ts", fileSizeBytes: 5, lastModifiedNs: "124" });
  const { result } = renderHook(() => useEditorTabs({ botAlias: "remote", client, remoteWorkspace: windowsRemote, enableDocumentSync: false }));
  await act(() => result.current.openFile("c:\\Users\\dev\\Code\\Main.ts"));
  act(() => result.current.updateActiveContent("after"));
  await act(() => result.current.openFile("/c:/Users/dev/Code/Main.ts"));
  await act(() => result.current.openFile("Code/Main.ts"));
  expect(result.current.tabs).toHaveLength(1);
  expect(result.current.activeTab).toMatchObject({ path: "Code/Main.ts", content: "after", dirty: true });
  await act(() => result.current.saveActiveTab());
  expect(read).toHaveBeenCalledExactlyOnceWith("remote", "Code/Main.ts");
  expect(write).toHaveBeenCalledWith("remote", "Code/Main.ts", "after", "123", undefined);
  await act(() => result.current.openFile("/C:/Users/dev/Code/main.ts"));
  expect(result.current.tabs).toHaveLength(2);
  expect(result.current.activeTab).toMatchObject({ path: "Code/main.ts", content: "before", dirty: false });
  act(() => result.current.updateActiveContent("second file"));
  await act(() => result.current.saveActiveTab());
  expect(write).toHaveBeenLastCalledWith("remote", "Code/main.ts", "second file", "123", undefined);
  expect(result.current.tabs.find((tab) => tab.path === "Code/Main.ts")?.content).toBe("after");
});

test("Windows desktop tree joins drive roots and returns created files to workspace-relative paths", async () => {
  const client = new MockWebBotClient();
  const target = { ...windowsRemote, root: "/C:/" };
  const list = vi.spyOn(client, "listFiles").mockImplementation(async (_alias, path) => ({
    workingDir: path || target.root,
    entries: path === "/C:/Code" ? [] : [{ name: "Main.ts", isDir: false }, { name: "Code", isDir: true }],
  }));
  vi.spyOn(client, "createTextFile").mockResolvedValue({ path: "c:\\New.txt", fileSizeBytes: 0, lastModifiedNs: "123" });
  render(<PersistentTerminalProvider client={client}><DesktopWorkbench botAlias="remote" client={client} remoteWorkspace={target} /></PersistentTerminalProvider>);
  expect(await screen.findByRole("button", { name: "打开 Main.ts" })).toHaveAttribute("title", "/C:/Main.ts");
  fireEvent.click(await screen.findByRole("button", { name: "展开 Code" }));
  await waitFor(() => expect(list).toHaveBeenCalledWith("remote", "/C:/Code", expect.anything()));
  fireEvent.click(screen.getByRole("button", { name: "新建文件" }));
  fireEvent.change(screen.getByRole("textbox", { name: "文件名" }), { target: { value: "New.txt" } });
  fireEvent.click(screen.getByRole("button", { name: "创建" }));
  expect(await screen.findByRole("tab", { name: "New.txt" })).toBeInTheDocument();
});
