import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatTranslationSettingsPanel } from "../components/ChatTranslationSettingsPanel";
import { MockWebBotClient } from "../services/mockWebBotClient";

test("translation settings save their own CLI type, path and parameters", async () => {
  const client = new MockWebBotClient();
  const update = vi.spyOn(client, "updateChatTranslationConfig");
  const user = userEvent.setup();
  render(<ChatTranslationSettingsPanel client={client} />);

  await user.click(await screen.findByRole("button", { name: "本地 CLI" }));
  await user.selectOptions(screen.getByLabelText("CLI 类型"), "claude");
  // Switching the type offers that CLI's command and parameters before anything is saved.
  expect(screen.getByLabelText("CLI 路径")).toHaveValue("claude");
  await user.selectOptions(screen.getByLabelText("推理努力程度"), "low");
  await user.selectOptions(screen.getByLabelText("模型选择"), "none");
  await user.click(screen.getByRole("button", { name: "保存聊天翻译配置" }));

  await screen.findByText("已保存，下一条消息开始生效。");
  // Only the edited parameters are sent, and "none" travels as "no model" rather than a model name.
  expect(update).toHaveBeenCalledWith(expect.objectContaining({
    method: "cli",
    cli_type: "claude",
    cli_path: "claude",
    cli_params: { reasoning_effort: "low", model: null },
  }));
  expect(await client.getChatTranslationConfig()).toMatchObject({ method: "cli", cli_type: "claude", cli_path: "claude" });
  expect(screen.getByRole("button", { name: "保存聊天翻译配置" })).toBeDisabled();
});

test("translation settings leave the CLI untouched when only the LLM API is edited", async () => {
  const client = new MockWebBotClient();
  const update = vi.spyOn(client, "updateChatTranslationConfig");
  const user = userEvent.setup();
  render(<ChatTranslationSettingsPanel client={client} />);

  await user.type(await screen.findByLabelText("翻译模型"), "translator-model");
  await user.click(screen.getByRole("button", { name: "保存聊天翻译配置" }));

  await screen.findByText("已保存，下一条消息开始生效。");
  expect(update.mock.calls[0][0]).toMatchObject({ method: "llm", model: "translator-model" });
  expect(update.mock.calls[0][0]).not.toHaveProperty("cli_type");
});
