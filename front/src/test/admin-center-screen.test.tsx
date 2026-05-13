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
  await user.click(screen.getByRole("button", { name: "发布公告" }));

  await waitFor(() => {
    expect(upsertAnnouncement).toHaveBeenCalledWith(expect.objectContaining({
      id: "ann-2026-05-13-admin-center",
      title: "管理中心更新",
    }));
  });
});
