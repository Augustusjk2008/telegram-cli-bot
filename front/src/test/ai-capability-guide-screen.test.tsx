import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { AiCapabilityGuideScreen } from "../screens/AiCapabilityGuideScreen";

test("renders AI capability guide content and sources", () => {
  render(<AiCapabilityGuideScreen />);

  expect(screen.getByRole("heading", { name: "欢迎使用面向协作开发的智能体操作系统" })).toBeInTheDocument();
  expect(screen.getByText(/本页面是 AI 协作开发入门指南/)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "新手路径：一次正确协作流程" })).toBeInTheDocument();
  expect(screen.getByText("文件和代码阅读")).toBeInTheDocument();
  expect(screen.getByText("终端和验证")).toBeInTheDocument();
  expect(screen.getByText("Git 和风险复核")).toBeInTheDocument();
  expect(screen.getByText("集群多 agent")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "验收闭环：不要只听完成" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Anthropic Building effective agents/ })).toHaveAttribute(
    "href",
    "https://www.anthropic.com/engineering/building-effective-agents",
  );
});
