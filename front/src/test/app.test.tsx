import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, vi } from "vitest";
import { App } from "../app/App";
import type { ChatMessage } from "../services/types";
import { MockWebBotClient } from "../services/mockWebBotClient";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

test("renders standalone login screen without backend", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Web Bot" })).toBeInTheDocument();
  expect(screen.getByLabelText("访问口令")).toBeInTheDocument();
});

test("shows bottom navigation after entering demo app shell", async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText("访问口令"), "123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("button", { name: "聊天" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "文件" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "设置" })).toBeInTheDocument();
});

test("keeps the waiting state after switching bots away and back", async () => {
  const user = userEvent.setup();
  vi.spyOn(MockWebBotClient.prototype, "sendMessage").mockImplementation(
    async (_botAlias: string, _text: string, _onChunk: (chunk: string) => void): Promise<ChatMessage> =>
      new Promise((resolve) => {
        window.setTimeout(() => {
          resolve({
            id: "assistant-later",
            role: "assistant",
            text: "完成",
            createdAt: new Date().toISOString(),
            state: "done",
          });
        }, 3500);
      }),
  );

  render(<App />);
  await user.type(screen.getByLabelText("访问口令"), "123");
  await user.click(screen.getByRole("button", { name: "登录" }));
  await screen.findByRole("button", { name: "聊天" });

  await user.type(screen.getByPlaceholderText("输入消息"), "继续");
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("已等待 1 秒", {}, { timeout: 2500 })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "main" }));
  await user.click(await screen.findByRole("button", { name: /team2/i }));

  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 1100));
  });

  await user.click(screen.getByRole("button", { name: "team2" }));
  await user.click(await screen.findByRole("button", { name: /main/i }));

  expect(await screen.findByText(/已等待 [1-9]\d* 秒/, {}, { timeout: 1500 })).toBeInTheDocument();
}, 10000);
