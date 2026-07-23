import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import { WorkbenchStatusBar } from "../workbench/WorkbenchStatusBar";

function renderStatusBar(overrides: Partial<ComponentProps<typeof WorkbenchStatusBar>> = {}) {
  return render(
    <WorkbenchStatusBar
      activeFilePath="src/main.py"
      fileDirty={false}
      terminalStatus={{ connected: false, connectionText: "终端未启动", currentCwd: "" }}
      chatStatus={{ state: "idle", processing: false }}
      debugStatus={{ phase: "idle", connectionText: "调试未启动" }}
      restoreState="clean"
      viewMode="desktop"
      {...overrides}
    />,
  );
}

test("workbench status bar shows the active file language service and an install hint", () => {
  renderStatusBar({
    languageServiceProvider: "pyright",
    languageServiceStatus: {
      provider: "pyright",
      status: "missing",
      source: null,
      version: "",
      commandSummary: "pyright-langserver --stdio",
      canInstall: true,
      canUpdate: false,
      message: "未检测到 Pyright",
      error: "未检测到 Pyright",
    },
  });

  const languageService = screen.getByTestId("workbench-language-service");
  expect(languageService).toHaveTextContent("Python · 缺失（可由管理员在设置安装）");
  expect(languageService).toHaveAttribute("data-language-service-status", "missing");
  expect(languageService).toHaveAttribute("title", "未检测到 Pyright");
});

test("workbench status bar reports loading and ready states without an install action", () => {
  const { rerender } = renderStatusBar({
    languageServiceProvider: "typescript",
    languageServiceLoading: true,
  });

  expect(screen.getByTestId("workbench-language-service")).toHaveTextContent("TS/JS · 检测中");

  rerender(
    <WorkbenchStatusBar
      activeFilePath="src/main.ts"
      fileDirty={false}
      terminalStatus={{ connected: false, connectionText: "终端未启动", currentCwd: "" }}
      chatStatus={{ state: "idle", processing: false }}
      debugStatus={{ phase: "idle", connectionText: "调试未启动" }}
      restoreState="clean"
      viewMode="desktop"
      languageServiceProvider="typescript"
      languageServiceStatus={{
        provider: "typescript",
        status: "available",
        source: "path",
        version: "5.8.3",
        commandSummary: "typescript-language-server --stdio",
        canInstall: false,
        canUpdate: false,
        message: "使用 PATH 中的命令",
        error: "",
      }}
    />,
  );

  expect(screen.getByTestId("workbench-language-service")).toHaveTextContent("TS/JS · 就绪");
  expect(screen.queryByRole("button", { name: /安装|更新/ })).not.toBeInTheDocument();
});

test("workbench status bar distinguishes language runtime startup and indexing", () => {
  const { rerender } = renderStatusBar({
    languageServiceProvider: "pyright",
    languageServiceStatus: {
      provider: "pyright",
      status: "available",
      source: "path",
      version: "1.1.410",
      commandSummary: "pyright-langserver --stdio",
      canInstall: false,
      canUpdate: false,
      message: "使用 PATH 中的命令",
      error: "",
      runtimeState: "starting",
      runtimeMessage: "正在初始化工作区",
    },
  });

  expect(screen.getByTestId("workbench-language-service")).toHaveTextContent("Python · 启动中");
  expect(screen.getByTestId("workbench-language-service")).toHaveAttribute("title", "正在初始化工作区");

  rerender(
    <WorkbenchStatusBar
      activeFilePath="src/main.py"
      fileDirty={false}
      terminalStatus={{ connected: false, connectionText: "终端未启动", currentCwd: "" }}
      chatStatus={{ state: "idle", processing: false }}
      debugStatus={{ phase: "idle", connectionText: "调试未启动" }}
      restoreState="clean"
      viewMode="desktop"
      languageServiceProvider="pyright"
      languageServiceStatus={{
        provider: "pyright",
        status: "available",
        source: "path",
        version: "1.1.410",
        commandSummary: "pyright-langserver --stdio",
        canInstall: false,
        canUpdate: false,
        message: "使用 PATH 中的命令",
        error: "",
        runtimeState: "indexing",
        runtimeMessage: "正在索引工作区",
      }}
    />,
  );

  expect(screen.getByTestId("workbench-language-service")).toHaveTextContent("Python · 索引中");
});
