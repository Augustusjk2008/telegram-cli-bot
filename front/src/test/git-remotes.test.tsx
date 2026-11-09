import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { GitHubAccountPanel } from "../components/GitHubAccountPanel";
import { GitRemotesPanel } from "../components/GitRemotesPanel";
import type { GitCapability, GitHubAccountStatus, GitHubRepository, GitRemoteList } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const available: GitCapability = { available: true, reason: "", requiresConfirmation: false };

const connectedAccount: GitHubAccountStatus = {
  connected: true,
  login: "octocat",
  name: "Mona",
  avatarUrl: "",
  htmlUrl: "https://github.com/octocat",
  authMethod: "device",
  tokenKind: "oauth",
  scopes: ["repo", "read:org"],
  connectedAt: "2026-11-09T00:00:00Z",
  deviceFlowAvailable: true,
  tokenCreateUrl: "https://github.com/settings/tokens/new",
  requiredScopes: ["repo", "read:org"],
};

const disconnectedAccount: GitHubAccountStatus = {
  ...connectedAccount,
  connected: false,
  login: "",
  authMethod: "",
  tokenKind: "",
  scopes: [],
};

function remoteList(overrides: Partial<GitRemoteList> = {}): GitRemoteList {
  return {
    repoFound: true,
    workingDir: "/work/demo",
    repoPath: "/work/demo",
    currentBranch: "main",
    upstream: "",
    hasCommits: true,
    remotes: [],
    githubAccountAuth: true,
    ...overrides,
  };
}

const createdRepository: GitHubRepository = {
  id: 9,
  name: "demo",
  fullName: "acme/demo",
  owner: "acme",
  private: true,
  archived: false,
  description: "",
  htmlUrl: "https://github.com/acme/demo",
  cloneUrl: "https://github.com/acme/demo.git",
  sshUrl: "git@github.com:acme/demo.git",
  defaultBranch: "",
  pushedAt: "",
  canPush: true,
};

const originRemote = {
  name: "origin",
  fetchUrl: "https://github.com/acme/demo.git",
  pushUrl: "https://github.com/acme/demo.git",
  protocol: "https",
  hasEmbeddedCredentials: false,
  github: { owner: "acme", repo: "demo", fullName: "acme/demo", htmlUrl: "https://github.com/acme/demo", protocol: "https" },
};

function renderPanel(client: Partial<WebBotClient>, props: Partial<Parameters<typeof GitRemotesPanel>[0]> = {}) {
  const onRepositoryChanged = vi.fn();
  render(
    <GitRemotesPanel
      botAlias="main"
      client={client as WebBotClient}
      remoteWorkspace={false}
      repoName="demo"
      remotesCapability={available}
      publishCapability={{ ...available, requiresConfirmation: true }}
      disabled={false}
      githubAccount={connectedAccount}
      githubAccountLoading={false}
      githubAccountError=""
      onGitHubAccountChange={vi.fn()}
      onReloadGitHubAccount={vi.fn()}
      onBusyChange={vi.fn()}
      onRepositoryChanged={onRepositoryChanged}
      {...props}
    />,
  );
  return { onRepositoryChanged };
}

test("creates an empty GitHub repository, links it as origin and publishes the branch", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  const linked = remoteList({ remotes: [originRemote] });
  const client = {
    listGitRemotes: vi.fn()
      .mockResolvedValueOnce(remoteList())
      .mockResolvedValue({ ...linked, upstream: "origin/main" }),
    listGitHubOwners: vi.fn(async () => [
      { login: "octocat", type: "user" as const, avatarUrl: "" },
      { login: "acme", type: "org" as const, avatarUrl: "" },
    ]),
    createGitHubRepository: vi.fn(async () => createdRepository),
    addGitRemote: vi.fn(async () => linked),
    publishGitBranch: vi.fn(async () => ({ message: "ok", overview: {} as never })),
  };
  const { onRepositoryChanged } = renderPanel(client);

  expect(await screen.findByText("main 尚未设置 upstream")).toBeInTheDocument();
  // The empty state offers the same action as the header icon.
  const [headerLink, emptyStateLink] = screen.getAllByRole("button", { name: "关联 GitHub 仓库" });
  expect(headerLink).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(emptyStateLink);
  const panel = await screen.findByTestId("git-github-link-panel");
  await waitFor(() => expect(within(panel).getByRole("option", { name: "acme（组织）" })).toBeInTheDocument());
  fireEvent.change(within(panel).getByLabelText("仓库所有者"), { target: { value: "acme" } });
  expect(within(panel).getByLabelText("新仓库名称")).toHaveValue("demo");
  expect(within(panel).getByLabelText("关联的远端名称")).toHaveValue("origin");
  expect(within(panel).getByText("HTTPS 同步自动使用 GitHub 账号 @octocat。")).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "创建并关联" }));

  await waitFor(() => expect(client.publishGitBranch).toHaveBeenCalledWith("main", "origin"));
  expect(confirm.mock.calls[0][0]).toContain("在 GitHub 创建私有仓库 acme/demo");
  expect(confirm.mock.calls[0][0]).toContain("推送分支 main 并设为 upstream");
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(client.createGitHubRepository).toHaveBeenCalledWith({ owner: "acme", name: "demo", description: "", private: true });
  expect(client.addGitRemote).toHaveBeenCalledWith("main", "origin", "https://github.com/acme/demo.git");
  expect(await screen.findByText("已创建并关联 acme/demo 为远端 origin，并发布分支 main")).toBeInTheDocument();
  expect(await screen.findByText("main → origin/main")).toBeInTheDocument();
  expect(onRepositoryChanged).toHaveBeenCalled();
});

test("remote workspaces keep host credentials and confirm before removing a remote", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const client = {
    listGitRemotes: vi.fn(async () => remoteList({ remotes: [originRemote], upstream: "origin/main", githubAccountAuth: false })),
    updateGitRemote: vi.fn(async () => remoteList({ remotes: [{ ...originRemote, fetchUrl: "git@github.com:acme/demo.git", pushUrl: "git@github.com:acme/demo.git", protocol: "ssh" }], githubAccountAuth: false })),
    removeGitRemote: vi.fn(),
  };
  renderPanel(client, { remoteWorkspace: true });

  const row = await screen.findByTestId("git-remote-row-origin");
  expect(within(row).getByText("HTTPS 使用远程主机的 Git 凭据")).toBeInTheDocument();
  expect(within(row).getByText("upstream")).toBeInTheDocument();

  fireEvent.click(within(row).getByRole("button", { name: "移除远端 origin" }));
  expect(confirm.mock.calls[0][0]).toContain("当前分支的 upstream origin/main 也会失效");
  expect(client.removeGitRemote).not.toHaveBeenCalled();

  fireEvent.click(within(row).getByRole("button", { name: "编辑远端 origin" }));
  fireEvent.change(screen.getByLabelText("远端 origin 的新地址"), { target: { value: "git@github.com:acme/demo.git" } });
  fireEvent.click(screen.getByRole("button", { name: "保存远端地址" }));
  await waitFor(() => expect(client.updateGitRemote).toHaveBeenCalledWith("main", "origin", "git@github.com:acme/demo.git"));
  expect(await screen.findByText("SSH 使用远程主机的 SSH 密钥")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "关联 GitHub 仓库" }));
  const sshToggle = within(await screen.findByTestId("git-github-link-panel")).getByRole("button", { name: "SSH" });
  expect(sshToggle).toHaveAttribute("aria-pressed", "true");
});

test("device login shows the code, polls at the GitHub interval and reports the connected account", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const onAccountChange = vi.fn();
  const client = {
    startGitHubDeviceLogin: vi.fn(async () => ({
      flowId: "flow-1",
      userCode: "ABCD-1234",
      verificationUri: "https://github.com/login/device",
      expiresIn: 900,
      interval: 5,
    })),
    pollGitHubDeviceLogin: vi.fn()
      .mockResolvedValueOnce({ status: "pending", interval: 5, expiresIn: 890, account: null })
      .mockResolvedValueOnce({ status: "connected", interval: 5, expiresIn: 0, account: connectedAccount }),
  };
  render(
    <GitHubAccountPanel
      client={client as unknown as WebBotClient}
      account={disconnectedAccount}
      loading={false}
      loadError=""
      onAccountChange={onAccountChange}
      onReload={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "通过浏览器登录 GitHub" }));
  expect(await screen.findByLabelText("GitHub 授权码")).toHaveTextContent("ABCD-1234");
  expect(screen.getByRole("link", { name: "打开 GitHub" })).toHaveAttribute("href", "https://github.com/login/device");

  await vi.advanceTimersByTimeAsync(4_000);
  expect(client.pollGitHubDeviceLogin).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1_000);
  await waitFor(() => expect(client.pollGitHubDeviceLogin).toHaveBeenCalledTimes(1));
  await vi.advanceTimersByTimeAsync(5_000);
  await waitFor(() => expect(onAccountChange).toHaveBeenCalledWith(connectedAccount));
  expect(client.pollGitHubDeviceLogin).toHaveBeenCalledWith("flow-1");
  expect(screen.queryByLabelText("GitHub 授权码")).not.toBeInTheDocument();
});
