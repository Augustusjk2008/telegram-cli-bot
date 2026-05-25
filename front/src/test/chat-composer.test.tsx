import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

test("can expand and collapse the message textarea", async () => {
  const user = userEvent.setup();

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
    />,
  );

  const input = screen.getByPlaceholderText("输入消息") as HTMLTextAreaElement;
  expect(input.rows).toBe(1);

  await user.click(screen.getByRole("button", { name: "展开输入框" }));
  expect(input.rows).toBe(6);

  await user.click(screen.getByRole("button", { name: "收起输入框" }));
  expect(input.rows).toBe(1);
});

test("inserts a prompt preset at the cursor", async () => {
  const user = userEvent.setup();

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      globalPromptPresets={[{ id: "review", title: "审查", content: "请审查" }]}
      botPromptPresets={[{ id: "plan", title: "方案", content: "请按方案执行" }]}
    />,
  );

  const input = screen.getByPlaceholderText("输入消息") as HTMLTextAreaElement;
  await user.type(input, "前后");
  input.setSelectionRange(1, 1);
  fireEvent.select(input);

  await user.click(screen.getByRole("button", { name: "打开提示词预设" }));
  expect(screen.getByText("全局预设")).toBeInTheDocument();
  expect(screen.getByText("当前 Bot")).toBeInTheDocument();
  await user.click(screen.getByText("审查"));

  expect(input).toHaveValue("前请审查后");
  expect(screen.queryByRole("button", { name: "预设" })).not.toBeInTheDocument();
});

test("saves global prompt preset edits from the config dialog", async () => {
  const user = userEvent.setup();
  const onSaveGlobalPromptPresets = vi.fn(async () => {});

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      canManagePromptPresets
      onSaveGlobalPromptPresets={onSaveGlobalPromptPresets}
    />,
  );

  await user.click(screen.getByRole("button", { name: "打开提示词预设" }));
  await user.click(screen.getByRole("button", { name: "配置预设" }));
  await user.click(screen.getByRole("button", { name: "全局" }));
  await user.click(screen.getByRole("button", { name: "新增预设" }));
  await user.type(screen.getByLabelText("预设标题 1"), "方案执行");
  await user.type(screen.getByLabelText("预设内容 1"), "请按方案执行");
  await user.click(screen.getByRole("button", { name: "保存预设" }));

  await waitFor(() => {
    expect(onSaveGlobalPromptPresets).toHaveBeenCalledWith([
      expect.objectContaining({
        title: "方案执行",
        content: "请按方案执行",
      }),
    ]);
  });
  expect(screen.queryByRole("dialog", { name: "配置提示词预设" })).not.toBeInTheDocument();
});

test("saves bot prompt preset edits from the config dialog", async () => {
  const user = userEvent.setup();
  const onSaveBotPromptPresets = vi.fn(async () => {});

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={() => {}}
      onRemoveAttachment={() => {}}
      attachments={[]}
      canManagePromptPresets
      onSaveBotPromptPresets={onSaveBotPromptPresets}
    />,
  );

  await user.click(screen.getByRole("button", { name: "打开提示词预设" }));
  await user.click(screen.getByRole("button", { name: "配置预设" }));
  await user.click(screen.getByRole("button", { name: "当前 Bot" }));
  await user.click(screen.getByRole("button", { name: "新增预设" }));
  await user.type(screen.getByLabelText("预设标题 1"), "当前方案");
  await user.type(screen.getByLabelText("预设内容 1"), "请按当前 bot 方案执行");
  await user.click(screen.getByRole("button", { name: "保存预设" }));

  await waitFor(() => {
    expect(onSaveBotPromptPresets).toHaveBeenCalledWith([
      expect.objectContaining({
        title: "当前方案",
        content: "请按当前 bot 方案执行",
      }),
    ]);
  });
});
