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
  };
}

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
