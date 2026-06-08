import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    getNativeAgentConfig: vi.spyOn(client, "getNativeAgentConfig"),
    updateNativeAgentConfig: vi.spyOn(client, "updateNativeAgentConfig"),
    previewEnvConfig: vi.spyOn(client, "previewEnvConfig"),
    updateEnvConfig: vi.spyOn(client, "updateEnvConfig"),
    updateUser: vi.spyOn(client, "updateUser"),
    updateUserBotPermissions: vi.spyOn(client, "updateUserBotPermissions"),
    restartService: vi.spyOn(client, "restartService"),
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







test("admin center can grant unsafe cli capability", async () => {
  const user = userEvent.setup();
  const { client, updateUser } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  const unsafeCliCapability = await screen.findByRole("checkbox", { name: "demo 账号能力 高风险 CLI" });
  await user.click(unsafeCliCapability);

  await waitFor(() => {
    expect(updateUser).toHaveBeenCalledWith("demo", expect.objectContaining({
      capabilities: expect.arrayContaining(["run_unsafe_cli"]),
    }));
  });
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

test("admin center blocks fixed forward and quick tunnel conflict", async () => {
  const user = userEvent.setup();
  const { client, updateEnvConfig } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Tunnel" }));
  const fixedForwardPanel = screen.getByText("固定公网转发").closest("article");
  expect(fixedForwardPanel).not.toBeNull();
  await user.click(within(fixedForwardPanel as HTMLElement).getByRole("checkbox"));

  expect(screen.getByText("固定公网转发和 Cloudflare Quick Tunnel 不能同时启用。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存环境配置" })).toBeDisabled();
  expect(updateEnvConfig).not.toHaveBeenCalled();
});

test("admin center shows fixed forward hub token and frps port fields", async () => {
  const user = userEvent.setup();
  const { client } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "环境配置" }));
  await screen.findByRole("heading", { name: "环境配置" });
  await user.click(screen.getByRole("button", { name: "Tunnel" }));

  expect(screen.getByText("Hub 节点授权码")).toBeInTheDocument();
  expect(screen.getByText("TCB_HUB_NODE_TOKEN")).toBeInTheDocument();
  expect(screen.getByText("Hub frps 端口")).toBeInTheDocument();
  expect(screen.getByText("TCB_HUB_FRPS_PORT")).toBeInTheDocument();
});

test("admin center shows native agent global fields", async () => {
  const user = userEvent.setup();
  const { client, updateNativeAgentConfig } = createClient();
  await client.login({ username: "127.0.0.1", password: "test" });

  render(<AdminCenterScreen client={client} onClose={() => {}} />);

  await user.click(await screen.findByRole("tab", { name: "原生 Agent" }));
  await screen.findByRole("heading", { name: "原生 Agent" });

  expect(screen.getByText(/OpenCode:/)).toBeInTheDocument();
  expect(screen.getByText("jojocode_max / gpt-5.4")).toBeInTheDocument();
  const editor = screen.getByLabelText("原生 Agent 配置 JSON");
  fireEvent.change(editor, { target: { value: JSON.stringify({ provider: {} }) } });
  await user.click(screen.getByRole("button", { name: "保存配置" }));

  await waitFor(() => expect(updateNativeAgentConfig).toHaveBeenCalledWith({ provider: {} }));
  expect(await screen.findByText("配置已保存，重启原生 agent 后生效")).toBeInTheDocument();
});

