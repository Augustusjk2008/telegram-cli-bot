import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { BotListScreen } from "../screens/BotListScreen";
import { RemoteConnectionForm } from "../components/RemoteConnectionForm";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import { WebApiClientError, type RemoteWorkspace } from "../services/types";
import { PersistentTerminalProvider, usePersistentTerminal } from "../terminal/PersistentTerminalProvider";
import { readTerminalTabs } from "../terminal/terminalStorage";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

const remote: RemoteWorkspace = { connectionId: "ssh-1", host: "linux.test", port: 22, username: "dev", root: "/home/dev", hostKeyFingerprint: "SHA256:abc" };
const wire = { connection_id: "ssh-1", host: "linux.test", port: 22, username: "dev", root: "/srv/project", host_key_fingerprint: "SHA256:abc", key_filename: "C:/keys/id_ed25519" };
const rawBot = { alias: "remote", cli_type: "codex", status: "running", working_dir: "C:/control/remote", remote_workspace: wire };
const ok = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });

beforeEach(() => localStorage.clear());
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("remote create requires explicit host key trust and a chosen directory, without local workingDir or secrets", async () => {
  const client = new MockWebBotClient();
  const connect = vi.spyOn(client, "connectRemote").mockRejectedValueOnce(new WebApiClientError("Unknown host", { code: "remote_host_key_unknown", status: 409, data: { fingerprint: remote.hostKeyFingerprint } })).mockResolvedValue(remote);
  const browse = vi.spyOn(client, "listRemoteDirectories").mockImplementation(async (_id, path) => ({ workingDir: path, entries: [] }));
  const add = vi.spyOn(client, "addBot").mockResolvedValue({ alias: "remote", cliType: "codex", status: "running", workingDir: "C:/control", remoteWorkspace: remote, lastActiveText: "" });
  render(<BotListScreen client={client} onSelect={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("新智能体别名"), { target: { value: "remote" } });
  fireEvent.change(screen.getByLabelText("工作区位置"), { target: { value: "remote" } });
  expect(screen.queryByLabelText("新智能体工作目录")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "创建智能体" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("SSH 主机"), { target: { value: remote.host } });
  fireEvent.change(screen.getByLabelText("SSH 用户名"), { target: { value: remote.username } });
  fireEvent.change(screen.getByLabelText("SSH 密码"), { target: { value: "secret-value" } });
  fireEvent.click(screen.getByRole("button", { name: "测试并连接 SSH" }));
  expect(await screen.findByText("SHA256:abc")).toBeInTheDocument();
  expect(connect).toHaveBeenCalledTimes(1);
  expect(browse).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "信任此主机密钥并连接" }));
  await screen.findByLabelText("远程目录路径");
  expect(connect).toHaveBeenLastCalledWith(expect.objectContaining({ password: "secret-value", hostKeyFingerprint: "SHA256:abc" }), undefined);
  expect(screen.queryByLabelText("SSH 密码")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("远程目录路径"), { target: { value: "/srv/project" } });
  fireEvent.click(screen.getByRole("button", { name: "打开" }));
  await waitFor(() => expect(browse).toHaveBeenLastCalledWith("ssh-1", "/srv/project"));
  await waitFor(() => expect(screen.getByRole("button", { name: "选择此远程工作目录" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "选择此远程工作目录" }));
  fireEvent.click(screen.getByRole("button", { name: "创建智能体" }));
  await waitFor(() => expect(add).toHaveBeenCalledWith(expect.objectContaining({ remoteWorkspace: { connectionId: "ssh-1", root: "/srv/project" }, workingDir: undefined })));
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
  render(<RemoteConnectionForm client={client} botAlias="remote" initial={{ ...remote, keyFilename: "C:/keys/id" }} onConnected={done} />);
  fireEvent.change(screen.getByLabelText("私钥口令（可选）"), { target: { value: "passphrase" } });
  fireEvent.click(screen.getByRole("button", { name: "测试并连接 SSH" }));
  await waitFor(() => expect(done).toHaveBeenCalled());
  expect(connect).toHaveBeenCalledWith(expect.objectContaining({ keyFilename: "C:/keys/id", passphrase: "passphrase" }), "remote");
  expect(screen.getByLabelText("私钥口令（可选）")).toHaveValue("");
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
  expect(screen.getByRole("button", { name: "SSH 重新登录" })).toBeInTheDocument();
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
