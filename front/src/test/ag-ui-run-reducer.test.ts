import { describe, expect, test } from "vitest";
import { EventType } from "../services/agUiProtocol";
import { createAgUiStreamAdapter } from "../services/agUiStreamAdapter";
import {
  buildAgUiMessageMeta,
  createAgUiRunState,
  reduceAgUiRunEvent,
} from "../utils/agUiRunReducer";

describe("agUiRunReducer", () => {
  test("deduplicates anonymous native activity replays", () => {
    const event = {
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-replay",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        summary: "重复过程",
        source: "native",
        rawKind: "commentary",
        rawType: "message.text.reclassified",
      },
    } as const;

    const state = [event, event].reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.traceEvents).toHaveLength(1);
    expect(state.entries).toHaveLength(1);
  });

  test("marks source=native activities as native transcript content", () => {
    const state = reduceAgUiRunEvent(createAgUiRunState(), {
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "legacy-message-1",
      activityType: "TCB_TRACE_COMMENTARY",
      replace: true,
      content: {
        summary: "原生过程",
        source: "native",
        rawKind: "commentary",
      },
    });

    expect(state.nativeAgent).toBe(true);
    expect(buildAgUiMessageMeta(state)?.tracePresentation).toBe("native_agent_flat");
  });

  test("folds cumulative anonymous native activity commentary", () => {
    const events = [
      ["我先", "message.text.reclassified"],
      ["我先检查目录。", "assistant_message"],
      ["我先检查目录。", "message.text.reclassified"],
    ].map(([summary, rawType]) => ({
      type: EventType.ACTIVITY_SNAPSHOT,
      messageId: "activity-cumulative",
      activityType: "TCB_NATIVE_AGENT_TRACE",
      replace: true,
      content: {
        summary,
        source: "native",
        rawKind: "commentary",
        rawType,
      },
    } as const));

    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.traceEvents).toHaveLength(1);
    expect(state.entries).toHaveLength(1);
    expect(state.entries[0]?.summary).toBe("我先检查目录。");
  });

  test("does not use the legacy adapter placeholder as an activity identity", () => {
    const adapter = createAgUiStreamAdapter({ bridgeLegacy: true });
    const events = ["过程一", "过程一", "过程二"].flatMap((summary) => adapter.adapt({
      type: "trace",
      event: {
        kind: "commentary",
        summary,
        source: "native",
        raw_type: "message.text.reclassified",
      },
    }));

    const state = events.reduce(reduceAgUiRunEvent, createAgUiRunState());

    expect(state.traceEvents.map((trace) => trace.summary)).toEqual(["过程一", "过程二"]);
  });
});
