import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { TutorialLauncher } from "../tutorial/TutorialLauncher";
import { TUTORIAL_STATE_STORAGE_KEY } from "../tutorial/tutorialProgress";

beforeEach(() => {
  localStorage.clear();
});

it("opens the guide from the logo, owns the keyboard while open and hands the workbench back on Escape", async () => {
  const { container } = render(
    <div className="desktop-workbench-root">
      <TutorialLauncher />
    </div>,
  );
  const workbench = container.querySelector(".desktop-workbench-root") as HTMLElement;
  const logo = screen.getByRole("button", { name: "使用教程" });
  expect(logo).toHaveAttribute("data-tutorial-hint", "true");

  // Declining the prompt only clears the first-run hint.
  fireEvent.click(logo);
  expect(screen.getByRole("heading", { name: "查看使用教程？" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "暂不" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(logo).not.toHaveAttribute("data-tutorial-hint");

  fireEvent.click(logo);
  fireEvent.click(screen.getByRole("button", { name: "查看教程" }));
  const guide = await screen.findByTestId("tutorial-overlay");
  expect(guide).toHaveAttribute("aria-modal", "true");
  expect(workbench).toHaveAttribute("inert");
  expect(within(within(guide).getByRole("list", { name: "教程章节" })).getAllByRole("listitem")).toHaveLength(11);
  expect(within(guide).getByRole("button", { name: /^快速上手/ })).toBeDisabled();

  fireEvent.click(within(guide).getByRole("button", { name: /^对话/ }));
  expect(within(guide).getByRole("button", { name: "发送消息", current: "step" })).toBeInTheDocument();

  // Workbench shortcuts are registered on window in the bubble phase; none may see keys pressed in the guide.
  const workbenchShortcut = vi.fn();
  window.addEventListener("keydown", workbenchShortcut);
  try {
    fireEvent.keyDown(document.body, { key: "p", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(workbenchShortcut).not.toHaveBeenCalled();
    expect(within(guide).getByRole("button", { name: "模型与附件", current: "step" })).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("tutorial-overlay")).not.toBeInTheDocument());
  } finally {
    window.removeEventListener("keydown", workbenchShortcut);
  }
  expect(workbench).not.toHaveAttribute("inert");
  expect(logo).toHaveFocus();
  expect(JSON.parse(localStorage.getItem(TUTORIAL_STATE_STORAGE_KEY) || "{}")).toMatchObject({
    v: 1,
    seen: true,
    chapterId: "chat",
    stepIndex: 1,
    completed: [],
  });

  // The next visit offers to resume where reading stopped.
  fireEvent.click(logo);
  fireEvent.click(screen.getByRole("button", { name: "查看教程" }));
  const reopened = await screen.findByTestId("tutorial-overlay");
  fireEvent.click(within(reopened).getByRole("button", { name: "继续上次阅读 · 对话" }));
  expect(within(reopened).getByRole("button", { name: "模型与附件", current: "step" })).toBeInTheDocument();
});
