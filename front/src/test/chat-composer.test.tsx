import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatComposer } from "../components/ChatComposer";

test("attachment input forwards selected files to the upload handler", async () => {
  const user = userEvent.setup();
  const onAttachFiles = vi.fn();
  const file = new File(["hello"], "report.txt", { type: "text/plain" });

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={onAttachFiles}
      onRemoveAttachment={() => {}}
      attachments={[]}
    />,
  );

  await user.upload(screen.getByLabelText("上传附件"), file);

  expect(onAttachFiles).toHaveBeenCalledTimes(1);
  expect(onAttachFiles).toHaveBeenCalledWith([
    expect.objectContaining({
      name: "report.txt",
    }),
  ]);
});

test("cluster mode collects agent mentions", async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();

  render(
    <ChatComposer
      onSend={onSend}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      clusterMode
      agents={[{
        id: "reviewer",
        name: "代码审查",
        systemPrompt: "",
        enabled: true,
        isMain: false,
      }]}
    />,
  );

  await user.type(screen.getByPlaceholderText("输入消息"), "@reviewer 看一下");
  await user.click(screen.getByRole("button", { name: "发送" }));

  expect(onSend).toHaveBeenCalledWith(
    "@reviewer 看一下",
    [expect.objectContaining({ agentId: "reviewer" })],
  );
});

test("cluster mode shows child agent chips and inserts a mention", async () => {
  const user = userEvent.setup();

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      clusterMode
      agents={[{
        id: "reviewer",
        name: "代码审查",
        systemPrompt: "",
        enabled: true,
        isMain: false,
      }]}
    />,
  );

  const input = screen.getByPlaceholderText("输入消息");
  const clusterLabel = screen.getByText("智能体集群");
  await user.click(screen.getByRole("button", { name: "@reviewer 代码审查" }));

  expect(clusterLabel).toHaveClass("text-emerald-700");
  expect(input).toHaveValue("@reviewer ");
});

test("typing at in cluster mode opens agent picker", async () => {
  const user = userEvent.setup();

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      clusterMode
      agents={[{
        id: "reviewer",
        name: "代码审查",
        systemPrompt: "",
        enabled: true,
        isMain: false,
      }]}
    />,
  );

  const input = screen.getByPlaceholderText("输入消息");
  await user.type(input, "@");
  await user.click(await screen.findByRole("option", { name: "@reviewer 代码审查" }));

  expect(input).toHaveValue("@reviewer ");
});

test("composer exposes pulse state without changing send semantics", async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();

  render(
    <ChatComposer
      onSend={onSend}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      pulse
    />,
  );

  expect(screen.getByTestId("chat-composer-root")).toHaveAttribute("data-pulse", "true");
  await user.type(screen.getByRole("textbox"), "hello");
  await user.keyboard("{Shift>}{Enter}{/Shift}");
  expect(onSend).toHaveBeenCalledWith("hello", []);
});
