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
    return EventSchemas.parse(raw);
  } catch (error) {
    if (typeof console !== "undefined" && typeof console.debug === "function") {
      console.debug("[ag-ui] invalid event", error, raw);
    }
    return null;
  }
}
