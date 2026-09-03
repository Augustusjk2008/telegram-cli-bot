import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  chatUnreadStoragePrefix,
  markStoredChatRead,
  reconcileStoredChatUnread,
  recordStoredChatCompletion,
} from "../app/chatUnreadState";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

test("restores an unread bot when its latest completion changed while the browser was closed", () => {
  const initial = reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerCompletedAt: "2026-08-27T01:00:00Z" },
    { alias: "worker", lastAnswerCompletedAt: "2026-08-27T01:05:00Z" },
  ]);
  expect(initial.unreadBots).toEqual([]);

  const restored = reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerCompletedAt: "2026-08-27T01:00:00Z" },
    { alias: "worker", lastAnswerCompletedAt: "2026-08-27T01:10:00Z" },
  ]);

  expect(restored.unreadBots).toEqual(["worker"]);
});

test("uses the latest terminal timestamp so an offline failed reply is also restored", () => {
  reconcileStoredChatUnread("account-1", [
    {
      alias: "main",
      lastAnswerCompletedAt: "2026-08-27T01:00:00Z",
      lastAnswerTerminalAt: "2026-08-27T01:00:00Z",
    },
  ]);

  const restored = reconcileStoredChatUnread("account-1", [
    {
      alias: "main",
      lastAnswerCompletedAt: "2026-08-27T01:00:00Z",
      lastAnswerTerminalAt: "2026-08-27T01:10:00Z",
    },
  ]);

  expect(restored.unreadBots).toEqual(["main"]);
});

test("a visible completion clears a stale unread marker and keeps it cleared after reload", () => {
  reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerCompletedAt: "2026-08-27T01:00:00Z" },
  ]);
  recordStoredChatCompletion("account-1", "main", "2026-08-27T01:10:00Z", true);

  const visible = recordStoredChatCompletion("account-1", "main", "2026-08-27T01:10:00Z", false);
  expect(visible.unreadBots).toEqual([]);

  const restored = reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerCompletedAt: "2026-08-27T01:10:00Z" },
  ]);
  expect(restored.unreadBots).toEqual([]);
});

test("an older visible completion cannot clear a newer unread completion", () => {
  reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerTerminalAt: "2026-08-27T01:00:00Z" },
  ]);
  recordStoredChatCompletion("account-1", "main", "2026-08-27T01:20:00Z", true);

  const state = recordStoredChatCompletion(
    "account-1",
    "main",
    "2026-08-27T01:10:00Z",
    false,
  );

  expect(state.unreadBots).toEqual(["main"]);
});

test("an older unread delivery cannot recreate a red dot after a newer completion was read", () => {
  reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerTerminalAt: "2026-08-27T01:00:00Z" },
  ]);
  recordStoredChatCompletion("account-1", "main", "2026-08-27T01:20:00Z", false);

  const state = recordStoredChatCompletion(
    "account-1",
    "main",
    "2026-08-27T01:10:00Z",
    true,
  );

  expect(state.unreadBots).toEqual([]);
});

test("compacts terminal markers that are older than the read watermark", () => {
  reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerTerminalAt: "2026-08-27T01:00:00Z" },
  ]);
  recordStoredChatCompletion("account-1", "main", "2026-08-27T01:10:00Z", false);
  recordStoredChatCompletion("account-1", "main", "2026-08-27T01:20:00Z", false);

  const prefix = chatUnreadStoragePrefix("account-1");
  const markerKeys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
    .filter((key): key is string => Boolean(key?.startsWith(prefix) && !key.endsWith("initialized")));

  expect(markerKeys).toHaveLength(2);
});

test("keeps repeated unread markers bounded before the bot is opened", () => {
  reconcileStoredChatUnread("account-1", [
    { alias: "main", lastAnswerTerminalAt: "2026-08-27T01:00:00Z" },
  ]);
  for (let index = 1; index <= 100; index += 1) {
    recordStoredChatCompletion(
      "account-1",
      "main",
      new Date(Date.parse("2026-08-27T01:00:00Z") + index * 1000).toISOString(),
      true,
    );
    recordStoredChatCompletion("account-1", "main", "", true);
  }

  const prefix = chatUnreadStoragePrefix("account-1");
  const markerKeys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
    .filter((key): key is string => Boolean(key?.startsWith(prefix) && !key.endsWith("initialized")));

  expect(markerKeys).toHaveLength(3);
});

test("keeps live unread state in memory when local storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage blocked");
  });

  const state = recordStoredChatCompletion(
    "account-1",
    "main",
    "2026-08-27T01:10:00Z",
    true,
  );

  expect(state.unreadBots).toEqual(["main"]);
});

test("opening a bot acknowledges its persisted unread state without affecting another account", () => {
  reconcileStoredChatUnread("account-1", []);
  recordStoredChatCompletion("account-1", "worker", "2026-08-27T01:10:00Z", true);
  reconcileStoredChatUnread("account-2", []);
  recordStoredChatCompletion("account-2", "worker", "2026-08-27T01:11:00Z", true);

  expect(markStoredChatRead("account-1", "worker").unreadBots).toEqual([]);
  expect(reconcileStoredChatUnread("account-2", [
    { alias: "worker", lastAnswerCompletedAt: "2026-08-27T01:11:00Z" },
  ]).unreadBots).toEqual(["worker"]);
});
