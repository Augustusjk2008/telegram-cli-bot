import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { AiCapabilityGuideScreen } from "../screens/AiCapabilityGuideScreen";

test("renders the help-center style guide structure", () => {
  render(<AiCapabilityGuideScreen />);

  expect(screen.getByRole("heading", { name: "智能体协作开发指南" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "提升模型能力" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "总览" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "聊天和会话" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "文件和工作区" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "桌面工作台" })).toBeInTheDocument();

  [
    "把任务讲清",
    "给足上下文",
    "让工具补强判断",
    "分步迭代和验收",
    "聊天",
    "文件",
    "搜索、大纲、Definition",
    "终端",
    "调试面板",
    "Git 工作流",
    "插件管理",
    "Assistant 运维",
    "个人和界面设置",
    "智能体管理",
    "管理中心",
    "公告、通知、Bot 切换器和 LAN Chat",
    "版本更新",
  ].forEach((name) => {
    expect(screen.getAllByRole("heading", { name }).length).toBeGreaterThan(0);
  });

  expect(screen.getByText(/LAN Chat 仅桌面状态栏暴露/)).toBeInTheDocument();
  expect(screen.getByText(/有新公告时登录后自动弹出公告/)).toBeInTheDocument();
  expect(screen.getByText(/通知中心查看聊天完成和系统通知/)).toBeInTheDocument();
  ["入口", "适用场景", "常用操作", "注意事项"].forEach((label) => {
    expect(screen.getAllByText(label).length).toBeGreaterThan(0);
  });
  expect(screen.getAllByText(/cluster 仅 CLI Bot 支持/).length).toBeGreaterThan(0);
  expect(screen.getByText(/仅 assistant Bot、桌面端、admin ops 权限下显示/)).toBeInTheDocument();
  expect(screen.getByText(/最多 1 个 assistant Bot/)).toBeInTheDocument();
  expect(screen.getByText(/访客和只读用户只看到已授权入口/)).toBeInTheDocument();

  expect(screen.getByTestId("ai-capability-guide-screen")).not.toHaveTextContent("小模型");
  expect(document.querySelector("section")?.id).toBe("model-capability");

  const nav = screen.getByRole("navigation", { name: "AI 使用指南目录" });
  [
    ["提升模型能力", "model-capability"],
    ["总览", "overview"],
    ["聊天和会话", "chat"],
    ["子 Agent 和 Cluster", "agents"],
    ["文件和工作区", "workspace"],
    ["桌面工作台", "desktop-workbench"],
    ["终端", "terminal"],
    ["调试", "debug"],
    ["Git", "git"],
    ["插件", "plugins"],
    ["Assistant 运维", "assistant-ops"],
    ["设置", "settings"],
    ["Bot 管理", "bot-management"],
    ["管理中心", "admin-center"],
    ["全局能力", "global"],
    ["更新", "updates"],
  ].forEach(([name, id]) => {
    expect(within(nav).getByRole("link", { name })).toHaveAttribute("href", `#${id}`);
    expect(document.querySelector(`section#${id}`)).not.toBeNull();
  });
});

test("renders embedded guide surface", () => {
  render(<AiCapabilityGuideScreen embedded />);

  expect(screen.getByTestId("ai-capability-guide-screen")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "智能体协作开发指南" })).toBeInTheDocument();
});
