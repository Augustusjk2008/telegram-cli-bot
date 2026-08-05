import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App, sortBotsForSwitcher } from "../app/App";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotSummary } from "../services/types";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

test("bot switcher keeps main first and sorts idle running bots by latest answer", () => {
  const bot = (alias: string, lastAnswerCompletedAt: string): BotSummary => ({
    alias,
    cliType: "codex",
    status: "running",
    activityStatus: "idle",
    workingDir: `C:\\workspace\\${alias}`,
    lastActiveText: "运行中",
    lastAnswerCompletedAt,
  });

  expect(sortBotsForSwitcher([
    bot("zeta", "2026-07-20T08:00:00Z"),
    bot("main", "2026-07-19T08:00:00Z"),
    bot("alpha", "2026-07-20T09:00:00Z"),
  ]).map(({ alias }) => alias)).toEqual(["main", "alpha", "zeta"]);
});

test("guest session exposes browsing but withholds member and admin entry points", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(screen.getByRole("button", { name: "以 guest 进入" }));

  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "设置" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "main" }));
  expect(await screen.findByRole("dialog", { name: "智能体切换" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "智能体管理" })).not.toBeInTheDocument();
});

test("without unsafe CLI permission, create form disables bypass and submits false", async () => {
  const user = userEvent.setup();
  const originalLogin = MockWebBotClient.prototype.login;
  const addBot = vi.spyOn(MockWebBotClient.prototype, "addBot");
  vi.spyOn(MockWebBotClient.prototype, "login").mockImplementation(
    async function (this: MockWebBotClient, input: { username: string; password: string } | string) {
      const session = await originalLogin.call(this, input);
      return {
        ...session,
        capabilities: session.capabilities.filter((capability) => capability !== "admin_ops" && capability !== "run_unsafe_cli"),
      };
    },
  );
  render(<App />);

  await user.type(screen.getByLabelText("访问口令"), "member");
  await user.type(screen.getByLabelText("密码"), "password");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await user.click(await screen.findByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: "智能体管理" }));

  const bypassToggle = await screen.findByLabelText("新智能体默认绕过审批和沙箱");
  expect(bypassToggle).toBeDisabled();
  expect(bypassToggle).not.toBeChecked();

  await user.type(screen.getByLabelText("新智能体别名"), "no-unsafe");
  await user.type(screen.getByLabelText("新智能体工作目录"), "C:\\workspace\\no-unsafe");
  await user.click(screen.getByRole("button", { name: "创建智能体" }));

  await waitFor(() => expect(addBot).toHaveBeenCalledWith(expect.objectContaining({
    alias: "no-unsafe",
    bypassApprovalAndSandbox: false,
  })));
});
