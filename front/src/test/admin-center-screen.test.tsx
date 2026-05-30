import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
import type { WebBotClient } from "../services/webBotClient";
import { MockWebBotClient } from "../services/mockWebBotClient";

function createClient() {
  const client = new MockWebBotClient() as WebBotClient;
  return {
    client,
    listAdminUsers: vi.spyOn(client, "listAdminUsers"),
    listBots: vi.spyOn(client, "listBots"),
    listRegisterCodes: vi.spyOn(client, "listRegisterCodes"),
    getUpdateStatus: vi.spyOn(client, "getUpdateStatus"),
    listOfflineUpdatePackages: vi.spyOn(client, "listOfflineUpdatePackages"),
    upsertAnnouncement: vi.spyOn(client, "upsertAnnouncement"),
    previewEnvConfig: vi.spyOn(client, "previewEnvConfig"),
    updateEnvConfig: vi.spyOn(client, "updateEnvConfig"),
    updateUser: vi.spyOn(client, "updateUser"),
    updateUserBotPermissions: vi.spyOn(client, "updateUserBotPermissions"),
    restartService: vi.spyOn(client, "restartService"),
  };
}

test("admin center lazy-loads and refreshes env tab only when active", async () => {
  const user = userEvent.setup();
  const { client, listAdminUsers, getUpdateStatus, listOfflineUpdatePackages } = createClient();
  const getEnvConfig = vi.spyOn(client, "getEnvConfig");
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await screen.findByRole("heading", { name: "用户权限" });
  expect(getEnvConfig).not.toHaveBeenCalled();

  vi.clearAllMocks();
  await user.click(screen.getByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });

  expect(getEnvConfig).toHaveBeenCalledTimes(1);
  expect(listAdminUsers).not.toHaveBeenCalled();
  expect(getUpdateStatus).not.toHaveBeenCalled();
  expect(listOfflineUpdatePackages).not.toHaveBeenCalled();

  vi.clearAllMocks();
  await user.click(screen.getByRole("button", { name: "刷新" }));

  await waitFor(() => {
    expect(getEnvConfig).toHaveBeenCalledTimes(1);
  });
  expect(listAdminUsers).not.toHaveBeenCalled();
  expect(getUpdateStatus).not.toHaveBeenCalled();
});

test("admin center loads user permissions without waiting for unrelated tabs", async () => {
  const { client, listRegisterCodes, getUpdateStatus, listOfflineUpdatePackages } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });
  listRegisterCodes.mockImplementation(() => new Promise(() => {}));
  getUpdateStatus.mockImplementation(() => new Promise(() => {}));
  listOfflineUpdatePackages.mockImplementation(() => new Promise(() => {}));

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  expect(await screen.findByRole("heading", { name: "用户权限" })).toBeInTheDocument();
  expect(screen.getAllByText("demo").length).toBeGreaterThan(0);
  expect(listRegisterCodes).not.toHaveBeenCalled();
  expect(getUpdateStatus).not.toHaveBeenCalled();
  expect(listOfflineUpdatePackages).not.toHaveBeenCalled();
});

test("admin center updates account capabilities separately from bot grants", async () => {
  const user = userEvent.setup();
  const { client, updateUser, updateUserBotPermissions } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  const terminalCapability = await screen.findByRole("checkbox", { name: "demo 账号能力 终端" });
  await user.click(terminalCapability);

  await waitFor(() => {
    expect(updateUser).toHaveBeenCalledWith("demo", expect.objectContaining({
      capabilities: expect.not.arrayContaining(["terminal_exec"]),
    }));
  });
  expect(updateUserBotPermissions).not.toHaveBeenCalled();

  await user.click(screen.getByRole("checkbox", { name: "demo 可操作 Bot main" }));

  await waitFor(() => {
    expect(updateUserBotPermissions).toHaveBeenCalledWith("demo", expect.not.arrayContaining(["main"]));
  });
});

test("admin center shows macOS update packages", async () => {
  const user = userEvent.setup();
  const { client } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "升级" }));
  expect(await screen.findByText("当前包: Windows 安装版")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /orbit-safe-claw-macos-universal-1\.2\.3\.tar\.gz · macOS/ })).toBeInTheDocument();
});

test("mock client prepares macOS offline update packages", async () => {
  const client = new MockWebBotClient();

  const status = await client.prepareOfflineUpdate(
    ".release-local/artifacts/orbit-safe-claw-macos-universal-1.2.3.tar.gz",
    "1.2.3",
  );

  expect(status.pendingUpdatePackageKind).toBe("macos");
  expect(status.pendingUpdatePlatform).toBe("macos-universal");
});

test("admin center refreshes only active tab", async () => {
  const user = userEvent.setup();
  const { client, listAdminUsers, listRegisterCodes, getUpdateStatus, listOfflineUpdatePackages } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await screen.findByRole("heading", { name: "用户权限" });
  vi.clearAllMocks();

  await user.click(screen.getByRole("button", { name: "刷新" }));

  await waitFor(() => {
    expect(listAdminUsers).toHaveBeenCalledTimes(1);
  });
  expect(listRegisterCodes).not.toHaveBeenCalled();
  expect(getUpdateStatus).not.toHaveBeenCalled();
  expect(listOfflineUpdatePackages).not.toHaveBeenCalled();
});

test("admin center publishes announcements", async () => {
  const user = userEvent.setup();
  const { client, upsertAnnouncement } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(screen.getByRole("tab", { name: "公告" }));
  await screen.findByRole("heading", { name: "发布公告" });
  expect(screen.queryByLabelText("公告 ID")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("公告发布时间")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "发布公告" }));

  await waitFor(() => {
    expect(upsertAnnouncement).toHaveBeenCalledWith(expect.objectContaining({
      publisher: "CLI Bridge",
      title: "管理中心更新",
    }));
  });
});

test("mock client generates announcement ids from publish minute", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-05-18T01:31:42.000Z"));
  try {
    const client = new MockWebBotClient();
    await client.login({ username: "127.0.0.1", password: "test" });

    const first = await client.upsertAnnouncement({
      publisher: "CLI Bridge",
      title: "第一条",
      category: "feature",
      severity: "info",
      summary: "摘要",
      sections: [],
    });
    const second = await client.upsertAnnouncement({
      publisher: "CLI Bridge",
      title: "第二条",
      category: "feature",
      severity: "info",
      summary: "摘要",
      sections: [],
    });

    expect(first.id).toBe("ann-2026-05-18-09-31");
    expect(first.publishedAt).toBe("2026-05-18T09:31:00+08:00");
    expect(second.id).toBe("ann-2026-05-18-09-31-02");
  } finally {
    vi.useRealTimers();
  }
});

test("admin center configures lan chat host mode", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const updateLanChatConfig = vi.spyOn(client, "updateLanChatConfig");

  render(<AdminCenterScreen client={client} onClose={vi.fn()} />);

  await user.click(await screen.findByRole("tab", { name: "联机聊天" }));
  await user.click(screen.getByRole("radio", { name: "作为主机" }));
  await user.clear(screen.getByLabelText("房间名"));
  await user.type(screen.getByLabelText("房间名"), "项目组");
  await user.click(screen.getByRole("button", { name: "保存联机聊天配置" }));

  await waitFor(() => {
    expect(updateLanChatConfig).toHaveBeenCalledWith(expect.objectContaining({
      mode: "host",
      roomName: "项目组",
    }));
  });
  expect(await screen.findByText("联机聊天配置已保存")).toBeInTheDocument();
});

test("admin center edits env config with diff confirmation and restart hint", async () => {
  const user = userEvent.setup();
  const { client, previewEnvConfig, updateEnvConfig } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Web" }));
  await user.clear(screen.getByLabelText("Web 端口"));
  await user.type(screen.getByLabelText("Web 端口"), "9000");
  await user.click(screen.getByRole("button", { name: "预览 diff" }));

  expect(await screen.findByRole("dialog", { name: "环境配置 diff 确认" })).toBeInTheDocument();
  expect(screen.getAllByText("WEB_PORT").length).toBeGreaterThan(0);
  expect(previewEnvConfig).toHaveBeenCalledWith({
    values: {
      WEB_PORT: 9000,
    },
  });

  await user.click(screen.getByRole("button", { name: "确认保存" }));

  await waitFor(() => {
    expect(updateEnvConfig).toHaveBeenCalledWith({
      values: {
        WEB_PORT: 9000,
      },
    });
  });
  expect(await screen.findByText(/需重启: WEB_PORT/)).toBeInTheDocument();
});

test("admin center saves env config on first save click", async () => {
  const user = userEvent.setup();
  const { client, previewEnvConfig, updateEnvConfig } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Web" }));
  await user.clear(screen.getByLabelText("Web 端口"));
  await user.type(screen.getByLabelText("Web 端口"), "9001");
  await user.click(screen.getByRole("button", { name: "保存环境配置" }));

  await waitFor(() => {
    expect(updateEnvConfig).toHaveBeenCalledWith({
      values: {
        WEB_PORT: 9001,
      },
    });
  });
  expect(previewEnvConfig).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog", { name: "环境配置 diff 确认" })).not.toBeInTheDocument();
});

test("admin center masks and clears sensitive env values", async () => {
  const user = userEvent.setup();
  const { client, previewEnvConfig } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "环境配置" }));
  await user.click(await screen.findByRole("button", { name: "Web" }));
  expect(await screen.findByDisplayValue("********")).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "清空" }));
  await user.click(screen.getByRole("button", { name: "预览 diff" }));

  await waitFor(() => {
    expect(previewEnvConfig).toHaveBeenCalledWith({
      values: {
        WEB_API_TOKEN: { action: "clear" },
      },
    });
  });
  expect(screen.getByText("保存后将禁用口令登录。")).toBeInTheDocument();
});

test("admin center shows env tab for admin ops without invite-code permission", async () => {
  const client = new MockWebBotClient();

  render(<AdminCenterScreen client={client} onClose={() => {}} canManageRegisterCodes={false} canManageEnvConfig />);

  expect(await screen.findByRole("tab", { name: "环境配置" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "邀请码" })).not.toBeInTheDocument();
});

test("admin center hides env tab without admin capability flag", async () => {
  const client = new MockWebBotClient();

  render(<AdminCenterScreen client={client} onClose={() => {}} canManageEnvConfig={false} />);

  expect(screen.queryByRole("tab", { name: "环境配置" })).not.toBeInTheDocument();
});
