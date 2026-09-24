import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ChatTranslationSettingsPanel } from "../components/ChatTranslationSettingsPanel";
import { BotChatTranslationSettings } from "../components/BotChatTranslationSettings";
import { ChatScreen, mergeMessagesPreservingClientState } from "../screens/ChatScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { ChatMessage, ChatTranslation, ConversationListResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_CHAT_TRANSLATION_CONFIG } from "../utils/chatTranslation";
import { copyText } from "../utils/clipboard";
import { EventType } from "../services/agUiProtocol";

vi.mock("../utils/clipboard", () => ({ copyText: vi.fn(async () => true) }));

const translation: ChatTranslation = { status: "completed", text: "译文内容", target_language: "简体中文", source_digest: "digest" };
const original: ChatMessage = { id: "answer-1", turnId: "turn-1", role: "assistant", text: "Original answer", state: "done", createdAt: "2026-09-16T08:00:00Z" };

function clientWith(overrides: Partial<WebBotClient> = {}): WebBotClient {
  return Object.assign(new MockWebBotClient(), {
    getBotOverview: async () => ({ alias: "main", cliType: "codex", status: "running", workingDir: "C:\\workspace", isProcessing: false }),
    listMessages: async () => ({ items: [] }),
    listConversations: async (): Promise<ConversationListResult> => ({ activeConversationId: "", items: [] }),
    ...overrides,
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  window.localStorage.clear();
});

test("bot translation keeps the saved preference when saving fails and allows retry", async () => {
  const config = { enabled: true, global_translate_user_enabled: false, global_translate_assistant_enabled: false, can_edit: true };
  const update = vi.fn().mockRejectedValueOnce(new Error("保存失败")).mockResolvedValueOnce({ ...config, enabled: false });
  render(<BotChatTranslationSettings botAlias="project" client={clientWith({
    getBotChatTranslationConfig: async () => config,
    updateBotChatTranslationConfig: update,
  })} />);
  const toggle = screen.getByRole("switch", { name: "本 Bot 启用聊天翻译" });
  await waitFor(() => expect(toggle).toBeEnabled());
  fireEvent.click(toggle);
  expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
  expect(toggle).toBeChecked();
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).not.toBeChecked());
  expect(update).toHaveBeenLastCalledWith("project", false);
});

test("bot translation is read-only without configuration access", async () => {
  render(<BotChatTranslationSettings botAlias="main" client={clientWith({
    getBotChatTranslationConfig: async () => ({ enabled: true, global_translate_user_enabled: true, global_translate_assistant_enabled: false, can_edit: false }),
  })} />);
  const toggle = screen.getByRole("switch", { name: "本 Bot 启用聊天翻译" });
  await waitFor(() => expect(toggle).toBeChecked());
  expect(toggle).toBeDisabled();
});

test("configuration saves independent complete prompts and explicitly clears the key", async () => {
  const config = { ...DEFAULT_CHAT_TRANSLATION_CONFIG, base_url: "https://example.test/v1", model: "translator", api_key_configured: true };
  const update = vi.fn(async (input) => ({ ...config, ...input, api_key_configured: !input.clear_api_key }));
  render(<ChatTranslationSettingsPanel client={clientWith({ getChatTranslationConfig: async () => config, updateChatTranslationConfig: update })} />);
  const save = screen.getByRole("button", { name: "保存聊天翻译配置" });
  await waitFor(() => expect(save).toBeEnabled());
  expect(screen.getByLabelText("翻译推理深度")).toHaveValue("none");
  fireEvent.change(screen.getByLabelText("翻译推理深度"), { target: { value: "high" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "翻译提问" }));
  fireEvent.change(screen.getByLabelText("用户消息翻译提示词"), { target: { value: " Translate into English. For logs return <skip translation>. " } });
  fireEvent.change(screen.getByLabelText("Bot 回答翻译提示词"), { target: { value: "Translate into Chinese. On failure return <translation failed>." } });
  fireEvent.click(save);
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
  expect(update.mock.calls[0][0]).toMatchObject({ translate_user_enabled: true, translate_assistant_enabled: false, api_key: "" });
  expect(update.mock.calls[0][0]).not.toHaveProperty("api_key_configured");
  expect(update.mock.calls[0][0]).toMatchObject({
    reasoning_effort: "high",
    user_prompt: " Translate into English. For logs return <skip translation>. ",
    assistant_prompt: "Translate into Chinese. On failure return <translation failed>.",
  });
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(screen.getByRole("checkbox", { name: "翻译提问" }));
  fireEvent.click(screen.getByLabelText("清除已保存的翻译 API 密钥"));
  fireEvent.click(save);
  await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
  expect(update.mock.calls[1][0]).toMatchObject({ clear_api_key: true, api_key: "" });
});

test.each([false, true])("defaults to translated content and copies the selected version (native=%s)", async (native) => {
  const item: ChatMessage = { ...original, translation, ...(native ? { meta: { tracePresentation: "native_agent_flat" } } : {}) };
  render(<ChatScreen botAlias="main" client={clientWith({ listMessages: async () => ({ items: [item] }) })} />);
  expect(await screen.findByText("译文内容")).toBeInTheDocument();
  expect(screen.queryByText("Original answer")).not.toBeInTheDocument();
  if (native) expect(screen.getByTestId("native-agent-final-result")).toHaveTextContent("译文内容");
  fireEvent.click(screen.getByRole("button", { name: "复制最终回答" }));
  await waitFor(() => expect(copyText).toHaveBeenLastCalledWith("译文内容"));
  fireEvent.click(screen.getByRole("button", { name: "显示原文" }));
  expect(screen.getByText("Original answer")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制完整回答" }));
  await waitFor(() => expect(copyText).toHaveBeenLastCalledWith(native ? "[最终回答]\nOriginal answer" : "Original answer"));
});

test.each(["Attachment path: ", "附件路径为："])("pending and failed translations show originals, while attachments always come from the original message (%s)", async (attachmentPrefix) => {
  render(<ChatScreen botAlias="main" client={clientWith({ listMessages: async () => ({ items: [
    { ...original, id: "pending", translation: { ...translation, status: "pending", text: undefined } },
    { ...original, id: "user", turnId: "turn-2", role: "user", text: `原始提问\n\n${attachmentPrefix}C:\\workspace\\source.txt`, translation: { ...translation, text: `Translated question\n\n${attachmentPrefix}C:\\workspace\\wrong.txt` } },
    { ...original, id: "failed", turnId: "turn-2", text: "Failed original", translation: { ...translation, status: "failed" } },
  ] }) })} />);
  expect(await screen.findByText("Original answer")).toBeInTheDocument();
  expect(screen.getByText("Failed original")).toBeInTheDocument();
  expect(screen.getByText("source.txt")).toBeInTheDocument();
  expect(screen.queryByText("wrong.txt")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制当前提问" }));
  await waitFor(() => expect(copyText).toHaveBeenLastCalledWith(expect.stringContaining("Translated question")));
});

test.each(["cli", "native_agent"] as const)("binds accepted and later translated input to one user row (%s)", async (mode) => {
  let finish!: (message: ChatMessage) => void;
  let update!: () => void;
  let repeatPending!: () => void;
  const send: WebBotClient["sendMessage"] = async (_bot, _text, _chunk, status, _trace, _options, agUi) => {
    const raw = { turn_id: "turn-1", user_message_id: "persisted-user", assistant_message_id: "persisted-assistant" };
    const pending = { ...translation, status: "pending" as const, text: undefined };
    if (mode === "cli") {
      repeatPending = () => status?.({ turnId: raw.turn_id, userMessageId: raw.user_message_id, assistantMessageId: raw.assistant_message_id, userTranslation: pending });
      update = () => status?.({ turnId: raw.turn_id, userMessageId: raw.user_message_id, userTranslation: translation, agentInputText: "译文内容" });
    } else {
      repeatPending = () => agUi?.({ type: EventType.CUSTOM, name: "TCB_CHAT_TRANSLATION", value: { ...raw, user_translation: pending } });
      update = () => agUi?.(Object.assign({ type: EventType.RUN_STARTED as const, threadId: "thread", runId: "run" }, raw, { user_translation: translation, agent_input_text: "译文内容" }));
    }
    repeatPending();
    return new Promise((resolve) => { finish = resolve; });
  };
  render(<ChatScreen botAlias="main" client={clientWith({ sendMessage: send })} />);
  await screen.findByText("暂无消息，开始聊天吧");
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "原始提问" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(update).toBeDefined());
  expect(screen.getByText("原始提问")).toBeInTheDocument();
  expect(document.querySelectorAll('[data-message-id="persisted-user"]')).toHaveLength(1);
  await act(async () => update());
  expect(await screen.findByText("译文内容")).toBeInTheDocument();
  expect(document.querySelectorAll('[data-message-id="persisted-user"]')).toHaveLength(1);
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
  await act(async () => repeatPending());
  expect(screen.getByText("译文内容")).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "显示原文" }));
  await act(async () => update());
  expect(screen.getByText("原始提问")).toBeInTheDocument();
  await act(async () => finish({ ...original, id: "persisted-assistant" }));
});

test("history translation merges keep selection and current streaming text, rejecting old pending", () => {
  const completed = { ...original, translation, translationView: "original" as const };
  const streaming: ChatMessage = { ...original, id: "active", turnId: "turn-2", state: "streaming", text: "Current live text", meta: { renderKey: "active" } };
  const merged = mergeMessagesPreservingClientState([completed, streaming], [
    { ...original, translation: { ...translation, status: "pending" } },
    { ...streaming, text: "Older persisted text", meta: undefined },
  ], true);
  expect(merged[0]).toMatchObject({ translation, translationView: "original", text: original.text });
  expect(merged[1]).toEqual(streaming);
  expect(mergeMessagesPreservingClientState([completed, streaming], [{ ...original, translation }], true)[1]).toEqual(streaming);
  const replaced = mergeMessagesPreservingClientState([completed], [{ ...original, text: "New source", translation: null }]);
  expect(replaced[0].translation).toBeNull();
});

test("history accepts a retried answer pending state but ignores late question pending state", () => {
  const failed = { ...translation, status: "failed" as const, text: undefined };
  const pending = { ...translation, status: "pending" as const, text: undefined };
  const answer: ChatMessage = { ...original, translation: failed };
  const question: ChatMessage = { ...original, id: "question", role: "user", translation: failed };
  const merged = mergeMessagesPreservingClientState([answer, question], [
    { ...answer, translation: pending }, { ...question, translation: pending },
  ]);
  expect(merged[0].translation?.status).toBe("pending");
  expect(merged[1].translation?.status).toBe("failed");
});

test("translation delta updates the prior answer during a new stream without resetting its version choice", async () => {
  let finish!: (value: ChatMessage) => void;
  const pending = { ...original, translation: { ...translation, status: "pending" as const, text: undefined } };
  const delta = vi.fn<WebBotClient["listMessageDelta"]>(async () => ({ items: [{ ...original, translation }], revision: 2, reset: false }));
  const client = clientWith({
    listMessages: async () => ({ items: [pending], revision: 1 }),
    listMessageDelta: delta,
    sendMessage: async (_bot, _text, chunk, status) => {
      status?.({ turnId: "turn-2", userMessageId: "user-2", assistantMessageId: "active" });
      chunk("Current live text");
      return new Promise((resolve) => { finish = resolve; });
    },
  });
  render(<ChatScreen botAlias="main" client={client} />);
  await screen.findByText("Original answer");
  fireEvent.change(screen.getByPlaceholderText("输入消息"), { target: { value: "Next question" } });
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  await waitFor(() => expect(finish).toBeDefined());
  await waitFor(() => expect(delta).toHaveBeenCalled(), { timeout: 3_000 });
  expect(screen.getByText("译文内容")).toBeInTheDocument();
  const answerRow = screen.getByText("译文内容").closest('[data-testid="chat-message-row"]') as HTMLElement;
  fireEvent.click(within(answerRow).getByRole("button", { name: "显示原文" }));
  expect(screen.getByText("Original answer")).toBeInTheDocument();
  expect(document.querySelector('[data-message-id="active"] [data-streaming="true"]')).toBeInTheDocument();
  expect(screen.getAllByTestId("chat-message-row")).toHaveLength(3);
  await act(async () => finish({ ...original, id: "active", turnId: "turn-2", text: "Current live text" }));
  expect(await screen.findByText("Current live text")).toBeInTheDocument();
});
