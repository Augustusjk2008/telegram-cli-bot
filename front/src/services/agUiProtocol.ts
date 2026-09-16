import {
  EventSchemas,
  EventType,
  type AGUIEvent,
  type BaseEvent,
} from "@ag-ui/core";

export {
  EventType,
};

export type {
  AGUIEvent as AgUiEvent,
  BaseEvent,
};

export function parseAgUiEvent(raw: unknown): AGUIEvent | null {
  try {
    const parsed = EventSchemas.parse(raw);
    if ((parsed.type === EventType.RUN_STARTED || parsed.type === EventType.CUSTOM) && raw && typeof raw === "object") {
      const extensions = raw as Record<string, unknown>;
      return Object.assign(parsed, Object.fromEntries(
        ["turn_id", "assistant_message_id", "user_message_id", "user_translation", "agent_input_text"]
          .filter((key) => key in extensions)
          .map((key) => [key, extensions[key]]),
      ));
    }
    return parsed;
  } catch (error) {
    if (typeof console !== "undefined" && typeof console.debug === "function") {
      console.debug("[ag-ui] invalid event", error, raw);
    }
    return null;
  }
}
