import { beforeEach, expect, test } from "vitest";
import {
  createStoredTerminalTab,
  readTerminalTabs,
  writeTerminalTabs,
} from "../terminal/terminalStorage";

beforeEach(() => {
  localStorage.clear();
});

test("首次读取会迁移旧的单终端 owner", () => {
  localStorage.setItem("web-terminal-owner-id", "legacy-owner");

  expect(readTerminalTabs()).toEqual([{
    id: "legacy-owner",
    ownerId: "legacy-owner",
    title: "终端 1",
    cwd: "",
    shell: "auto",
  }]);
  expect(localStorage.getItem("web-terminal-tabs:v1")).toContain("legacy-owner");
});

test("多个 tab 保存独立 owner 和工作目录", () => {
  const first = createStoredTerminalTab([], { cwd: "C:/one" });
  const second = createStoredTerminalTab([first], { cwd: "C:/two" });
  writeTerminalTabs([first, second]);

  const restored = readTerminalTabs();
  expect(restored).toEqual([first, second]);
  expect(restored[0].ownerId).not.toBe(restored[1].ownerId);
});

test("关闭全部 tab 后允许恢复为空列表", () => {
  writeTerminalTabs([]);

  expect(readTerminalTabs()).toEqual([]);
});
