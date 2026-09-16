import { afterEach, expect, test, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";
import { DEFAULT_CHAT_TRANSLATION_CONFIG } from "../utils/chatTranslation";
import { applyHistoryDelta } from "../chat/historyDeltaState";
import type { ChatMessage, ChatTranslation } from "../services/types";

const translation: ChatTranslation = { status: "completed", text: "Translated input", source_digest: "digest", target_language: "English", completed_at: "2026-09-16T08:00:00Z" };
const jsonOk = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });

afterEach(() => vi.unstubAllGlobals());

test("uses the global config GET/PATCH contract without changing key-preservation semantics", async () => {
  const config = { ...DEFAULT_CHAT_TRANSLATION_CONFIG, api_key_configured: true };
  const fetch = vi.fn(async (..._args: unknown[]) => jsonOk(config));
  vi.stubGlobal("fetch", fetch);
  const client = new RealWebBotClient();
  expect(await client.getChatTranslationConfig()).toEqual(config);
  expect(fetch.mock.calls[0][0]).toBe("/api/admin/chat-translation/config");
  await client.updateChatTranslationConfig({ api_key: "", translate_assistant_enabled: true, assistant_target_language: "粤语" });
  expect(fetch.mock.calls[1][1]).toMatchObject({ method: "PATCH", body: JSON.stringify({ api_key: "", translate_assistant_enabled: true, assistant_target_language: "粤语" }) });
  await client.updateChatTranslationConfig({ clear_api_key: true });
  expect(fetch.mock.calls[2][1]).toMatchObject({ body: JSON.stringify({ clear_api_key: true }) });
});

test("maps api_key_set on GET and PATCH responses, including key removal", async () => {
  const { api_key_configured: _configured, ...config } = DEFAULT_CHAT_TRANSLATION_CONFIG;
  const fetch = vi.fn()
    .mockResolvedValueOnce(jsonOk({ ...config, api_key_set: true }))
    .mockResolvedValueOnce(jsonOk({ ...config, api_key_set: false }));
  vi.stubGlobal("fetch", fetch);
  const client = new RealWebBotClient();
  expect(await client.getChatTranslationConfig()).toEqual({ ...config, api_key_configured: true });
  expect(await client.updateChatTranslationConfig({ clear_api_key: true })).toEqual({ ...config, api_key_configured: false });
});

test("maps persisted translation and execution text in snapshots and revision deltas, preserving source content", async () => {
  const row = { id: "user-1", role: "user", content: "原始提问", translation, agent_input_text: "Translated input" };
  const fetch = vi.fn(async () => jsonOk({ items: [row], revision: 2, reset: false }));
  vi.stubGlobal("fetch", fetch);
  const client = new RealWebBotClient();
  const snapshot = await client.listMessages("main");
  const delta = await client.listMessageDelta("main", "user-1", 50, { revision: 1 });
  for (const result of [snapshot, delta]) {
    expect(result.items[0]).toMatchObject({ text: "原始提问", translation, agentInputText: "Translated input" });
  }
  const previous: ChatMessage = { ...snapshot.items[0], translationView: "original" };
  const stale = applyHistoryDelta([previous], { reset: false, items: [{ ...previous, translationView: undefined, translation: { ...translation, status: "pending" } }] });
  expect(stale[0]).toMatchObject({ translation, translationView: "original" });
});

test.each(["cli", "native_agent"] as const)("keeps initial and later translation events and stable turn IDs (%s)", async (mode) => {
  const binding = { turn_id: "turn-1", user_message_id: "user-1", assistant_message_id: "assistant-1" };
  const final = { id: "assistant-1", role: "assistant", content: "Final answer", turn_id: "turn-1" };
  const pending = { ...translation, status: "pending", text: undefined, completed_at: undefined };
  const events = mode === "cli" ? [
    { type: "status", ...binding, user_translation: pending },
    { type: "meta", ...binding, user_translation: translation, agent_input_text: "Translated input" },
    { type: "done", ...binding, message: final },
  ] : [
    { type: "CUSTOM", name: "TCB_CHAT_TRANSLATION", value: { ...binding, user_translation: pending } },
    { type: "RUN_STARTED", threadId: "thread", runId: "run", ...binding, user_translation: translation, agent_input_text: "Translated input" },
    { type: "RUN_FINISHED", threadId: "thread", runId: "run", result: { ...binding, message: final } },
  ];
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true,
    body: new ReadableStream({ start(controller) {
      for (const event of events) controller.enqueue(new TextEncoder().encode(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`));
      controller.close();
    } }),
  })));
  const status = vi.fn();
  const agUi = vi.fn();
  const result = await new RealWebBotClient().sendMessage("main", "原始提问", vi.fn(), status, undefined, { executionMode: mode }, agUi);
  expect(result).toMatchObject({ id: "assistant-1", turnId: "turn-1", text: "Final answer" });
  if (mode === "cli") {
    expect(status).toHaveBeenNthCalledWith(1, expect.objectContaining({ turnId: "turn-1", assistantMessageId: "assistant-1", userMessageId: "user-1" }));
    expect(status).toHaveBeenNthCalledWith(2, expect.objectContaining({ userMessageId: "user-1", userTranslation: translation, agentInputText: "Translated input" }));
  } else {
    expect(agUi).toHaveBeenNthCalledWith(1, expect.objectContaining({ name: "TCB_CHAT_TRANSLATION", value: expect.objectContaining({ ...binding, user_translation: expect.objectContaining({ status: "pending" }) }) }));
    expect(agUi).toHaveBeenNthCalledWith(2, expect.objectContaining({ ...binding, user_translation: translation, agent_input_text: "Translated input" }));
  }
});
