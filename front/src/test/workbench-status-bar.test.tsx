import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
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

test("workbench status bar disables restart during runtime restart", () => {
  const restart = vi.fn();
  renderStatusBar({
    languageServiceProvider: "pyright",
    languageServiceStatus: {
      provider: "pyright",
      status: "available",
      source: "path",
      version: "1.1.410",
      commandSummary: "pyright-langserver --stdio",
      canInstall: false,
      canUpdate: false,
      message: "正在重启语言服务",
      error: "",
      runtimeState: "restarting",
    },
    onRestartLanguageService: restart,
  });

  expect(screen.getByRole("button", { name: "重启当前语言服务" })).toBeDisabled();


});

test("workbench status bar restarts only the current language service and exposes failures", () => {
  const restart = vi.fn();
  renderStatusBar({
    languageServiceProvider: "typescript",
    languageServiceStatus: {
      provider: "typescript",
      status: "available",
      source: "path",
      version: "5.8.3",
      commandSummary: "typescript-language-server --stdio",
      canInstall: false,
      canUpdate: false,
      message: "语言服务已就绪",
      error: "",
      runtimeState: "ready",
    },
    onRestartLanguageService: restart,
    languageServiceRestartError: "服务暂时不可用",
  });

  const button = screen.getByRole("button", { name: "重启当前语言服务" });
  fireEvent.click(button);
  expect(restart).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert")).toHaveTextContent("服务暂时不可用");
});

test("workbench status bar disables the restart icon while a restart is pending", () => {
  renderStatusBar({
    languageServiceProvider: "pyright",
    languageServiceRestarting: true,
    onRestartLanguageService: vi.fn(),
  });

  expect(screen.getByRole("button", { name: "重启当前语言服务" })).toBeDisabled();
});
