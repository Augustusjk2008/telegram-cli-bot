import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatComposer } from "../components/ChatComposer";

function renderComposer({
  enterToSend = true,
  clusterMode = false,
}: {
  enterToSend?: boolean;
  clusterMode?: boolean;
} = {}) {
  const onSend = vi.fn();
  render(
    <ChatComposer
      onSend={onSend}
      onAttachFiles={() => undefined}
      onRemoveAttachment={() => undefined}
      attachments={[]}
      enterToSend={enterToSend}
      clusterMode={clusterMode}
      agents={clusterMode ? [{
        id: "reviewer",
        name: "审查专家",
        systemPrompt: "",
        enabled: true,
        isMain: false,
      }] : []}
    />,
  );
  return {
    input: screen.getByPlaceholderText("输入消息"),
    onSend,
  };
}

describe("ChatComposer send shortcuts", () => {
  it("sends with Enter when Enter-to-send is enabled", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer();

    await user.type(input, "运行测试");
    await user.keyboard("{Enter}");

    expect(onSend).toHaveBeenCalledWith("运行测试", []);
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

  it("accepts an agent mention with Enter before sending", async () => {
    const user = userEvent.setup();
    const { input, onSend } = renderComposer({ clusterMode: true });

    await user.type(input, "@rev");
    expect(await screen.findByRole("option", { name: "@reviewer 审查专家" })).toBeInTheDocument();
    await user.keyboard("{Enter}");

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("@reviewer ");
  });
});
