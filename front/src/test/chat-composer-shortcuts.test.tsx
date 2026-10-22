import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatComposer } from "../components/ChatComposer";

function renderComposer({
  enterToSend = true,
}: {
  enterToSend?: boolean;
} = {}) {
  const onSend = vi.fn();
  render(
    <ChatComposer
      onSend={onSend}
      onAttachFiles={() => undefined}
      onRemoveAttachment={() => undefined}
      attachments={[]}
      enterToSend={enterToSend}
    />,
  );
  return {
    input: screen.getByPlaceholderText("输入消息"),
    onSend,
  };
}

describe("ChatComposer send shortcuts", () => {
  it("closes presets with Escape and returns focus without changing the draft", async () => {
    const user = userEvent.setup();
    render(<ChatComposer onSend={vi.fn()} onRemoveAttachment={vi.fn()} attachments={[]} promptPresets={[{ id: "review", title: "检查改动", content: "检查当前改动" }]} />);
    const input = screen.getByPlaceholderText("输入消息");
    await user.type(input, "保留草稿");
    const trigger = screen.getByRole("button", { name: "打开提示词预设" });
    await user.click(trigger);
    await user.tab();
    expect(screen.getByRole("listbox", { name: "提示词预设" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox", { name: "提示词预设" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(input).toHaveValue("保留草稿");
    await user.click(trigger);
    await user.click(input);
    expect(screen.queryByRole("listbox", { name: "提示词预设" })).not.toBeInTheDocument();
  });

  it("sends with Enter when Enter-to-send is enabled", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer();

    await user.type(input, "运行测试");
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("运行测试");
    expect(input).toHaveValue("");
  });

  it("inserts a newline with Shift+Enter without sending", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer();

    await user.type(input, "第一行");
    await user.keyboard("{Shift>}{Enter}{/Shift}");

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("第一行\n");
  });

  it("keeps Enter as a newline when Enter-to-send is disabled", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer({ enterToSend: false });

    await user.type(input, "移动端输入");
    await user.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("移动端输入\n");
  });

  it("does not send while an input method composition is active", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer();

    await user.type(input, "拼音");
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", isComposing: true });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("拼音");
  });

  it("keeps @ text unchanged without parsing an agent mention", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer();

    await user.type(input, "@reviewer 请审查");
    expect(screen.queryByRole("option", { name: /reviewer/ })).not.toBeInTheDocument();
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("@reviewer 请审查");
    expect(input).toHaveValue("");
  });
});
